import os
import random
from pprint import pprint
import unittest
import nest_asyncio

nest_asyncio.apply()

from leanclient import LeanLSPClient

from run_tests import TEST_FILE_PATH, TEST_ENV_DIR


class TestLSPClientRequests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lsp = LeanLSPClient(TEST_ENV_DIR, initial_build=False, print_warnings=False)

    @classmethod
    def tearDownClass(cls):
        cls.lsp.close()

    # Takes long but might be worth it
    # def setUp(self):
    #     self.lsp = LeanLSPClient(
    #         TEST_ENV_DIR, initial_build=False, print_warnings=False
    #     )

    # def tearDown(self):
    #     self.lsp.close()

    def test_completion(self):
        result = self.lsp.get_completions(TEST_FILE_PATH, 9, 15)
        assert type(result) == list
        assert len(result) > 100

    def test_completion_item_resolve(self):
        result = self.lsp.get_completions(TEST_FILE_PATH, 9, 15)
        assert type(result) == list
        item = random.choice(result)
        resolve_res = self.lsp.get_completion_item_resolve(item)
        assert type(resolve_res) == str

    def test_hover(self):
        res = self.lsp.get_hover(TEST_FILE_PATH, 4, 4)
        assert type(res) == dict
        assert "The left hand" in res["contents"]["value"]

    def test_declaration(self):
        res = self.lsp.get_declarations(TEST_FILE_PATH, 6, 4)
        assert type(res) == list
        assert "targetUri" in res[0]

    def test_request_definition(self):
        res = self.lsp.get_definitions(TEST_FILE_PATH, 1, 29)
        assert type(res) == list
        res = res[0]
        if "uri" in res:
            # print(
            #     "This is highly worrisome, investigate response to definition request."
            # )
            assert res["uri"].endswith("Prelude.lean")
        else:
            assert res["targetUri"].endswith("Prelude.lean")

    # def test_references(self):
    #     res = self.lsp.get_references(TEST_FILE_PATH, 9, 24)
    #     assert type(res) == list
    #     self.assertTrue(len(res) == 1)

    def test_type_definition(self):
        res = self.lsp.get_type_definitions(TEST_FILE_PATH, 1, 36)
        assert type(res) == list
        self.assertTrue(res[0]["targetUri"].endswith("Prelude.lean"))

    def test_document_highlight(self):
        res = self.lsp.get_document_highlights(TEST_FILE_PATH, 9, 8)
        assert type(res) == list
        assert res[0]["range"]["end"]["character"] == 20

    def test_document_symbol(self):
        res = self.lsp.get_document_symbols(TEST_FILE_PATH)
        assert type(res) == list
        assert res[0]["name"] == "add_zero_custom"

    def test_semantic_tokens_full(self):
        res = self.lsp.get_semantic_tokens(TEST_FILE_PATH)
        assert type(res) == list
        exp = [
            [1, 0, 7, "keyword"],
            [1, 25, 1, "variable"],
            [1, 36, 1, "variable"],
            [1, 44, 1, "variable"],
            [1, 49, 2, "keyword"],
        ]
        self.assertEqual(res[:5], exp)

    def test_semantic_tokens_range(self):
        res = self.lsp.get_semantic_tokens_range(TEST_FILE_PATH, 0, 0, 2, 0)
        assert type(res) == list
        exp = [
            [1, 0, 7, "keyword"],
            [1, 25, 1, "variable"],
            [1, 36, 1, "variable"],
            [1, 44, 1, "variable"],
            [1, 49, 2, "keyword"],
        ]
        self.assertEqual(res, exp)

    def test_folding_range(self):
        res = self.lsp.get_folding_ranges(TEST_FILE_PATH)
        assert type(res) == list
        assert res[0]["kind"] == "region"

    def test_plain_goal(self):
        res = self.lsp.get_goal(TEST_FILE_PATH, 9, 12)
        assert type(res) == dict
        assert "⊢" in res["goals"][0]
        res = self.lsp.get_goal(TEST_FILE_PATH, 9, 25)
        assert len(res["goals"]) == 0

    def test_plain_term_goal(self):
        res = self.lsp.get_term_goal(TEST_FILE_PATH, 9, 12)
        assert type(res) == dict
        assert "⊢" in res["goal"]
        res2 = self.lsp.get_term_goal(TEST_FILE_PATH, 9, 15)
        self.assertEqual(res, res2)

    # def test_code_actions(self):
    #     res = self.lsp.get_code_actions(TEST_FILE_PATH, 12, 8, 12, 18)
    #     assert type(res) == list
    #     assert len(res) == 0

    # def test_code_action_resolve(self):
    #     res = self.lsp.get_code_action_resolve({"title": "Test"})
    #     assert res["error"]["message"].startswith("Cannot process request")

    def test_mathlib_file(self):
        path = ".lake/packages/mathlib/Mathlib/Data/Finset/SDiff.lean"

        # self.lsp.open_file(path)

        # Finset
        res = self.lsp.get_definitions(path, 52, 27)
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

        # references = self.lsp.get_references(path, 52, 27)
        # flat = set([flatten(ref) for ref in references])
        # assert len(flat) == len(references)
        # assert len(references) == 5538  # References for Finset

        res = self.lsp.get_declarations(path, 52, 27)
        assert len(res) == 1
        assert res[0]["targetUri"].endswith("Defs.lean")

        # Local theorem: sdiff_val
        res = self.lsp.get_definitions(path, 52, 9)
        assert res[0]["uri"] == self.lsp.client.lsp._local_to_uri(path)

        # res = self.lsp.get_references(path, 52, 9)
        # assert len(res) == 2

        # res = self.lsp.get_references(path, 52, 9, include_declaration=True)
        # assert len(res) == 3

        # res = self.lsp.get_references(
        #     path, 52, 9, include_declaration=True, max_retries=1, retry_delay=0
        # )
        # assert len(res) == 3

    def test_call_hierarchy(self):
        path = ".lake/packages/mathlib/Mathlib/Data/Finset/SDiff.lean"

        ch_item = self.lsp.get_call_hierarchy_items(path, 52, 9)
        ch_item = ch_item[0]
        assert ch_item["data"]["name"] == "Finset.sdiff_val"

        res = self.lsp.get_call_hierarchy_incoming(ch_item)
        # assert len(res) == 2, len(res)

        res = self.lsp.get_call_hierarchy_outgoing(ch_item)
        # assert len(res) == 3, len(res)

    def test_empty_response(self):
        res = self.lsp.get_goal(TEST_FILE_PATH, 0, 0)
        self.assertEqual(res, None)
        res = self.lsp.get_term_goal(TEST_FILE_PATH, 0, 0)
        self.assertEqual(res, None)
        res = self.lsp.get_hover(TEST_FILE_PATH, 0, 0)
        self.assertEqual(res, None)

        res = self.lsp.get_declarations(TEST_FILE_PATH, 0, 0)
        self.assertEqual(res, [])
        res = self.lsp.get_definitions(TEST_FILE_PATH, 0, 0)
        self.assertEqual(res, [])

        res = self.lsp.get_references(TEST_FILE_PATH, 0, 0)
        self.assertEqual(res, [])
        res = self.lsp.get_type_definitions(TEST_FILE_PATH, 0, 0)
        self.assertEqual(res, [])
        res = self.lsp.get_document_highlights(TEST_FILE_PATH, 0, 0)
        self.assertEqual(res, [])
        res = self.lsp.get_semantic_tokens_range(TEST_FILE_PATH, 0, 0, 0, 0)
        self.assertEqual(res, [])

        # Create an empty file in the project directory
        path = "TestEmpty.lean"
        with open(TEST_ENV_DIR + path, "w") as f:
            f.write("")

        res = self.lsp.get_document_symbols(path)
        self.assertEqual(res, [])
        res = self.lsp.get_semantic_tokens(path)
        self.assertEqual(res, [])
        res = self.lsp.get_folding_ranges(path)
        self.assertEqual(res, [])
        # res = self.lsp.get_completion(path, 0, 0)  # Never empty?
        # self.assertEqual(res, None)
        # res = self.lsp.get_completion_item_resolve(None)  # Invalid item fails anyway

        # Remove the empty file
        os.remove(TEST_ENV_DIR + path)
