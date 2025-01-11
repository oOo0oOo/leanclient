import random
import sys
import os
from pprint import pprint
import unittest

import orjson

from leanclient import LeanLSPClient

from run_tests import TEST_FILE_PATH, TEST_ENV_DIR


EXP_DIAGNOSTICS = [
    ["unexpected end of input; expected ':'"],
    ["declaration uses 'sorry'", "declaration uses 'sorry'"],
]


class TestLSPClientDiagnostics(unittest.TestCase):
    def setUp(self):
        self.lsp = LeanLSPClient(TEST_ENV_DIR, initial_build=False)

    def tearDown(self):
        self.lsp.close()

    def test_open_diagnostics(self):
        diagnostics = self.lsp.open_file(TEST_FILE_PATH)
        errors = [d["message"] for d in diagnostics if d["severity"] == 1]
        self.assertEqual(errors, EXP_DIAGNOSTICS[0])
        warnings = [d["message"] for d in diagnostics if d["severity"] == 2]
        self.assertEqual(warnings, EXP_DIAGNOSTICS[1])

    def test_get_diagnostics(self):
        diag = self.lsp.get_diagnostics(TEST_FILE_PATH)
        errors = [d["message"] for d in diag if d["severity"] == 1]
        self.assertEqual(errors, EXP_DIAGNOSTICS[0])
        warnings = [d["message"] for d in diag if d["severity"] == 2]
        self.assertEqual(warnings, EXP_DIAGNOSTICS[1])

        paths = [TEST_FILE_PATH] * 2
        # paths.append("Main.lean")  # FIX: Why does this hang?
        paths.append(
            ".lake/packages/mathlib/Mathlib/Algebra/GroupWithZero/Divisibility.lean"
        )
        diag2 = self.lsp.get_diagnostics_multi(paths)
        self.assertEqual(len(diag2[0]), len(diag))
        assert len(diag2[-1]) > 0  # Any diagnostics in the mathlib file

    def test_non_terminating_waitForDiagnostics(self):
        # Create a file with non-terminating diagnostics (processing: {"kind": 2})
        content = "/- Unclosed comment"
        path = "BadFile.lean"
        with open(TEST_ENV_DIR + path, "w") as f:
            f.write(content)

        diag = self.lsp.open_file(path)
        self.assertEqual(diag[0]["message"], "unterminated comment")
        self.lsp.close_files([path])

        content = "/-! Unterminated comment 2"
        with open(TEST_ENV_DIR + path, "w") as f:
            f.write(content)

        diag = self.lsp.open_file(path)
        self.assertEqual(diag[0]["message"], "unterminated comment")

        os.remove(TEST_ENV_DIR + path)


