import os

from leanclient.utils import DocumentContentChange, experimental


class SingleFileClient:
    """A simplified API for interacting with a single file only.

    See :class:`leanclient.client.LeanLSPClient` for information.

    Can also be created from a client using :meth:`leanclient.client.LeanLSPClient.create_file_client`.

    Args:
        client(LeanLSPClient): The LeanLSPClient instance to use.
        file_path(str): The path to the file to interact with.
    """

    def __init__(self, client, file_path: str):
        # Check if file exists
        path = os.path.join(client.project_path, file_path)
        if not os.path.exists(path):
            raise FileNotFoundError(f"File not found: {path}")

        self.client = client
        self.file_path = file_path
        self.print_warnings = client.print_warnings

    def open_file(self, timeout: float = 30) -> list:
        """Open the file.

        This is usually called automatically when a method is called that requires an open file.
        Use this to open the file manually and recieve its diagnostics.

        Args:
            timeout(float): Time to wait for diagnostics. Defaults to 30 seconds.

        Returns:
            list: The diagnostic messages of the file.
        """
        return self.client.open_file(self.file_path, timeout)

    def close_file(self, blocking: bool = True):
        """Close the file.

        Calling this manually is optional, files are automatically closed when max_opened_files is reached.

        Args:
            blocking(bool): Not blocking can be risky if you close files frequently or reopen them.
        """
        return self.client.close_files([self.file_path], blocking)

    def update_file(
        self, changes: list[DocumentContentChange], timeout: float = 30
    ) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.update_file`"""
        return self.client.update_file(self.file_path, changes, timeout)

    def get_diagnostics(self) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_diagnostics`"""
        return self.client.get_diagnostics(self.file_path)

    def get_diagnostics_multi(self, paths: list[str]) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_diagnostics_multi`"""
        return self.client.get_diagnostics_multi(paths)

    def get_file_content(self) -> str:
        """See :meth:`leanclient.client.LeanLSPClient.get_file_content`"""
        return self.client.get_file_content(self.file_path)

    def get_completions(self, line: int, character: int) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_completions`"""
        return self.client.get_completions(self.file_path, line, character)

    def get_completion_item_resolve(self, item: dict) -> str:
        """See :meth:`leanclient.client.LeanLSPClient.get_completion_item_resolve`"""
        return self.client.get_completion_item_resolve(item)

    def get_hover(self, line: int, character: int) -> dict:
        """See :meth:`leanclient.client.LeanLSPClient.get_hover`"""
        return self.client.get_hover(self.file_path, line, character)

    def get_declarations(self, line: int, character: int) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_declarations`"""
        return self.client.get_declarations(self.file_path, line, character)

    def get_definitions(self, line: int, character: int) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_definitions`"""
        return self.client.get_definitions(self.file_path, line, character)

    def get_references(
        self,
        line: int,
        character: int,
        include_declaration: bool = False,
        max_retries: int = 3,
        retry_delay: float = 0.001,
    ) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_references`"""
        return self.client.get_references(
            self.file_path,
            line,
            character,
            include_declaration,
            max_retries,
            retry_delay,
        )

    def get_type_definitions(self, line: int, character: int) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_type_definitions`"""
        return self.client.get_type_definitions(self.file_path, line, character)

    def get_document_symbols(self) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_document_symbols`"""
        return self.client.get_document_symbols(self.file_path)

    def get_document_highlights(self, line: int, character: int) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_document_highlights`"""
        return self.client.get_document_highlights(self.file_path, line, character)

    def get_semantic_tokens(self) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_semantic_tokens`"""
        return self.client.get_semantic_tokens(self.file_path)

    def get_semantic_tokens_range(
        self, start_line: int, start_character: int, end_line: int, end_character: int
    ) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_semantic_tokens_range`"""
        return self.client.get_semantic_tokens_range(
            self.file_path, start_line, start_character, end_line, end_character
        )

    def get_folding_ranges(self) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_folding_ranges`"""
        return self.client.get_folding_ranges(self.file_path)

    @experimental
    def get_call_hierarchy_items(self, line: int, character: int) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_call_hierarchy_items`"""
        return self.client.get_call_hierarchy_items(self.file_path, line, character)

    @experimental
    def get_call_hierarchy_incoming(self, item: dict) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_call_hierarchy_incoming`"""
        return self.client.get_call_hierarchy_incoming(item)

    @experimental
    def get_call_hierarchy_outgoing(self, item: dict) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_call_hierarchy_outgoing`"""
        return self.client.get_call_hierarchy_outgoing(item)

    def get_goal(self, line: int, character: int) -> dict:
        """See :meth:`leanclient.client.LeanLSPClient.get_goal`"""
        return self.client.get_goal(self.file_path, line, character)

    def get_term_goal(self, line: int, character: int) -> dict:
        """See :meth:`leanclient.client.LeanLSPClient.get_term_goal`"""
        return self.client.get_term_goal(self.file_path, line, character)

    @experimental
    def get_code_actions(
        self, start_line: int, start_character: int, end_line: int, end_character: int
    ) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_code_actions`"""
        return self.client.get_code_actions(
            self.file_path, start_line, start_character, end_line, end_character
        )

    @experimental
    def get_code_action_resolve(self, code_action: dict) -> dict:
        """See :meth:`leanclient.client.LeanLSPClient.get_code_action_resolve`"""
        return self.client.get_code_action_resolve(code_action)
