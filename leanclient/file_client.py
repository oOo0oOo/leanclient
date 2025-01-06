from leanclient.utils import DocumentContentChange


class SingleFileClient:
    """A simplified API for interacting with a single file only.

    See :class:`leanclient.client.LeanLSPClient` for information.

    Can also be created from a client using :meth:`leanclient.client.LeanLSPClient.create_file_client`.

    Args:
        client(LeanLSPClient): The LeanLSPClient instance to use.
        file_path(str): The path to the file to interact with.
    """

    def __init__(self, client, file_path: str):
        self.client = client
        self.file_path = file_path

    def open_file(self) -> list:
        """Open the file.

        This is usually called automatically when a method is called that requires an open file.
        Use this to open the file manually and recieve its diagnostics.

        Returns:
            list: The diagnostic messages of the file.
        """
        return self.client.open_file(self.file_path)

    def close_file(self, blocking: bool = True):
        """Close the file.

        Calling this manually is optional, files are automatically closed when max_opened_files is reached.

        Args:
            blocking(bool): Not blocking can be risky if you close files frequently or reopen them.
        """
        return self.client.close_files([self.file_path], blocking)

    def update_file(self, changes: list[DocumentContentChange]) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.update_file`"""
        return self.client.update_file(self.file_path, changes)

    def get_diagnostics(self) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_diagnostics`"""
        return self.client.get_diagnostics(self.file_path)

    def get_diagnostics_multi(self, paths: list[str]) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_diagnostics_multi`"""
        return self.client.get_diagnostics_multi(paths)

    def get_completion(self, line: int, column: int) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_completion`"""
        return self.client.get_completion(self.file_path, line, column)

    def get_completion_item_resolve(self, item: dict) -> str:
        """See :meth:`leanclient.client.LeanLSPClient.get_completion_item_resolve`"""
        return self.client.get_completion_item_resolve(item)

    def get_hover(self, line: int, column: int) -> dict:
        """See :meth:`leanclient.client.LeanLSPClient.get_hover`"""
        return self.client.get_hover(self.file_path, line, column)

    def get_declaration(self, line: int, column: int) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_declaration`"""
        return self.client.get_declaration(self.file_path, line, column)

    def get_definition(self, line: int, column: int) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_definition`"""
        return self.client.get_definition(self.file_path, line, column)

    def get_references(self, line: int, column: int) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_references`"""
        return self.client.get_references(self.file_path, line, column)

    def get_type_definition(self, line: int, column: int) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_type_definition`"""
        return self.client.get_type_definition(self.file_path, line, column)

    def get_document_symbol(self) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_document_symbol`"""
        return self.client.get_document_symbol(self.file_path)

    def get_document_highlight(self, line: int, column: int) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_document_highlight`"""
        return self.client.get_document_highlight(self.file_path, line, column)

    def get_semantic_tokens(self) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_semantic_tokens`"""
        return self.client.get_semantic_tokens(self.file_path)

    def get_semantic_tokens_range(
        self, start_line: int, start_column: int, end_line: int, end_column: int
    ) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_semantic_tokens_range`"""
        return self.client.get_semantic_tokens_range(
            self.file_path, start_line, start_column, end_line, end_column
        )

    def get_folding_range(self) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_folding_range`"""
        return self.client.get_folding_range(self.file_path)

    def get_goal(self, line: int, column: int) -> dict:
        """See :meth:`leanclient.client.LeanLSPClient.get_goal`"""
        return self.client.get_goal(self.file_path, line, column)

    def get_term_goal(self, line: int, column: int) -> dict:
        """See :meth:`leanclient.client.LeanLSPClient.get_term_goal`"""
        return self.client.get_term_goal(self.file_path, line, column)
