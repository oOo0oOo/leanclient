from leanclient.utils import DocumentContentChange, experimental


class AsyncSingleFileClient:
    """A simplified API for interacting with a single file only.

    See :class:`leanclient.async_client.AsyncLeanLSPClient` for information.

    Can also be created from a client using :meth:`leanclient.async_client.AsyncLeanLSPClient.create_file_client`.

    Note:
        SingleFileClients can not be started or closed. Close the parent AsyncLeanLSPClient if your done.

    Args:
        client(AsyncLeanLSPClient): The AsyncLeanLSPClient instance to use.
        file_path(str): The path to the file to interact with.
    """

    def __init__(self, client, file_path: str):
        self.client = client
        self.file_path = file_path

    async def open_file(self):
        """Open the file.

        This is usually called automatically when a method is called that requires an open file.
        Use this to open the file manually and recieve its diagnostics.

        See :meth:`leanclient.client.LeanLSPClient.open_file` for more information.
        """
        await self.client.open_file(self.file_path)

    async def close_file(self):
        """Close the file.

        Calling this manually is optional, files are automatically closed when max_opened_files is reached.

        See :meth:`leanclient.client.LeanLSPClient.close_files` for more information.
        """
        await self.client.close_files([self.file_path])

    def local_to_uri(self, path: str) -> str:
        """See :meth:`leanclient.client.LeanLSPClient.local_to_uri`"""
        return self.client.local_to_uri(path)

    def uri_to_local(self, uri: str) -> str:
        """See :meth:`leanclient.client.LeanLSPClient.uri_to_local`"""
        return self.client.uri_to_local(uri)

    async def wait_for_file(self, timeout: float = 10):
        """See :meth:`leanclient.client.LeanLSPClient.wait_for_file`"""
        await self.client.wait_for_file(self.file_path, timeout)

    async def wait_for_line(self, path: str, line: int, timeout: float = 10):
        """See :meth:`leanclient.client.LeanLSPClient.wait_for_line`"""
        await self.client.wait_for_line(path, line, timeout)

    async def update_file(self, changes: list[DocumentContentChange]):
        """See :meth:`leanclient.client.LeanLSPClient.update_file`"""
        await self.client.update_file(self.file_path, changes)

    async def get_diagnostics(self, line: int = -1, timeout: float = 10) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_diagnostics`"""
        return await self.client.get_diagnostics(self.file_path, line, timeout)

    def get_file_content(self) -> str:
        """See :meth:`leanclient.client.LeanLSPClient.get_file_content`"""
        return self.client.get_file_content(self.file_path)

    async def get_completions(self, line: int, character: int) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_completions`"""
        return await self.client.get_completions(self.file_path, line, character)

    async def get_completion_item_resolve(self, item: dict) -> str:
        """See :meth:`leanclient.client.LeanLSPClient.get_completion_item_resolve`"""
        return await self.client.get_completion_item_resolve(item)

    async def get_hover(self, line: int, character: int) -> dict:
        """See :meth:`leanclient.client.LeanLSPClient.get_hover`"""
        return await self.client.get_hover(self.file_path, line, character)

    async def get_declarations(self, line: int, character: int) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_declarations`"""
        return await self.client.get_declarations(self.file_path, line, character)

    async def get_definitions(self, line: int, character: int) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_definitions`"""
        return await self.client.get_definitions(self.file_path, line, character)

    @experimental
    async def get_references(
        self,
        line: int,
        character: int,
        include_declaration: bool = False,
        timeout: float = 3,
    ) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_references`"""
        return await self.client.get_references(
            self.file_path,
            line,
            character,
            include_declaration,
            timeout,
        )

    async def get_type_definitions(self, line: int, character: int) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_type_definitions`"""
        return await self.client.get_type_definitions(self.file_path, line, character)

    async def get_document_symbols(self) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_document_symbols`"""
        return await self.client.get_document_symbols(self.file_path)

    async def get_document_highlights(self, line: int, character: int) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_document_highlights`"""
        return await self.client.get_document_highlights(
            self.file_path, line, character
        )

    async def get_semantic_tokens(self) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_semantic_tokens`"""
        return await self.client.get_semantic_tokens(self.file_path)

    async def get_semantic_tokens_range(
        self, start_line: int, start_character: int, end_line: int, end_character: int
    ) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_semantic_tokens_range`"""
        return await self.client.get_semantic_tokens_range(
            self.file_path, start_line, start_character, end_line, end_character
        )

    async def get_folding_ranges(self) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_folding_ranges`"""
        return await self.client.get_folding_ranges(self.file_path)

    @experimental
    async def get_call_hierarchy_items(self, line: int, character: int) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_call_hierarchy_items`"""
        return await self.client.get_call_hierarchy_items(
            self.file_path, line, character
        )

    @experimental
    async def get_call_hierarchy_incoming(self, item: dict) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_call_hierarchy_incoming`"""
        return await self.client.get_call_hierarchy_incoming(item)

    @experimental
    async def get_call_hierarchy_outgoing(self, item: dict) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_call_hierarchy_outgoing`"""
        return await self.client.get_call_hierarchy_outgoing(item)

    async def get_goal(self, line: int, character: int) -> dict:
        """See :meth:`leanclient.client.LeanLSPClient.get_goal`"""
        return await self.client.get_goal(self.file_path, line, character)

    async def get_term_goal(self, line: int, character: int) -> dict:
        """See :meth:`leanclient.client.LeanLSPClient.get_term_goal`"""
        return await self.client.get_term_goal(self.file_path, line, character)

    @experimental
    async def get_code_actions(
        self, start_line: int, start_character: int, end_line: int, end_character: int
    ) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_code_actions`"""
        return await self.client.get_code_actions(
            self.file_path, start_line, start_character, end_line, end_character
        )

    @experimental
    async def get_code_action_resolve(self, code_action: dict) -> dict:
        """See :meth:`leanclient.client.LeanLSPClient.get_code_action_resolve`"""
        return await self.client.get_code_action_resolve(code_action)
