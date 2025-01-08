import os
import collections
from pprint import pprint
import select
import subprocess

import orjson

from .utils import SemanticTokenProcessor, DocumentContentChange
from .file_client import SingleFileClient


class LeanLSPClient:
    """LeanLSPClient is a thin wrapper around the Lean language server.

    It interacts with a subprocess running `lake serve` via the `Language Server Protocol (LSP) <https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/>`_.
    This wrapper is blocking, it always waits until the language server responds.

    NOTE:
        Your **project_path** is the root folder of a Lean project where `lakefile.toml` is located.
        This is where `lake build` and `lake serve` are run.

        All file paths are **relative** to the project_path.

        E.g. ".lake/packages/mathlib/Mathlib/Init.lean" can be a valid path.

    Args:
        project_path (str): Path to the root folder of a Lean project.
        max_opened_files (int): Maximum number of files to keep open at once.
        initial_build (bool): Whether to run `lake build` on initialization. This is usually not required, but is the only check whether the project is valid.
    """

    def __init__(
        self, project_path: str, max_opened_files: int = 8, initial_build: bool = True
    ):
        self.project_path = os.path.abspath(project_path) + "/"
        self.len_project_uri = len(self.project_path) + 7
        self.max_opened_files = max_opened_files
        self.request_id = 0
        self.opened_files = collections.OrderedDict()

        if initial_build:
            subprocess.run(["lake", "build"], cwd=self.project_path, check=True)

        # Run the lean4 language server in a subprocess
        self.process = subprocess.Popen(
            ["lake", "serve"],
            cwd=self.project_path,
            stdout=subprocess.PIPE,
            stdin=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.stdin = self.process.stdin
        self.stdout = self.process.stdout

        # Check stderr for any errors
        error = self._read_stderr_non_blocking()
        if error:
            print("Process started with stderr message:\n", error)

        # Send initialization request, surprisingly no params required
        results = self._send_request("initialize", {"processId": os.getpid()})
        server_info = results[-1]["result"]
        legend = server_info["capabilities"]["semanticTokensProvider"]["legend"]
        self.token_processor = SemanticTokenProcessor(legend["tokenTypes"])

        self._send_notification("initialized", {})

    def close(self):
        """Always close the client when done!

        Terminates the language server process and close all pipes.
        """
        self.process.terminate()
        self.process.stderr.close()
        self.stdout.close()
        self.stdin.close()
        self.process.wait()

    # URI HANDLING
    def _local_to_uri(self, local_path: str) -> str:
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
        return "file://" + self.project_path + local_path

    def _locals_to_uris(self, local_paths: list[str]) -> list[str]:
        """See :meth:`_local_to_uri`"""
        return [
            "file://" + self.project_path + local_path for local_path in local_paths
        ]

    def _uri_to_abs(self, uri: str) -> str:
        """See :meth:`_local_to_uri`"""
        return uri[7:]

    def _uri_to_local(self, uri: str) -> str:
        """See :meth:`_local_to_uri`"""
        return uri[self.len_project_uri :]

    # LANGUAGE SERVER RPC INTERACTION
    def _read_stdout(self) -> dict:
        """Read the next message from the language server.

        This is the main blocking function in this synchronous client:


        Returns:
            dict: JSON response from the language server.
        """
        header = self.stdout.readline().decode("ascii")

        # Handle EOF: Return contents of stderr (non-blocking using select)
        if not header:
            line = self._read_stderr_non_blocking()
            if line:
                line = "lake stderr message:\n" + line
            if not line:
                line = "No lake stderr message."
            self.close()
            raise EOFError(f"Language server has closed. {line}")

        # Parse message
        content_length = int(header.split(":")[1])
        next(self.stdout)
        resp = orjson.loads(self.stdout.read(content_length))

        # Display RPC error messages (from language server)
        if "error" in resp:
            print("RPC Error Message:\n", resp)

        return resp

    def _read_stderr_non_blocking(self, timeout: float = 0.00001) -> str:
        """Read the next message from the language server's stderr.

        Args:
            timeout (float): Time to wait for stderr message.

        Returns:
            str: Message from the language server's stderr.
        """
        stderr = self.process.stderr
        if select.select([stderr], [], [], timeout)[0]:
            return stderr.readline().decode("utf-8")
        return ""

    def _send_request_rpc(self, method: str, params: dict, is_notification: bool):
        """Send a JSON RPC request to the language server.

        Args:
            method (str): Method name.
            params (dict): Parameters for the method.
            is_notification (bool): Whether the request is a notification.
        """
        request = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            **({"id": self.request_id} if not is_notification else {}),
        }
        if not is_notification:
            self.request_id += 1

        body = orjson.dumps(request)
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        self.stdin.write(header + body)
        self.stdin.flush()

    def _send_request(self, method: str, params: dict) -> list[dict]:
        """Send a request to the language server and return all responses.

        Args:
            method (str): Method name.
            params (dict): Parameters for the method.

        Returns:
            list[dict]: List of responses in the order they were received.
        """
        self._send_request_rpc(method, params, is_notification=False)
        rid = self.request_id - 1

        result = self._read_stdout()
        results = [result]
        while result.get("id") != rid and "error" not in result:
            result = self._read_stdout()
            results.append(result)

        return results

    def _send_request_document(self, path: str, method: str, params: dict) -> dict:
        """Send request about a document and return the final response.

        This function drops all intermediate responses since we typically don't need them.

        Args:
            path (str): Relative file path.
            method (str): Method name.
            params (dict): Parameters for the method.

        Returns:
            dict: Final response.
        """
        self.open_file(path)
        params["textDocument"] = {"uri": self._local_to_uri(path)}
        results = self._send_request(method, params)
        return results[-1]["result"]

    def _send_notification(self, method: str, params: dict):
        """Send a notification to the language server.

        Args:
            method (str): Method name.
            params (dict): Parameters for the method.
        """
        self._send_request_rpc(method, params, is_notification=True)

    # OPEN/CLOSE FILES IN LANGUAGE SERVER
    def _wait_for_diagnostics(self, uris: list[str]) -> list[dict]:
        """Wait until `waitForDiagnostics` returns or an rpc error occurs.

        This should only be used right after opening or updating files not to miss any responses.

        **Example diagnostics**:

        .. code-block:: python

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
            ]

        Args:
            uris (list[str]): List of URIs to wait for diagnostics on.

        Returns:
            list[dict]: List of diagnostic messages.
        """
        # Waiting in series; Parallel requests are not reliable?
        responses = []
        for uri in uris:
            responses += self._send_request(
                "textDocument/waitForDiagnostics", {"uri": uri, "version": 1}
            )
            result = responses[-1]
            while True:
                # Could also require: result.get("id") == self.request_id - 1
                # Currently works bc the return value of waitForDiagnostics is `{}` (a bit unusual and therefore unique?)
                if result.get("result", True) == {}:
                    break
                elif "error" in result:
                    return responses + [result]
                result = self._read_stdout()
                responses.append(result)

        diagnostics = {
            resp["params"]["uri"]: resp["params"]["diagnostics"]
            for resp in responses
            if resp.get("method") == "textDocument/publishDiagnostics"
        }
        return [diagnostics[uri] for uri in uris]

    def _open_new_files(self, paths: list[str]) -> list:
        """Open new files in the language server.

        See :meth:`_wait_for_diagnostics` for information on the diagnostic response.

        Args:
            paths (list[str]): List of relative file paths.

        Returns:
            list: List of diagnostics for each file.
        """
        uris = self._locals_to_uris(paths)
        for uri in uris:
            params = {"textDocument": {"uri": uri}}
            with open(self._uri_to_abs(uri), "r") as f:
                params["textDocument"]["text"] = f.read()
            params["textDocument"]["languageId"] = "lean"
            params["textDocument"]["version"] = 1
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
            print(
                f"Warning! Should not open more than {self.max_opened_files} files at once."
            )

        # Open new files
        new_files = [p for p in paths if p not in self.opened_files]
        if new_files:
            diagnostics = self._open_new_files(new_files)
            self.opened_files.update(zip(new_files, diagnostics))

        # Remove files if over limit
        remove_count = max(0, len(self.opened_files) - self.max_opened_files)
        if remove_count > 0:
            removable_paths = [p for p in self.opened_files if p not in paths]
            removable_paths = removable_paths[:remove_count]
            self.close_files(removable_paths)

        return [self.opened_files[path] for path in paths]

    def open_file(self, path: str) -> list:
        """Open a file in the language server or retrieve diagnostics from cache.

        See :meth:`_wait_for_diagnostics` for information on the diagnostic response.

        Args:
            path (str): Relative file path to open.

        Returns:
            list: Diagnostics of file
        """
        return self.open_files([path])[0]

    def update_file(self, path: str, changes: list[DocumentContentChange]) -> list:
        """Update a file in the language server.

        Note:

            Changes are not written to disk! Will be implemented in the future.

        See :meth:`_wait_for_diagnostics` for information on the diagnostic response.
        Raises a FileNotFoundError if the file is not open.

        Args:
            path (str): Relative file path to update.
            changes (list[DocumentContentChange]): List of changes to apply.

        Returns:
            list: Diagnostics of file
        """
        if path not in self.opened_files:
            raise FileNotFoundError(f"File {path} is not open. Call open_file first.")
        uri = self._local_to_uri(path)
        params = {"textDocument": {"uri": uri}}
        params["textDocument"]["languageId"] = "lean"
        params["textDocument"]["version"] = 1
        params["contentChanges"] = [c.get_dict() for c in changes]
        self._send_notification("textDocument/didChange", params)

        # Simply await the first diagnostics
        # waitForDiagnostics does not return...
        while True:
            resp = self._read_stdout()
            if resp.get("method") == "textDocument/publishDiagnostics":
                break
        diagnostics = resp["params"]["diagnostics"]
        self.opened_files[path] = resp["params"]["diagnostics"]
        return diagnostics

    def close_files(self, paths: list[str], blocking: bool = True):
        """Close files in the language server.

        Calling this manually is optional, files are automatically closed when max_opened_files is reached.

        Args:
            paths (list[str]): List of relative file paths to close.
            blocking (bool): Not blocking can be risky if you close files frequently or reopen them.
        """
        # Only close if file is open
        paths = [p for p in paths if p in self.opened_files]
        uris = self._locals_to_uris(paths)
        for uri in uris:
            params = {"textDocument": {"uri": uri}}
            self._send_notification("textDocument/didClose", params)

        for path in paths:
            del self.opened_files[path]

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
        if path in self.opened_files:
            return self.opened_files[path]
        return self.open_file(path)

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
            if path in self.opened_files:
                # Store these now, because they might be closed soon?
                diagnostics[path] = self.opened_files[path]
            else:
                missing.append(path)

        if missing:
            missing = list(set(missing))
            diagnostics.update(zip(missing, self.open_files(missing)))

        return [diagnostics[path] for path in paths]

    def create_file_client(self, file_path: str) -> SingleFileClient:
        """Create a SingleFileClient for a file.

        Args:
            file_path (str): Relative file path.

        Returns:
            SingleFileClient: A client for interacting with a single file.
        """
        return SingleFileClient(self, file_path)

    # LEAN LANGUAGE SERVER API

    def get_completions(self, path: str, line: int, character: int) -> list:
        """Get completion items at a file position.

        The :guilabel:`textDocument/completion` method in LSP provides context-aware code completion suggestions at a specified cursor position.
        It returns a list of possible completions for partially typed code, suggesting continuations.

        More information:

        - LSP Docs: `Completion Request <https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#textDocument_completion>`_
        - Lean Source: `FileWorker.lean <https://github.com/leanprover/lean4/blob/master/src/Lean/Server/FileWorker.lean#L616>`_

        Example response:

        .. code-block:: python

            [
                {
                    'data': {
                        'id': {'const': {'declName': 'Nat.dvd_add'}},
                        'params': {
                            'position': {'character': 15, 'line': 9},
                            'textDocument': {'uri': 'file://...'}
                        }
                    },
                    'kind': 23,
                    'label': 'dvd_add',
                    'sortText': '001'
                },
                # ...
            ]

        Args:
            path (str): Relative file path.
            line (int): Line number.
            character (int): Character number.

        Returns:
            list: Completion items.
        """
        resp = self._send_request_document(
            path,
            "textDocument/completion",
            {"position": {"line": line, "character": character}},
        )
        return resp["items"]  # NOTE: We discard `isIncomplete` for now

    def get_completion_item_resolve(self, item: dict) -> str:
        """Resolve a completion item.

        The :guilabel:`completionItem/resolve` method in LSP is used to resolve additional information for a completion item.

        More information:

        - LSP Docs: `Completion Item Resolve Request <https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#completionItem_resolve>`_
        - Lean Source: `ImportCompletion.lean <https://github.com/leanprover/lean4/blob/master/src/Lean/Server/Completion/ImportCompletion.lean#L130>`_

        Example response:

        .. code-block:: python

            # Input item
            {"label": "add_lt_of_lt_sub'", ...}

            # Detail is:
            "b < c - a → a + b < c"

        Args:
            item (dict): Completion item.

        Returns:
            str: Additional detail about the completion item.

        """
        uri = item["data"]["params"]["textDocument"]["uri"]
        return self._send_request_document(
            self._uri_to_local(uri), "completionItem/resolve", item
        )["detail"]

    def get_hover(self, path: str, line: int, character: int) -> dict | None:
        """Get hover information at a cursor position.

        The :guilabel:`textDocument/hover` method in LSP retrieves hover information,
        providing details such as type information, documentation, or other relevant data about the symbol under the cursor.

        More information:

        - LSP Docs: `Hover Request <https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#textDocument_hover>`_
        - Lean Source: `RequestHandling.lean\u200B\u200C <https://github.com/leanprover/lean4/blob/master/src/Lean/Server/FileWorker/RequestHandling.lean#L77₀>`_

        Example response:

        .. code-block:: python

            {
                "range": {
                    "start": {"line": 4, "character": 2},
                    "end": {"line": 4, "character": 8}
                },
                "contents": {
                    "value": "The left hand side of an induction arm, `| foo a b c` or `| @foo a b c`\\nwhere `foo` is a constructor of the inductive type and `a b c` are the arguments\\nto the constructor.\\n",
                    "kind": "markdown"
                }
            }

        Args:
            path (str): Relative file path.
            line (int): Line number.
            character (int): Character number.

        Returns:
            dict: Hover information or None if no hover information is available.
        """
        return self._send_request_document(
            path,
            "textDocument/hover",
            {"position": {"line": line, "character": character}},
        )

    def get_declarations(self, path: str, line: int, character: int) -> list:
        """Get locations of declarations at a file position.

        The :guilabel:`textDocument/declaration` method in LSP retrieves the declaration location of a symbol at a specified cursor position.

        More information:

        - LSP Docs: `Goto Declaration Request <https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#textDocument_declaration>`_
        - Lean Source: `Watchdog.lean <https://github.com/leanprover/lean4/blob/master/src/Lean/Server/Watchdog.lean#L911>`_

        Example response:

        .. code-block:: python

             [{
                'originSelectionRange': {
                    'end': {'character': 7, 'line': 6},
                    'start': {'character': 4, 'line': 6}
                },
                'targetRange': {
                    'end': {'character': 21, 'line': 370},
                    'start': {'character': 0, 'line': 365}
                },
                'targetSelectionRange': {
                    'end': {'character': 6, 'line': 370},
                    'start': {'character': 0, 'line': 370}
                },
                'targetUri': 'file://...'
            }]

        Args:
            path (str): Relative file path.
            line (int): Line number.
            character (int): Character number.

        Returns:
            list: Locations.
        """
        return self._send_request_document(
            path,
            "textDocument/declaration",
            {"position": {"line": line, "character": character}},
        )

    def get_definitions(self, path: str, line: int, character: int) -> list:
        """Get location of symbol definition at a file position.

        The :guilabel:`textDocument/definition` method in LSP retrieves the definition location of a symbol at a specified cursor position.
        Find implementations or definitions of variables, functions, or types within the codebase.

        More information:

        - LSP Docs: `Goto Definition Request <https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#textDocument_definition>`_
        - Lean Source: `Watchdog.lean <https://github.com/leanprover/lean4/blob/master/src/Lean/Server/Watchdog.lean#L911>`_

        Example response:

        .. code-block:: python

             [{
                'originSelectionRange': {
                    'end': {'character': 7, 'line': 6},
                    'start': {'character': 4, 'line': 6}
                },
                'targetRange': {
                    'end': {'character': 21, 'line': 370},
                    'start': {'character': 0, 'line': 365}
                },
                'targetSelectionRange': {
                    'end': {'character': 6, 'line': 370},
                    'start': {'character': 0, 'line': 370}
                },
                'targetUri': 'file://...'
            }]

        Args:
            path (str): Relative file path.
            line (int): Line number.
            character (int): Character number.

        Returns:
            list: Locations.
        """
        return self._send_request_document(
            path,
            "textDocument/definition",
            {"position": {"line": line, "character": character}},
        )

    def get_references(self, path: str, line: int, character: int) -> list:
        """Get locations of references to a symbol at a file position.

        In LSP, the :guilabel:`textDocument/references` method provides the locations of all references to a symbol at a given cursor position.

        More information:

        - LSP Docs: `Find References Request <https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#textDocument_references>`_
        - Lean Source: `Watchdog.lean\u200B <https://github.com/leanprover/lean4/blob/master/src/Lean/Server/Watchdog.lean#L528>`_

        Example response:

        .. code-block:: python

            [
                {
                    'range': {
                        'end': {'character': 14, 'line': 7},
                        'start': {'character': 12, 'line': 7}
                    },
                    'uri': 'file://...'
                },
                # ...
            ]

        Args:
            path (str): Relative file path.
            line (int): Line number.
            character (int): Character number.

        Returns:
            list: Locations.
        """
        return self._send_request_document(
            path,
            "textDocument/references",
            {
                "position": {"line": line, "character": character},
                "context": {"includeDeclaration": True},
            },
        )

    def get_type_definitions(self, path: str, line: int, character: int) -> list:
        """Get locations of type definition of a symbol at a file position.

        The :guilabel:`textDocument/typeDefinition` method in LSP returns the location of a symbol's type definition based on the cursor's position.

        More information:

        - LSP Docs: `Goto Type Definition Request <https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#textDocument_typeDefinition>`_
        - Lean Source: `RequestHandling.lean <https://github.com/leanprover/lean4/blob/master/src/Lean/Server/FileWorker/RequestHandling.lean#L245>`_

        Example response:

        .. code-block:: python

             [{
                'originSelectionRange': {
                    'end': {'character': 7, 'line': 6},
                    'start': {'character': 4, 'line': 6}
                },
                'targetRange': {
                    'end': {'character': 21, 'line': 370},
                    'start': {'character': 0, 'line': 365}
                },
                'targetSelectionRange': {
                    'end': {'character': 6, 'line': 370},
                    'start': {'character': 0, 'line': 370}
                },
                'targetUri': 'file://...'
            }]

        Args:
            path (str): Relative file path.
            line (int): Line number.
            character (int): Character number.

        Returns:
            list: Locations.
        """
        return self._send_request_document(
            path,
            "textDocument/typeDefinition",
            {"position": {"line": line, "character": character}},
        )

    def get_document_highlights(self, path: str, line: int, character: int) -> list:
        """Get highlight ranges for a symbol at a file position.

        The :guilabel:`textDocument/documentHighlight` method in LSP returns the highlighted range at a specified cursor position.

        More information:

        - LSP Docs: `Document Highlight Request <https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#textDocument_documentHighlight>`_
        - Lean Source: `RequestHandling.lean\u200B <https://github.com/leanprover/lean4/blob/master/src/Lean/Server/FileWorker/RequestHandling.lean#L324>`_

        Example response:

        .. code-block:: python

                [{
                    'range': {
                        'start': {'line': 5, 'character': 10},
                        'end': {'line': 5, 'character': 15}
                    },
                    'kind': 1
                }]

        Args:
            path (str): Relative file path.
            line (int): Line number.
            character (int): Character number.

        Returns:
            list: Document highlights.
        """

        return self._send_request_document(
            path,
            "textDocument/documentHighlight",
            {"position": {"line": line, "character": character}},
        )

    def get_document_symbols(self, path: str) -> list:
        """Get all document symbols in a document.

        The :guilabel:`textDocument/documentSymbol` method in LSP retrieves all symbols within a document, providing their names, kinds, and locations.

        More information:

        - LSP Docs: `Document Symbol Request <https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#textDocument_documentSymbol>`_
        - Lean Source: `RequestHandling.lean\u200C <https://github.com/leanprover/lean4/blob/master/src/Lean/Server/FileWorker/RequestHandling.lean#L387>`_

        Example response:

        .. code-block:: python

            [
                {
                    'kind': 6,
                    'name': 'add_zero_custom',
                    'range': {
                        'end': {'character': 25, 'line': 9},
                        'start': {'character': 0, 'line': 1}
                    },
                    'selectionRange': {
                        'end': {'character': 23, 'line': 1},
                        'start': {'character': 8, 'line': 1}}
                },
                # ...
            ]

        Args:
            path (str): Relative file path.

        Returns:
            list: Document symbols.
        """
        return self._send_request_document(path, "textDocument/documentSymbol", {})

    def get_semantic_tokens(self, path: str) -> list:
        """Get semantic tokens for the entire document.

        The :guilabel:`textDocument/semanticTokens/full` method in LSP returns semantic tokens for the entire document.

        Tokens are formated as: [line, char, length, token_type]

        See :meth:`get_semantic_tokens_range` for limiting to parts of a document.

        More information:

        - LSP Docs: `Semantic Tokens Full Request <https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#semanticTokens_fullRequest>`_
        - Lean Source: `RequestHandling.lean\u200D <https://github.com/leanprover/lean4/blob/master/src/Lean/Server/FileWorker/RequestHandling.lean#L573>`_

        Example response:

        .. code-block:: python

            [
                [1, 0, 7, "keyword"],
                [1, 25, 1, "variable"],
                [1, 36, 1, "variable"],
                # ...
            ]

        Args:
            path (str): Relative file path.

        Returns:
            list: Semantic tokens.
        """
        res = self._send_request_document(path, "textDocument/semanticTokens/full", {})
        return self.token_processor(res["data"])

    def get_semantic_tokens_range(
        self,
        path: str,
        start_line: int,
        start_character: int,
        end_line: int,
        end_character: int,
    ) -> list:
        """Get semantic tokens for a range in a document.

        See :meth:`get_semantic_tokens_full` for more information.

        Args:
            path (str): Relative file path.
            start_line (int): Start line.
            start_character (int): Start character.
            end_line (int): End line.
            end_character (int): End character.

        Returns:
            list: Semantic tokens.
        """
        res = self._send_request_document(
            path,
            "textDocument/semanticTokens/range",
            {
                "range": {
                    "start": {"line": start_line, "character": start_character},
                    "end": {"line": end_line, "character": end_character},
                }
            },
        )
        return self.token_processor(res["data"])

    def get_folding_ranges(self, path: str) -> list:
        """Get folding ranges in a document.

        The :guilabel:`textDocument/foldingRange` method in LSP returns folding ranges in a document.

        More information:

        - LSP Docs: `Folding Range Request <https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#textDocument_foldingRange>`_
        - Lean Source: `RequestHandling.lean\u200F <https://github.com/leanprover/lean4/blob/master/src/Lean/Server/FileWorker/RequestHandling.lean#L615>`_

        Example response:

        .. code-block:: python

            [
                {
                    'startLine': 0,
                    'endLine': 1,
                    'kind': 'region'
                },
                # ...
            ]

        Args:
            path (str): Relative file path.

        Returns:
            list: Folding ranges.

        """
        return self._send_request_document(path, "textDocument/foldingRange", {})

    def get_call_hierarchy_items(self, path: str, line: int, character: int) -> list:
        """Get call hierarchy items at a file position.

        The :guilabel:`textDocument/prepareCallHierarchy` method in LSP retrieves call hierarchy items at a specified cursor position.
        Use a call hierarchy item to get the incoming and outgoing calls: :meth:`get_call_hierarchy_incoming` and :meth:`get_call_hierarchy_outgoing`.

        More Information:

        - LSP Docs: `Prepare Call Hierarchy Request <https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#textDocument_prepareCallHierarchy>`_
        - Lean Source: `Watchdog.lean\u200D <https://github.com/leanprover/lean4/blob/master/src/Lean/Server/Watchdog.lean#L611>`_

        Example response:

        .. code-block:: python

            [
                {
                    'data': {'module': 'LeanTestProject.Basic', 'name': 'add_zero_custom'},
                    'kind': 14,
                    'name': 'add_zero_custom',
                    'range': {'end': {'character': 23, 'line': 1},
                                'start': {'character': 8, 'line': 1}},
                    'selectionRange': {'end': {'character': 23, 'line': 1},
                                        'start': {'character': 8, 'line': 1}},
                    'uri': 'file://...'
                }
            ]

        Args:
            path (str): Relative file path.
            line (int): Line number.
            character (int): Character number.

        Returns:
            list: Call hierarchy items.
        """
        return self._send_request_document(
            path,
            "textDocument/prepareCallHierarchy",
            {"position": {"line": line, "character": character}},
        )

    def get_call_hierarchy_incoming(self, item: dict) -> list:
        """Get call hierarchy items that call a symbol.

        The :guilabel:`callHierarchy/incomingCalls` method in LSP retrieves incoming call hierarchy items for a specified item.
        Use :meth:`get_call_hierarchy_items` first to get an item.

        More Information:

        - LSP Docs: `Incoming Calls Request <https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#callHierarchy_incomingCalls>`_
        - Lean Source: `Watchdog.lean\u200E <https://github.com/leanprover/lean4/blob/master/src/Lean/Server/Watchdog.lean#L624>`_

        Example response:

        .. code-block:: python

            [
                {
                    'from': {
                        'data': {'module': 'Mathlib.Data.Finset.Card', 'name': 'Finset.exists_eq_insert_iff'},
                        'kind': 14,
                        'name': 'Finset.exists_eq_insert_iff',
                        'range': {'end': {'character': 39, 'line': 630},
                                    'start': {'character': 0, 'line': 618}},
                        'selectionRange': {'end': {'character': 28, 'line': 618},
                                            'start': {'character': 8, 'line': 618}},
                        'uri': 'file://...'
                    },
                    'fromRanges': [{'end': {'character': 36, 'line': 630},
                                    'start': {'character': 10, 'line': 630}}]
                },
                # ...
            ]

        Args:
            item (dict): The call hierarchy item.

        Returns:
            list: Incoming call hierarchy items.
        """
        return self._send_request_document(
            self._uri_to_local(item["uri"]),
            "callHierarchy/incomingCalls",
            {"item": item},
        )

    def get_call_hierarchy_outgoing(self, item: dict) -> list:
        """Get outgoing call hierarchy items for a given item.

        The :guilabel:`callHierarchy/outgoingCalls` method in LSP retrieves outgoing call hierarchy items for a specified item.
        Use :meth:`get_call_hierarchy_items` first to get an item.

        More Information:

        - LSP Docs: `Outgoing Calls Request <https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#callHierarchy_outgoingCalls>`_
        - Lean Source: `Watchdog.lean\u200F <https://github.com/leanprover/lean4/blob/master/src/Lean/Server/Watchdog.lean#L676>`_

        Example response:

        .. code-block:: python

            [
                {
                    'fromRanges': [{'end': {'character': 52, 'line': 184},
                                    'start': {'character': 48, 'line': 184}},
                                    {'end': {'character': 66, 'line': 184},
                                    'start': {'character': 62, 'line': 184}}],
                    'to': {'data': {'module': 'Mathlib.Data.Finset.Insert', 'name': 'Finset.cons'},
                            'kind': 14,
                            'name': 'Finset.cons',
                            'range': {'end': {'character': 8, 'line': 234},
                                    'start': {'character': 4, 'line': 234}},
                            'selectionRange': {'end': {'character': 8, 'line': 234},
                                            'start': {'character': 4, 'line': 234}},
                            'uri': 'file://...'}
                }
            ]

        Args:
            item (dict): The call hierarchy item.

        Returns:
            list: Outgoing call hierarchy items.
        """
        return self._send_request_document(
            self._uri_to_local(item["uri"]),
            "callHierarchy/outgoingCalls",
            {"item": item},
        )

    def get_goal(self, path: str, line: int, character: int) -> dict | None:
        """Get proof goal at a file position.

        :guilabel:`$/lean/plainGoal` is a custom lsp request that returns the proof goal at a specified cursor position.

        In the VSCode `Lean Infoview`, this is shown as `Tactic state`.

        Use :meth:`get_term_goal` to get term goal.

        More information:

        - Lean Source: `RequestHandling.lean\u200A\u200F <https://github.com/leanprover/lean4/blob/master/src/Lean/Server/FileWorker/RequestHandling.lean#L285>`_

        Note:

            - Returns ``{'goals': [], 'rendered': 'no goals'}`` if there are no goals left 🎉.
            - Returns ``None`` if there are no goals at the position.

        Example response:

        .. code-block:: python

            {
                "goals": [
                    "case succ\\nn' : Nat\\nih : n' + 0 = n'\\n⊢ (n' + 0).succ + 0 = (n' + 0).succ"
                ],
                "rendered": "```lean\\ncase succ\\nn' : Nat\\nih : n' + 0 = n'\\n⊢ (n' + 0).succ + 0 = (n' + 0).succ\\n```"
            }

        Args:
            path (str): Relative file path.
            line (int): Line number.
            character (int): Character number.

        Returns:
            dict | None: Proof goals at the position.
        """
        return self._send_request_document(
            path,
            "$/lean/plainGoal",
            {"position": {"line": line, "character": character}},
        )

    def get_term_goal(self, path: str, line: int, character: int) -> dict | None:
        """Get term goal at a file position.

        :guilabel:`$/lean/plainTermGoal` is a custom lsp request that returns the term goal at a specified cursor position.

        In the VSCode Lean Infoview, this is shown as ``Expected type``.

        Use :meth:`get_goal` for the full proof goal.

        More information:

        - Lean Source: `RequestHandling.lean\u200A\u200B <https://github.com/leanprover/lean4/blob/master/src/Lean/Server/FileWorker/RequestHandling.lean#L316>`_

        Note:

            Returns ``None`` if there are is no term goal at the position.

        Example response:

        .. code-block:: python

            {
                'range': {
                    'start': {'line': 9, 'character': 8},
                    'end': {'line': 9, 'character': 20}
                },
                'goal': "n' : Nat\\nih : n' + 0 = n'\\n⊢ ∀ (n m : Nat), n + m.succ = (n + m).succ"
            }

        Args:
            path (str): Relative file path.
            line (int): Line number.
            character (int): Character number.

        Returns:
            dict | None: Term goal at the position.


        """
        return self._send_request_document(
            path,
            "$/lean/plainTermGoal",
            {"position": {"line": line, "character": character}},
        )
