import sys
import os

from pprint import pprint
import unittest

import orjson

from leanclient.language_server import LeanLanguageServer
from leanclient.config import LEAN_FILE_PATH


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


class TestLanguageServerErrors(unittest.TestCase):
    def setUp(self):
        self.lsp = LeanLanguageServer(
            use_mathlib=True, starting_file_path="tests/tests.lean"
        )
        self.uri = self.lsp.local_to_uri(LEAN_FILE_PATH)

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
        resp = self.lsp._wait_for_diagnostics(self.uri)
        exp = "Cannot process request to closed file 'f'"
        resp = resp[-1]["error"]["message"]
        self.assertEqual(resp, exp)

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
