import asyncio
import atexit
import logging
import os
import subprocess
import threading
import urllib.parse
from pathlib import Path
from typing import Any, Callable

import orjson
import psutil

from .utils import SemanticTokenProcessor, needs_mathlib_cache_get

logger = logging.getLogger(__name__)

# Methods from the server that should be ignored
IGNORED_METHODS = {
    "workspace/didChangeWatchedFiles",
    "workspace/semanticTokens/refresh",
    "client/registerCapability",
    "workspace/inlayHint/refresh",
}
ENABLE_LEANCLIENT_HISTORY = (
    os.getenv("ENABLE_LEANCLIENT_HISTORY", "false").lower() == "true"
)


class LSPProtocolError(RuntimeError):
    """Raised when the language server writes an invalid LSP frame."""


class BaseLeanLSPClient:
    """BaseLeanLSPClient runs a language server in a subprocess.

    See :meth:`leanclient.client.LeanLSPClient` for more information.
    """

    def __init__(
        self,
        project_path: str,
        initial_build: bool = False,
        prevent_cache_get: bool = False,
    ):
        self.project_path = Path(project_path).resolve()
        self.request_id = 0  # Counter for generating unique request IDs
        self.enable_history = ENABLE_LEANCLIENT_HISTORY
        self.history = []  # List of requests/responses sent/received from the server

        if initial_build:
            self.build_project(get_cache=not prevent_cache_get)
        elif not prevent_cache_get and needs_mathlib_cache_get(self.project_path):
            # Only run cache get if mathlib dep exists AND olean files missing
            subprocess.run(
                ["lake", "exe", "cache", "get"],
                cwd=self.project_path,
                check=False,
                stderr=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
            )

        # Run the lean4 language server in a subprocess
        # -Dserver.reportDelayMs=0 bc we don't need debouncing
        self.process = subprocess.Popen(
            ["lake", "serve", "--", "-Dserver.reportDelayMs=0"],
            cwd=self.project_path,
            stdout=subprocess.PIPE,
            stdin=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        assert self.process.stdin is not None
        assert self.process.stdout is not None
        self.stdin = self.process.stdin
        self.stdout = self.process.stdout

        # Asyncio infrastructure for non-blocking requests
        self._loop = asyncio.new_event_loop()
        self._futures = {}  # {request_id: asyncio.Future}
        self._futures_lock = threading.Lock()  # guards _futures and request_id
        self._write_lock = threading.Lock()  # serializes writes to stdin
        self._notification_handlers: dict[str, Callable[[dict], Any]] = {}
        self._reader_error: Exception | None = None

        # Start event loop in a separate thread
        self._loop_thread = threading.Thread(
            target=self._run_event_loop,
            daemon=True,
        )
        self._loop_thread.start()

        # Thread to read stdout
        self._stdout_thread_stop_event = threading.Event()
        self._stdout_thread = threading.Thread(
            target=self._read_stdout_loop,
            args=(self._stdout_thread_stop_event,),
            daemon=True,
        )
        self._stdout_thread.start()

        # RPC session management for widgets
        self._rpc_sessions: dict[str, str] = {}  # uri -> sessionId

        # Initialize language server. Options can be found here:
        # https://github.com/leanprover/lean4/blob/a955708b6c5f25e7f9c9ae7b951f8f3d5aefe377/src/Lean/Data/Lsp/InitShutdown.lean
        server_info = self._send_request_sync(
            "initialize",
            {
                "processId": os.getpid(),
                "rootUri": self._local_to_uri(self.project_path),
                "initializationOptions": {
                    "editDelay": 1,  # It seems like this has no effect.
                    "hasWidgets": True,  # Enable widget support for interactive diagnostics
                },
            },
        )

        legend = server_info["capabilities"]["semanticTokensProvider"]["legend"]
        self.token_processor = SemanticTokenProcessor(legend["tokenTypes"])

        self._send_notification("initialized", {})

        # Register cleanup at exit in case user forgets to call close()
        atexit.register(self.close)

    def build_project(self, get_cache: bool = True):
        """Build the Lean project by running `lake build`.

        Args:
            get_cache (bool): Whether to run `lake exe cache get` before building.
        """
        if get_cache:
            subprocess.run(
                ["lake", "exe", "cache", "get"], cwd=self.project_path, check=False
            )
        subprocess.run(["lake", "build"], cwd=self.project_path, check=True)

    def close(self, timeout: float | None = 2):
        """Always close the client when done!

        Terminates the language server process and cleans up resources.

        Args:
            timeout (float | None): Time to wait for the process to terminate. Defaults to 2 seconds.
        """
        # Unregister atexit handler since we're closing properly
        try:
            atexit.unregister(self.close)
        except Exception:
            pass

        # Terminate the language server process
        ## terminate children processes: `ps aux | grep lean`
        try:
            children = psutil.Process(self.process.pid).children(recursive=True)
            for child in children:
                child.kill()
        except psutil.NoSuchProcess:
            pass
        ## terminate main process: `ps aux | grep lake`
        self.process.terminate()

        try:
            self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            logger.warning(
                "Language server did not terminate in time. Killing process."
            )
            self.process.kill()
            self.process.wait()

        # Signal stdout thread to stop and stop event loop
        self._stdout_thread_stop_event.set()
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)

        # Close event loop (wait a moment for it to stop gracefully)
        if self._loop and not self._loop.is_closed():
            # Give the loop thread a moment to finish
            self._loop_thread.join(timeout=0.5)
            if not self._loop.is_closed():
                try:
                    self._loop.close()
                except RuntimeError:
                    # Event loop might still be running, force close in thread
                    pass

    # URI HANDLING
    @staticmethod
    def _normalize_local_path(local_path: str | os.PathLike[str]) -> str:
        """Normalize Lean project-local paths to forward slashes."""
        return urllib.parse.unquote(str(local_path)).replace("\\", "/")

    def _local_to_uri(self, local_path: str | os.PathLike[str]) -> str:
        """Convert a local file path to a URI.

        User API is based on local file paths (relative to project path) but internally we use URIs.
        Example:

        - local path:  MyProject/LeanFile.lean
        - URI:         file:///abs/to/project_path/MyProject/LeanFile.lean

        Args:
            local_path (str): Relative file path.

        Returns:
            str: URI representation of the file.
        """
        path = (
            self.project_path / Path(self._normalize_local_path(local_path))
        ).resolve()
        return urllib.parse.unquote(path.as_uri())

    def _locals_to_uris(self, local_paths: list[str]) -> list[str]:
        """See :meth:`_local_to_uri`"""
        return [self._local_to_uri(path) for path in local_paths]

    def _uri_to_abs(self, uri: str) -> Path:
        """See :meth:`_local_to_uri`"""
        parsed = urllib.parse.urlparse(uri)
        if parsed.scheme and parsed.scheme != "file":
            raise ValueError(f"Unsupported URI scheme: {parsed.scheme}")

        path = urllib.parse.unquote(parsed.path)
        # On windows we need to remove the leading slash
        if os.name == "nt" and path.startswith("/"):
            path = path[1:]
        return Path(path)

    def _uri_to_local(self, uri: str) -> str:
        """See :meth:`_local_to_uri`"""
        abs_path = self._uri_to_abs(uri).resolve()
        try:
            rel_path = abs_path.relative_to(self.project_path)
        except ValueError:
            return abs_path.as_posix()
        return rel_path.as_posix()

    # LANGUAGE SERVER RPC INTERACTION
    def clear_history(self):
        """Clear all stored LSP communication history entries.

        Note: History tracking is controlled by the ENABLE_LEANCLIENT_HISTORY environment
        variable at initialization, or can be enabled at runtime via `enable_history = True`.

        Example:
            >>> client.enable_history = True
            >>> # ... some LSP communications occur ...
            >>> len(client.history)
            5
            >>> client.enable_history = False
            >>> client.clear_history()
            >>> len(client.history)
            0
        """
        self.history.clear()

    def _run_event_loop(self):
        """Run the asyncio event loop in a separate thread."""
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    @staticmethod
    def _set_future_exception_if_pending(
        future: asyncio.Future, error: Exception
    ) -> None:
        """Fail a future unless another response already completed it."""
        if not future.done():
            future.set_exception(error)

    def _fail_pending_futures(self, error: Exception) -> None:
        """Remember a terminal reader failure and fail every pending request."""
        with self._futures_lock:
            if self._reader_error is None:
                self._reader_error = error
            pending = list(self._futures.values())
            self._futures.clear()

        if self._loop and not self._loop.is_closed():
            for future in pending:
                self._loop.call_soon_threadsafe(
                    self._set_future_exception_if_pending, future, error
                )

    def _read_stdout_message(self) -> dict[str, Any]:
        """Read and validate one Content-Length framed LSP message."""
        headers: dict[str, str] = {}
        raw_headers: list[str] = []

        while True:
            header_line = self.stdout.readline()
            if not header_line:
                raise EOFError("Language server process exited unexpectedly.")

            header = header_line.decode("utf-8", errors="replace").rstrip("\r\n")
            if not header:
                break

            raw_headers.append(header)
            name, separator, value = header.partition(":")
            normalized_name = name.strip().lower()
            if not separator or not normalized_name:
                raise LSPProtocolError(f"Malformed LSP header line: {header[:200]!r}")
            if normalized_name in headers:
                raise LSPProtocolError(
                    f"Duplicate LSP header {name.strip()!r}: {header[:200]!r}"
                )
            headers[normalized_name] = value.strip()

        raw_content_length = headers.get("content-length")
        if raw_content_length is None:
            rendered_headers = ", ".join(repr(header[:200]) for header in raw_headers)
            raise LSPProtocolError(
                f"Missing Content-Length LSP header; received [{rendered_headers}]"
            )

        if not raw_content_length.isascii() or not raw_content_length.isdigit():
            raise LSPProtocolError(
                f"Invalid Content-Length LSP header: {raw_content_length!r}"
            )
        content_length = int(raw_content_length)

        body = self.stdout.read(content_length)
        if len(body) != content_length:
            raise LSPProtocolError(
                "Language server closed before the complete LSP message body "
                f"arrived: expected {content_length} bytes, got {len(body)}"
            )

        try:
            message = orjson.loads(body)
        except orjson.JSONDecodeError as exc:
            raise LSPProtocolError("Language server wrote invalid LSP JSON.") from exc
        if not isinstance(message, dict):
            raise LSPProtocolError(
                f"Language server wrote a non-object LSP message: {type(message).__name__}"
            )
        return message

    def _read_stdout_loop(self, stop_event: threading.Event):
        """Read the stdout of the language server in a separate thread.

        This is necessary to avoid blocking the main thread.
        Dispatches responses to futures and notifications to handlers.
        """
        while not stop_event.is_set():
            if self.stdout.closed:
                self._fail_pending_futures(
                    EOFError("Language server process exited unexpectedly.")
                )
                break

            try:
                msg = self._read_stdout_message()
            except EOFError as exc:
                if not stop_event.is_set():
                    self._fail_pending_futures(exc)
                break
            except Exception as exc:
                error = (
                    exc
                    if isinstance(exc, LSPProtocolError)
                    else LSPProtocolError(f"Failed to read LSP message: {exc}")
                )
                logger.exception("Language server emitted an invalid LSP frame")
                self._fail_pending_futures(error)
                break

            # Dispatch to futures and notification handlers
            msg_id = msg.get("id")
            method = msg.get("method")

            if self.enable_history:
                self.history.append({"type": "server", "content": msg})

            # Ignore certain methods from the server
            if method in IGNORED_METHODS:
                continue

            # Handle response to a request
            future = None
            if msg_id is not None:
                with self._futures_lock:
                    future = self._futures.pop(msg_id, None)
            if future is not None:
                # Check if event loop is still running before dispatching
                if self._loop and not self._loop.is_closed():
                    if "error" in msg:
                        self._loop.call_soon_threadsafe(
                            future.set_exception,
                            Exception(f"LSP Error: {msg['error']}"),
                        )
                    else:
                        self._loop.call_soon_threadsafe(
                            future.set_result, msg.get("result", msg)
                        )
                continue

            # Handle notification with registered handler
            if method is not None:
                handler = self._notification_handlers.get(method)
                if handler:
                    try:
                        handler(msg)
                    except Exception as e:
                        logger.warning(f"Notification handler for {method} failed: {e}")

    def _write_message(self, message: dict) -> None:
        """Serialize and write a JSON-RPC message to the server's stdin.

        Writes are serialized with a lock so messages from different threads
        cannot interleave on the pipe.

        Args:
            message (dict): Full JSON-RPC message (including ``id`` for requests).
        """
        body = orjson.dumps(message)
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        with self._write_lock:
            self.stdin.write(header + body)
            self.stdin.flush()

        if self.enable_history:
            self.history.append({"type": "client", "content": message})

    def _send_notification(self, method: str, params: dict):
        """Send a notification to the language server.

        Args:
            method (str): Method name.
            params (dict): Parameters for the method.
        """
        self._write_message({"jsonrpc": "2.0", "method": method, "params": params})

    def _send_request_async(self, method: str, params: dict) -> asyncio.Future:
        """Send a request and return an asyncio.Future immediately (non-blocking).

        The future is registered before the request is written, so a fast
        response read by the stdout thread cannot arrive before the future
        exists to receive it.

        Args:
            method (str): Method name.
            params (dict): Parameters for the method.

        Returns:
            asyncio.Future: Future that will be resolved when the response arrives.
        """
        future = self._loop.create_future()
        reader_error = None
        with self._futures_lock:
            if self._reader_error is not None:
                reader_error = self._reader_error
            else:
                request_id = self.request_id
                self.request_id += 1
                self._futures[request_id] = future

        if reader_error is not None:
            self._loop.call_soon_threadsafe(
                self._set_future_exception_if_pending, future, reader_error
            )
            return future

        self._write_message(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        )
        return future

    def _send_request_sync(
        self, method: str, params: dict, timeout: float | None = 120.0
    ) -> Any:
        """Send a request and block until response arrives.

        Args:
            method (str): Method name.
            params (dict): Parameters for the method.
            timeout (float | None): Timeout in seconds. Defaults to 120.

        Returns:
            dict: Response from the language server.
        """
        async_future = self._send_request_async(method, params)

        # Wrap the future in an awaitable coroutine
        async def await_future():
            return await async_future

        # Use asyncio.run_coroutine_threadsafe to bridge async to sync
        return asyncio.run_coroutine_threadsafe(await_future(), self._loop).result(
            timeout=timeout
        )

    def _register_notification_handler(self, method: str, handler):
        """Register a handler for a specific notification method.

        Args:
            method (str): Notification method name (e.g., "textDocument/publishDiagnostics").
            handler: Callable that takes the notification message as argument.
        """
        self._notification_handlers[method] = handler

    def _unregister_notification_handler(self, method: str):
        """Unregister a notification handler.

        Args:
            method (str): Notification method name.
        """
        self._notification_handlers.pop(method, None)

    # LEAN RPC (for widgets) - internal methods, not part of public API
    def _rpc_connect(self, uri: str, timeout: float = 10) -> str:
        """Connect to Lean RPC for a file and get a session ID.

        The Lean server provides RPC capabilities for interactive features like widgets.
        This method establishes an RPC session for a file, which is required before
        making RPC calls.

        Note:
            This is an internal method. Session management is handled automatically
            by the widget methods.

        Args:
            uri (str): File URI (use _local_to_uri to convert local paths).
            timeout (float): Timeout in seconds. Defaults to 10.

        Returns:
            str: Session ID for use in subsequent RPC calls.

        Raises:
            RuntimeError: If session ID cannot be obtained.
        """
        if uri in self._rpc_sessions:
            return self._rpc_sessions[uri]

        result = self._send_request_sync(
            "$/lean/rpc/connect", {"uri": uri}, timeout=timeout
        )
        session_id = result.get("sessionId")
        if not session_id:
            raise RuntimeError(f"Failed to get RPC session for {uri}")
        self._rpc_sessions[uri] = session_id
        return session_id

    def _rpc_call(
        self,
        uri: str,
        method: str,
        params: dict,
        line: int = 0,
        character: int = 0,
        timeout: float = 15,
    ) -> dict:
        """Make an RPC call to the Lean server.

        RPC calls are used for interactive features like widgets. Common methods include:
        - "Lean.Widget.getWidgets": Get panel widgets at a position
        - "Lean.Widget.getInteractiveDiagnostics": Get diagnostics with embedded widgets

        Note:
            This is an internal method. Use the public widget methods instead.

        Args:
            uri (str): File URI.
            method (str): RPC method name (e.g., "Lean.Widget.getWidgets").
            params (dict): Parameters to pass to the RPC method.
            line (int): Line number for snapshot lookup (0-indexed). Defaults to 0.
            character (int): Character number for snapshot lookup (0-indexed). Defaults to 0.
            timeout (float): Timeout in seconds. Defaults to 15.

        Returns:
            dict: Response from the RPC call.
        """
        session_id = self._rpc_connect(uri, timeout=timeout)

        call_params = {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": character},
            "sessionId": session_id,
            "method": method,
            "params": params,
        }
        return self._send_request_sync("$/lean/rpc/call", call_params, timeout=timeout)

    def _rpc_release_session(self, uri: str) -> None:
        """Release an RPC session for a file.

        Called when a file is closed/reopened to prevent stale sessions.

        Args:
            uri (str): File URI.
        """
        self._rpc_sessions.pop(uri, None)

    # HELPERS
    def get_env(self, return_dict: bool = True) -> dict | str:
        """Get the environment variables of the project.

        Args:
            return_dict (bool): Return as dict or string.

        Returns:
            dict | str: Environment variables.
        """
        response = subprocess.run(
            ["lake", "env"], cwd=self.project_path, capture_output=True, text=True
        )
        if not return_dict:
            return response.stdout

        env = {}
        for line in response.stdout.split("\n"):
            if not line:
                continue
            key, value = line.split("=", 1)
            env[key] = value
        return env
