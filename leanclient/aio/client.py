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
from typing import Literal, Optional, cast
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from .convert import (
    codepoint_to_utf16,
    range_from_utf16,
)
from .document import DocState, DocStatus
from .errors import (
    LeanClientError,
    LeanFileNotOpen,
    LeanRequestTimeout,
    LeanRpcError,
    LeanUnsupportedVersion,
    LeanWorkerCrashed,
)
from .transport import LspTransport

MIN_LEAN_VERSION = (4, 24)

# Lean-specific error codes (Lean.Data.Lsp.Utf16 / Watchdog)
_WORKER_ERROR_CODES = {-32901, -32902}  # workerExited, workerCrashed
_CONTENT_MODIFIED = -32801


def _as_dict_list(value: object) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


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

    ``partial`` is True when the elaboration barrier timed out: ``items`` may
    be incomplete and ``processing_ranges`` lists the (codepoint-converted)
    ranges the server was still elaborating. Poll again for a full report.
    """

    items: list[dict]
    version: Optional[int]
    fatal_error: bool = False
    partial: bool = False
    processing_ranges: list = field(default_factory=list)

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
        raw = (
            (Path(project_path) / "lean-toolchain").read_text(encoding="utf-8").strip()
        )
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
        server_command: Optional[list[str]] = None,
        report_delay_ms: Optional[int] = 0,
    ):
        self.project_path = str(Path(project_path).resolve())
        self.max_workers = max_workers or _default_max_workers()
        self.request_timeout = request_timeout
        self._check_version = check_version

        command = server_command or ["lake", "serve", "--"]
        if server_command is None and report_delay_ms is not None:
            command = [*command, f"-Dserver.reportDelayMs={report_delay_ms}"]
        self._transport = LspTransport(
            command,
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
        await self._start_impl()

    async def _start_impl(self) -> None:
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
                "capabilities": {
                    "lean": {
                        # Lean 4.32+: append incremental diagnostic updates
                        # instead of receiving the full quadratic prefix.
                        "incrementalDiagnosticSupport": True,
                    }
                },
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
        # NOTE: $/lean/waitForILeans is handled ON the watchdog's main loop
        # and blocks ALL message processing (didOpen included) until the
        # .ilean scan finishes — measured +20s on first requests when fired
        # eagerly. It is therefore only sent lazily, on the first
        # wait_for_ileans()/workspace_symbol(wait_for_index=...) call.
        self._ileans_ready = asyncio.Event()
        self._ileans_task: Optional[asyncio.Task] = None

    def _ensure_ileans_task(self) -> None:
        if self._ileans_task is None:
            self._ileans_task = asyncio.create_task(self._await_ileans())

    async def _await_ileans(self) -> None:
        try:
            await self._transport.request(
                "$/lean/waitForILeans", {}, timeout=self.request_timeout
            )
        except LeanClientError:
            pass  # index unavailable; searches degrade to partial results
        finally:
            self._ileans_ready.set()

    @property
    def ileans_ready(self) -> bool:
        """True once the workspace symbol/reference index is fully loaded."""
        return self._ileans_ready.is_set()

    async def wait_for_ileans(self, timeout: Optional[float] = None) -> bool:
        """Wait for the index; returns readiness (False on timeout).

        First call triggers the (watchdog-blocking) index barrier — avoid
        interleaving with cold file opens where possible.
        """
        self._ensure_ileans_task()
        try:
            await asyncio.wait_for(
                self._ileans_ready.wait(), timeout=timeout or self.request_timeout
            )
        except asyncio.TimeoutError:
            return False
        return self.ileans_ready

    async def close(self) -> None:
        self._started = False
        task = getattr(self, "_ileans_task", None)
        if task is not None and not task.done():
            task.cancel()
        await self._transport.close()
        self._docs.clear()
        self._docs_by_uri.clear()

    @property
    def alive(self) -> bool:
        return self._started and self._transport.alive

    # -- uri/path helpers ----------------------------------------------------

    def _path_to_uri(self, path: str) -> str:
        # as_uri() keeps the drive letter in the path on Windows; the
        # pathname2url form ("file://" + "///C:/...") produces a broken URI.
        abs_path = Path(self.project_path) / path
        return abs_path.as_uri()

    def _uri_to_abs(self, uri: str) -> str:
        # Decode first so Windows recognizes a percent-encoded drive colon.
        return url2pathname(unquote(urlparse(uri).path))

    def _uri_to_relpath(self, uri: str) -> str:
        local = self._uri_to_abs(uri)
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
        self,
        path: str,
        text: Optional[str] = None,
        wait: bool = True,
        dependency_build_mode: str = "never",
    ) -> DocState:
        """Open a file (or a virtual document when ``text`` is given).

        Virtual documents get a path under the project root that need not
        exist on disk; the server elaborates the provided text.

        ``dependency_build_mode`` controls whether the server may run
        ``lake`` to build missing/out-of-date dependencies for this file:
        "never" (default), "once", or "always".
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
                text = (Path(self.project_path) / path).read_text(encoding="utf-8")
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
                    },
                    "dependencyBuildMode": dependency_build_mode,
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
        doc.replace_text(text)
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
        disk = (Path(self.project_path) / path).read_text(encoding="utf-8")
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
        return await self.open(
            path, text=text if doc and doc.virtual else None, wait=wait
        )

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
        requested_version = doc.version
        if doc.barrier_version is not None and doc.barrier_version >= requested_version:
            doc.touch()
            return
        doc.refcount += 1
        try:
            await self._transport.request(
                "textDocument/waitForDiagnostics",
                {"uri": doc.uri, "version": requested_version},
                timeout=timeout or self.request_timeout,
            )
            doc.barrier_version = max(
                doc.barrier_version or requested_version, requested_version
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
        self,
        path: str,
        fresh: bool = True,
        timeout: Optional[float] = None,
        partial_ok: bool = False,
    ) -> DiagnosticsReport:
        """Diagnostics for ``path``; fresh (barrier-gated) by default.

        With ``partial_ok=True`` a barrier timeout returns a report with
        ``partial=True`` and the still-processing ranges instead of raising —
        the caller can poll again rather than treating slowness as failure.
        """
        doc = self._doc(path)
        partial = False
        if fresh:
            try:
                await self.barrier(path, timeout=timeout)
            except LeanRequestTimeout:
                if not partial_ok:
                    raise
                partial = True
        lines = doc.lines()
        items = []
        for diag in doc.diagnostics:
            d = dict(diag)
            for key in ("range", "fullRange"):
                if key in d and d[key]:
                    d[key] = range_from_utf16(lines, d[key])
            items.append(d)
        processing = []
        if partial:
            for entry in doc.processing:
                rng = entry.get("range")
                if rng:
                    processing.append(range_from_utf16(lines, rng))
        return DiagnosticsReport(
            items=items,
            version=doc.diagnostics_version,
            fatal_error=doc.fatal_error,
            partial=partial,
            processing_ranges=processing,
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
        return GoalResult(
            status="goals", goals=list(goals), rendered=res.get("rendered")
        )

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
        res = await self._transport.request(
            "completionItem/resolve", item, timeout=timeout
        )
        if not isinstance(res, dict):
            raise LeanClientError(
                "completionItem/resolve returned a non-object response"
            )
        return res

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
        return _as_dict_list(res)

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
        return _as_dict_list(res)

    async def code_action_resolve(self, action: dict, timeout: float = 30.0) -> dict:
        res = await self._transport.request(
            "codeAction/resolve", action, timeout=timeout
        )
        if not isinstance(res, dict):
            raise LeanClientError("codeAction/resolve returned a non-object response")
        return res

    async def workspace_symbol(
        self,
        query: str,
        max_results: Optional[int] = None,
        wait_for_index: float = 0.0,
        timeout: float = 30.0,
    ) -> tuple[list[dict], bool]:
        """Fuzzy, score-ranked symbol search over the project AND all
        compiled dependencies (watchdog-served from the .ilean index).

        Returns ``(symbols, index_ready)``. Results are partial until the
        index finishes loading; pass ``wait_for_index`` seconds to wait for
        completeness first. Locations are converted to codepoint columns.
        """
        if wait_for_index > 0 and not self.ileans_ready:
            await self.wait_for_ileans(timeout=wait_for_index)
        res = await self._transport.request(
            "workspace/symbol", {"query": query}, timeout=timeout
        )
        symbols = _as_dict_list(res)
        if max_results is not None:
            symbols = symbols[:max_results]
        out = []
        for sym in symbols:
            converted = dict(sym)
            loc = sym.get("location")
            if loc:
                converted["location"] = self._convert_location(loc)
            out.append(converted)
        return out, self.ileans_ready

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
        if not isinstance(res, dict):
            raise LeanClientError("$/lean/rpc/connect returned no sessionId")
        data = cast(dict[str, object], res)
        session = data.get("sessionId")
        if not isinstance(session, str):
            raise LeanClientError("$/lean/rpc/connect returned no sessionId")
        self._rpc_sessions[doc.uri] = (session, now)
        return session

    async def interactive_goals(
        self, path: str, line: int, col: int, fresh: bool = True
    ) -> Optional[dict]:
        """Structured goals via ``Lean.Widget.getInteractiveGoals``: hypothesis
        bundles (names, types, instance/type flags, inserted/removed deltas),
        goal mvar ids and case names. Types come as TaggedText trees.
        """
        if fresh:
            await self.barrier(path)
        doc = self._doc(path)
        lines = doc.lines()
        line_str = lines[line] if 0 <= line < len(lines) else ""
        pos = {"line": line, "character": codepoint_to_utf16(line_str, col)}
        return await self.rpc_call(
            path,
            line,
            col,
            "Lean.Widget.getInteractiveGoals",
            {"textDocument": {"uri": doc.uri}, "position": pos},
        )

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
            path,
            line,
            col,
            "Lean.Widget.getWidgetSource",
            {"pos": pos, "hash": widget_hash},
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
        local = self._uri_to_abs(uri)
        try:
            mtime = os.path.getmtime(local)
            cached = self._file_lines_cache.get(local)
            if cached is not None and cached[0] == mtime:
                return cached[1]
            lines = (
                Path(local).read_text(encoding="utf-8", errors="replace").splitlines()
            )
            if len(self._file_lines_cache) > 64:
                self._file_lines_cache.clear()
            self._file_lines_cache[local] = (mtime, lines)
            return lines
        except OSError:
            return []
