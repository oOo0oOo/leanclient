import collections
from pprint import pprint

from .utils import DocumentContentChange, apply_changes_to_text, experimental

from .base_client import BaseLeanLSPClient


class LSPFileManager(BaseLeanLSPClient):
    """Manages opening, closing and syncing files on the language server.

    See :meth:`leanclient.client.BaseLeanLSPClient` for details.
    """

    def __init__(
        self,
        max_opened_files: int = 8,
    ):
        self.max_opened_files = max_opened_files
        self.opened_files_diagnostics = collections.OrderedDict()
        self.opened_files_content = {}

    def _open_new_files(self, paths: list[str]) -> list:
        """Open new files in the language server.

        See :meth:`_wait_for_diagnostics` for information on the diagnostic response.

        Args:
            paths (list[str]): List of relative file paths.

        Returns:
            list: List of diagnostics for each file.
        """
        uris = self._locals_to_uris(paths)
        for path, uri in zip(paths, uris):
            with open(self._uri_to_abs(uri), "r") as f:
                txt = f.read()
            self.opened_files_content[path] = txt

            params = {
                "textDocument": {
                    "uri": uri,
                    "text": txt,
                    "languageId": "lean",
                    "version": 1,
                },
                "dependencyBuildMode": "always",
            }
            self._send_notification("textDocument/didOpen", params)

        return self._wait_for_diagnostics(uris)

    def open_files(self, paths: list[str]) -> list:
        """Open files in the language server or retrieve diagnostics from cache.

        See :meth:`_wait_for_diagnostics` for information on the diagnostic response.

        Args:
            paths (list[str]): List of relative file paths to open.

        Returns:
            list: List of diagnostics for each file.
        """
        if len(paths) > self.max_opened_files:
            raise RuntimeError(
                f"Warning! Can not open more than {self.max_opened_files} files at once. Increase LeanLSPClient.max_opened_files or open less files."
            )

        # Open new files
        new_files = [p for p in paths if p not in self.opened_files_diagnostics]
        if new_files:
            diagnostics = self._open_new_files(new_files)
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

    def open_file(self, path: str) -> list:
        """Open a file in the language server or retrieve diagnostics from cache.

        See :meth:`_wait_for_diagnostics` for information on the diagnostic response.

        Args:
            path (str): Relative file path to open.

        Returns:
            list: Diagnostics of file
        """
        return self.open_files([path])[0]

    @experimental
    def update_file(self, path: str, changes: list[DocumentContentChange]) -> list:
        """Update a file in the language server.

        Note:

            Changes are not written to disk! Use :meth:`get_file_content` to get the current content of a file, as seen by the language server.

        See :meth:`_wait_for_diagnostics` for information on the diagnostic response.
        Raises a FileNotFoundError if the file is not open.

        Args:
            path (str): Relative file path to update.
            changes (list[DocumentContentChange]): List of changes to apply.

        Returns:
            list: Diagnostics of file
        """
        if path not in self.opened_files_diagnostics:
            raise FileNotFoundError(f"File {path} is not open. Call open_file first.")
        uri = self._local_to_uri(path)

        text = self.opened_files_content[path]
        text = apply_changes_to_text(text, changes)
        self.opened_files_content[path] = text

        # TODO: Make any of these work instead of the nuclear version of reloading the file
        # params = ("textDocument/didSave", {"textDocument": {"uri": uri}, "text": text})
        # params = ("textDocument/didChange", {"textDocument": {"uri": uri, "version": 1, "languageId": "lean"}, "contentChanges": [c.get_dict() for c in changes]})
        # params = ("textDocument/didChange", {"textDocument": {"uri": uri, "version": 1, "languageId": "lean"}, "contentChanges": [{"text": text}]})
        # params = ("workspace/applyEdit", {"changes": [{"textDocument": {"uri": uri, "version": 1}, "edits": [c.get_dict() for c in changes]}]})
        # params = ("workspace/didChangeWatchedFiles", {"changes": [{"uri": uri, "type": 2}]})

        params = (
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": uri,
                    "text": text,
                    "languageId": "lean",
                    "version": 1,
                }
            },
        )

        self._send_notification(*params)

        diagnostics = self._wait_for_diagnostics([uri])[0]
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
        paths = [p for p in paths if p in self.opened_files_diagnostics]
        uris = self._locals_to_uris(paths)
        for uri in uris:
            params = {"textDocument": {"uri": uri}}
            self._send_notification("textDocument/didClose", params)

        for path in paths:
            del self.opened_files_diagnostics[path]
            del self.opened_files_content[path]

        # Wait for published diagnostics
        if blocking:
            waiting_uris = set(uris)
            while waiting_uris:
                resp = self._read_stdout()
                if resp and resp.get("method") == "textDocument/publishDiagnostics":
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