class TestLSPClientErrors(unittest.TestCase):
    def setUp(self):
        self.lsp = LeanLSPClient(TEST_ENV_DIR, initial_build=False)
        self.uri = self.lsp._local_to_uri(TEST_FILE_PATH)

    def tearDown(self):
        self.lsp.close()

    def test_rpc_errors(self):
        # Mute stdout
        orig_stdout = sys.stdout
        sys.stdout = open(os.devnull, "w")

        # Invalid method
        resp = self.lsp._send_request("garbageMethod", {})
        exp = "No request handler found for 'garbageMethod'"
        self.assertEqual(resp[-1]["error"]["message"], exp)

        # Invalid params
        resp = self.lsp._send_request("textDocument/hover", {})
        resp = resp[-1]["error"]["message"].split("\n")[0]
        exp = "Cannot parse request params: {}"
        self.assertEqual(resp, exp)

        # Invalid params2
        resp = self.lsp._send_request("textDocument/hover", {"textDocument": {}})
        resp = resp[-1]["error"]["message"].split("\n")[0]
        exp = 'Cannot parse request params: {"textDocument":{}}'
        self.assertEqual(resp, exp)

        # Unopened file
        body = orjson.dumps(
            {
                "jsonrpc": "2.0",
                "method": "textDocument/hover",
                "params": {
                    "textDocument": {"uri": self.uri},
                    "position": {"line": 9, "character": 4},
                },
            }
        )
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        self.lsp.stdin.write(header + body)
        self.lsp.stdin.flush()
        resp = self.lsp._wait_for_diagnostics([self.uri])
        exp = "Cannot process request to closed file"
        resp = resp[0]["error"]["message"]
        assert resp.startswith(exp)

        # Unmute
        sys.stdout.close()
        sys.stdout = orig_stdout

    def test_lake_error_invalid_rpc(self):
        body = orjson.dumps({"jsonrpc": "2.0"})
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        self.lsp.stdin.write(header + body)
        self.lsp.stdin.flush()
        self.assertRaises(EOFError, self.lsp._wait_for_diagnostics, self.uri)

    def test_lake_error_end_of_input(self):
        body = orjson.dumps({})
        header = f"Content-Length: {len(body) + 1}\r\n\r\n".encode("ascii")
        self.lsp.stdin.write(header + body)
        self.lsp.stdin.flush()
        self.assertRaises(EOFError, self.lsp._wait_for_diagnostics, self.uri)

    def test_lake_error_content_length(self):
        request = {
            "jsonrpc": "2.0",
            "method": "textDocument/hover",
            "params": {
                "textDocument": {"uri": self.uri},
                "position": {"line": 9, "character": 4},
            },
        }
        body = orjson.dumps(request)
        header = f"Content-Length: 3.14\r\n\r\n".encode("ascii")
        self.lsp.stdin.write(header + body)
        self.lsp.stdin.flush()
        self.assertRaises(EOFError, self.lsp._wait_for_diagnostics, self.uri)

    def invalid_path(self):
        invalid_paths = [
            "g.lean",
            "garbage",
            "g.txt",
            "fantasy/f.lean",
            "../e.lean",
            " ",
            " " + TEST_FILE_PATH,
            TEST_FILE_PATH + " ",
        ]

        p = lambda: random.choice(invalid_paths)

        # Check all methods
        # _send_request_document
        self.assertRaises(
            FileNotFoundError,
            self.lsp._send_request_document,
            p(),
            "textDocument/hover",
            {{"position": {"line": 9, "character": 4}}},
        )
        self.assertRaises(FileNotFoundError, self.lsp._open_new_files[p()])
        self.assertRaises(FileNotFoundError, self.lsp._open_new_files[p(), p()])
        self.assertRaises(FileNotFoundError, self.lsp.open_files([p()]))
        self.assertRaises(FileNotFoundError, self.lsp.open_file, p())
        self.assertRaises(FileNotFoundError, self.lsp.update_file, p(), [])
        self.assertRaises(FileNotFoundError, self.lsp.close_files, [p()])
        self.assertRaises(FileNotFoundError, self.lsp.get_diagnostics, p())
        self.assertRaises(FileNotFoundError, self.lsp.get_diagnostics_multi, [p()])
        self.assertRaises(FileNotFoundError, self.lsp.create_file_client, p())

        self.assertRaises(FileNotFoundError, self.lsp.get_completions, p(), 9, 4)
        self.assertRaises(FileNotFoundError, self.lsp.get_completion_item_resolve, {})
        self.assertRaises(FileNotFoundError, self.lsp.get_hover, p(), 9, 4)
        self.assertRaises(FileNotFoundError, self.lsp.get_declarations, p(), 9, 4)
        self.assertRaises(FileNotFoundError, self.lsp.get_definitions, p(), 9, 4)
        self.assertRaises(FileNotFoundError, self.lsp.get_references, p(), 9, 4)
        self.assertRaises(FileNotFoundError, self.lsp.get_type_definitions, p(), 9, 4)
        self.assertRaises(FileNotFoundError, self.lsp.get_document_symbols, p())
        self.assertRaises(
            FileNotFoundError, self.lsp.get_document_highlights, p(), 9, 4
        )
        self.assertRaises(FileNotFoundError, self.lsp.get_semantic_tokens, p())
        self.assertRaises(
            FileNotFoundError, self.lsp.get_semantic_tokens_range, p(), 0, 0, 10, 10
        )
        self.assertRaises(FileNotFoundError, self.lsp.get_folding_ranges, p())
        self.assertRaises(FileNotFoundError, self.lsp.get_goal, p(), 9, 4)
        self.assertRaises(FileNotFoundError, self.lsp.get_term_goal, p(), 9, 4)

    def test_invalid_root(self):
        with self.assertRaises(FileNotFoundError, msg=f"Path: invalid_path"):
            LeanLSPClient("invalid_path", initial_build=False)

        with self.assertRaises(NotADirectoryError, msg=f"Path: invalid_path"):
            LeanLSPClient("leanclient/client.py", initial_build=False)

        # Valid but not a lean project
        with self.assertRaises(Exception, msg=f"Path: leanclient/"):
            LeanLSPClient("leanclient/", initial_build=True)
