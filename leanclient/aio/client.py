"""AsyncLeanLSPClient — asyncio-native client for the Lean 4 language server.

Design contract (see PROTOCOL notes in the repo docs):

- The server parallelizes across files (one worker process per open file) and
  within files (async declaration elaboration); responses are unordered.
  Everything here is awaitable and safe to run concurrently.
- **Freshness**: after any change, position requests may answer instantly from
  a partial snapshot (``null`` goals). The one reliable barrier is
  ``textDocument/waitForDiagnostics`` sent *after* the change for the same
  version — exposed as :meth:`barrier` and used by ``fresh=True`` (default)
  on all queries.
- **Positions**: 0-indexed lines and **codepoint** columns everywhere in this
  API. UTF-16 conversion happens internally.
- **Errors**: typed exceptions only (see ``errors.py``).
- **Crash policy**: a crashed file worker is revived lazily by a ``didChange``
  on next use (the watchdog contract). Transport death fails all pending
  calls with :class:`LeanTransportError`.
- **Memory**: each open Mathlib file costs a worker process (~5 GB RSS).
  ``max_workers`` bounds open files with LRU eviction (in-flight and pinned
  files are never evicted).

Requires Lean toolchain >= 4.24 (checked from ``lean-toolchain`` on start).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import unquote, urlparse
from urllib.request import pathname2url

from .convert import (
    codepoint_to_utf16,
    range_from_utf16,
    utf16_to_codepoint,
)
from .document import DocState, DocStatus
from .errors import (
    LeanClientError,
    LeanFileNotOpen,
    LeanRpcError,
    LeanUnsupportedVersion,
    LeanWorkerCrashed,
)
from .transport import LspTransport

MIN_LEAN_VERSION = (4, 24)

# Lean-specific error codes (Lean.Data.Lsp.Utf16 / Watchdog)
_WORKER_ERROR_CODES = {-32901, -32902}  # workerExited, workerCrashed
_CONTENT_MODIFIED = -32801


@dataclass
class GoalResult:
    """Result of a goal query with unambiguous status.

    - ``goals``: open goals at the position (pretty-printed)
    - ``complete``: elaboration reached the position and there are no goals
      left ("no goals" — the proof is finished at this point)
    - ``no_goal``: the position carries no proof state at all (outside a
      proof, on a blank line, ...)
    """

    status: Literal["goals", "complete", "no_goal"]
    goals: list[str] = field(default_factory=list)
    rendered: Optional[str] = None


@dataclass
class DiagnosticsReport:
    """Diagnostics for a file at a known version.

    ``items`` are raw LSP diagnostics with all ``range``/``fullRange`` columns
    converted to codepoints. ``fatal_error`` mirrors fileProgress kind=2.
    """

    items: list[dict]
    version: Optional[int]
    fatal_error: bool = False

    @property
    def errors(self) -> list[dict]:
        return [d for d in self.items if d.get("severity") == 1]

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)


def _default_max_workers() -> int:
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    gb = int(line.split()[1]) // (1024 * 1024)
                    return max(2, min(8, gb // 6))
    except OSError:
        pass
    return 4


def _parse_toolchain(project_path: str) -> Optional[tuple[int, int]]:
    try:
        raw = (Path(project_path) / "lean-toolchain").read_text().strip()
    except OSError:
        return None
    m = re.search(r"v(\d+)\.(\d+)", raw)
    return (int(m.group(1)), int(m.group(2))) if m else None


class AsyncLeanLSPClient:
    def __init__(
        self,
        project_path: str,
        max_workers: Optional[int] = None,
        request_timeout: float = 300.0,
        check_version: bool = True,
    ):
        self.project_path = str(Path(project_path).resolve())
        self.max_workers = max_workers or _default_max_workers()
        self.request_timeout = request_timeout
        self._check_version = check_version

        self._transport = LspTransport(
            ["lake", "serve", "--"],
            cwd=self.project_path,
            on_notification=self._on_notification,
            default_timeout=request_timeout,
        )
        self._docs: dict[str, DocState] = {}
        self._docs_by_uri: dict[str, DocState] = {}
        self._open_lock = asyncio.Lock()
        self._rpc_sessions: dict[str, tuple[str, float]] = {}
        self._started = False

    # -- lifecycle -----------------------------------------------------------

    async def start(self) -> None:
        if self._check_version:
            version = _parse_toolchain(self.project_path)
            if version is not None and version < MIN_LEAN_VERSION:
                raise LeanUnsupportedVersion(
                    f"Project toolchain is Lean {version[0]}.{version[1]}; "
                    f"leanclient.aio requires >= "
                    f"{MIN_LEAN_VERSION[0]}.{MIN_LEAN_VERSION[1]}. "
                    "Update lean-toolchain, or pass check_version=False "
                    "(unsupported)."
                )
        await self._transport.start()
        await self._transport.request(
            "initialize",
            {
                "processId": os.getpid(),
                "rootUri": self._path_to_uri(self.project_path),
                "capabilities": {},
                "initializationOptions": {
                    "editDelay": 1,
                    # Widget support: without this, interactive diagnostics
                    # render embedded widgets as plain text.
                    "hasWidgets": True,
                },
            },
            timeout=30.0,
        )
        await self._transport.notify("initialized", {})
        self._started = True

    async def close(self) -> None:
        self._started = False
        await self._transport.close()
        self._docs.clear()
        self._docs_by_uri.clear()

    @property
    def alive(self) -> bool:
        return self._started and self._transport.alive

    # -- uri/path helpers ----------------------------------------------------

    def _path_to_uri(self, path: str) -> str:
        abs_path = Path(self.project_path) / path
        return "file://" + pathname2url(str(abs_path))

    def _uri_to_relpath(self, uri: str) -> str:
        local = unquote(urlparse(uri).path)
        try:
            return str(Path(local).relative_to(self.project_path))
        except ValueError:
            return local

    def _doc(self, path: str) -> DocState:
        doc = self._docs.get(path)
        if doc is None:
            raise LeanFileNotOpen(f"{path} is not open (call open() first)")
        return doc

    def content(self, path: str) -> str:
        return self._doc(path).text

    def open_paths(self) -> list[str]:
        return list(self._docs)

    # -- notification intake ---------------------------------------------

    def _on_notification(self, method: str, params: dict) -> None:
        uri = None
        if "uri" in params:
            uri = params["uri"]
        elif "textDocument" in params:
            uri = params["textDocument"].get("uri")
        doc = self._docs_by_uri.get(uri) if uri else None
        if doc is None:
            return
        if method == "textDocument/publishDiagnostics":
            doc.on_publish_diagnostics(params)
        elif method == "$/lean/fileProgress":
            doc.on_file_progress(params)
        elif method == "$/lean/staleDependency":
            doc.on_stale_dependency()

    # -- open/close/update -----------------------------------------------

    async def open(
        self, path: str, text: Optional[str] = None, wait: bool = True
    ) -> DocState:
        """Open a file (or a virtual document when ``text`` is given).

        Virtual documents get a path under the project root that need not
        exist on disk; the server elaborates the provided text.
        """
        existing = self._docs.get(path)
        if existing is not None and existing.status is not DocStatus.CLOSED:
            if text is not None and text != existing.text:
                await self.update(path, text, wait=wait)
            elif wait:
                await self.barrier(path)
            existing.touch()
            return existing

        async with self._open_lock:
            await self._evict_if_needed()
            virtual = text is not None
            if text is None:
                text = (Path(self.project_path) / path).read_text()
            doc = DocState(
                path=path,
                uri=self._path_to_uri(path),
                text=text,
                virtual=virtual,
            )
            self._docs[path] = doc
            self._docs_by_uri[doc.uri] = doc
            await self._transport.notify(
                "textDocument/didOpen",
                {
                    "textDocument": {
                        "uri": doc.uri,
                        "languageId": "lean4",
                        "version": doc.version,
                        "text": doc.text,
                    }
                },
            )
            doc.status = DocStatus.LIVE
        if wait:
            await self.barrier(path)
        return doc

    async def open_many(self, paths: list[str], wait: bool = True) -> list[DocState]:
        """Open several files at once — elaboration runs in parallel workers."""
        docs = [await self.open(p, wait=False) for p in paths]
        if wait:
            await asyncio.gather(*(self.barrier(p) for p in paths))
        return docs

    async def update(self, path: str, text: str, wait: bool = False) -> DocState:
        """Replace the document text (full-text didChange).

        The server reuses snapshots for the unchanged prefix, so this is the
        right primitive even for single-line edits.
        """
        doc = self._doc(path)
        doc.text = text
        doc.version += 1
        doc.diagnostics_version = None
        doc.fatal_error = False
        doc.status = DocStatus.LIVE  # didChange also revives a crashed worker
        doc.touch()
        await self._transport.notify(
            "textDocument/didChange",
            {
                "textDocument": {"uri": doc.uri, "version": doc.version},
                "contentChanges": [{"text": text}],
            },
        )
        if wait:
            await self.barrier(path)
        return doc

    async def reload_from_disk(self, path: str, wait: bool = False) -> DocState:
        """Sync the document with the file's current on-disk content."""
        doc = self._docs.get(path)
        disk = (Path(self.project_path) / path).read_text()
        if doc is None or doc.status is DocStatus.CLOSED:
            return await self.open(path, wait=wait)
        if disk != doc.text:
            return await self.update(path, disk, wait=wait)
        if wait:
            await self.barrier(path)
        return doc

    async def close_file(self, path: str) -> None:
        doc = self._docs.pop(path, None)
        if doc is None:
            return
        self._docs_by_uri.pop(doc.uri, None)
        self._rpc_sessions.pop(doc.uri, None)
        doc.status = DocStatus.CLOSED
        with contextlib.suppress(LeanClientError):
            await self._transport.notify(
                "textDocument/didClose", {"textDocument": {"uri": doc.uri}}
            )

    async def restart_file(self, path: str, wait: bool = True) -> DocState:
        """didClose + didOpen — picks up rebuilt imports (staleDependency)."""
        doc = self._docs.get(path)
        text = doc.text if doc is not None else None
        await self.close_file(path)
        return await self.open(path, text=text if doc and doc.virtual else None, wait=wait)

    async def _evict_if_needed(self) -> None:
        def budget_used() -> int:
            # Pinned docs (e.g. scratch-pool slots) don't consume the budget;
            # otherwise a 2-slot pool halves the effective open-file capacity.
            return sum(1 for d in self._docs.values() if not d.pinned)

        while budget_used() >= self.max_workers:
            candidates = [
                d
                for d in self._docs.values()
                if not d.pinned and d.refcount == 0 and d.status is not DocStatus.CLOSED
            ]
            if not candidates:
                return  # soft cap: never deadlock, never evict in-flight docs
            victim = min(candidates, key=lambda d: d.last_used)
            await self.close_file(victim.path)

    # -- freshness ---------------------------------------------------------

    async def barrier(self, path: str, timeout: Optional[float] = None) -> None:
        """Resolve when the server finished elaborating the current version.

        Sent strictly after the didOpen/didChange it refers to (this client
        owns write ordering). After ``barrier()`` returns, position queries
        and diagnostics reflect the current text.
        """
        doc = self._doc(path)
        if doc.status is DocStatus.CRASHED:
            # Watchdog contract: only didChange revives a crashed worker.
            await self.update(path, doc.text, wait=False)
        doc.refcount += 1
        try:
            await self._transport.request(
                "textDocument/waitForDiagnostics",
                {"uri": doc.uri, "version": doc.version},
                timeout=timeout or self.request_timeout,
            )
        except LeanRpcError as e:
            if e.code in _WORKER_ERROR_CODES or "worker" in e.rpc_message.lower():
                doc.mark_crashed(e.rpc_message)
                raise LeanWorkerCrashed(
                    f"File worker for {path} died: {e.rpc_message}", uri=doc.uri
                ) from e
            raise
        finally:
            doc.refcount -= 1
            doc.touch()

    # -- queries -------------------------------------------------------------

    async def _request_at(
        self,
        doc: DocState,
        method: str,
        line: int,
        col: int,
        extra: Optional[dict] = None,
        timeout: Optional[float] = None,
    ):
        lines = doc.lines()
        line_str = lines[line] if 0 <= line < len(lines) else ""
        params = {
            "textDocument": {"uri": doc.uri},
            "position": {
                "line": line,
                "character": codepoint_to_utf16(line_str, col),
            },
        }
        if extra:
            params.update(extra)
        doc.refcount += 1
        try:
            return await self._transport.request(method, params, timeout=timeout)
        except LeanRpcError as e:
            if e.code in _WORKER_ERROR_CODES:
                doc.mark_crashed(e.rpc_message)
                raise LeanWorkerCrashed(
                    f"File worker for {doc.path} died: {e.rpc_message}", uri=doc.uri
                ) from e
            raise
        finally:
            doc.refcount -= 1
            doc.touch()

    async def diagnostics(
        self, path: str, fresh: bool = True, timeout: Optional[float] = None
    ) -> DiagnosticsReport:
        doc = self._doc(path)
        if fresh:
            await self.barrier(path, timeout=timeout)
        lines = doc.lines()
        items = []
        for diag in doc.diagnostics:
            d = dict(diag)
            for key in ("range", "fullRange"):
                if key in d and d[key]:
                    d[key] = range_from_utf16(lines, d[key])
            items.append(d)
        return DiagnosticsReport(
            items=items, version=doc.diagnostics_version, fatal_error=doc.fatal_error
        )

    async def goal(
        self, path: str, line: int, col: int, fresh: bool = True
    ) -> GoalResult:
        doc = self._doc(path)
        if fresh:
            await self.barrier(path)
        res = await self._request_at(doc, "$/lean/plainGoal", line, col)
        if res is None:
            return GoalResult(status="no_goal")
        goals = res.get("goals", [])
        if not goals:
            return GoalResult(status="complete", rendered=res.get("rendered"))
        return GoalResult(status="goals", goals=list(goals), rendered=res.get("rendered"))

    async def term_goal(
        self, path: str, line: int, col: int, fresh: bool = True
    ) -> Optional[dict]:
        doc = self._doc(path)
        if fresh:
            await self.barrier(path)
        return await self._request_at(doc, "$/lean/plainTermGoal", line, col)

    async def hover(
        self, path: str, line: int, col: int, fresh: bool = True
    ) -> Optional[dict]:
        doc = self._doc(path)
        if fresh:
            await self.barrier(path)
        res = await self._request_at(doc, "textDocument/hover", line, col)
        if res and "range" in res:
            res["range"] = range_from_utf16(doc.lines(), res["range"])
        return res

    async def completions(
        self, path: str, line: int, col: int, fresh: bool = False
    ) -> list[dict]:
        doc = self._doc(path)
        if fresh:
            await self.barrier(path)
        res = await self._request_at(
            doc,
            "textDocument/completion",
            line,
            col,
            extra={"context": {"triggerKind": 1}},
        )
        if res is None:
            return []
        return res.get("items", res if isinstance(res, list) else [])

    async def completion_resolve(self, item: dict, timeout: float = 15.0) -> dict:
        return await self._transport.request(
            "completionItem/resolve", item, timeout=timeout
        )

    async def references(
        self,
        path: str,
        line: int,
        col: int,
        include_declaration: bool = True,
        max_results: Optional[int] = None,
        fresh: bool = True,
    ) -> list[dict]:
        doc = self._doc(path)
        if fresh:
            await self.barrier(path)
        res = await self._request_at(
            doc,
            "textDocument/references",
            line,
            col,
            extra={"context": {"includeDeclaration": include_declaration}},
        )
        locations = res or []
        if max_results is not None:
            locations = locations[:max_results]
        return [self._convert_location(loc) for loc in locations]

    async def goto(
        self,
        kind: Literal["definition", "declaration", "typeDefinition"],
        path: str,
        line: int,
        col: int,
        fresh: bool = True,
    ) -> list[dict]:
        doc = self._doc(path)
        if fresh:
            await self.barrier(path)
        res = await self._request_at(doc, f"textDocument/{kind}", line, col)
        if res is None:
            return []
        if isinstance(res, dict):
            res = [res]
        return [self._convert_location(loc) for loc in res]

    async def document_symbols(self, path: str, fresh: bool = True) -> list[dict]:
        doc = self._doc(path)
        if fresh:
            await self.barrier(path)
        doc.refcount += 1
        try:
            res = await self._transport.request(
                "textDocument/documentSymbol", {"textDocument": {"uri": doc.uri}}
            )
        finally:
            doc.refcount -= 1
        return res or []

    async def code_actions(
        self,
        path: str,
        start_line: int,
        start_col: int,
        end_line: int,
        end_col: int,
        fresh: bool = True,
    ) -> list[dict]:
        doc = self._doc(path)
        if fresh:
            await self.barrier(path)
        lines = doc.lines()

        def pos(line: int, col: int) -> dict:
            line_str = lines[line] if 0 <= line < len(lines) else ""
            return {"line": line, "character": codepoint_to_utf16(line_str, col)}

        doc.refcount += 1
        try:
            res = await self._transport.request(
                "textDocument/codeAction",
                {
                    "textDocument": {"uri": doc.uri},
                    "range": {
                        "start": pos(start_line, start_col),
                        "end": pos(end_line, end_col),
                    },
                    "context": {"diagnostics": []},
                },
            )
        finally:
            doc.refcount -= 1
        return res or []

    async def code_action_resolve(self, action: dict, timeout: float = 30.0) -> dict:
        return await self._transport.request(
            "codeAction/resolve", action, timeout=timeout
        )

    # -- Lean RPC (widgets, interactive goals) --------------------------------

    async def rpc_call(
        self,
        path: str,
        line: int,
        col: int,
        method: str,
        params: dict,
        timeout: float = 20.0,
    ):
        doc = self._doc(path)
        session = await self._rpc_session(doc, timeout)
        lines = doc.lines()
        line_str = lines[line] if 0 <= line < len(lines) else ""
        return await self._transport.request(
            "$/lean/rpc/call",
            {
                "textDocument": {"uri": doc.uri},
                "position": {
                    "line": line,
                    "character": codepoint_to_utf16(line_str, col),
                },
                "sessionId": session,
                "method": method,
                "params": params,
            },
            timeout=timeout,
        )

    async def _rpc_session(self, doc: DocState, timeout: float) -> str:
        entry = self._rpc_sessions.get(doc.uri)
        now = time.monotonic()
        if entry is not None and now - entry[1] < 20.0:  # sessions expire at 30s
            self._rpc_sessions[doc.uri] = (entry[0], now)
            return entry[0]
        res = await self._transport.request(
            "$/lean/rpc/connect", {"uri": doc.uri}, timeout=timeout
        )
        session = res["sessionId"]
        self._rpc_sessions[doc.uri] = (session, now)
        return session

    async def get_widgets(
        self, path: str, line: int, col: int, fresh: bool = True
    ) -> list[dict]:
        if fresh:
            await self.barrier(path)
        doc = self._doc(path)
        lines = doc.lines()
        line_str = lines[line] if 0 <= line < len(lines) else ""
        res = await self.rpc_call(
            path,
            line,
            col,
            "Lean.Widget.getWidgets",
            {"line": line, "character": codepoint_to_utf16(line_str, col)},
        )
        return (res or {}).get("widgets", [])

    async def get_widget_source(
        self, path: str, line: int, col: int, widget_hash: str
    ) -> Optional[dict]:
        lines = self._doc(path).lines()
        line_str = lines[line] if 0 <= line < len(lines) else ""
        pos = {"line": line, "character": codepoint_to_utf16(line_str, col)}
        return await self.rpc_call(
            path, line, col, "Lean.Widget.getWidgetSource", {"pos": pos, "hash": widget_hash}
        )

    # -- location conversion --------------------------------------------------

    _file_lines_cache: dict[str, tuple[float, list[str]]] = {}

    def _convert_location(self, loc: dict) -> dict:
        """Convert a Location's range to codepoint columns.

        For locations in other files, the target line is read from disk
        (cached by mtime) so astral characters convert correctly.
        """
        uri = loc.get("uri") or (loc.get("targetUri") or "")
        rng_key = "range" if "range" in loc else "targetRange"
        rng = loc.get(rng_key)
        out = dict(loc)
        rel = self._uri_to_relpath(uri)
        out["path"] = rel
        if rng is None:
            return out
        doc = self._docs_by_uri.get(uri)
        if doc is not None:
            lines = doc.lines()
        else:
            lines = self._disk_lines(uri)
        out[rng_key] = range_from_utf16(lines, rng)
        if "targetSelectionRange" in loc:
            out["targetSelectionRange"] = range_from_utf16(
                lines, loc["targetSelectionRange"]
            )
        return out

    def _disk_lines(self, uri: str) -> list[str]:
        local = unquote(urlparse(uri).path)
        try:
            mtime = os.path.getmtime(local)
            cached = self._file_lines_cache.get(local)
            if cached is not None and cached[0] == mtime:
                return cached[1]
            lines = Path(local).read_text(errors="replace").splitlines()
            if len(self._file_lines_cache) > 64:
                self._file_lines_cache.clear()
            self._file_lines_cache[local] = (mtime, lines)
            return lines
        except OSError:
            return []
