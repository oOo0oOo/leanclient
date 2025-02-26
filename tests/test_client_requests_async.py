import os
import random
from pprint import pprint
import unittest

from leanclient.async_client import AsyncLeanLSPClient
from run_tests import TEST_FILE_PATH, TEST_ENV_DIR


class TestLSPClientRequestsAsync(unittest.IsolatedAsyncioTestCase):
    # Unfortunately no @classmethod for async tests
    # Setup takes a long time...
    async def asyncSetUp(self):
        self.lsp = AsyncLeanLSPClient(TEST_ENV_DIR, initial_build=False)
        await self.lsp.start()

    async def asyncTearDown(self):
        await self.lsp.close()

    async def test_methods(self):
        result = await self.lsp.get_completions(TEST_FILE_PATH, 9, 15)
        assert type(result) == list
        assert len(result) > 100

        result = await self.lsp.get_completions(TEST_FILE_PATH, 9, 15)
        assert type(result) == list
        item = random.choice(result)
        resolve_res = await self.lsp.get_completion_item_resolve(item)
        assert type(resolve_res) == str

        res = await self.lsp.get_hover(TEST_FILE_PATH, 4, 4)
        assert type(res) == dict
        assert "The left hand" in res["contents"]["value"]

        res = await self.lsp.get_declarations(TEST_FILE_PATH, 6, 4)
        assert type(res) == list
        assert "targetUri" in res[0]

        res = await self.lsp.get_definitions(TEST_FILE_PATH, 1, 29)
        assert type(res) == list
        res = res[0]
        if "uri" in res:
            # print(
            #     "This is highly worrisome, investigate response to definition request."
            # )
            assert res["uri"].endswith("Prelude.lean")
        else:
            assert res["targetUri"].endswith("Prelude.lean")

        res = await self.lsp.get_references(TEST_FILE_PATH, 9, 24)
        assert type(res) == list
        self.assertTrue(len(res) == 1)

        res = await self.lsp.get_type_definitions(TEST_FILE_PATH, 1, 36)
        assert type(res) == list
        self.assertTrue(res[0]["targetUri"].endswith("Prelude.lean"))

        res = await self.lsp.get_document_highlights(TEST_FILE_PATH, 9, 8)
        assert type(res) == list
        assert res[0]["range"]["end"]["character"] == 20

        res = await self.lsp.get_document_symbols(TEST_FILE_PATH)
        assert type(res) == list
        assert res[0]["name"] == "add_zero_custom"

        res = await self.lsp.get_semantic_tokens(TEST_FILE_PATH)
        assert type(res) == list
        exp = [
            [1, 0, 7, "keyword"],
            [1, 25, 1, "variable"],
            [1, 36, 1, "variable"],
            [1, 44, 1, "variable"],
            [1, 49, 2, "keyword"],
        ]
        self.assertEqual(res[:5], exp)

        res = await self.lsp.get_semantic_tokens_range(TEST_FILE_PATH, 0, 0, 2, 0)
        assert type(res) == list
        exp = [
            [1, 0, 7, "keyword"],
            [1, 25, 1, "variable"],
            [1, 36, 1, "variable"],
            [1, 44, 1, "variable"],
            [1, 49, 2, "keyword"],
        ]
        self.assertEqual(res, exp)

        res = await self.lsp.get_folding_ranges(TEST_FILE_PATH)
        assert type(res) == list
        assert res[0]["kind"] == "region"

        res = await self.lsp.get_goal(TEST_FILE_PATH, 9, 12)
        assert type(res) == dict
        assert "⊢" in res["goals"][0]
        res = await self.lsp.get_goal(TEST_FILE_PATH, 9, 25)
        assert len(res["goals"]) == 0

        res = await self.lsp.get_term_goal(TEST_FILE_PATH, 9, 12)
        assert type(res) == dict
        assert "⊢" in res["goal"]
        res2 = await self.lsp.get_term_goal(TEST_FILE_PATH, 9, 15)
        self.assertEqual(res, res2)

    # async def test_code_actions(self):
    #     res = await self.lsp.get_code_actions(TEST_FILE_PATH, 12, 8, 12, 18)
    #     assert type(res) == list
    #     assert len(res) == 0

    # async def test_code_action_resolve(self):
    #     res = await self.lsp.get_code_action_resolve({"title": "Test"})
    #     assert res["error"]["message"].startswith("Cannot process request")

    async def test_mathlib_file(self):
        path = ".lake/packages/mathlib/Mathlib/Data/Finset/SDiff.lean"
        await self.lsp.lsp.wait_for_file(path)

        # Finset
        res = await self.lsp.get_definitions(path, 52, 27)
        assert len(res) == 1
        uri = res[0]["uri"] if "uri" in res[0] else res[0]["targetUri"]
        assert uri.endswith("Defs.lean")

        def flatten(ref):
            return tuple(
                [
                    ref["uri"],
                    ref["range"]["start"]["line"],
                    ref["range"]["start"]["character"],
                    ref["range"]["end"]["line"],
                    ref["range"]["end"]["character"],
                ]
            )

        # references = await self.lsp.get_references(path, 52, 27)
        # print(references)
        # flat = set([flatten(ref) for ref in references])
        # assert len(flat) == len(references)
        # assert len(references) == 5538  # References for Finset

        res = await self.lsp.get_declarations(path, 52, 27)
        assert len(res) == 1
        assert res[0]["targetUri"].endswith("Defs.lean")

        # Local theorem: sdiff_val
        res = await self.lsp.get_definitions(path, 52, 9)
        assert res[0]["uri"] == self.lsp.lsp._local_to_uri(path)

        # res = await self.lsp.get_references(path, 52, 9)
        # assert len(res) == 2

        # res = await self.lsp.get_references(path, 52, 9, include_declaration=True)
        # assert len(res) == 3

        # res = await self.lsp.get_references(
        #     path, 52, 9, include_declaration=True, timeout=0
        # )
        # assert len(res) <= 3

        ch_item = await self.lsp.get_call_hierarchy_items(path, 52, 9)
        ch_item = ch_item[0]
        assert ch_item["data"]["name"] == "Finset.sdiff_val"

        res = await self.lsp.get_call_hierarchy_incoming(ch_item)
        # assert len(res) == 2, len(res)

        res = await self.lsp.get_call_hierarchy_outgoing(ch_item)
        # assert len(res) == 3, len(res)

    async def test_empty_response(self):
        res = await self.lsp.get_goal(TEST_FILE_PATH, 0, 0)
        self.assertEqual(res, None)
        res = await self.lsp.get_term_goal(TEST_FILE_PATH, 0, 0)
        self.assertEqual(res, None)
        res = await self.lsp.get_hover(TEST_FILE_PATH, 0, 0)
        self.assertEqual(res, None)
        res = await self.lsp.get_declarations(TEST_FILE_PATH, 0, 0)
        self.assertEqual(res, [])
        res = await self.lsp.get_definitions(TEST_FILE_PATH, 0, 0)
        self.assertEqual(res, [])
        res = await self.lsp.get_references(TEST_FILE_PATH, 0, 0)
        self.assertEqual(res, [])
        res = await self.lsp.get_type_definitions(TEST_FILE_PATH, 0, 0)
        self.assertEqual(res, [])
        res = await self.lsp.get_document_highlights(TEST_FILE_PATH, 0, 0)
        self.assertEqual(res, [])
        res = await self.lsp.get_semantic_tokens_range(TEST_FILE_PATH, 0, 0, 0, 0)
        self.assertEqual(res, [])

        # Create an empty file in the project directory
        path = "TestEmpty.lean"
        with open(TEST_ENV_DIR + path, "w") as f:
            f.write("")

        res = await self.lsp.get_document_symbols(path)
        self.assertEqual(res, [])
        res = await self.lsp.get_semantic_tokens(path)
        self.assertEqual(res, [])
        res = await self.lsp.get_folding_ranges(path)
        self.assertEqual(res, [])
        # res = await self.lsp.get_completion(path, 0, 0)  # Never empty?
        # self.assertEqual(res, None)
        # res = await self.lsp.get_completion_item_resolve(None)  # Invalid item fails anyway

        # Remove the empty file
        os.remove(TEST_ENV_DIR + path)
