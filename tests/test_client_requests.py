import os
import random
from pprint import pprint
import unittest

from leanclient import LeanLSPClient

from run_tests import TEST_FILE_PATH, TEST_ENV_DIR


class TestLSPClientRequests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lsp = LeanLSPClient(TEST_ENV_DIR, initial_build=False)

    @classmethod
    def tearDownClass(cls):
        cls.lsp.close()

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
            print(
                "This is highly worrisome, investigate response to definition request."
            )
            assert res["uri"].endswith("Prelude.lean")
        else:
            assert res["targetUri"].endswith("Prelude.lean")

    def test_references(self):
        res = self.lsp.get_references(TEST_FILE_PATH, 9, 24)
        assert type(res) == list
        self.assertTrue(len(res) > 1)

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


class TestClientBasics(unittest.TestCase):
    def test_initial_build(self):
        lsp = LeanLSPClient(TEST_ENV_DIR, initial_build=True)
        lsp.close()
