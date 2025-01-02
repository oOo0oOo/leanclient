import random
from pprint import pprint
import unittest

from leanclient.language_server import LeanLanguageServer
from leanclient.config import LEAN_FILE_PATH
from leanclient.utils import find_lean_files_recursively


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

    # Test lsp requests
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

    def test_sync_files(self):
        path = self.lsp.lake_dir
        path += ".lake/packages/mathlib/Mathlib/Topology/"
        all_files = find_lean_files_recursively(path)
        N = 3  # randint(0, len(all_files) - 3)  ?
        diag = self.lsp.sync_file(all_files[N])
        diag2 = self.lsp.sync_file(all_files[N])  # One file overlap
        diags = self.lsp.sync_files(all_files[N : N + 2])  # Two file overlap
        diags2 = self.lsp.sync_files(all_files[N : N + 2])  # Cache

        self.assertEqual(diag, diag2)
        self.assertEqual(diag, diags[0])
        self.assertEqual(diags, diags2)

    # Test custom methods
    def test_get_sorries(self):
        res = self.lsp.get_sorries(self.uri)
        self.assertEqual(res, [[12, 47, 5], [13, 52, 5]])


class TestLanguageServerDiagnostics(unittest.TestCase):
    def setUp(self):
        self.lsp = LeanLanguageServer(
            use_mathlib=True, starting_file_path="tests/tests.lean"
        )
        self.uri = self.lsp.local_to_uri(LEAN_FILE_PATH)

    def tearDown(self):
        self.lsp.close()

    def test_get_diagnostics(self):
        diagnostics = self.lsp.sync_file(self.uri)
        exp = [
            ["declaration uses 'sorry'", "declaration uses 'sorry'"],
            ["unexpected end of input; expected ':'"],
        ]
        self.assertEqual(diagnostics, exp)
