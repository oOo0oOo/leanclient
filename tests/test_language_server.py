import os
import random
from pprint import pprint
import time
import unittest

from leanclient.language_server import LeanLanguageServer, DocumentContentChange
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

        result = self.lsp._send_request_document(
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
        diags = self.lsp.sync_files(all_files[N : N + 2])  # Two files, 1 overlap
        diags2 = self.lsp.sync_files(all_files[N : N + 2])  # Cache

        self.assertEqual(diag, diag2)
        self.assertEqual(diag, diags[0])
        self.assertEqual(diags, diags2)

    def test_sync_update(self):
        path = ".lake/packages/mathlib/Mathlib/NumberTheory/FLT/Basic.lean"
        path = self.lsp.local_to_uri(path)
        errors, __ = self.lsp.sync_file(path)
        self.assertEqual(len(errors), 0)

        # Make some random changes
        random.seed(6.28)
        changes = []
        t0 = time.time()
        for _ in range(8):
            line = random.randint(10, 200)
            d = DocumentContentChange(
                "inv#lid", [line, random.randint(0, 4)], [line, random.randint(4, 8)]
            )
            changes.append(d)
        errors, __ = self.lsp.update_file(path, changes)
        self.assertTrue(len(errors) > 0)
        print(
            f"Updated {len(changes)} changes in one call: {len(changes) / (time.time() - t0):.2f} changes/s"
        )

    def test_sync_line_by_line(self):
        path = ".lake/packages/mathlib/Mathlib/NumberTheory/FLT/Basic.lean"
        path = self.lsp.local_to_uri(path)

        with open(path[7:], "r") as f:
            lines = f.readlines()

        fantasy = self.lsp.local_to_uri("Fantasy.lean")
        start = len(lines) - 32
        text = "".join(lines[:start])
        with open(fantasy[7:], "w") as f:
            f.write(text)

        self.lsp.sync_file(fantasy)

        count = 0
        lines = lines[start:]
        t0 = time.time()
        for i, line in enumerate(lines):
            text += line
            reply = self.lsp.update_file(
                fantasy,
                [DocumentContentChange(line, [i + start, 0], [i + start, len(line)])],
            )
            errors, warnings = reply
            count += len(errors) + len(warnings)
        self.assertTrue(count > 25)
        self.assertEqual(len(errors), 0)
        speed = len(lines) / (time.time() - t0)
        os.remove(fantasy[7:])
        print(f"Updated {len(lines)} lines one by one: {speed:.2f} lines/s")

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
            ["unexpected end of input; expected ':'"],
            ["declaration uses 'sorry'", "declaration uses 'sorry'"],
        ]
        self.assertEqual(diagnostics, exp)
