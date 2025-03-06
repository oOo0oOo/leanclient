import collections
import os
import pathlib
import asyncio
from pprint import pprint
import secrets
import time
import urllib.parse

import orjson

from .utils import DocumentContentChange, SemanticTokenProcessor, apply_changes_to_text


LEN_URI_PREFIX = 7
IGNORED_METHODS = {
    "workspace/didChangeWatchedFiles",
    "workspace/semanticTokens/refresh",
    "client/registerCapability",
}


class BaseLeanLSPClient:
    """BaseLeanLSPClient runs a language server in a subprocess.

    This base class provides an async interface to the Lean 4 language server.

    See :meth:`leanclient.client.LeanLSPClient` for more information.
    """

    def __init__(
        self,
        project_path: str,
        initial_build: bool = True,
        max_opened_files: int = 8,
    ):
        self.project_path = os.path.abspath(project_path) + "/"
        self.len_project_uri = len(self.project_path) + LEN_URI_PREFIX
        self.initial_build = initial_build
        self.request_id = 0
        self.tasks = set()
        self.pending = {}
        self.files_finished = collections.OrderedDict()
        self.files_diagnostics = {}
        self.files_last_update = {}  # Time of last update to the diagnostics
        self.files_content = {}
        self.max_opened_files = max_opened_files
        self.loop = asyncio.get_event_loop()

    async def start(self):
        """Start the language server process and initialize it.

        This is required before most other methods can be called.
        """
        if self.initial_build:
            build_proc = await asyncio.create_subprocess_exec(
                "lake", "build", cwd=self.project_path
            )
            await build_proc.wait()

        # Run the Lean 4 language server in a subprocess
        self.process = await asyncio.create_subprocess_exec(
            "lake",
            "serve",
            cwd=self.project_path,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self.stdin = self.process.stdin
        self.stdout = self.process.stdout
        self.stderr = self.process.stderr

        self.tasks.add(self.loop.create_task(self._run_stdout()))
        self.tasks.add(self.loop.create_task(self._run_stderr()))

        # Initialize language server. Options can be found here:
        # https://github.com/leanprover/lean4/blob/a955708b6c5f25e7f9c9ae7b951f8f3d5aefe377/src/Lean/Data/Lsp/InitShutdown.lean
        initial = await self.send_request_rpc(
            "initialize",
            {
                "processId": os.getpid(),
                "rootUri": self.local_to_uri(self.project_path),
                "initializationOptions": {
                    "editDelay": 1  # It seems like this has no effect.
                },
            },
            is_notification=False,
        )

        legend = initial["result"]["capabilities"]["semanticTokensProvider"]["legend"]
        self.token_processor = SemanticTokenProcessor(legend["tokenTypes"])

        await self.send_notification("initialized", {})

    async def close(self, timeout: float = 10):
        """Always close the client when done!

        Terminates the language server process and close all pipes.

        Args:
            timeout (float): Time to wait until the process is killed. Defaults to 10 seconds.
        """
        # await self._send_request_rpc("shutdown", {}, is_notification=False)

        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks)

        self.stdin.close()

        for future in self.pending.values():
            future.cancel()

        wait = self.process.wait()

        try:
            await asyncio.wait_for(wait, timeout=timeout)
        except asyncio.TimeoutError:
            print("Warning: Language server did not close in time. Killing process.")
            await self.process.kill()

    # URI HANDLING
    def local_to_uri(self, local_path: str) -> str:
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
        uri = pathlib.Path(self.project_path, local_path).as_uri()
        return urllib.parse.unquote(uri)

    def uri_to_local(self, uri: str) -> str:
        """See :meth:`local_to_uri`"""
        return uri[self.len_project_uri :]

    # LANGUAGE SERVER RPC INTERACTION
    async def _run_stdout(self):
        """Loop: Read and process messages from the language server.

        This is the main blocking function.
        """
        while self.process:
            try:
                message = await self._read_stdout()
            except (asyncio.CancelledError, ValueError):
                break

            method = message.get("method", "")

            if method in IGNORED_METHODS:
                pass

            elif method == "textDocument/publishDiagnostics":
                path = self.uri_to_local(message["params"]["uri"])
                self.files_diagnostics[path] = message["params"]["diagnostics"]
                self.files_last_update[path] = time.time()

            elif method == "$/lean/fileProgress":
                proc = message["params"]["processing"]
                path = self.uri_to_local(message["params"]["textDocument"]["uri"])
                self.files_last_update[path] = time.time()

                if proc == []:
                    self.files_finished[path] = -2

                # Check for fatalError from fileProgress. See here:
                # https://github.com/leanprover/lean4/blob/8791a9ce069d6dc87f7cccc4387545b1110c89bd/src/Lean/Data/Lsp/Extra.lean#L55
                elif proc[-1]["kind"] == 2:
                    msg = "leanclient: Received LeanFileProgressKind.fatalError from language server."
                    message["error"] = {"message": msg}
                    self.files_diagnostics[path] = [message]
                    self.files_finished[path] = -2

                else:
                    # 0 turns into -1 which conveniently means not started yet
                    line = proc[-1]["range"]["start"]["line"] - 1
                    self.files_finished[path] = line

            elif "id" in message and message["id"] in self.pending:
                future = self.pending.pop(message["id"])
                if not future.cancelled():
                    future.set_result(message)
            else:
                # print("Response without matching request:", message)
                pass

    async def _run_stderr(self):
        """Loop: Read and print error messages from lake process stderr."""
        while self.process:
            try:
                line = await self.stderr.readline()
            except asyncio.CancelledError:
                break
            if not line:
                break
            print("lake stderr:", line)

    async def _read_stdout(self) -> dict:
        """Read the next message from the language server.

        This is the main blocking function.

        Returns:
            dict: JSON response from the language server.
        """
        header = await self.stdout.readline()

        # Handle EOF: Return contents of stderr (non-blocking using select)
        if not header:
            await self.close()
            raise EOFError(f"Language server has closed.")

        # Parse message
        content_length = int(header.decode("ascii").split(":")[1])
        await self.stdout.readline()  # Skip the empty line
        data = await self.stdout.read(content_length)

        # Check if the data length matches the expected content length
        # This is relevant during closing
        if len(data) != content_length:
            return {}

        return orjson.loads(data)

    async def send_request_rpc(
        self, method: str, params: dict, is_notification: bool
    ) -> dict | None:
        """Send a JSON RPC request to the language server.

        Args:
            method (str): Method name.
            params (dict): Parameters for the method.
            is_notification (bool): Whether the request is a notification.

        Returns:
            dict | None: The response or None if it is a notification.
        """
        request = {"jsonrpc": "2.0", "method": method, "params": params}

        if not is_notification:
            #     request_id = self.request_id
            #     self.request_id += 1
            #     request["id"] = request_id

            request_id = secrets.randbits(64)
            while request_id in self.pending:
                request_id = secrets.randbits(64)
            request["id"] = request_id

            future = self.loop.create_future()
            self.pending[request_id] = future

        body = orjson.dumps(request)
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        self.stdin.write(header + body)
        await self.stdin.drain()

        if not is_notification:
            return await future

    async def send_notification(self, method: str, params: dict):
        """Send a notification to the language server.

        Args:
            method (str): Method name.
            params (dict): Parameters for the method.
        """
        await self.send_request_rpc(method, params, is_notification=True)

    # FILE MANAGEMENT
    async def _open_new_files(self, paths: list[str]):
        """Open new files in the language server.

        See :meth:`_wait_for_diagnostics` for information on the diagnostic response.

        Args:
            paths (list[str]): List of relative file paths.
        """
        uris = [self.local_to_uri(p) for p in paths]
        for path, uri in zip(paths, uris):
            with open(uri[LEN_URI_PREFIX:], "r") as f:
                txt = f.read()
            self.files_content[path] = txt

            params = {
                "textDocument": {
                    "uri": uri,
                    "text": txt,
                    "languageId": "lean",
                    "version": 1,
                },
                "dependencyBuildMode": "always",
            }

            await self.send_notification("textDocument/didOpen", params)

    async def send_request(self, path: str, method: str, params: dict) -> dict:
        """Send request about a document and return a response or and error.

        Args:
            path (str): Relative file path.
            method (str): Method name.
            params (dict): Parameters for the method.

        Returns:
            dict: Response or error.
        """
        await self.open_file(path)
        params["textDocument"] = {"uri": self.local_to_uri(path)}
        result = await self.send_request_rpc(method, params, is_notification=False)
        return result.get("result", result)

    async def send_request_retry(
        self,
        path: str,
        method: str,
        params: dict,
        timeout: float = 0.1,
        retries: int = 4,
    ) -> dict | None:
        """Send requests until the result is stable for at least `timeout` seconds.

        Note:
            This method expects the request to return. Use `send_request_timeout` if the request could timeout.

        Args:
            path (str): Relative file path.
            method (str): Method name.
            params (dict): Parameters for the method.
            timeout (float): No new results in X seconds. Defaults to 0.1.
            retries (int): Number of retries (only timeouts count). Defaults to 4.

        Returns:
            dict | None: Final response or None.
        """
        await self.open_file(path)
        prev_results = "Nvr_gnn_gv_y_p"
        retry_count = 0
        while True:
            results = await self.send_request(path, method, params)

            if results == prev_results:
                retry_count += 1
                if retry_count >= retries:
                    break
                await asyncio.sleep(timeout)
            else:
                prev_results = results
                retry_count = 0

        return results

    async def send_request_timeout(
        self,
        path: str,
        method: str,
        params: dict,
        timeout: float = 10,
    ) -> dict | None:
        """Send a request with a timeout.

        Args:
            path (str): Relative file path.
            method (str): Method name.
            params (dict): Parameters for the method.
            timeout (float): Time to wait for the response. Defaults to 5.

        Returns:
            dict | None: Response or None if timeout.
        """
        await self.open_file(path)
        try:
            result = await asyncio.wait_for(
                self.send_request(path, method, params), timeout=timeout
            )
        except asyncio.TimeoutError:
            print(
                f"Warning: send_request_timeout for {method} for {path} after {timeout}s."
            )
            return None
        return result

    async def open_files(self, paths: list[str]):
        """Open files in the language server and return diagnostics.

        This function maintains a cache of opened files and their diagnostics.
        See :meth:`_wait_for_diagnostics` for information on the diagnostic response.

        Note:
            Opening multiple files is typically faster than opening them sequentially.

        Args:
            paths (list[str]): List of relative file paths to open.

        Returns:
            list: List of diagnostics for each file.
        """
        if len(paths) > self.max_opened_files:
            raise RuntimeError(
                f"Warning! Can not open more than {self.max_opened_files} files at once. Increase LeanLSPClient.max_opened_files or open less files."
            )

        paths = [urllib.parse.unquote(p) for p in paths]

        # Open new files
        new_files = [p for p in paths if p not in self.files_finished]
        if new_files:
            for path in new_files:
                # File progress: -2 = finished, -1 = not started yet, 0 - n = processed lines
                self.files_finished[path] = -1
                self.files_last_update[path] = time.time()
                self.files_diagnostics[path] = None
            await self._open_new_files(new_files)

        # Remove files if over limit
        remove_count = max(0, len(self.files_finished) - self.max_opened_files)
        if remove_count > 0:
            removable_paths = [p for p in self.files_finished if p not in paths]
            removable_paths = removable_paths[:remove_count]
            await self.close_files(removable_paths)

    async def open_file(self, path: str):
        """Open a file in the language server and return diagnostics.

        See :meth:`_wait_for_diagnostics` for information on the diagnostic response.

        Args:
            path (str): Relative file path to open.
        """
        await self.open_files([path])

    async def update_file(self, path: str, changes: list[DocumentContentChange]):
        """Update a file in the language server.

        Note:

            Changes are not written to disk! Use :meth:`get_file_content` to get the current content of a file, as seen by the language server.

        See :meth:`_wait_for_diagnostics` for information on the diagnostic response.
        Raises a FileNotFoundError if the file is not open.

        Args:
            path (str): Relative file path to update.
            changes (list[DocumentContentChange]): List of changes to apply.
        """
        if path not in self.files_finished:
            raise FileNotFoundError(f"File {path} is not open. Call open_file first.")
        uri = self.local_to_uri(path)

        text = self.files_content[path]
        text = apply_changes_to_text(text, changes)
        self.files_content[path] = text

        # TODO: Any of these useful?
        # params = ("textDocument/didChange", {"textDocument": {"uri": uri, "version": 1, "languageId": "lean"}, "contentChanges": [{"text": text}]})
        # params = ("textDocument/didSave", {"textDocument": {"uri": uri}, "text": text})
        # params = ("workspace/applyEdit", {"changes": [{"textDocument": {"uri": uri, "version": 1}, "edits": [c.get_dict() for c in changes]}]})
        # params = ("workspace/didChangeWatchedFiles", {"changes": [{"uri": uri, "type": 2}]})

        params = (
            "textDocument/didChange",
            {
                "textDocument": {"uri": uri, "version": 1, "languageId": "lean"},
                "contentChanges": [c.get_dict() for c in changes],
            },
        )

        await self.send_notification(*params)

    async def close_files(self, paths: list[str]):
        """Close files in the language server.

        Calling this manually is optional, files are automatically closed when max_opened_files is reached.

        Args:
            paths (list[str]): List of relative file paths to close.
        """
        # Only close if file is open
        paths = [p for p in paths if p in self.files_finished]
        uris = [self.local_to_uri(p) for p in paths]
        for uri in uris:
            params = {"textDocument": {"uri": uri}}
            await self.send_notification("textDocument/didClose", params)

        for path in paths:
            del self.files_finished[path]
            del self.files_diagnostics[path]
            del self.files_content[path]
            del self.files_last_update[path]

    async def get_diagnostics(
        self, path: str, line: int = -1, timeout: float = 10
    ) -> list | None:
        """Get diagnostic messages of a file.

        If the `line` parameter is >= 0, this function will only wait until that line is processed.

        Args:
            path (str): Relative file path.
            line (int): Line number to wait for. Defaults to -1, which means waiting for the full file to load.
            timeout (float): Time to wait for diagnostics. Defaults to 5 seconds.

        Returns:
            list | None: List of current diagnostic messages or errors. None if no diagnostics were received.
        """
        if path not in self.files_finished:
            await self.open_file(path)

        if line >= 0:
            await self.wait_for_line(path, line, timeout)
        else:
            await self.wait_for_file(path, timeout)
        return self.files_diagnostics[path]

    async def wait_for_file(self, path: str, timeout: float = 10) -> bool:
        """Wait for a file to finish processing.

        Checks `waitForDiagnostics` and `fileProgress`.

        Sometimes either of these can fail, so we need a timeout..
        See source for more details.

        Args:
            path (str): Relative file path.
            timeout (float): Time to wait for diagnostics. Defaults to 10 seconds.

        Returns:
            bool: True if the file was processed, False if timed out.
        """
        await self.open_file(path)

        # Wait for file to finish processing with timeout
        if self.files_finished[path] != -2:  # -2 = finished
            duration = 0
            while duration < timeout / 2:
                await asyncio.sleep(0.001)
                if self.files_finished[path] == -2:
                    break
                duration = time.time() - self.files_last_update[path]
            else:
                print(
                    f"Warning: Timed out waiting for diagnostics (finish processing) after {duration:.1f}s for {path}."
                )

        # Wait for diagnostics with timeout
        uri = self.local_to_uri(path)
        try:
            await asyncio.wait_for(
                self.send_request_rpc(
                    "textDocument/waitForDiagnostics",
                    {"uri": uri, "version": 1},
                    is_notification=False,
                ),
                timeout=timeout / 2,
            )
        except asyncio.TimeoutError:
            print(
                f"Warning: Timed out waiting for diagnostics (waitForDiagnostics) after {timeout / 2:}s for {path}."
            )
            return False
        return True

    async def wait_for_line(self, path: str, line: int, timeout: float = 10) -> bool:
        """Wait for a line to be processed.

        This is useful for waiting for diagnostics on a specific line.

        Args:
            path (str): Relative file path.
            line (int): Line number to wait for.
            timeout (float): Time to wait for diagnostics. Defaults to 10 seconds.

        Returns:
            bool: True if the line was processed, False if timed out.
        """
        await self.open_file(path)

        while True:
            cur_line = self.files_finished[path]
            if cur_line == -2:
                return True
            elif cur_line >= line:
                return True
            await asyncio.sleep(0.001)
            duration = time.time() - self.files_last_update[path]
            if duration > timeout:
                print(
                    f"Warning: Timed out waiting for line {line} after {duration:.1f}s for {path}."
                )
                return False

    def get_file_content(self, path: str) -> str:
        """Get the content of a file as seen by the language server.

        Args:
            path (str): Relative file path.

        Returns:
            str: Content of the file.
        """
        if path in self.files_content:
            return self.files_content[path]

        raise FileNotFoundError(f"File {path} is not open. Call open_file first.")

    # HELPERS
    async def get_env(self, return_dict: bool = True) -> dict | str:
        """Get the environment variables of the project.

        Args:
            return_dict (bool): Return as dict or string.

        Returns:
            dict | str: Environment variables.
        """
        process = await asyncio.create_subprocess_exec(
            "lake",
            "env",
            cwd=self.project_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            raise RuntimeError(
                f"Command failed with exit code {process.returncode}: {stderr.decode()}"
            )

        if not return_dict:
            return stdout.decode()

        env = {}
        for line in stdout.decode().split("\n"):
            if not line:
                continue
            key, value = line.split("=", 1)
            env[key] = value
        return env
