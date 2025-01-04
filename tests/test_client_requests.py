import random
from pprint import pprint
import unittest

from leanclient import LeanLSPClient

from run_tests import TEST_FILE_PATH, TEST_ENV_DIR


class TestLSPClientRequests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lsp = LeanLSPClient(TEST_ENV_DIR)

    @classmethod
    def tearDownClass(cls):
        cls.lsp.close()

    def test_setup(self):
        # Open a document
        self.lsp.open_file(TEST_FILE_PATH)

        result = self.lsp._send_request_document(
            TEST_FILE_PATH,
            "textDocument/hover",
            {"position": {"line": 9, "character": 4}},
        )
        val = result["contents"]["value"]
        self.assertTrue(val.startswith("`rw`"))

    # Test lsp requests
    def test_completion(self):
        result = self.lsp.get_completion(TEST_FILE_PATH, 9, 15)
        assert "isIncomplete" in result
        assert len(result["items"]) > 100

    def test_completion_item_resolve(self):
        result = self.lsp.get_completion(TEST_FILE_PATH, 9, 15)
        item = random.choice(result["items"])
        result = self.lsp.get_completion_item_resolve(item)
        result["data"]["id"]["const"]["declName"]

    def test_hover(self):
        res = self.lsp.get_hover(TEST_FILE_PATH, 4, 4)
        assert "The left hand" in res["contents"]["value"]

    def test_declaration(self):
        res = self.lsp.get_declaration(TEST_FILE_PATH, 6, 4)
        assert "targetUri" in res[0]

    def test_request_definition(self):
        res = self.lsp.get_definition(TEST_FILE_PATH, 1, 29)[0]
        if "uri" in res:
            print(
                "This is highly worrisome, investigate response to definition request."
            )
            assert res["uri"].endswith("Prelude.lean")
        else:
            assert res["targetUri"].endswith("Prelude.lean")

    def test_references(self):
        res = self.lsp.get_references(TEST_FILE_PATH, 9, 24)
        self.assertTrue(len(res) > 1)

    def test_type_definition(self):
        res = self.lsp.get_type_definition(TEST_FILE_PATH, 1, 36)
        self.assertTrue(res[0]["targetUri"].endswith("Prelude.lean"))

    def test_document_highlight(self):
        res = self.lsp.get_document_highlight(TEST_FILE_PATH, 9, 8)
        assert res[0]["range"]["end"]["character"] == 20

    def test_document_symbol(self):
        res = self.lsp.get_document_symbol(TEST_FILE_PATH)
        assert res[0]["name"] == "add_zero_custom"

    def test_semantic_tokens_full(self):
        res = self.lsp.get_semantic_tokens_full(TEST_FILE_PATH)
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
        exp = [
            [1, 0, 7, "keyword"],
            [1, 25, 1, "variable"],
            [1, 36, 1, "variable"],
            [1, 44, 1, "variable"],
            [1, 49, 2, "keyword"],
        ]
        self.assertEqual(res, exp)

    def test_folding_range(self):
        res = self.lsp.get_folding_range(TEST_FILE_PATH)
        assert res[0]["kind"] == "region"

    def test_plain_goal(self):
        res = self.lsp.get_plain_goal(TEST_FILE_PATH, 9, 12)
        assert "⊢" in res["goals"][0]
        res = self.lsp.get_plain_goal(TEST_FILE_PATH, 9, 25)
        assert len(res["goals"]) == 0

    def test_plain_term_goal(self):
        res = self.lsp.get_plain_term_goal(TEST_FILE_PATH, 9, 12)
        assert "⊢" in res["goal"]
        res = self.lsp.get_plain_term_goal(TEST_FILE_PATH, 9, 15)
        assert "⊢" in res["goal"]