"""Async JSON-RPC/LSP transport over a ``lake serve`` subprocess.

Responsibilities (and nothing else):
- spawn/kill the process, keep a bounded stderr tail for diagnostics
- frame and parse LSP messages (robust header handling)
- match responses to requests via futures; fail ALL pending futures on
  transport death (in ``finally`` — a malformed message can never wedge the
  client)
- answer server->client requests (registerCapability etc.)
- dispatch notifications to a callback
- send ``$/cancelRequest`` when a request is cancelled or times out
"""

from __future__ import annotations

import asyncio
import itertools
from collections import deque
from typing import Callable, Optional

import orjson

from .errors import (
    LeanRequestCancelled,
    LeanRequestTimeout,
    LeanRpcError,
    LeanTransportError,
)

REQUEST_CANCELLED = -32800
METHOD_NOT_FOUND = -32601

# Server->client requests we acknowledge with a null result.
_ACK_REQUESTS = {
    "client/registerCapability",
    "client/unregisterCapability",
    "workspace/semanticTokens/refresh",
    "workspace/inlayHint/refresh",
    "workspace/codeLens/refresh",
    "workspace/diagnostic/refresh",
}

_STDERR_TAIL_BYTES = 64 * 1024


class LspTransport:
    def __init__(
        self,
        command: list[str],
        cwd: str,
        on_notification: Callable[[str, dict], None],
        default_timeout: float = 300.0,
        on_server_request: Optional[Callable[[str, dict], None]] = None,
    ):
        self._command = command
        self._cwd = cwd
        self._on_notification = on_notification
        self._on_server_request = on_server_request
        self._default_timeout = default_timeout

        self._proc: Optional[asyncio.subprocess.Process] = None
        self._ids = itertools.count(1)
        self._futures: dict[int, asyncio.Future] = {}
        self._write_lock = asyncio.Lock()
        self._stderr_tail: deque[bytes] = deque()
        self._stderr_len = 0
        self._reader_task: Optional[asyncio.Task] = None
        self._stderr_task: Optional[asyncio.Task] = None
        self._closed = asyncio.Event()
        self._death: Optional[LeanTransportError] = None

    # -- lifecycle -----------------------------------------------------------

    @property
    def alive(self) -> bool:
        return (
            self._proc is not None
            and self._proc.returncode is None
            and not self._closed.is_set()
        )

    def stderr_tail(self) -> str:
        return b"".join(self._stderr_tail).decode(errors="replace")

    async def start(self) -> None:
        self._proc = await asyncio.create_subprocess_exec(
            *self._command,
            cwd=self._cwd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=64 * 1024 * 1024,  # single LSP messages can be large
            start_new_session=True,  # own process group: killpg reaps workers
        )
        self._reader_task = asyncio.create_task(self._read_loop())
        self._stderr_task = asyncio.create_task(self._stderr_loop())

    async def close(self) -> None:
        if self._closed.is_set():
            return
        self._die(LeanTransportError("Transport closed", self.stderr_tail()))
        if self._proc is not None:
            if self._proc.stdin is not None:
                try:
                    self._proc.stdin.close()
                except (OSError, RuntimeError):
                    pass
            self._kill_group()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                pass
        for task in (self._reader_task, self._stderr_task):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        await asyncio.sleep(0)  # let pipe transports finish connection_lost

    def _kill_group(self) -> None:
        """SIGKILL the server's whole process group (lake + watchdog + workers)."""
        import os
        import platform
        import signal

        if self._proc is None:
            return
        if platform.system() == "Windows":
            try:
                self._proc.kill()
            except ProcessLookupError:
                pass
            return

        try:
            os.killpg(os.getpgid(self._proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                self._proc.kill()
            except ProcessLookupError:
                pass

    def _die(self, exc: LeanTransportError) -> None:
        """Mark the transport dead and fail every pending future."""
        if self._closed.is_set():
            return
        self._death = exc
        self._closed.set()
        futures, self._futures = self._futures, {}
        for fut in futures.values():
            if not fut.done():
                fut.set_exception(exc)

    # -- read side -----------------------------------------------------------

    async def _stderr_loop(self) -> None:
        assert self._proc is not None and self._proc.stderr is not None
        try:
            while True:
                chunk = await self._proc.stderr.read(4096)
                if not chunk:
                    return
                self._stderr_tail.append(chunk)
                self._stderr_len += len(chunk)
                while (
                    self._stderr_len > _STDERR_TAIL_BYTES and len(self._stderr_tail) > 1
                ):
                    self._stderr_len -= len(self._stderr_tail.popleft())
        except asyncio.CancelledError:
            pass

    async def _read_loop(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        rd = self._proc.stdout
        try:
            while True:
                content_length = None
                # Parse headers until blank line; tolerate any header order.
                while True:
                    line = await rd.readline()
                    if not line:
                        raise LeanTransportError(
                            "Language server closed the connection",
                            self.stderr_tail(),
                        )
                    line = line.strip()
                    if not line:
                        break
                    if line.lower().startswith(b"content-length:"):
                        try:
                            content_length = int(line.split(b":", 1)[1])
                        except ValueError:
                            raise LeanTransportError(
                                f"Malformed Content-Length header: {line!r}",
                                self.stderr_tail(),
                            )
                if content_length is None:
                    raise LeanTransportError(
                        "Message without Content-Length header", self.stderr_tail()
                    )
                body = await rd.readexactly(content_length)
                try:
                    msg = orjson.loads(body)
                except orjson.JSONDecodeError as e:
                    raise LeanTransportError(
                        f"Malformed JSON from server: {e}", self.stderr_tail()
                    )
                self._dispatch(msg)
        except asyncio.CancelledError:
            raise
        except LeanTransportError as e:
            self._die(e)
        except Exception as e:  # anything else: fail everything, never wedge
            self._die(LeanTransportError(f"Reader failed: {e!r}", self.stderr_tail()))

    def _dispatch(self, msg: dict) -> None:
        method = msg.get("method")
        msg_id = msg.get("id")
        if method is not None and msg_id is not None:
            # Server->client REQUEST (never a response, even on id collision).
            asyncio.ensure_future(
                self._answer_server_request(msg_id, method, msg.get("params") or {})
            )
            return
        if msg_id is not None:
            fut = self._futures.pop(msg_id, None)
            if fut is None or fut.done():
                return  # cancelled/timed-out request; drop the late response
            if "error" in msg:
                err = msg["error"] or {}
                code = err.get("code", 0)
                if code == REQUEST_CANCELLED:
                    fut.set_exception(LeanRequestCancelled(err.get("message", "")))
                else:
                    fut.set_exception(
                        LeanRpcError(code, err.get("message", ""), err.get("data"))
                    )
            else:
                fut.set_result(msg.get("result"))
            return
        if method is not None:
            try:
                self._on_notification(method, msg.get("params") or {})
            except Exception:
                pass  # a broken notification handler must not kill the reader

    async def _answer_server_request(self, msg_id, method: str, params: dict) -> None:
        if method in _ACK_REQUESTS:
            if self._on_server_request is not None:
                try:
                    self._on_server_request(method, params)
                except Exception:
                    pass  # server requests must never kill the transport
            payload = {"jsonrpc": "2.0", "id": msg_id, "result": None}
        else:
            payload = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": METHOD_NOT_FOUND,
                    "message": f"Unsupported: {method}",
                },
            }
        try:
            await self._write(payload)
        except LeanTransportError:
            pass

    # -- write side ----------------------------------------------------------

    async def _write(self, payload: dict) -> None:
        if not self.alive:
            raise self._death or LeanTransportError("Transport not started")
        body = orjson.dumps(payload)
        frame = b"Content-Length: %d\r\n\r\n" % len(body) + body
        async with self._write_lock:
            assert self._proc is not None and self._proc.stdin is not None
            try:
                self._proc.stdin.write(frame)
                await self._proc.stdin.drain()
            except (ConnectionResetError, BrokenPipeError) as e:
                exc = LeanTransportError(f"Write failed: {e}", self.stderr_tail())
                self._die(exc)
                raise exc

    async def notify(self, method: str, params: dict) -> None:
        await self._write({"jsonrpc": "2.0", "method": method, "params": params})

    async def request(
        self, method: str, params: dict, timeout: Optional[float] = None
    ) -> object:
        """Send a request; return the ``result`` field.

        Raises :class:`LeanRpcError` on error responses,
        :class:`LeanRequestTimeout` on deadline (a ``$/cancelRequest`` is sent
        and the local future is dropped), :class:`LeanTransportError` if the
        connection dies while waiting.
        """
        if timeout is None:
            timeout = self._default_timeout
        req_id = next(self._ids)
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._futures[req_id] = fut
        try:
            await self._write(
                {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
            )
        except BaseException:
            self._futures.pop(req_id, None)
            raise
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            await self._abandon(req_id)
            raise LeanRequestTimeout(f"{method} timed out after {timeout}s") from None
        except asyncio.CancelledError:
            await self._abandon(req_id)
            raise

    async def _abandon(self, req_id: int) -> None:
        """Drop a pending request locally and tell the server to cancel it."""
        self._futures.pop(req_id, None)
        if self.alive:
            try:
                await self.notify("$/cancelRequest", {"id": req_id})
            except LeanTransportError:
                pass
