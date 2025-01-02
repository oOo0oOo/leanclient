import random
from pprint import pprint
import unittest

from leanclient.language_server import LeanLanguageServer
from leanclient.config import LEAN_FILE_PATH


class TestLanguageServer(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.lsp = LeanLanguageServer(
            use_mathlib=True, starting_file_path="tests/tests.lean"
        )
        cls.uri = cls.lsp.local_to_uri(LEAN_FILE_PATH)

    @classmethod
    def tearDownClass(cls):
        cls.lsp.close()

    def test_setup(self):
        # Open a document
        self.lsp.sync_file(self.uri)
        exp = f"file://{self.lsp.lake_dir}{LEAN_FILE_PATH}"
        self.assertEqual(self.uri, exp)

        result = self.lsp.send_request_document(
            self.uri,
            "textDocument/hover",
            {"position": {"line": 9, "character": 4}},
        )
        val = result["contents"]["value"]
        self.assertTrue(val.startswith("`rw`"))

    def test_completion(self):
        result = self.lsp.request_completion(self.uri, 9, 15)
        assert "isIncomplete" in result
        assert len(result["items"]) > 100

    def test_completion_item_resolve(self):
        result = self.lsp.request_completion(self.uri, 9, 15)
        item = random.choice(result["items"])
        result = self.lsp.request_completion_item_resolve(self.uri, item)
        result["data"]["id"]["const"]["declName"]

    def test_hover(self):
        res = self.lsp.request_hover(self.uri, 4, 4)
        assert "The left hand" in res["contents"]["value"]

    def test_declaration(self):
        res = self.lsp.request_declaration(self.uri, 6, 4)
        assert "targetUri" in res[0]

    def test_request_definition(self):
        res = self.lsp.request_definition(self.uri, 1, 29)
        self.assertTrue(res[0]["targetUri"].endswith("Prelude.lean"))

    def test_type_definition(self):
        res = self.lsp.request_type_definition(self.uri, 1, 36)
        self.assertTrue(res[0]["targetUri"].endswith("Prelude.lean"))

    def test_document_highlight(self):
        res = self.lsp.request_document_highlight(self.uri, 9, 8)
        assert res[0]["range"]["end"]["character"] == 20

    def test_document_symbol(self):
        res = self.lsp.request_document_symbol(self.uri)
        assert res[0]["name"] == "add_zero_custom"

    def test_semantic_tokens_full(self):
        res = self.lsp.request_semantic_tokens_full(self.uri)
        assert res[0][0] < 30

    def test_semantic_tokens_range(self):
        res = self.lsp.request_semantic_tokens_range(self.uri, 0, 0, 6, 6)
        assert res[0][0] < 30

    def test_folding_range(self):
        res = self.lsp.request_folding_range(self.uri)
        assert res[0]["kind"] == "region"

    def test_plain_goal(self):
        res = self.lsp.request_plain_goal(self.uri, 9, 12)
        assert "⊢" in res["goals"][0]
        res = self.lsp.request_plain_goal(self.uri, 9, 25)
        assert len(res["goals"]) == 0

    def test_plain_term_goal(self):
        res = self.lsp.request_plain_term_goal(self.uri, 9, 12)
        assert "⊢" in res["goal"]
        res = self.lsp.request_plain_term_goal(self.uri, 9, 15)
        assert "⊢" in res["goal"]

    def test_get_sorries(self):
        res = self.lsp.get_sorries(self.uri)
        self.assertEqual(res, [[11, 53, 5]])
