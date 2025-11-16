from collections import defaultdict

from leanclient.info_tree import parse_info_tree
from leanclient.single_file_client import SingleFileClient

from .utils import (
    SYMBOL_KIND_MAP,
    DocumentContentChange,
    experimental,
    get_diagnostics_in_range,
)
from .base_client import BaseLeanLSPClient
from .file_manager import LSPFileManager


class LeanLSPClient(LSPFileManager, BaseLeanLSPClient):
    """LeanLSPClient is a thin wrapper around the Lean language server.

    It allows interaction with a subprocess running `lake serve` via the `Language Server Protocol (LSP) <https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/>`_.
    This wrapper is blocking, it waits until the language server responds.

    NOTE:
        Your **project_path** is the root folder of a Lean project where `lakefile.toml` is located.
        This is where `lake build` and `lake serve` are run.

        All file paths are **relative** to the project_path.

        E.g. ".lake/packages/mathlib/Mathlib/Init.lean" can be a valid path.

        To control logging output, configure the 'leanclient' logger:

        .. code-block:: python

            import logging
            logging.getLogger('leanclient').setLevel(logging.WARNING)  # Show warnings and errors
            logging.getLogger('leanclient').setLevel(logging.DEBUG)    # Show all messages

    Args:
        project_path (str): Path to the root folder of a Lean project.
        max_opened_files (int): Maximum number of files to keep open at once. Defaults to 4.
        initial_build (bool): Whether to run `lake build` on initialization. Defaults to False. The Lean LSP server does not require a build to function - it will build dependencies on-demand when files are opened.
        prevent_cache_get (bool): Prevent automatic `lake exe cache get` for mathlib projects. Defaults to False. Useful for tests to avoid repeated cache downloads.
    """

    def __init__(
        self,
        project_path: str,
        max_opened_files: int = 4,
        initial_build: bool = False,
        prevent_cache_get: bool = False,
    ):
        BaseLeanLSPClient.__init__(self, project_path, initial_build, prevent_cache_get)
        LSPFileManager.__init__(self, max_opened_files)

    def create_file_client(self, file_path: str) -> SingleFileClient:
        """Create a SingleFileClient for a file.

        Args:
            file_path (str): Relative file path.

        Returns:
            SingleFileClient: A client for interacting with a single file.
        """
        return SingleFileClient(self, file_path)

    def get_completions(self, path: str, line: int, character: int) -> list:
        """Get completion items at a file position.

        The :guilabel:`textDocument/completion` method in LSP provides context-aware code completion suggestions at a specified cursor position.
        It returns a list of possible completions for partially typed code, suggesting continuations.

        Note:
            The _uri field is added by leanclient to enable later resolution. It is not part of the LSP response.

        More information:

        - LSP Docs: `Completion Request <https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#textDocument_completion>`_
        - Lean Source: `FileWorker.lean <https://github.com/leanprover/lean4/blob/master/src/Lean/Server/FileWorker.lean#L616>`_

        Example response:

        .. code-block:: python

            [
                {'_uri': 'LeanTestProject/Basic.lean',
                'data': ['LeanTestProject.Basic', 9, 15, 0, 'cNat.dvd_add_left'],
                'kind': 23,
                'label': 'dvd_add_left'},
                # ...
            ]

        Args:
            path (str): Relative file path.
            line (int): Line number.
            character (int): Character number.

        Returns:
            list: Completion items.
        """
        resp = self._send_request(
            path,
            "textDocument/completion",
            {
                "position": {"line": line, "character": character},
                "context": {"triggerKind": 1},
            },
        )
        items = resp["items"]  # NOTE: We discard `isIncomplete` for now
        # We add the original file URI so we can resolve later
        for item in items:
            item["_uri"] = path
        return items

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
        return self._send_request(item["_uri"], "completionItem/resolve", item)[
            "detail"
        ]

    def get_hover(self, path: str, line: int, character: int) -> dict | None:
        """Get hover information at a cursor position.

        The :guilabel:`textDocument/hover` method in LSP retrieves hover information,
        providing details such as type information, documentation, or other relevant data about the symbol under the cursor.

        More information:

        - LSP Docs: `Hover Request <https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#textDocument_hover>`_
        - Lean Source: `RequestHandling.lean\u200b\u200c <https://github.com/leanprover/lean4/blob/master/src/Lean/Server/FileWorker/RequestHandling.lean#L77₀>`_

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
        return self._send_request(
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
        return self._send_request(
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
        return self._send_request(
            path,
            "textDocument/definition",
            {"position": {"line": line, "character": character}},
        )

    def get_references(
        self,
        path: str,
        line: int,
        character: int,
        include_declaration: bool = False,
        max_retries: int = 3,
        retry_delay: float = 0.001,
    ) -> list:
        """Get locations of references to a symbol at a file position.

        In LSP, the :guilabel:`textDocument/references` method provides the locations of all references to a symbol at a given cursor position.

        More information:

        - LSP Docs: `Find References Request <https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#textDocument_references>`_
        - Lean Source: `Watchdog.lean\u200b <https://github.com/leanprover/lean4/blob/master/src/Lean/Server/Watchdog.lean#L528>`_

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
        return self._send_request_retry(
            path,
            "textDocument/references",
            {
                "position": {"line": line, "character": character},
                "context": {"includeDeclaration": include_declaration},
            },
            max_retries,
            retry_delay,
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
        return self._send_request(
            path,
            "textDocument/typeDefinition",
            {"position": {"line": line, "character": character}},
        )

    def get_document_highlights(self, path: str, line: int, character: int) -> list:
        """Get highlight ranges for a symbol at a file position.

        The :guilabel:`textDocument/documentHighlight` method in LSP returns the highlighted range at a specified cursor position.

        More information:

        - LSP Docs: `Document Highlight Request <https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#textDocument_documentHighlight>`_
        - Lean Source: `RequestHandling.lean\u200b <https://github.com/leanprover/lean4/blob/master/src/Lean/Server/FileWorker/RequestHandling.lean#L324>`_

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

        return self._send_request(
            path,
            "textDocument/documentHighlight",
            {"position": {"line": line, "character": character}},
        )

    def get_document_symbols(self, path: str) -> list:
        """Get all document symbols in a document.

        The :guilabel:`textDocument/documentSymbol` method in LSP retrieves all symbols within a document, providing their names, kinds, and locations.

        More information:

        - LSP Docs: `Document Symbol Request <https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#textDocument_documentSymbol>`_
        - Lean Source: `RequestHandling.lean\u200c <https://github.com/leanprover/lean4/blob/master/src/Lean/Server/FileWorker/RequestHandling.lean#L387>`_
        - Symbol kinds are defined in `LanguageFeatures.lean\u200c <https://github.com/leanprover/lean4/blob/master/src/Lean/Data/Lsp/LanguageFeatures.lean#L143>`_

        Example response:

        .. code-block:: python

            [
                {
                    'kind': 'method',
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
        self.open_file(path)
        
        # Wait for file to be processed if needed
        with self._opened_files_lock:
            state = self.opened_files[path]
            uri = state.uri
            version = state.version
            need_wait = not state.complete
        
        if need_wait:
            self._wait_for_diagnostics([uri], inactivity_timeout=5.0)
            with self._opened_files_lock:
                version = self.opened_files[path].version
        
        # Send request
        params = {"textDocument": {"uri": uri, "version": version}}
        response = self._send_request_sync("textDocument/documentSymbol", params)
        
        for symbol in response:
            if isinstance(symbol["kind"], int):
                symbol["kind"] = SYMBOL_KIND_MAP.get(symbol["kind"], "unknown")
        return response

    def get_semantic_tokens(self, path: str) -> list:
        """Get semantic tokens for the entire document.

        The :guilabel:`textDocument/semanticTokens/full` method in LSP returns semantic tokens for the entire document.

        Tokens are formated as: [line, char, length, token_type]

        See :meth:`get_semantic_tokens_range` for limiting to parts of a document.

        More information:

        - LSP Docs: `Semantic Tokens Full Request <https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#semanticTokens_fullRequest>`_
        - Lean Source: `RequestHandling.lean\u200d <https://github.com/leanprover/lean4/blob/master/src/Lean/Server/FileWorker/RequestHandling.lean#L573>`_

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
        res = self._send_request(path, "textDocument/semanticTokens/full", {})
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
        res = self._send_request(
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
        - Lean Source: `RequestHandling.lean\u200f <https://github.com/leanprover/lean4/blob/master/src/Lean/Server/FileWorker/RequestHandling.lean#L615>`_

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
        self.open_file(path)
        
        # Wait for file to be processed if needed
        with self._opened_files_lock:
            state = self.opened_files[path]
            uri = state.uri
            version = state.version
            need_wait = not state.complete
        
        if need_wait:
            self._wait_for_diagnostics([uri], inactivity_timeout=5.0)
            with self._opened_files_lock:
                version = self.opened_files[path].version
        
        # Send request
        params = {"textDocument": {"uri": uri, "version": version}}
        return self._send_request_sync("textDocument/foldingRange", params)

    @experimental
    def get_call_hierarchy_items(self, path: str, line: int, character: int) -> list:
        """Get call hierarchy items at a file position.

        The :guilabel:`textDocument/prepareCallHierarchy` method in LSP retrieves call hierarchy items at a specified cursor position.
        Use a call hierarchy item to get the incoming and outgoing calls: :meth:`get_call_hierarchy_incoming` and :meth:`get_call_hierarchy_outgoing`.

        More Information:

        - LSP Docs: `Prepare Call Hierarchy Request <https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#textDocument_prepareCallHierarchy>`_
        - Lean Source: `Watchdog.lean\u200d <https://github.com/leanprover/lean4/blob/master/src/Lean/Server/Watchdog.lean#L611>`_

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
        # Ensure diagnostics are up-to-date so the server has processed the file.
        self.get_diagnostics(path)

        return self._send_request(
            path,
            "textDocument/prepareCallHierarchy",
            {"position": {"line": line, "character": character}},
        )

    @experimental
    def get_call_hierarchy_incoming(self, item: dict) -> list:
        """Get call hierarchy items that call a symbol.

        The :guilabel:`callHierarchy/incomingCalls` method in LSP retrieves incoming call hierarchy items for a specified item.
        Use :meth:`get_call_hierarchy_items` first to get an item.

        More Information:

        - LSP Docs: `Incoming Calls Request <https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#callHierarchy_incomingCalls>`_
        - Lean Source: `Watchdog.lean\u200e <https://github.com/leanprover/lean4/blob/master/src/Lean/Server/Watchdog.lean#L624>`_

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
        return self._send_request(
            self._uri_to_local(item["uri"]),
            "callHierarchy/incomingCalls",
            {"item": item},
        )

    @experimental
    def get_call_hierarchy_outgoing(self, item: dict) -> list:
        """Get outgoing call hierarchy items for a given item.

        The :guilabel:`callHierarchy/outgoingCalls` method in LSP retrieves outgoing call hierarchy items for a specified item.
        Use :meth:`get_call_hierarchy_items` first to get an item.

        More Information:

        - LSP Docs: `Outgoing Calls Request <https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#callHierarchy_outgoingCalls>`_
        - Lean Source: `Watchdog.lean\u200f <https://github.com/leanprover/lean4/blob/master/src/Lean/Server/Watchdog.lean#L676>`_

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
        return self._send_request(
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

        - Lean Source: `RequestHandling.lean\u200a\u200f <https://github.com/leanprover/lean4/blob/master/src/Lean/Server/FileWorker/RequestHandling.lean#L285>`_

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
        return self._send_request(
            path,
            "$/lean/plainGoal",
            {"position": {"line": line, "character": character}},
        )

    def get_term_goal(self, path: str, line: int, character: int) -> dict | None:
        """Get term goal at a file position.

        :guilabel:`$/lean/plainTermGoal` is a custom lsp request that returns the term goal at a specified cursor position.

        In the VSCode `Lean Infoview`, this is shown as `Expected type`.

        Use :meth:`get_goal` for the full proof goal.

        More information:

        - Lean Source: `RequestHandling.lean\u200a\u200b <https://github.com/leanprover/lean4/blob/master/src/Lean/Server/FileWorker/RequestHandling.lean#L316>`_

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
        return self._send_request(
            path,
            "$/lean/plainTermGoal",
            {"position": {"line": line, "character": character}},
        )

    def get_code_actions(
        self,
        path: str,
        start_line: int,
        start_character: int,
        end_line: int,
        end_character: int,
        max_retries: int = 3,
        retry_delay: float = 0.001,
    ) -> list:
        """Get code actions for a text range.

        The :guilabel:`textDocument/codeAction` method in LSP returns a list of commands that can be executed to fix or improve the code.

        You can resolve the returned code actions using :meth:`get_code_action_resolve`.
        Finally you can apply the resolved code action using :meth:`apply_code_action_resolve`.

        More information:

        - LSP Docs: `Code Action Request <https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#textDocument_codeAction>`_
        - Lean Source: `Basic.lean <https://github.com/leanprover/lean4/blob/master/src/Lean/Server/CodeActions/Basic.lean#L116>`_

        Example response:

        .. code-block:: python

            [
                {
                    'title': 'Update #guard_msgs with tactic output',
                    'kind': 'quickfix',
                    'isPreferred': True,
                    'data': {
                        'providerResultIndex': 0,
                        'providerName': 'Lean.CodeAction.cmdCodeActionProvider',
                        'params': {
                            'textDocument': {
                                'uri': 'file:///home/ooo/Code/leanclient/.test_env/LeanTestProject/Basic.lean'
                            },
                            'range': {
                                'start': {'line': 12, 'character': 8},
                                'end': {'line': 12, 'character': 18}
                            },
                            'context': {
                                'triggerKind': 1,
                                'diagnostics': [
                                    {
                                        'source': 'Lean 4',
                                        'severity': 3,
                                        'range': {
                                            'start': {'line': 12, 'character': 37},
                                            'end': {'line': 12, 'character': 42}
                                        },
                                        'message': '1',
                                        'fullRange': {
                                            'start': {'line': 12, 'character': 37},
                                            'end': {'line': 12, 'character': 42}
                                        }
                                    },
                                    {
                                        'source': 'Lean 4',
                                        'severity': 1,
                                        'range': {
                                            'start': {'line': 12, 'character': 15},
                                            'end': {'line': 12, 'character': 26}
                                        },
                                        'message': '❌️ Docstring on `#guard_msgs` does not match generated message:\\n\\ninfo: 1',
                                        'fullRange': {
                                            'start': {'line': 12, 'character': 15},
                                            'end': {'line': 12, 'character': 26}
                                        }
                                    }
                                ]
                            }
                        }
                    }
                }
            ]

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
        return self._send_request_retry(
            path,
            "textDocument/codeAction",
            {
                "range": {
                    "start": {"line": start_line, "character": start_character},
                    "end": {"line": end_line, "character": end_character},
                },
                "context": {
                    "diagnostics": get_diagnostics_in_range(
                        self.get_diagnostics(path), start_line, end_line
                    ),
                    "triggerKind": 1,  # Doesn't come up in lean4 repo. 1 = Invoked: Completion was triggered by typing an identifier (24x7 code complete), manual invocation (e.g Ctrl+Space) or via API.
                },
            },
            max_retries,
            retry_delay,
        )

    def get_code_action_resolve(self, code_action: dict) -> dict:
        """Resolve a code action.

        Calls the :guilabel:`codeAction/resolve` method.

        Use :meth:`get_code_actions` to get the code actions in a file first. Select one and get the resolved code action.
        Then apply the resolved code action using :meth:`apply_code_action_resolve`.

        More information:

        - LSP Docs: `Code Action Resolve Request <https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#codeAction_resolve>`_
        - Lean Source: `Basic.lean\u200b <https://github.com/leanprover/lean4/blob/master/src/Lean/Server/CodeActions/Basic.lean#L145>`_

        Example response:

        .. code-block:: python

            {
                'title': 'Update #guard_msgs with tactic output',
                'kind': 'quickfix',
                'isPreferred': True,
                'edit': {
                    'documentChanges': [
                        {
                            'textDocument': {
                                'version': 0,
                                'uri': 'file:///home/ooo/Code/leanclient/.test_env/LeanTestProject/Basic.lean'
                            },
                            'edits': [
                                {
                                    'range': {
                                        'start': {'line': 12, 'character': 0},
                                        'end': {'line': 12, 'character': 15}
                                    },
                                    'newText': '/-- info: 1 -/\\n'
                                }
                            ]
                        }
                    ]
                }
            }


        Args:
            code_action (dict): Code action as returned by :meth:`get_code_actions` (only one).

        Returns:
            dict: Resolved code action.
        """
        try:
            # Hoping for the best
            uri = code_action["edit"]["changes"].keys()[0]
            self.open_file(uri)
        except Exception:
            pass

        try:
            result = self._send_request_sync("codeAction/resolve", code_action)
            return result
        except Exception as e:
            # Return error in the old format for backward compatibility
            if "LSP Error:" in str(e):
                error_msg = str(e).replace("LSP Error: ", "")
                import ast

                try:
                    error_dict = ast.literal_eval(error_msg)
                    return {"error": error_dict}
                except Exception:
                    return {"error": {"message": str(e)}}
            raise

    def apply_code_action_resolve(self, code_action_resolved: dict) -> None:
        """Apply all edits of a resolved code action.

        Helper to apply the edits required to resolve a code action.
        Converts the edits to :class:`DocumentContentChange` and calls :meth:`update_file`

        First get the code action using :meth:`get_code_actions`, then resolve it using :meth:`get_code_action_resolve`.
        Finally apply the resolved code action using this method.

        Note:
            Does not update the file system, only the in-memory representation of the file in the LSP.
            Use :meth:`get_file_content` to get the updated file content.

        Args:
            code_action_resolved (dict): Resolved code action as returned by :meth:`get_code_action_resolve`.
        """
        changes_per_uri = defaultdict(list)
        for document_change in code_action_resolved["edit"]["documentChanges"]:
            uri = document_change["textDocument"]["uri"]
            for edit in document_change["edits"]:
                changes_per_uri[uri].append(
                    DocumentContentChange(
                        text=edit["newText"],
                        start=[
                            edit["range"]["start"]["line"],
                            edit["range"]["start"]["character"],
                        ],
                        end=[
                            edit["range"]["end"]["line"],
                            edit["range"]["end"]["character"],
                        ],
                    )
                )

        for uri, changes in changes_per_uri.items():
            self.update_file(self._uri_to_local(uri), changes)

    def get_info_trees(self, path: str, parse: bool = False) -> list:
        """Get info trees for a all "method" symbols (e.g. theorems) in a file.

        Inserts ``#info_trees in`` for each method symbol and analyzes resulting diagnostic messages.

        Note:
            This method currently only returns info trees for symbols of kind "method" (e.g. "theorem").
            Further, this method ignores invalid symbols, e.g. if a theorem contains a syntax error.

        More information:
            - `Commit <https://github.com/leanprover/lean4/commit/de99c8015a547bcd8baa91852970a2e15cda2abf>`_

        Check :func:`leanclient.info_tree.parse_info_tree` for more information on the parsed info tree format.

        Example response:

        .. code-block:: python

           [
               '''• command @ ⟨18, 0⟩-⟨18, 52⟩ @ Lean.Elab.Command.elabDeclaration
              • Nat : Type @ ⟨18, 24⟩-⟨18, 27⟩ @ Lean.Elab.Term.elabIdent
                • [.] Nat : some Sort.{?_uniq.127} @ ⟨18, 24⟩-⟨18, 27⟩
                • Nat : Type @ ⟨18, 24⟩-⟨18, 27⟩
              • n (isBinder := true) : Nat @ ⟨18, 20⟩-⟨18, 21⟩
              • n + 0 = n : Prop @ ⟨18, 31⟩-⟨18, 40⟩ @ «_aux_Init_Notation___macroRules_term_=__2»
                • Macro expansion
                  n + 0 = n
                  ===>
                  binrel% Eq✝ (n + 0) n
                  • n + 0 = n : Prop @ ⟨18, 31⟩†-⟨18, 40⟩† @ Lean.Elab.Term.Op.elabBinRel
                    • n + 0 = n : Prop @ ⟨18, 31⟩†-⟨18, 40⟩†
                      • n + 0 : Nat @ ⟨18, 31⟩-⟨18, 36⟩ @ «_aux_Init_Notation___macroRules_term_+__2»
                        • Macro expansion
                          n + 0
                          ===>
                          binop% HAdd.hAdd✝ n 0
                          • n + 0 : Nat @ ⟨18, 31⟩†-⟨18, 36⟩†
                            • [.] Eq✝ : none @ ⟨18, 31⟩†-⟨18, 40⟩†
                            • [.] HAdd.hAdd✝ : none @ ⟨18, 31⟩†-⟨18, 36⟩†
                            • n : Nat @ ⟨18, 31⟩-⟨18, 32⟩ @ Lean.Elab.Term.elabIdent
                              • [.] n : none @ ⟨18, 31⟩-⟨18, 32⟩
                              • n : Nat @ ⟨18, 31⟩-⟨18, 32⟩
                            • 0 : Nat @ ⟨18, 35⟩-⟨18, 36⟩ @ Lean.Elab.Term.elabNumLit
                      • n : Nat @ ⟨18, 39⟩-⟨18, 40⟩ @ Lean.Elab.Term.elabIdent
                        • [.] n : none @ ⟨18, 39⟩-⟨18, 40⟩
                        • n : Nat @ ⟨18, 39⟩-⟨18, 40⟩
              • CustomInfo(Lean.Elab.Term.AsyncBodyInfo)
                • incomplete (isBinder := true) : ∀ (n : Nat), n + 0 = n @ ⟨18, 8⟩-⟨18, 18⟩
                • n (isBinder := true) : Nat @ ⟨18, 20⟩-⟨18, 21⟩
                • CustomInfo(Lean.Elab.Term.BodyInfo)
                  • Tactic @ ⟨18, 44⟩-⟨18, 52⟩
                    (Term.byTactic "by" (Tactic.tacticSeq (Tactic.tacticSeq1Indented [(Tactic.tacticSorry "sorry")])))
                    before
                    n : Nat
                    ⊢ n + 0 = n
                    after no goals
                    • Tactic @ ⟨18, 44⟩-⟨18, 46⟩
                      "by"
                      before
                      n : Nat
                      ⊢ n + 0 = n
                      after no goals
                      • Tactic @ ⟨18, 47⟩-⟨18, 52⟩ @ Lean.Elab.Tactic.evalTacticSeq
                        (Tactic.tacticSeq (Tactic.tacticSeq1Indented [(Tactic.tacticSorry "sorry")]))
                        before
                        n : Nat
                        ⊢ n + 0 = n
                        after no goals
                        • Tactic @ ⟨18, 47⟩-⟨18, 52⟩ @ Lean.Elab.Tactic.evalTacticSeq1Indented
                          (Tactic.tacticSeq1Indented [(Tactic.tacticSorry "sorry")])
                          before
                          n : Nat
                          ⊢ n + 0 = n
                          after no goals
                          • Tactic @ ⟨18, 47⟩-⟨18, 52⟩ @ Lean.Parser.Tactic._aux_Init_Tactics___macroRules_Lean_Parser_Tactic_tacticSorry_1
                            (Tactic.tacticSorry "sorry")
                            before
                            n : Nat
                            ⊢ n + 0 = n
                            after no goals
                            • Tactic @ ⟨18, 47⟩†-⟨18, 52⟩† @ Lean.Elab.Tactic.evalExact
                              (Tactic.exact "exact" (Term.sorry "sorry"))
                              before
                              n : Nat
                              ⊢ n + 0 = n
                              after no goals
                              • sorry : n + 0 = n @ ⟨18, 47⟩†-⟨18, 52⟩† @ Lean.Elab.Term.elabSorry
                • incomplete (isBinder := true) : ∀ (n : Nat), n + 0 = n @ ⟨18, 8⟩-⟨18, 18⟩'''

                ...
           ]

        Args:
            path (str): Relative file path.
            parse (bool): Whether to parse the info trees. Parsing is experimental! Defaults to False.

        Returns:
            list: List of info trees as raw strings or parsed into structured data if `parse` is True.
        """
        # Find the lines of all "method" symbols in the document (e.g. "theorem")
        symbols = self.get_document_symbols(path)
        lines = [s["range"]["start"]["line"] for s in symbols if s["kind"] == "method"]

        if not lines:
            return []

        # Add new line before each symbol line `#info_trees in`
        changes = []
        info_trees_lines = []
        for i, line in enumerate(sorted(lines)):
            info_trees_lines.append(line + i)
            pos = [line + i, 0]
            changes.append(
                DocumentContentChange(text="#info_trees in\n", start=pos, end=pos)
            )
        self.update_file(path, changes)
        diagnostics = self.get_diagnostics(path)

        # Revert the changes to remove the added lines
        revert_changes = [
            DocumentContentChange(text="", start=[line, 0], end=[line + 1, 0])
            for line in lines
        ]
        self.update_file(path, revert_changes)

        # Extract info trees from diagnostic messages
        info_trees = []
        for message in diagnostics:
            if message["severity"] == 3:
                line = message["range"]["start"]["line"]
                if line in info_trees_lines:
                    info_trees.append(message["message"])

        if parse:
            # Parse the info trees into structured data
            info_trees = [
                parse_info_tree(info_tree) for info_tree in info_trees if info_tree
            ]
        return info_trees
