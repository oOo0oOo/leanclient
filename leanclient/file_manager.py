from dataclasses import dataclass, field
import time
import threading
import urllib.parse
import logging
from typing import Any

from .utils import DocumentContentChange, apply_changes_to_text, normalize_newlines
from .base_client import BaseLeanLSPClient

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class FileState:
    """Represents the mutable state of an open Lean file."""

    uri: str
    content: str
    version: int = 0
    diagnostics: list[Any] = field(default_factory=list)
    diagnostics_version: int = -1
    processing: bool = True
    error: dict | None = None
    fatal_error: bool = False
    complete: bool = False
    close_pending: bool = False
    close_ready: bool = False
    dependency_rebuild_attempted: bool = False
    last_activity: float = field(default_factory=time.monotonic)

    def reset_after_change(self):
        """Reset diagnostics-related state after a content change."""
        self.diagnostics = []
        self.diagnostics_version = self.version - 1
        self.processing = True
        self.error = None
        self.fatal_error = False
        self.complete = False
        self.close_pending = False
        self.close_ready = False
        self.last_activity = time.monotonic()


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
        self.opened_files: dict[str, FileState] = {}
        self._opened_files_lock = threading.Lock()
        self._close_condition = threading.Condition(self._opened_files_lock)
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
            needs_rebuild = False
            notify_close = False

            with self._opened_files_lock:
                state = self.opened_files.get(path)
                if state is None:
                    return

                # Only update if diagnostics version is current or newer
                if diag_version >= state.diagnostics_version:
                    has_error = state.error is not None

                    if not has_error:
                        state.diagnostics = diagnostics
                        state.diagnostics_version = diag_version
                        state.last_activity = time.monotonic()
                        if state.close_pending and not diagnostics:
                            state.close_ready = True
                            notify_close = True

                        # Auto-rebuild stale imports (one-time only)
                        if not state.dependency_rebuild_attempted and any(
                            d.get("severity") == 1
                            and "Imports are out of date" in d.get("message", "")
                            for d in diagnostics
                        ):
                            state.dependency_rebuild_attempted = True
                            needs_rebuild = True

            # Notify waiting threads outside the lock to avoid deadlock
            if notify_close:
                with self._close_condition:
                    self._close_condition.notify_all()

            # Outside lock: send rebuild notifications
            if needs_rebuild:
                logger.info(f"Auto-rebuilding stale imports for {path}")
                self._send_notification(
                    "textDocument/didClose", {"textDocument": {"uri": uri}}
                )

                # Reopen with dependency rebuild
                with self._opened_files_lock:
                    state = self.opened_files.get(path)
                    if state:  # Only rebuild if file still open
                        state.version += 1
                        state.reset_after_change()

                        open_params = {
                            "textDocument": {
                                "uri": uri,
                                "text": state.content,
                                "languageId": "lean",
                                "version": state.version,
                            },
                            "dependencyBuildMode": "once",
                        }
                        self._send_notification("textDocument/didOpen", open_params)

        def handle_file_progress(msg):
            """Handle $/lean/fileProgress notifications."""
            uri = msg["params"]["textDocument"]["uri"]
            processing = msg["params"]["processing"]

            path = self._uri_to_local(uri)

            with self._opened_files_lock:
                # Only update if file is still open
                state = self.opened_files.get(path)
                if state is None:
                    return

                # Always check for fatal errors regardless of version
                # Check for fatal error (kind == 2)
                if processing and processing[-1].get("kind") == 2:
                    # Mark that we saw a fatal error, but don't set error message yet
                    # We'll set it later if no diagnostics arrive
                    state.fatal_error = True
                    state.processing = False
                    state.complete = True
                    state.last_activity = time.monotonic()

                # Mark processing complete when processing array is empty
                if not processing:
                    # Processing complete (but may still get more diagnostics)
                    state.processing = False

        # Register permanent handlers
        self._register_notification_handler(
            "textDocument/publishDiagnostics", handle_publish_diagnostics
        )
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
                self.opened_files[path] = FileState(uri=uri, content=txt)

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
            state = self.opened_files[path]
            uri = state.uri
            version = state.version

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
                except Exception:
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

    def open_files(
        self,
        paths: list[str],
        dependency_build_mode: str = "never",
        force_reopen: bool = False,
    ) -> None:
        """Open files in the language server.

        Use :meth:`get_diagnostics` to get diagnostics.

        Note:
            Opening multiple files is typically faster than opening them sequentially.

        Args:
            paths (list[str]): List of relative file paths to open.
            dependency_build_mode (str): Whether to automatically rebuild dependencies. Defaults to "never". Can be "once", "never" or "always".
            force_reopen (bool): If True, close and reopen files that are already open. If False (default), sync content from disk using update for already-open files.
        """
        if len(paths) > self.max_opened_files:
            raise RuntimeError(
                f"Warning! Can not open more than {self.max_opened_files} files at once. Increase LeanLSPClient.max_opened_files or open less files."
            )

        paths = [urllib.parse.unquote(p) for p in paths]

        # Separate files into categories
        with self._opened_files_lock:
            new_files = [p for p in paths if p not in self.opened_files]
            already_open = [p for p in paths if p in self.opened_files]

        # Handle already-open files
        if already_open:
            if force_reopen:
                # Close and reopen
                self.close_files(already_open)
                new_files.extend(already_open)
            else:
                # Sync from disk using update
                for path in already_open:
                    abs_path = self._uri_to_abs(self._local_to_uri(path))
                    with open(abs_path, "r") as f:
                        new_content = normalize_newlines(f.read())

                    with self._opened_files_lock:
                        state = self.opened_files[path]
                        old_content = state.content

                    if old_content != new_content:
                        # Replace entire content
                        change = DocumentContentChange(
                            text=new_content,
                            start=(0, 0),
                            end=(len(old_content.splitlines()), 0),
                        )
                        self.update_file(path, [change])

        # Open new files
        if new_files:
            self._open_new_files(new_files, dependency_build_mode)

        # Remove files if over limit
        with self._opened_files_lock:
            remove_count = max(0, len(self.opened_files) - self.max_opened_files)
            if remove_count > 0:
                removable_paths = [p for p in self.opened_files if p not in paths]
                removable_paths = removable_paths[:remove_count]

        if remove_count > 0:
            self.close_files(removable_paths)

    def open_file(
        self,
        path: str,
        dependency_build_mode: str = "never",
        force_reopen: bool = False,
    ) -> None:
        """Open a file in the language server.

        Use :meth:`get_diagnostics` to get diagnostics for the file.

        Args:
            path (str): Relative file path to open.
            dependency_build_mode (str): Whether to automatically rebuild dependencies. Defaults to "never". Can be "once", "never" or "always".
            force_reopen (bool): If True, always close and reopen the file. If False (default), sync file content from disk using update if already open.
        """
        self.open_files(
            [path],
            dependency_build_mode=dependency_build_mode,
            force_reopen=force_reopen,
        )

    def update_file(self, path: str, changes: list[DocumentContentChange]) -> None:
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
                raise FileNotFoundError(
                    f"File {path} is not open. Call open_file first."
                )

            state = self.opened_files[path]
            text = state.content
            text = apply_changes_to_text(text, changes)

            # Update state - reset for new version
            state.content = text
            state.version += 1
            state.reset_after_change()

            uri = state.uri
            version = state.version

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

    def update_file_content(self, path: str, content: str) -> None:
        """Update the entire content of a file in the language server.

        This is a convenience method that replaces the entire file content.
        More efficient than closing and reopening when the file is already open.

        Note:
            Changes are not written to disk! This only updates the LSP server's view.

        Use :meth:`get_diagnostics` to get diagnostics after the update.
        Raises a FileNotFoundError if the file is not open.

        Args:
            path (str): Relative file path to update.
            content (str): New complete file content.
        """
        content = normalize_newlines(content)

        with self._opened_files_lock:
            if path not in self.opened_files:
                raise FileNotFoundError(
                    f"File {path} is not open. Call open_file first."
                )
            state = self.opened_files[path]
            old_content = state.content

        # Create change that replaces entire content
        change = DocumentContentChange(
            text=content, start=(0, 0), end=(len(old_content.splitlines()), 0)
        )
        self.update_file(path, [change])

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
            uris = [self.opened_files[p].uri for p in paths]
            if blocking:
                for path in paths:
                    state = self.opened_files[path]
                    state.close_pending = True
                    state.close_ready = False
            for path in paths:
                self._recently_closed.add(path)

        for uri in uris:
            params = {"textDocument": {"uri": uri}}
            self._send_notification("textDocument/didClose", params)

        # Wait for published diagnostics if blocking (event-driven, not polling)
        if blocking:
            deadline = time.monotonic() + 5
            with self._close_condition:
                while True:
                    ready = [self.opened_files[p].close_ready for p in paths]
                    if all(ready):
                        break
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        logger.warning(
                            "close_files timed out waiting for diagnostics flush."
                        )
                        break
                    self._close_condition.wait(timeout=remaining)

                for path in paths:
                    # Reset flags; file about to be removed
                    if path in self.opened_files:
                        state = self.opened_files[path]
                        state.close_pending = False
                        state.close_ready = False

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
            self.open_files([path])

        # Check if we need to wait
        with self._opened_files_lock:
            state = self.opened_files[path]
            is_complete = state.complete
            uri = state.uri

        need_to_wait = not is_complete

        if need_to_wait:
            # Wait for diagnostics to be ready
            self._wait_for_diagnostics([uri], timeout)

        # Return diagnostics or error
        with self._opened_files_lock:
            state = self.opened_files[path]
            logger.debug(
                "get_diagnostics: path=%s, diag=%s, error=%s, processing=%s, "
                "version=%s, diag_version=%s",
                path,
                state.diagnostics,
                state.error,
                state.processing,
                state.version,
                state.diagnostics_version,
            )
            if state.error:
                return [state.error]
            # If we saw a fatal error but have no diagnostics, return generic error message
            if state.fatal_error and not state.diagnostics:
                return [
                    {"message": "leanclient: Received LeanFileProgressKind.fatalError."}
                ]
            return state.diagnostics

    def get_file_content(self, path: str) -> str:
        """Get the content of a file as seen by the language server.

        Args:
            path (str): Relative file path.

        Returns:
            str: Content of the file.
        """
        with self._opened_files_lock:
            state = self.opened_files.get(path)
            if state is not None:
                return state.content

        raise FileNotFoundError(f"File {path} is not open. Call open_file first.")

    def _wait_for_diagnostics(
        self, uris: list[str], inactivity_timeout: float = 3.0
    ) -> None:
        """Wait until file is loaded or an rpc error occurs.

        This method uses an adaptive timeout that resets whenever diagnostics are received.
        This allows long-running operations to complete while quickly detecting stuck states.

        Args:
            uris (list[str]): List of URIs to wait for diagnostics on.
            inactivity_timeout (float): Time to wait since last activity (diagnostics update). Defaults to 3 seconds.
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
                    not state.complete
                    and not state.processing
                    and state.diagnostics_version >= state.version
                ):
                    state.complete = True

                if not state.complete:
                    uris_needing_wait.append(uri)
                    target_versions[uri] = state.version

        if not uris_needing_wait:
            # All files already have diagnostics or errors
            return

        # Send waitForDiagnostics requests for files that need it
        futures_by_uri = {}
        for uri in uris_needing_wait:
            params = {"uri": uri, "version": target_versions[uri]}
            futures_by_uri[uri] = self._send_request_async(
                "textDocument/waitForDiagnostics", params
            )

        # Wait for completion with adaptive timeout
        start_time = time.monotonic()
        pending_uris = set(uris_needing_wait)

        while pending_uris:
            current_time = time.monotonic()
            total_elapsed = current_time - start_time

            completed_uris: set[str] = set()
            max_inactivity = 0.0

            with self._opened_files_lock:
                # First, process futures that completed
                for uri in list(pending_uris):
                    future = futures_by_uri[uri]
                    if future.done():
                        path = path_by_uri[uri]
                        state = self.opened_files[path]
                        try:
                            future.result()
                        except Exception as e:
                            state.error = {"message": str(e)}
                            state.processing = False
                        state.complete = True
                        state.last_activity = current_time
                        completed_uris.add(uri)

                # Then check remaining URIs for state changes via notification handlers
                for uri in pending_uris - completed_uris:
                    path = path_by_uri[uri]
                    state = self.opened_files[path]
                    target_version = target_versions[uri]

                    if (
                        not state.complete
                        and not state.processing
                        and state.diagnostics_version >= target_version
                    ):
                        state.complete = True
                        state.last_activity = current_time
                        completed_uris.add(uri)
                    elif state.complete:
                        completed_uris.add(uri)
                    else:
                        # Track maximum inactivity time across all pending URIs
                        inactivity = current_time - state.last_activity
                        max_inactivity = max(max_inactivity, inactivity)

            pending_uris.difference_update(completed_uris)

            if not pending_uris:
                break

            # Check inactivity timeout - if no progress for inactivity_timeout seconds, give up
            if max_inactivity > inactivity_timeout:
                logger.warning(
                    "_wait_for_diagnostics timed out after %.1fs of inactivity (%.1fs total).",
                    inactivity_timeout,
                    total_elapsed,
                )
                break

            time.sleep(0.001)
