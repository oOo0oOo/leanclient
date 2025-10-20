import collections
from pprint import pprint
import time
import threading
import urllib.parse

from .utils import DocumentContentChange, apply_changes_to_text, normalize_newlines
from .base_client import BaseLeanLSPClient


class LSPFileManager(BaseLeanLSPClient):
    """Manages opening, closing and syncing files on the language server.

    See :meth:`leanclient.client.BaseLeanLSPClient` for details.
    """

    def __init__(
        self,
        max_opened_files: int = 4,
    ):
        # Only allow initialization after BaseLeanLSPClient
        if not hasattr(self, "project_path"):
            msg = "BaseLeanLSPClient is not initialized. Call BaseLeanLSPClient.__init__ first."
            raise RuntimeError(msg)

        self.max_opened_files = max_opened_files
        self.opened_files_diagnostics = collections.OrderedDict()
        self.opened_files_content = {}
        self.opened_files_versions = {}

    def _open_new_files(
        self,
        paths: list[str],
        dependency_build_mode: str = "never",
    ) -> None:
        """Open new files in the language server.

        Args:
            paths (list[str]): List of relative file paths.
            dependency_build_mode (str): Whether to automatically rebuild dependencies. Defaults to "never".
        """
        uris = self._locals_to_uris(paths)
        for path, uri in zip(paths, uris):
            with open(self._uri_to_abs(uri), "r") as f:
                txt = normalize_newlines(f.read())
            self.opened_files_content[path] = txt
            self.opened_files_versions[path] = 0
            self.opened_files_diagnostics[path] = None

            params = {
                "textDocument": {
                    "uri": uri,
                    "text": txt,
                    "languageId": "lean",
                    "version": 0,
                },
                "dependencyBuildMode": dependency_build_mode,
            }
            self._send_notification("textDocument/didOpen", params)

    def _send_request(self, path: str, method: str, params: dict) -> dict:
        """Send request about a document and return a response or and error.

        Args:
            path (str): Relative file path.
            method (str): Method name.
            params (dict): Parameters for the method.

        Returns:
            dict: Response or error.
        """
        self.open_file(path)
        params["textDocument"] = {
            "uri": self._local_to_uri(path),
            "version": self.opened_files_versions[path],
        }
        
        try:
            result = self._send_request_sync(method, params)
            return result
        except EOFError:
            raise EOFError("LeanLSPClient: Language server closed unexpectedly.")
        except Exception as e:
            # Return error in dict format for backward compatibility
            if "LSP Error:" in str(e):
                error_msg = str(e).replace("LSP Error: ", "")
                import ast
                try:
                    error_dict = ast.literal_eval(error_msg)
                    return {"error": error_dict}
                except:
                    return {"error": {"message": str(e)}}
            raise

    def _send_request_retry(
        self,
        path: str,
        method: str,
        params: dict,
        max_retries: int = 1,
        retry_delay: float = 0.0,
    ) -> dict:
        """Send requests until no new results are found after a number of retries.

        Args:
            path (str): Relative file path.
            method (str): Method name.
            params (dict): Parameters for the method.
            max_retries (int): Number of times to retry if no new results were found. Defaults to 1.
            retry_delay (float): Time to wait between retries. Defaults to 0.0.

        Returns:
            dict: Final response.
        """
        prev_results = "Nvr_gnn_gv_y_p"
        retry_count = 0
        while True:
            results = self._send_request(
                path,
                method,
                params,
            )
            if results == prev_results:
                retry_count += 1
                if retry_count > max_retries:
                    break
                time.sleep(retry_delay)
            else:
                retry_count = 0
                prev_results = results

        return results

    def open_files(self, paths: list[str]) -> None:
        """Open files in the language server.

        Use :meth:`get_diagnostics` to get diagnostics.

        Note:
            Opening multiple files is typically faster than opening them sequentially.

        Args:
            paths (list[str]): List of relative file paths to open.
        """
        if len(paths) > self.max_opened_files:
            raise RuntimeError(
                f"Warning! Can not open more than {self.max_opened_files} files at once. Increase LeanLSPClient.max_opened_files or open less files."
            )

        paths = [urllib.parse.unquote(p) for p in paths]

        # Open new files
        new_files = [p for p in paths if p not in self.opened_files_diagnostics]
        if new_files:
            self._open_new_files(new_files)

        # Remove files if over limit
        remove_count = max(
            0, len(self.opened_files_diagnostics) - self.max_opened_files
        )
        if remove_count > 0:
            removable_paths = [
                p for p in self.opened_files_diagnostics if p not in paths
            ]
            removable_paths = removable_paths[:remove_count]
            self.close_files(removable_paths)

    def open_file(self, path: str) -> None:
        """Open a file in the language server.

        Use :meth:`get_diagnostics` to get diagnostics for the file.

        Args:
            path (str): Relative file path to open.
        """
        self.open_files([path])

    def update_file(
        self, path: str, changes: list[DocumentContentChange]
    ) -> None:
        """Update a file in the language server.

        Note:

            Changes are not written to disk! Use :meth:`get_file_content` to get the current content of a file, as seen by the language server.

        Use :meth:`get_diagnostics` to get diagnostics after the update.
        Raises a FileNotFoundError if the file is not open.

        Args:
            path (str): Relative file path to update.
            changes (list[DocumentContentChange]): List of changes to apply.
        """
        if path not in self.opened_files_diagnostics:
            raise FileNotFoundError(f"File {path} is not open. Call open_file first.")
        uri = self._local_to_uri(path)

        text = self.opened_files_content[path]
        text = apply_changes_to_text(text, changes)
        self.opened_files_content[path] = text

        self.opened_files_versions[path] += 1
        version = self.opened_files_versions[path]

        # TODO: Any of these useful?
        # params = ("textDocument/didSave", {"textDocument": {"uri": uri}, "text": text})
        # params = ("workspace/applyEdit", {"changes": [{"textDocument": {"uri": uri, "version": 1}, "edits": [c.get_dict() for c in changes]}]})
        # params = ("workspace/didChangeWatchedFiles", {"changes": [{"uri": uri, "type": 2}]})

        params = (
            "textDocument/didChange",
            {
                "textDocument": {"uri": uri, "version": version},
                "contentChanges": [c.get_dict() for c in changes],
            },
        )

        # Clear diagnostics cache so next get_diagnostics() waits for fresh diagnostics
        self.opened_files_diagnostics[path] = None

        self._send_notification(*params)
        
    def close_files(self, paths: list[str], blocking: bool = True):
        """Close files in the language server.

        Calling this manually is optional, files are automatically closed when max_opened_files is reached.

        Args:
            paths (list[str]): List of relative file paths to close.
            blocking (bool): Not blocking can be risky if you close files frequently or reopen them.
        """
        # Only close if file is open
        missing = [p for p in paths if p not in self.opened_files_diagnostics]
        if any(missing):
            raise FileNotFoundError(
                f"Files {missing} are not open. Call open_files first."
            )

        uris = self._locals_to_uris(paths)
        for uri in uris:
            params = {"textDocument": {"uri": uri}}
            self._send_notification("textDocument/didClose", params)

        for path in paths:
            del self.opened_files_diagnostics[path]
            del self.opened_files_content[path]
            del self.opened_files_versions[path]

        # Wait for published diagnostics
        if blocking:
            waiting_uris = set(uris)
            completion_event = threading.Event()
            
            def handle_close_diagnostics(msg):
                uri = msg["params"]["uri"]
                waiting_uris.discard(uri)
                if not waiting_uris:
                    completion_event.set()
            
            self._register_notification_handler("textDocument/publishDiagnostics", handle_close_diagnostics)
            try:
                # Wait up to 5 seconds for all diagnostics
                completion_event.wait(timeout=5)
            finally:
                self._unregister_notification_handler("textDocument/publishDiagnostics")

    def get_diagnostics(self, path: str, timeout: float = 30) -> list | None:
        """Get diagnostics for a single file.

        If the file is not open, it will be opened first and wait for diagnostics.
        If the file is already open but diagnostics not yet loaded, waits for them.
        If diagnostics are already loaded, returns cached value.

        **Example diagnostics**:

        .. code-block:: python

            [
            # For each file:
            [
                {
                    'message': "declaration uses 'sorry'",
                    'severity': 2,
                    'source': 'Lean 4',
                    'range': {'end': {'character': 19, 'line': 13},
                                'start': {'character': 8, 'line': 13}},
                    'fullRange': {'end': {'character': 19, 'line': 13},
                                'start': {'character': 8, 'line': 13}}
                },
                {
                    'message': "unexpected end of input; expected ':'",
                    'severity': 1,
                    'source': 'Lean 4',
                    'range': {'end': {'character': 0, 'line': 17},
                                'start': {'character': 0, 'line': 17}},
                    'fullRange': {'end': {'character': 0, 'line': 17},
                                'start': {'character': 0, 'line': 17}}
                },
                # ...
            ], #...
            ]

        Args:
            path (str): Relative file path.
            timeout (float): Time to wait for diagnostics. Defaults to 30 seconds.

        Returns:
            list | None: Diagnostics of file or None if timed out
        """
        need_to_wait = False
        
        if path not in self.opened_files_diagnostics:
            # File not open yet, open it and wait
            self.open_files([path])
            need_to_wait = True
        elif self.opened_files_diagnostics[path] is None:
            # File is open but diagnostics not yet received (None)
            need_to_wait = True
        
        if need_to_wait:
            # Wait for diagnostics to be ready
            self._wait_for_diagnostics([self._local_to_uri(path)], timeout)
        
        # Return cached diagnostics
        return self.opened_files_diagnostics[path]

    def get_file_content(self, path: str) -> str:
        """Get the content of a file as seen by the language server.

        Args:
            path (str): Relative file path.

        Returns:
            str: Content of the file.
        """
        if path in self.opened_files_content:
            return self.opened_files_content[path]

        raise FileNotFoundError(f"File {path} is not open. Call open_file first.")

    def _wait_for_diagnostics(self, uris: list[str], timeout: float = 30) -> None:
        """Wait until file is loaded or an rpc error occurs.

        This should only be used right after opening or updating files not to miss any responses.
        Returns either diagnostics or an [{error dict}] for each file.

        Checks `waitForDiagnostics` and `fileProgress` for each file.

        Sometimes either of these can fail, so we need to check for "rpc errors", "fatal errors" and use a timeout..
        See source for more details.

        Args:
            uris (list[str]): List of URIs to wait for diagnostics on.
            timeout (float): Time to wait for diagnostics. Defaults to 30 seconds.
        """
        # Check if all files are opened
        paths = [self._uri_to_local(uri) for uri in uris]
        missing = [p for p in paths if p not in self.opened_files_diagnostics]
        if missing:
            raise FileNotFoundError(
                f"Files {missing} are not open. Call open_files first."
            )

        # Request waitForDiagnostics for each file - now non-blocking
        futures_by_uri = {}
        for uri, path in zip(uris, paths):
            version = self.opened_files_versions[path]
            params = {"uri": uri, "version": version}
            future = self._send_request_async("textDocument/waitForDiagnostics", params)
            futures_by_uri[uri] = future

        # Use sets for explicit, robust state tracking.
        waiting_uris = set(uris)  # Original URIs we're waiting for
        uris_to_wait_for_response = set(uris)
        uris_to_wait_for_processing = set(uris)
        diagnostics = {}
        completion_event = threading.Event()

        # Register notification handlers for diagnostics and file progress
        def handle_publish_diagnostics(msg):
            uri = msg["params"]["uri"]
            if uri in waiting_uris:  # Only process if we're waiting for this URI
                new_diagnostics = msg["params"]["diagnostics"]
                # Only store if:
                # 1. We don't have diagnostics yet, OR
                # 2. The new diagnostics are non-empty (server sends empty first, then real ones), AND
                # 3. We don't already have an error diagnostic (from fatal error)
                has_error = uri in diagnostics and diagnostics[uri] and "error" in diagnostics[uri][0]
                if (uri not in diagnostics or new_diagnostics) and not has_error:
                    diagnostics[uri] = new_diagnostics
                # Getting diagnostics means processing is done
                uris_to_wait_for_processing.discard(uri)
                if not uris_to_wait_for_response and not uris_to_wait_for_processing:
                    completion_event.set()

        def handle_file_progress(msg):
            uri = msg["params"]["textDocument"]["uri"]
            if uri not in waiting_uris:  # Only process if we're waiting for this URI
                return
            
            proc = msg["params"]["processing"]
            if not proc:
                uris_to_wait_for_processing.discard(uri)
                if not uris_to_wait_for_response and not uris_to_wait_for_processing:
                    completion_event.set()
            # Check for fatalError from fileProgress.
            # https://github.com/leanprover/lean4/blob/8791a9ce069d6dc87f7cccc4387545b1110c89bd/src/Lean/Data/Lsp/Extra.lean#L55
            elif proc[-1].get("kind") == 2:
                uris_to_wait_for_processing.discard(uri)
                uris_to_wait_for_response.discard(uri)
                if uri not in diagnostics:
                    msg_text = "leanclient: Received LeanFileProgressKind.fatalError."
                    diagnostics[uri] = [{"error": {"message": msg_text}}]
                if not uris_to_wait_for_response and not uris_to_wait_for_processing:
                    completion_event.set()

        self._register_notification_handler("textDocument/publishDiagnostics", handle_publish_diagnostics)
        self._register_notification_handler("$/lean/fileProgress", handle_file_progress)

        try:
            # Wait for futures to complete and check for errors
            start_time = time.time()
            while uris_to_wait_for_response or uris_to_wait_for_processing:
                # Check if we've timed out
                elapsed = time.time() - start_time
                if elapsed > timeout:
                    if self.print_warnings:
                        print(f"WARNING: `_wait_for_diagnostics` timed out after {timeout} seconds.")
                    break

                # Check for completed futures
                for uri in list(uris_to_wait_for_response):
                    future = futures_by_uri[uri]
                    if future.done():
                        uris_to_wait_for_response.discard(uri)
                        try:
                            # Try to get the result to check for errors
                            future.result()
                        except Exception as e:
                            # On error, mark processing as done and store error
                            uris_to_wait_for_processing.discard(uri)
                            if uri not in diagnostics:
                                diagnostics[uri] = [{"error": {"message": str(e)}}]

                # Wait for notifications or timeout
                if uris_to_wait_for_response or uris_to_wait_for_processing:
                    remaining_time = timeout - elapsed
                    wait_time = min(0.1, max(0.001, remaining_time))
                    completion_event.wait(timeout=wait_time)
                    if completion_event.is_set():
                        completion_event.clear()

        finally:
            # Always unregister handlers
            self._unregister_notification_handler("textDocument/publishDiagnostics")
            self._unregister_notification_handler("$/lean/fileProgress")
        
        # Update diagnostics cache
        for uri in waiting_uris:
            path = self._uri_to_local(uri)
            if uri in diagnostics:
                self.opened_files_diagnostics[path] = diagnostics[uri]
            else:
                # No diagnostics received, set to empty list
                self.opened_files_diagnostics[path] = []
