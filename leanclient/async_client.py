from pprint import pprint

from .utils import DocumentContentChange, experimental, get_diagnostics_in_range
from .base_client import BaseLeanLSPClient
from .async_single_file_client import AsyncSingleFileClient


class AsyncLeanLSPClient:
    """Async wrapper around the Lean language server.

    Call :meth:`start` before any other method.
    Call :meth:`close` when done.

    See :class:`leanclient.client.LeanLSPClient` for more information.
    """

    def __init__(
        self, project_path: str, initial_build: bool = True, max_opened_files: int = 8
    ):
        self.lsp = BaseLeanLSPClient(project_path, initial_build, max_opened_files)
        self.loop = self.lsp.loop

    async def start(self):
        """Start the server. Call this before any other method.

        When using the AsyncLeanLSPClient, you have to call this method yourself.
        """
        await self.lsp.start()

    async def close(self, timeout: float = 2):
        """See :meth:`leanclient.client.LeanLSPClient.close`"""
        await self.lsp.close(timeout)

    def local_to_uri(self, path: str) -> str:
        """See :meth:`leanclient.client.LeanLSPClient.local_to_uri`"""
        return self.lsp.local_to_uri(path)

    def uri_to_local(self, uri: str) -> str:
        """See :meth:`leanclient.client.LeanLSPClient.uri_to_local`"""
        return self.lsp.uri_to_local(uri)

    async def _send_request(self, path: str, method: str, params: dict) -> dict:
        """See :meth:`leanclient.client.LeanLSPClient.send_request`"""
        return await self.lsp.send_request(path, method, params)

    async def wait_for_file(self, path: str, timeout: float = 5):
        """See :meth:`leanclient.client.LeanLSPClient.wait_for_file`"""
        await self.lsp.wait_for_file(path, timeout)

    async def wait_for_line(self, path: str, line: int, timeout: float = 5):
        """See :meth:`leanclient.client.LeanLSPClient.wait_for_line`"""
        await self.lsp.wait_for_line(path, line, timeout)

    async def open_file(self, path: str):
        """See :meth:`leanclient.client.LeanLSPClient.open_file`"""
        await self.lsp.open_file(path)

    async def open_files(self, paths: list[str]):
        """See :meth:`leanclient.client.LeanLSPClient.open_files`"""
        await self.lsp.open_files(paths)

    async def update_file(self, path: str, changes: list[DocumentContentChange]):
        """See :meth:`leanclient.client.LeanLSPClient.update_file`"""
        await self.lsp.update_file(path, changes)

    async def close_files(self, paths: list[str]):
        """See :meth:`leanclient.client.LeanLSPClient.close_files`"""
        await self.lsp.close_files(paths)

    async def get_diagnostics(
        self, path: str, line: int = -1, timeout: float = 5
    ) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_diagnostics`"""
        return await self.lsp.get_diagnostics(path, line, timeout)

    def get_file_content(self, path: str) -> str:
        """See :meth:`leanclient.client.LeanLSPClient.get_file_content`"""
        return self.lsp.get_file_content(path)

    def create_file_client(self, file_path: str) -> AsyncSingleFileClient:
        """Create a SingleFileClient for a file.

        Args:
            file_path (str): Relative file path.

        Returns:
            SingleFileClient: A client for interacting with a single file.
        """
        return AsyncSingleFileClient(self, file_path)

    async def get_completions(self, path: str, line: int, character: int) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_completions`"""
        resp = await self._send_request(
            path,
            "textDocument/completion",
            {"position": {"line": line, "character": character}},
        )
        return resp["items"]  # NOTE: We discard `isIncomplete` for now

    async def get_completion_item_resolve(self, item: dict) -> str:
        """See :meth:`leanclient.client.LeanLSPClient.get_completion_item_resolve`"""
        uri = item["data"]["params"]["textDocument"]["uri"]
        res = await self._send_request(
            self.lsp.uri_to_local(uri), "completionItem/resolve", item
        )
        return res["detail"]

    async def get_hover(self, path: str, line: int, character: int) -> dict | None:
        """See :meth:`leanclient.client.LeanLSPClient.get_hover`"""
        return await self._send_request(
            path,
            "textDocument/hover",
            {"position": {"line": line, "character": character}},
        )

    async def get_declarations(self, path: str, line: int, character: int) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_declarations`"""
        return await self._send_request(
            path,
            "textDocument/declaration",
            {"position": {"line": line, "character": character}},
        )

    async def get_definitions(self, path: str, line: int, character: int) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_definitions`"""
        return await self._send_request(
            path,
            "textDocument/definition",
            {"position": {"line": line, "character": character}},
        )

    @experimental
    async def get_references(
        self,
        path: str,
        line: int,
        character: int,
        include_declaration: bool = False,
        timeout: float = 0.1,
        retries: int = 4,
    ) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_references`"""
        await self.lsp.wait_for_file(path)
        return await self.lsp.send_request_retry(
            path,
            "textDocument/references",
            {
                "position": {"line": line, "character": character},
                "context": {"includeDeclaration": include_declaration},
            },
            timeout,
            retries,
        )

    async def get_type_definitions(self, path: str, line: int, character: int) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_type_definitions`"""
        return await self._send_request(
            path,
            "textDocument/typeDefinition",
            {"position": {"line": line, "character": character}},
        )

    async def get_document_highlights(
        self, path: str, line: int, character: int
    ) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_document_highlights`"""

        return await self._send_request(
            path,
            "textDocument/documentHighlight",
            {"position": {"line": line, "character": character}},
        )

    async def get_document_symbols(self, path: str) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_document_symbols`"""
        return await self._send_request(path, "textDocument/documentSymbol", {})

    async def get_semantic_tokens(self, path: str) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_semantic_tokens`"""
        await self.lsp.wait_for_file(path)
        res = await self._send_request(path, "textDocument/semanticTokens/full", {})
        return self.lsp.token_processor(res["data"])

    async def get_semantic_tokens_range(
        self,
        path: str,
        start_line: int,
        start_character: int,
        end_line: int,
        end_character: int,
    ) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_semantic_tokens_range`"""
        await self.lsp.wait_for_file(path)
        res = await self._send_request(
            path,
            "textDocument/semanticTokens/range",
            {
                "range": {
                    "start": {"line": start_line, "character": start_character},
                    "end": {"line": end_line, "character": end_character},
                }
            },
        )
        return self.lsp.token_processor(res["data"])

    async def get_folding_ranges(self, path: str) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_folding_ranges`"""
        return await self._send_request(path, "textDocument/foldingRange", {})

    @experimental
    async def get_call_hierarchy_items(
        self, path: str, line: int, character: int
    ) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_call_hierarchy_items`"""
        await self.lsp.wait_for_file(path)
        return await self._send_request(
            path,
            "textDocument/prepareCallHierarchy",
            {"position": {"line": line, "character": character}},
        )

    @experimental
    async def get_call_hierarchy_incoming(self, item: dict) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_call_hierarchy_incoming`"""
        return await self._send_request(
            self.lsp.uri_to_local(item["uri"]),
            "callHierarchy/incomingCalls",
            {"item": item},
        )

    @experimental
    async def get_call_hierarchy_outgoing(self, item: dict) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_call_hierarchy_outgoing`"""
        return await self._send_request(
            self.lsp.uri_to_local(item["uri"]),
            "callHierarchy/outgoingCalls",
            {"item": item},
        )

    async def get_goal(self, path: str, line: int, character: int) -> dict | None:
        """See :meth:`leanclient.client.LeanLSPClient.get_goal`"""
        return await self._send_request(
            path,
            "$/lean/plainGoal",
            {"position": {"line": line, "character": character}},
        )

    async def get_term_goal(self, path: str, line: int, character: int) -> dict | None:
        """See :meth:`leanclient.client.LeanLSPClient.get_term_goal`"""
        return await self._send_request(
            path,
            "$/lean/plainTermGoal",
            {"position": {"line": line, "character": character}},
        )

    @experimental
    async def get_code_actions(
        self,
        path: str,
        start_line: int,
        start_character: int,
        end_line: int,
        end_character: int,
        timeout: float = 0.1,
        retries: int = 4,
    ) -> list:
        """See :meth:`leanclient.client.LeanLSPClient.get_code_actions`"""
        diag = await self.lsp.get_diagnostics(path, end_line + 1)
        sel = get_diagnostics_in_range(diag, start_line, end_line)
        return await self.lsp.send_request_retry(
            path,
            "textDocument/codeAction",
            {
                "range": {
                    "start": {"line": start_line, "character": start_character},
                    "end": {"line": end_line, "character": end_character},
                },
                "context": {
                    "diagnostics": sel,
                    "triggerKind": 1,  # Doesn't come up in lean4 repo. 1 = Invoked: Completion was triggered by typing an identifier (24x7 code complete), manual invocation (e.g Ctrl+Space) or via API.
                },
            },
            timeout,
            retries,
        )

    @experimental
    async def get_code_action_resolve(self, code_action: dict) -> dict:
        """See :meth:`leanclient.client.LeanLSPClient.get_code_action_resolve`"""
        try:
            # Hoping for the best
            uri = code_action["edit"]["changes"].keys()[0]
            await self.open_file(uri)
        except:
            pass

        res = await self.lsp.send_request_rpc("codeAction/resolve", code_action, False)
        return res.get("result", res)
