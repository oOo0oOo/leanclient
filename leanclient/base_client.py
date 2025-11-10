import os
import subprocess
import urllib.parse
import threading
import asyncio
import logging
import atexit
from pathlib import Path
from typing import Any, Callable

import orjson

from .utils import SemanticTokenProcessor, has_mathlib_dependency

logger = logging.getLogger(__name__)

# Methods from the server that should be ignored
IGNORED_METHODS = {
    "workspace/didChangeWatchedFiles",
    "workspace/semanticTokens/refresh",
    "client/registerCapability",
    "workspace/inlayHint/refresh",
}


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

        if initial_build:
            self.build_project(get_cache=not prevent_cache_get)
        elif not prevent_cache_get and has_mathlib_dependency(self.project_path):
            # Get cached builds for mathlib projects to avoid slow on-demand builds
            subprocess.run(
                ["lake", "exe", "cache", "get"],
                cwd=self.project_path,
                check=False,
                stderr=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
            )

        # Run the lean4 language server in a subprocess
        self.process = subprocess.Popen(
            ["lake", "serve"],
            cwd=self.project_path,
            stdout=subprocess.PIPE,
            stdin=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        self.stdin = self.process.stdin
        self.stdout = self.process.stdout

        # Asyncio infrastructure for non-blocking requests
        self._loop = asyncio.new_event_loop()
        self._futures = {}  # {request_id: asyncio.Future}
        self._notification_handlers: dict[str, Callable[[dict], Any]] = {}

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

        # Initialize language server. Options can be found here:
        # https://github.com/leanprover/lean4/blob/a955708b6c5f25e7f9c9ae7b951f8f3d5aefe377/src/Lean/Data/Lsp/InitShutdown.lean
        server_info = self._send_request_sync(
            "initialize",
            {
                "processId": os.getpid(),
                "rootUri": self._local_to_uri(self.project_path),
                "initializationOptions": {
                    "editDelay": 1  # It seems like this has no effect.
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
        path = (self.project_path / Path(local_path)).resolve()
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
            return str(abs_path)
        return str(rel_path)

    # LANGUAGE SERVER RPC INTERACTION
    def _run_event_loop(self):
        """Run the asyncio event loop in a separate thread."""
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _read_stdout_loop(self, stop_event: threading.Event):
        """Read the stdout of the language server in a separate thread.

        This is necessary to avoid blocking the main thread.
        Dispatches responses to futures and notifications to handlers.
        """
        while not stop_event.is_set():
            if self.stdout.closed:
                break

            try:
                header = self.stdout.readline()
            except (EOFError, ValueError):
                break

            if not header:
                break

            # Parse message
            # Use errors='replace' to handle invalid UTF-8 bytes on Windows
            header = header.decode("utf-8", errors="replace")
            content_length = int(header.split(":")[1])
            next(self.stdout)
            msg = orjson.loads(self.stdout.read(content_length))

            # Dispatch to futures and notification handlers
            msg_id = msg.get("id")
            method = msg.get("method")

            # Ignore certain methods from the server
            if method in IGNORED_METHODS:
                continue

            # Handle response to a request
            if msg_id is not None and msg_id in self._futures:
                future = self._futures.pop(msg_id)
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

    def _send_request_rpc(
        self, method: str, params: dict, is_notification: bool
    ) -> int | None:
        """Send a JSON RPC request to the language server.

        Args:
            method (str): Method name.
            params (dict): Parameters for the method.
            is_notification (bool): Whether the request is a notification.

        Returns:
            int | None: Id of the request if it is not a notification.
        """
        if not is_notification:
            request_id = self.request_id
            self.request_id += 1

        request = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            **({"id": request_id} if not is_notification else {}),
        }

        body = orjson.dumps(request)
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        self.stdin.write(header + body)
        self.stdin.flush()

        if not is_notification:
            return request_id

    def _send_notification(self, method: str, params: dict):
        """Send a notification to the language server.

        Args:
            method (str): Method name.
            params (dict): Parameters for the method.
        """
        self._send_request_rpc(method, params, is_notification=True)

    def _send_request_async(self, method: str, params: dict) -> asyncio.Future:
        """Send a request and return an asyncio.Future immediately (non-blocking).

        Args:
            method (str): Method name.
            params (dict): Parameters for the method.

        Returns:
            asyncio.Future: Future that will be resolved when the response arrives.
        """
        req_id = self._send_request_rpc(method, params, is_notification=False)
        future = self._loop.create_future()
        self._futures[req_id] = future
        return future

    def _send_request_sync(
        self, method: str, params: dict, timeout: float | None = None
    ) -> dict:
        """Send a request and block until response arrives.

        Args:
            method (str): Method name.
            params (dict): Parameters for the method.
            timeout (float | None): Timeout in seconds. None means wait indefinitely.

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
