from pprint import pprint

from leanclient.async_client import AsyncLeanLSPClient
from leanclient.single_file_client import SingleFileClient

from .utils import DocumentContentChange, experimental


class LeanLSPClient:
    """LeanLSPClient is a thin wrapper around the Lean language server.

    It allows interaction with a subprocess running `lake serve` via the `Language Server Protocol (LSP) <https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/>`_.
    This wrapper is blocking, it waits until the language server responds.

    NOTE:
        Your **project_path** is the root folder of a Lean project where `lakefile.toml` is located.
        This is where `lake build` and `lake serve` are run.

        All file paths are **relative** to the project_path.

        E.g. ".lake/packages/mathlib/Mathlib/Init.lean" can be a valid path.

    Args:
        project_path (str): Path to the root folder of a Lean project.
        max_opened_files (int): Maximum number of files to keep open at once.
        initial_build (bool): Whether to run `lake build` on initialization. This is usually not required, but is the only check whether the project is valid.
        print_warnings (bool): Whether to print warnings about experimental features.
    """

    def __init__(
        self,
        project_path: str,
        max_opened_files: int = 8,
        initial_build: bool = True,
        print_warnings: bool = True,
    ):
        self.client = AsyncLeanLSPClient(
            project_path, max_opened_files, initial_build, print_warnings
        )
        self.loop = self.client.loop
        self._call_async(self.client.start)

    def _call_async(self, func, *args, **kwargs):
        """Helper: Call an async function using the event loop."""
        return self.loop.run_until_complete(func(*args, **kwargs))

    def create_file_client(self, file_path: str) -> SingleFileClient:
        """Create a SingleFileClient for a file.

        Args:
            file_path (str): Relative file path.

        Returns:
            SingleFileClient: A client for interacting with a single file.
        """
        return SingleFileClient(self, file_path)

    def close(self, timeout: float = 2):
        """Always close the client when done!

        Terminates the language server process and close all pipes.

        Args:
            timeout (float): Time to wait until the process is killed. Defaults to 2 seconds.
        """
        self._call_async(self.client.close, timeout)

    def wait_for_file(self, path: str, timeout: float = 3):
        """Wait for a file to be fully loaded.

        Internally we check for fileProgress to be finished and `waitForDiagnostic` to return.
        Still, a timeout is required to prevent infinite waiting.

        Args:
            path (str): Relative file path.
            timeout (float): Time to wait. Defaults to 3 seconds.
        """
        self._call_async(self.client.wait_for_file, path, timeout)

    def open_file(self, path: str):
        """Open a file in the language server.

        This is usually called automatically when a method is called that requires an open file.

        Args:
            path (str): Relative file path to open.
        """
        self._call_async(self.client.open_file, path)

    def open_files(self, paths: list[str]):
        """Open multiple files in the language server.

        Opening multiple files at once can be faster than opening them one by one.

        Args:
            paths (list): List of relative file paths to open.
        """
        self._call_async(self.client.open_files, paths)

    def update_file(self, path: str, changes: list[DocumentContentChange]):
        """Apply changes to a file in the language server.

        Note:

            Changes are not written to disk! Use :meth:`get_file_content` to get the current content of a file, as seen by the language server.

        See :meth:`_wait_for_diagnostics` for information on the diagnostic response.
        Raises a FileNotFoundError if the file is not open.

        Args:
            path (str): Relative file path to update.
            changes (list[DocumentContentChange]): List of changes to apply.
        """
        self._call_async(self.client.update_file, path, changes)

    def close_files(self, paths: list[str]):
        """Close files in the language server.

        Calling this manually is optional, files are automatically closed when max_opened_files is reached.

        Args:
            paths (list[str]): List of relative file paths to close.
        """
        self._call_async(self.client.close_files, paths)

    def get_diagnostics(self, path: str, timeout: float = 3) -> list:
        """Wait until file is loaded or errors, then return diagnostics.

        Checks `waitForDiagnostics` and `fileProgress` for each file.

        Sometimes either of these can fail, so we need to check for "rpc errors", "fatal errors" and use a timeout..
        See source for more details.

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
            path str: Relative file path.
            timeout (float): Timeout for fileProgress and waitForDiagnostics each. Defaults to 3 seconds.

        Returns:
            list | None: List of diagnostic messages or errors. None if no diagnostics were received.
        """
        return self._call_async(self.client.get_diagnostics, path, timeout)

    def get_file_content(self, path: str) -> str:
        """Get the content of a file as seen by the language server.

        Args:
            path (str): Relative file path.

        Returns:
            str: Content of the file.
        """
        return self.client.get_file_content(path)

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
        return self._call_async(self.client.get_completions, path, line, character)

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
        return self._call_async(self.client.get_completion_item_resolve, item)

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
        return self._call_async(self.client.get_hover, path, line, character)

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
        return self._call_async(self.client.get_declarations, path, line, character)

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
        return self._call_async(self.client.get_definitions, path, line, character)

    @experimental
    def get_references(
        self,
        path: str,
        line: int,
        character: int,
        include_declaration: bool = False,
        timeout: float = 0.01,
    ) -> list:
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
            include_declaration (bool): Whether to include the declaration itself in the results. Defaults to False.
            max_retries (int): Number of times to retry if no new results were found. Defaults to 3.
            retry_delay (float): Time to wait between retries. Defaults to 0.001.

        Returns:
            list: Locations.
        """
        return self._call_async(
            self.client.get_references,
            path,
            line,
            character,
            include_declaration,
            timeout,
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
        return self._call_async(self.client.get_type_definitions, path, line, character)

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
        return self._call_async(
            self.client.get_document_highlights, path, line, character
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
        return self._call_async(self.client.get_document_symbols, path)

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
        return self._call_async(self.client.get_semantic_tokens, path)

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
        return self._call_async(
            self.client.get_semantic_tokens_range,
            path,
            start_line,
            start_character,
            end_line,
            end_character,
        )

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
        return self._call_async(self.client.get_folding_ranges, path)

    @experimental
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
        return self._call_async(
            self.client.get_call_hierarchy_items, path, line, character
        )

    @experimental
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
        return self._call_async(self.client.get_call_hierarchy_incoming, item)

    @experimental
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
        return self._call_async(self.client.get_call_hierarchy_outgoing, item)

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
        return self._call_async(self.client.get_goal, path, line, character)

    def get_term_goal(self, path: str, line: int, character: int) -> dict | None:
        """Get term goal at a file position.

        :guilabel:`$/lean/plainTermGoal` is a custom lsp request that returns the term goal at a specified cursor position.

        In the VSCode `Lean Infoview`, this is shown as `Expected type`.

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
        return self._call_async(self.client.get_term_goal, path, line, character)

    @experimental
    def get_code_actions(
        self,
        path: str,
        start_line: int,
        start_character: int,
        end_line: int,
        end_character: int,
        timeout: float = 0.01,
    ) -> list:
        """Get code actions for a text range.

        The :guilabel:`textDocument/codeAction` method in LSP returns a list of commands that can be executed to fix or improve the code.

        More information:

        - LSP Docs: `Code Action Request <https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#textDocument_codeAction>`_
        - Lean Source: `Basic.lean <https://github.com/leanprover/lean4/blob/master/src/Lean/Server/CodeActions/Basic.lean#L116>`_

        Args:
            path (str): Relative file path.
            start_line (int): Start line.
            start_character (int): Start character.
            end_line (int): End line.
            end_character (int): End character.
            max_retries (int): Number of times to retry if no new results were found. Defaults to 3.
            retry_delay (float): Time to wait between retries. Defaults to 0.001.

        Returns:
            list: Code actions.
        """
        return self._call_async(
            self.client.get_code_actions,
            path,
            start_line,
            start_character,
            end_line,
            end_character,
            timeout,
        )

    @experimental
    def get_code_action_resolve(self, code_action: dict) -> dict:
        """Resolve a code action.

        Calls the :guilabel:`codeAction/resolve` method.

        More information:

        - LSP Docs: `Code Action Resolve Request <https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#codeAction_resolve>`_
        - Lean Source: `Basic.lean\u200B <https://github.com/leanprover/lean4/blob/master/src/Lean/Server/CodeActions/Basic.lean#L145>`_

        Args:
            code_action (dict): Code action.

        Returns:
            dict: Resolved code action.
        """
        return self._call_async(self.client.get_code_action_resolve, code_action)
