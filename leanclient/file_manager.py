import collections
from pprint import pprint
import time
import urllib.parse
import select

from .utils import DocumentContentChange, apply_changes_to_text
from .base_client import BaseLeanLSPClient


IGNORED_METHODS = {
    "workspace/didChangeWatchedFiles",
    "workspace/semanticTokens/refresh",
    "client/registerCapability",
}


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
        timeout: float = 30,
        dependency_build_mode: str = "never",
    ) -> list:
        """Open new files in the language server.

        See :meth:`_wait_for_diagnostics` for information on the diagnostic response.

        Args:
            paths (list[str]): List of relative file paths.
            timeout (float): Time to wait for diagnostics. Defaults to 30 seconds.
            dependency_build_mode (str): Whether to automatically rebuild dependencies. Defaults to "never".

        Returns:
            list: List of diagnostics for each file.
        """
        uris = self._locals_to_uris(paths)
        for path, uri in zip(paths, uris):
            with open(self._uri_to_abs(uri), "r") as f:
                txt = f.read()
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

        return self._wait_for_diagnostics(uris, timeout)

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
        rid = self._send_request_rpc(method, params, is_notification=False)

        result = self._read_stdout()
        while result.get("method") == "workspace/semanticTokens/refresh" or (
            result.get("id") != rid and "error" not in result
        ):
            # Ignore some messages from `workspace/semanticTokens/refresh` and the like
            result = self._read_stdout()
        return result.get("result", result)

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

    def open_files(self, paths: list[str], timeout: float = 30) -> list:
        """Open files in the language server and return diagnostics.

        This function maintains a cache of opened files and their diagnostics.
        See :meth:`_wait_for_diagnostics` for information on the diagnostic response.

        Note:
            Opening multiple files is typically faster than opening them sequentially.

        Args:
            paths (list[str]): List of relative file paths to open.
            timeout (float): Time to wait for diagnostics. Defaults to 30 seconds.

        Returns:
            list: List of diagnostics for each file.
        """
        if len(paths) > self.max_opened_files:
            raise RuntimeError(
                f"Warning! Can not open more than {self.max_opened_files} files at once. Increase LeanLSPClient.max_opened_files or open less files."
            )

        paths = [urllib.parse.unquote(p) for p in paths]

        # Open new files
        new_files = [p for p in paths if p not in self.opened_files_diagnostics]
        if new_files:
            diagnostics = self._open_new_files(new_files, timeout)
            self.opened_files_diagnostics.update(zip(new_files, diagnostics))

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

        return [self.opened_files_diagnostics[path] for path in paths]

    def open_file(self, path: str, timeout: float = 30) -> list:
        """Open a file in the language server and return diagnostics.

        See :meth:`_wait_for_diagnostics` for information on the diagnostic response.

        Args:
            path (str): Relative file path to open.
            timeout (float): Time to wait for diagnostics. Defaults to 30 seconds.

        Returns:
            list: Diagnostics of file
        """
        return self.open_files([path], timeout)[0]

    def update_file(
        self, path: str, changes: list[DocumentContentChange], timeout: float = 30
    ) -> list:
        """Update a file in the language server.

        Note:

            Changes are not written to disk! Use :meth:`get_file_content` to get the current content of a file, as seen by the language server.

        See :meth:`_wait_for_diagnostics` for information on the diagnostic response.
        Raises a FileNotFoundError if the file is not open.

        Args:
            path (str): Relative file path to update.
            changes (list[DocumentContentChange]): List of changes to apply.
            timeout (float): Time to wait for diagnostics. Defaults to 30 seconds.

        Returns:
            list: Diagnostics of file
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
        # params = ("textDocument/didChange", {"textDocument": {"uri": uri, "version": 1, "languageId": "lean"}, "contentChanges": [{"text": text}]})
        # params = ("textDocument/didSave", {"textDocument": {"uri": uri}, "text": text})
        # params = ("workspace/applyEdit", {"changes": [{"textDocument": {"uri": uri, "version": 1}, "edits": [c.get_dict() for c in changes]}]})
        # params = ("workspace/didChangeWatchedFiles", {"changes": [{"uri": uri, "type": 2}]})

        params = (
            "textDocument/didChange",
            {
                "textDocument": {"uri": uri, "version": version, "languageId": "lean"},
                "contentChanges": [c.get_dict() for c in changes],
            },
        )

        self._send_notification(*params)

        diagnostics = self._wait_for_diagnostics([uri], timeout)[0]
        self.opened_files_diagnostics[path] = diagnostics
        return diagnostics

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
            while waiting_uris:
                resp = self._read_stdout()
                if resp.get("method") == "textDocument/publishDiagnostics":
                    waiting_uris.discard(resp["params"]["uri"])

    def get_diagnostics(self, path: str) -> list:
        """Get diagnostics for a single file.

        See :meth:`_wait_for_diagnostics` for information on the diagnostic response.

        Args:
            path (str): Relative file path.

        Returns:
            list: Diagnostics of file
        """
        if path in self.opened_files_diagnostics:
            return self.opened_files_diagnostics[path]
        return self.open_file(path)

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

    def get_diagnostics_multi(self, paths: list[str]) -> list:
        """Get diagnostics for a list of files.

        See :meth:`_wait_for_diagnostics` for information on the diagnostic response.

        Args:
            paths (list[str]): List of relative file paths.

        Returns:
            list: List of diagnostics for each file.
        """
        diagnostics = {}
        missing = []
        for path in paths:
            if path in self.opened_files_diagnostics:
                # Store these now, because they might be closed soon?
                diagnostics[path] = self.opened_files_diagnostics[path]
            else:
                missing.append(path)

        if missing:
            missing = list(set(missing))
            diagnostics.update(zip(missing, self.open_files(missing)))

        return [diagnostics[path] for path in paths]

    def _wait_for_diagnostics(self, uris: list[str], timeout: float = 30) -> list:
        """Wait until file is loaded or an rpc error occurs.

        This should only be used right after opening or updating files not to miss any responses.
        Returns either diagnostics or an [{error dict}] for each file.

        Checks `waitForDiagnostics` and `fileProgress` for each file.

        Sometimes either of these can fail, so we need to check for "rpc errors", "fatal errors" and use a timeout..
        See source for more details.

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
            uris (list[str]): List of URIs to wait for diagnostics on.
            timeout (float): Time to wait for diagnostics. Defaults to 30 seconds.

        Returns:
            list: List of diagnostic messages or errors.
        """
        TIMEOUT_SHORT = 0.01

        # Check if all files are opened
        paths = [self._uri_to_local(uri) for uri in uris]
        missing = [p for p in paths if p not in self.opened_files_diagnostics]
        if missing:
            raise FileNotFoundError(
                f"Files {missing} are not open. Call open_files first."
            )

        # Request waitForDiagnostics for each file
        rid_to_uri = {}
        for uri, path in zip(uris, paths):
            version = self.opened_files_versions[path]
            rid = self._send_request_rpc(
                "textDocument/waitForDiagnostics",
                {"uri": uri, "version": version},
                is_notification=False,
            )
            rid_to_uri[rid] = uri

        num_missing_processing = len(uris)
        num_missing_wait = len(uris)
        errored = set()
        diagnostics = {}
        while num_missing_processing > 0 or num_missing_wait > 0:
            # Non-blocking read, `waitForDiagnostics` or `processing == []` doesn't always return e.g. "unfinished comment"
            # Timeout is shortened if all remaining files have errored
            num_errors = len(errored)
            short = (
                num_errors >= num_missing_processing and num_errors >= num_missing_wait
            )
            tmt = TIMEOUT_SHORT if short else timeout
            if select.select([self.stdout], [], [], tmt)[0]:
                res = self._read_stdout()
            else:
                print(
                    f"WARNING: `_wait_for_diagnostics` timed out after {tmt} seconds."
                )
                break

            method = res.get("method")

            # Capture diagnostics
            if method == "textDocument/publishDiagnostics":
                uri = res["params"]["uri"]
                diagnostics[uri] = res["params"]["diagnostics"]
                continue

            # `waitForDiagnostics` has returned
            elif res.get("result", True) == {}:
                num_missing_wait -= 1
                continue

            # RPC error (only from `waitForDiagnostics`)
            # These can lead to confusing BUGS, remove?
            elif "error" in res:
                uri = rid_to_uri.get(res.get("id"))
                if uri:
                    diagnostics[uri] = [res]
                errored.add(uri)
                continue

            elif method in IGNORED_METHODS:
                continue

            if method != "$/lean/fileProgress":
                print(
                    f"WARNING: Unhandled method: {method}. Consider opening an issue on leanclient github."
                )
                continue

            # Check for fatalError from fileProgress. See here:
            # https://github.com/leanprover/lean4/blob/8791a9ce069d6dc87f7cccc4387545b1110c89bd/src/Lean/Data/Lsp/Extra.lean#L55
            proc = res["params"]["processing"]
            if proc == []:
                num_missing_processing -= 1
            elif proc and proc[-1]["kind"] == 2:
                uri = res["params"]["textDocument"]["uri"]
                errored.add(uri)
                if not diagnostics.get(uri):
                    msg = f"leanclient: Received LeanFileProgressKind.fatalError from language server."
                    res["error"] = {"message": msg}
                    diagnostics[uri] = [res]

        return [diagnostics.get(uri, []) for uri in uris]
