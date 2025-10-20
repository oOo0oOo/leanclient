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
        # Unified state tracking for opened files
        self.opened_files = collections.OrderedDict()  # path -> state dict
        self._opened_files_lock = threading.Lock()
        self._recently_closed: set[str] = set()
        
        # Setup global handlers for diagnostics and file progress
        self._setup_global_handlers()

    def _setup_global_handlers(self):
        """Setup permanent handlers for diagnostics and file progress notifications."""
        
        def handle_publish_diagnostics(msg):
            """Handle textDocument/publishDiagnostics notifications."""
            uri = msg["params"]["uri"]
            diagnostics = msg["params"]["diagnostics"]
            diag_version = msg["params"].get("version", -2)
            
            path = self._uri_to_local(uri)
            
            with self._opened_files_lock:
                # Only update if file is still open
                if path not in self.opened_files:
                    return
                
                # Only update if diagnostics version is current or newer
                if diag_version >= self.opened_files[path]["diagnostics_version"]:
                    has_error = self.opened_files[path]["error"] is not None
                    
                    # Always update diagnostics unless we have an error
                    # (Server sends empty [] first, then progressively more diagnostics)
                    if not has_error:
                        self.opened_files[path]["diagnostics"] = diagnostics
                        self.opened_files[path]["diagnostics_version"] = diag_version
                        if self.opened_files[path]["close_pending"] and not diagnostics:
                            self.opened_files[path]["close_ready"] = True
        
        def handle_file_progress(msg):
            """Handle $/lean/fileProgress notifications."""
            uri = msg["params"]["textDocument"]["uri"]
            processing = msg["params"]["processing"]
            diag_version = msg["params"].get("version", None)
            
            path = self._uri_to_local(uri)
            
            with self._opened_files_lock:
                # Only update if file is still open
                if path not in self.opened_files:
                    return

                # Always check for fatal errors regardless of version
                # Check for fatal error (kind == 2)
                if processing and processing[-1].get("kind") == 2:
                    # Mark that we saw a fatal error, but don't set error message yet
                    # We'll set it later if no diagnostics arrive
                    self.opened_files[path]["fatal_error"] = True
                    self.opened_files[path]["processing"] = False
                    self.opened_files[path]["complete"] = True
                
                # Mark processing complete when processing array is empty
                if not processing:
                    # Processing complete (but may still get more diagnostics)
                    self.opened_files[path]["processing"] = False        
        
        # Register permanent handlers
        self._register_notification_handler("textDocument/publishDiagnostics", handle_publish_diagnostics)
        self._register_notification_handler("$/lean/fileProgress", handle_file_progress)

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
            
            # Initialize file state
            with self._opened_files_lock:
                self._recently_closed.discard(path)
                self.opened_files[path] = {
                    "content": txt,
                    "version": 0,
                    "uri": uri,
                    "diagnostics": [],
                    "diagnostics_version": -1,
                    "processing": True,
                    "error": None,
                    "fatal_error": False,  # Track if we saw a fatal error
                    "complete": False,  # True either when error or (waitForDiagnostics returns and processing done)
                    "close_pending": False,
                    "close_ready": False,
                }

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
        with self._opened_files_lock:
            uri = self.opened_files[path]["uri"]
            version = self.opened_files[path]["version"]
        
        params["textDocument"] = {
            "uri": uri,
            "version": version,
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
        with self._opened_files_lock:
            new_files = [p for p in paths if p not in self.opened_files]
        if new_files:
            self._open_new_files(new_files)

        # Remove files if over limit
        with self._opened_files_lock:
            remove_count = max(
                0, len(self.opened_files) - self.max_opened_files
            )
            if remove_count > 0:
                removable_paths = [
                    p for p in self.opened_files if p not in paths
                ]
                removable_paths = removable_paths[:remove_count]
        
        if remove_count > 0:
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
        with self._opened_files_lock:
            if path not in self.opened_files:
                raise FileNotFoundError(f"File {path} is not open. Call open_file first.")
            
            text = self.opened_files[path]["content"]
            text = apply_changes_to_text(text, changes)
            
            # Update state - reset for new version
            self.opened_files[path]["content"] = text
            self.opened_files[path]["version"] += 1
            self.opened_files[path]["diagnostics"] = []
            self.opened_files[path]["diagnostics_version"] = self.opened_files[path]["version"] - 1
            self.opened_files[path]["processing"] = True
            self.opened_files[path]["error"] = None
            self.opened_files[path]["fatal_error"] = False
            self.opened_files[path]["complete"] = False
            self.opened_files[path]["close_pending"] = False
            self.opened_files[path]["close_ready"] = False
            
            uri = self.opened_files[path]["uri"]
            version = self.opened_files[path]["version"]

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

        self._send_notification(*params)
        
    def close_files(self, paths: list[str], blocking: bool = True):
        """Close files in the language server.

        Calling this manually is optional, files are automatically closed when max_opened_files is reached.

        Args:
            paths (list[str]): List of relative file paths to close.
            blocking (bool): Not blocking can be risky if you close files frequently or reopen them.
        """
        # Only close if file is open
        with self._opened_files_lock:
            missing = [p for p in paths if p not in self.opened_files]
            if any(missing):
                raise FileNotFoundError(
                    f"Files {missing} are not open. Call open_files first."
                )
            uris = [self.opened_files[p]["uri"] for p in paths]
            if blocking:
                for path in paths:
                    self.opened_files[path]["close_pending"] = True
                    self.opened_files[path]["close_ready"] = False
            for path in paths:
                self._recently_closed.add(path)

        for uri in uris:
            params = {"textDocument": {"uri": uri}}
            self._send_notification("textDocument/didClose", params)

        # Wait for published diagnostics if blocking
        if blocking:
            deadline = time.monotonic() + 5
            while True:
                with self._opened_files_lock:
                    ready = [self.opened_files[p]["close_ready"] for p in paths]
                if all(ready):
                    break
                if time.monotonic() >= deadline:
                    if self.print_warnings:
                        print("WARNING: close_files timed out waiting for diagnostics flush.")
                    break
                time.sleep(0.02)
            with self._opened_files_lock:
                for path in paths:
                    # Reset flags; file about to be removed
                    if path in self.opened_files:
                        self.opened_files[path]["close_pending"] = False
                        self.opened_files[path]["close_ready"] = False
        
        # Remove from state
        with self._opened_files_lock:
            for path in paths:
                del self.opened_files[path]

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
        # Open file if not already open
        with self._opened_files_lock:
            if path not in self.opened_files:
                need_to_open = True
            else:
                need_to_open = False
        
        if need_to_open:
            with self._opened_files_lock:
                if path in self._recently_closed:
                    self._recently_closed.discard(path)
                    return []
            self.open_files([path])
        
        # Check if we need to wait
        with self._opened_files_lock:
            is_complete = self.opened_files[path]["complete"]
            uri = self.opened_files[path]["uri"]
        
        need_to_wait = not is_complete
        
        if need_to_wait:
            # Wait for diagnostics to be ready
            self._wait_for_diagnostics([uri], timeout)
        
        # Return diagnostics or error
        with self._opened_files_lock:
            state = self.opened_files[path]
            if self.print_warnings:
                print(f"DEBUG get_diagnostics: path={path}, diag={state['diagnostics']}, error={state['error']}, processing={state['processing']}, version={state['version']}, diag_version={state['diagnostics_version']}")
            if state["error"]:
                return [state["error"]]
            # If we saw a fatal error but have no diagnostics, return generic error message
            if state["fatal_error"] and not state["diagnostics"]:
                return [{
                    "message": "leanclient: Received LeanFileProgressKind.fatalError."
                }]
            return state["diagnostics"]

    def get_file_content(self, path: str) -> str:
        """Get the content of a file as seen by the language server.

        Args:
            path (str): Relative file path.

        Returns:
            str: Content of the file.
        """
        with self._opened_files_lock:
            if path in self.opened_files:
                return self.opened_files[path]["content"]

        raise FileNotFoundError(f"File {path} is not open. Call open_file first.")

    def _wait_for_diagnostics(self, uris: list[str], timeout: float = 30) -> None:
        """Wait until file is loaded or an rpc error occurs.

        This method checks state first and only blocks if needed.
        The global handlers update state automatically in the background.

        Args:
            uris (list[str]): List of URIs to wait for diagnostics on.
            timeout (float): Time to wait for diagnostics. Defaults to 30 seconds.
        """
        paths = [self._uri_to_local(uri) for uri in uris]
        path_by_uri = dict(zip(uris, paths))
        
        # Check if all files are opened
        with self._opened_files_lock:
            missing = [p for p in paths if p not in self.opened_files]
            if missing:
                raise FileNotFoundError(
                    f"Files {missing} are not open. Call open_files first."
                )
        
        # Check current state - do we need to wait?
        uris_needing_wait = []
        target_versions: dict[str, int] = {}
        with self._opened_files_lock:
            for uri in uris:
                path = path_by_uri[uri]
                state = self.opened_files[path]

                if (
                    not state["complete"]
                    and not state["processing"]
                    and state["diagnostics_version"] >= state["version"]
                ):
                    state["complete"] = True

                if not state["complete"]:
                    uris_needing_wait.append(uri)
                    target_versions[uri] = state["version"]
        
        if not uris_needing_wait:
            # All files already have diagnostics or errors
            return
        
        # Send waitForDiagnostics requests for files that need it
        futures_by_uri = {}
        for uri in uris_needing_wait:
            params = {"uri": uri, "version": target_versions[uri]}
            futures_by_uri[uri] = self._send_request_async("textDocument/waitForDiagnostics", params)
        
        # Wait for completion
        start_time = time.monotonic()
        pending_uris = set(uris_needing_wait)

        while pending_uris:
            elapsed = time.monotonic() - start_time
            if elapsed > timeout:
                if self.print_warnings:
                    print(f"WARNING: `_wait_for_diagnostics` timed out after {timeout} seconds.")
                break
            
            done_uris = [uri for uri in pending_uris if futures_by_uri[uri].done()]
            completed_uris: set[str] = set()

            with self._opened_files_lock:
                for uri in done_uris:
                    path = path_by_uri[uri]
                    future = futures_by_uri[uri]
                    try:
                        future.result()
                    except Exception as e:
                        self.opened_files[path]["error"] = {"message": str(e)}
                        self.opened_files[path]["processing"] = False
                    finally:
                        self.opened_files[path]["complete"] = True
                        completed_uris.add(uri)

                for uri in pending_uris - completed_uris:
                    path = path_by_uri[uri]
                    state = self.opened_files[path]
                    target_version = target_versions[uri]

                    if (
                        not state["complete"]
                        and not state["processing"]
                        and state["diagnostics_version"] >= target_version
                    ):
                        state["complete"] = True
                        completed_uris.add(uri)
                    elif state["complete"]:
                        completed_uris.add(uri)

            pending_uris.difference_update(completed_uris)

            if not pending_uris:
                break

            remaining_time = timeout - elapsed
            wait_time = min(0.02, max(0.001, remaining_time))
            time.sleep(wait_time)
