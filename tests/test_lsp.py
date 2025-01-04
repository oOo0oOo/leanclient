import os
import random
from pprint import pprint
import time
import unittest

from leanclient import LeanLSPClient, DocumentContentChange, find_lean_files_recursively

from run_tests import TEST_FILE_PATH, TEST_ENV_DIR


class TestLanguageServer(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.lsp = LeanLSPClient(TEST_ENV_DIR)
        cls.uri = cls.lsp.local_to_uri(TEST_FILE_PATH)

    @classmethod
    def tearDownClass(cls):
        cls.lsp.close()

    def test_setup(self):
        # Open a document
        self.lsp.open_file(self.uri)
        self.assertTrue(self.uri.endswith("Basic.lean"))

        result = self.lsp._send_request_document(
            self.uri,
            "textDocument/hover",
            {"position": {"line": 9, "character": 4}},
        )
        val = result["contents"]["value"]
        self.assertTrue(val.startswith("`rw`"))

    # Test lsp requests
    def test_completion(self):
        result = self.lsp.get_completion(self.uri, 9, 15)
        assert "isIncomplete" in result
        assert len(result["items"]) > 100

    def test_completion_item_resolve(self):
        result = self.lsp.get_completion(self.uri, 9, 15)
        item = random.choice(result["items"])
        result = self.lsp.get_completion_item_resolve(item)
        result["data"]["id"]["const"]["declName"]

    def test_hover(self):
        res = self.lsp.get_hover(self.uri, 4, 4)
        assert "The left hand" in res["contents"]["value"]

    def test_declaration(self):
        res = self.lsp.get_declaration(self.uri, 6, 4)
        assert "targetUri" in res[0]

    def test_request_definition(self):
        res = self.lsp.get_definition(self.uri, 1, 29)
        self.assertTrue(res[0]["uri"].endswith("Prelude.lean"))

    def test_references(self):
        res = self.lsp.get_references(self.uri, 9, 24)
        self.assertTrue(len(res) > 1)

    def test_type_definition(self):
        res = self.lsp.get_type_definition(self.uri, 1, 36)
        self.assertTrue(res[0]["targetUri"].endswith("Prelude.lean"))

    def test_document_highlight(self):
        res = self.lsp.get_document_highlight(self.uri, 9, 8)
        assert res[0]["range"]["end"]["character"] == 20

    def test_document_symbol(self):
        res = self.lsp.get_document_symbol(self.uri)
        assert res[0]["name"] == "add_zero_custom"

    def test_semantic_tokens_full(self):
        res = self.lsp.get_semantic_tokens_full(self.uri)
        exp = [
            [1, 0, 7, "keyword"],
            [1, 25, 1, "variable"],
            [1, 36, 1, "variable"],
            [1, 44, 1, "variable"],
            [1, 49, 2, "keyword"],
        ]
        self.assertEqual(res[:5], exp)

    def test_semantic_tokens_range(self):
        res = self.lsp.get_semantic_tokens_range(self.uri, 0, 0, 2, 0)
        exp = [
            [1, 0, 7, "keyword"],
            [1, 25, 1, "variable"],
            [1, 36, 1, "variable"],
            [1, 44, 1, "variable"],
            [1, 49, 2, "keyword"],
        ]
        self.assertEqual(res, exp)

    def test_folding_range(self):
        res = self.lsp.get_folding_range(self.uri)
        assert res[0]["kind"] == "region"

    def test_plain_goal(self):
        res = self.lsp.get_plain_goal(self.uri, 9, 12)
        assert "⊢" in res["goals"][0]
        res = self.lsp.get_plain_goal(self.uri, 9, 25)
        assert len(res["goals"]) == 0

    def test_plain_term_goal(self):
        res = self.lsp.get_plain_term_goal(self.uri, 9, 12)
        assert "⊢" in res["goal"]
        res = self.lsp.get_plain_term_goal(self.uri, 9, 15)
        assert "⊢" in res["goal"]

    def test_open_files(self):
        path = self.lsp.project_path
        path += ".lake/packages/mathlib/Mathlib/Topology/"
        all_files = find_lean_files_recursively(path)
        N = 3  # randint(0, len(all_files) - 3)  ?
        diag = self.lsp.open_file(all_files[N])
        diag2 = self.lsp.open_file(all_files[N])  # One file overlap
        diags = self.lsp.open_files(all_files[N : N + 2])  # Two files, 1 overlap
        diags2 = self.lsp.open_files(all_files[N : N + 2])  # Cache

        self.assertEqual(diag, diag2)
        self.assertEqual(diag, diags[0])
        self.assertEqual(diags, diags2)

    def test_file_update(self):
        path = ".lake/packages/mathlib/Mathlib/NumberTheory/FLT/Basic.lean"
        path = self.lsp.local_to_uri(path)
        errors, __ = self.lsp.open_file(path)
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

    def test_file_update_line_by_line(self):
        path = ".lake/packages/mathlib/Mathlib/NumberTheory/FLT/Basic.lean"
        path = self.lsp.local_to_uri(path)

        with open(path[7:], "r") as f:
            lines = f.readlines()

        fantasy = self.lsp.local_to_uri("Fantasy.lean")
        start = len(lines) - 32
        text = "".join(lines[:start])
        with open(fantasy[7:], "w") as f:
            f.write(text)

        self.lsp.open_file(fantasy)

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
