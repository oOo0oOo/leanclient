import random
import sys
import os
from pprint import pprint
import unittest
import nest_asyncio

nest_asyncio.apply()

import orjson

from leanclient import LeanLSPClient

from leanclient.async_client import AsyncLeanLSPClient
from run_tests import TEST_FILE_PATH, TEST_ENV_DIR
from tests.utils import get_random_fast_mathlib_files, read_stdout_timeout


EXP_DIAGNOSTICS = [
    ["unexpected end of input; expected ':'"],
    ["declaration uses 'sorry'", "declaration uses 'sorry'"],
]


class TestLSPClientDiagnostics(unittest.TestCase):
    def setUp(self):
        self.lsp = LeanLSPClient(
            TEST_ENV_DIR, initial_build=False, print_warnings=False
        )

    def tearDown(self):
        self.lsp.close()

    def test_open_diagnostics(self):
        diagnostics = self.lsp.get_diagnostics(TEST_FILE_PATH)
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

    def test_non_terminating_waitForDiagnostics(self):
        # Create a file with non-terminating diagnostics (processing: {"kind": 2})
        content = "/- Unclosed comment"
        path = "BadFile.lean"
        with open(TEST_ENV_DIR + path, "w") as f:
            f.write(content)

        self.lsp.open_file(path)
        diag = self.lsp.get_diagnostics(path)
        self.assertEqual(diag[0]["message"], "unterminated comment")
        self.lsp.close_files([path])

        content = "/-! Unterminated comment 2"
        with open(TEST_ENV_DIR + path, "w") as f:
            f.write(content)

        self.lsp.open_file(path)
        diag = self.lsp.get_diagnostics(path)
        self.assertEqual(diag[0]["message"], "unterminated comment")
        self.lsp.close_files([path])

        os.remove(TEST_ENV_DIR + path)


class TestLSPClientErrors(unittest.IsolatedAsyncioTestCase):
    # def setUp(self):
    #     self.client = LeanLSPClient(
    #         TEST_ENV_DIR, initial_build=False, print_warnings=False
    #     )
    #     self.lsp = self.client.client.lsp
    #     self.uri = self.lsp._local_to_uri(TEST_FILE_PATH)

    # def tearDown(self):
    #     self.client.close()

    async def asyncSetUp(self):
        self.client = AsyncLeanLSPClient(
            TEST_ENV_DIR, initial_build=False, print_warnings=False
        )
        await self.client.start()
        self.lsp = self.client.lsp
        self.uri = self.lsp._local_to_uri(TEST_FILE_PATH)

    async def asyncTearDown(self):
        await self.client.close()

    async def test_rpc_errors(self):
        # Invalid method
        p = TEST_FILE_PATH
        resp = await self.client.send_request(p, "garbageMethod", {})
        exp = "No request handler found for 'garbageMethod'"
        self.assertEqual(resp["error"]["message"], exp)

        # Invalid params
        resp = await self.client.send_request(p, "textDocument/hover", {})
        resp = resp["error"]["message"]
        exp = "Cannot parse request params:"
        assert resp.startswith(exp)

        # Invalid params2
        resp = await self.client.send_request(
            p, "textDocument/hover", {"textDocument": {}}
        )
        resp = resp["error"]["message"]
        exp = 'Cannot parse request params: {"textDocument"'
        assert resp.startswith(exp)

    # Unopened file
    # body = orjson.dumps(
    #     {
    #         "jsonrpc": "2.0",
    #         "method": "textDocument/hover",
    #         "params": {
    #             "textDocument": {"uri": self.uri},
    #             "position": {"line": 9, "character": 4},
    #         },
    #         "id": 1,
    #     }
    # )
    # header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    # self.lsp.stdin.write(header + body)
    # await self.lsp.stdin.drain()

    # exp = "Cannot process request to closed file"
    # assert resp == [], f"Why is this working again?, got {resp}"
    # resp = resp["error"]["message"]
    # assert resp.startswith(exp)
    # return resp

    # def test_lake_error_invalid_rpc(self):
    #     body = orjson.dumps({"jsonrpc": "2.0"})
    #     header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    #     self.lsp.stdin.write(header + body)
    #     self.lsp.stdin.flush()
    #     self.assertRaises(EOFError, self.lsp._wait_for_diagnostics, [self.uri])

    # def test_lake_error_end_of_input(self):
    #     body = orjson.dumps({})
    #     header = f"Content-Length: {len(body) + 1}\r\n\r\n".encode("ascii")
    #     self.lsp.stdin.write(header + body)
    #     self.lsp.stdin.flush()
    #     self.assertRaises(EOFError, self.lsp._wait_for_diagnostics, [self.uri])

    # def test_lake_error_content_length(self):
    #     request = {
    #         "jsonrpc": "2.0",
    #         "method": "textDocument/hover",
    #         "params": {
    #             "textDocument": {"uri": self.uri},
    #             "position": {"line": 9, "character": 4},
    #         },
    #     }
    #     body = orjson.dumps(request)
    #     header = f"Content-Length: 3.14\r\n\r\n".encode("ascii")
    #     self.lsp.stdin.write(header + body)
    #     self.lsp.stdin.flush()
    #     self.assertRaises(EOFError, self.lsp._wait_for_diagnostics, self.uri)

    async def invalid_path(self):
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
            self.lsp.client.lsp.send_request,
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
            LeanLSPClient("invalid_path", initial_build=False, print_warnings=False)

        with self.assertRaises(NotADirectoryError, msg=f"Path: invalid_path"):
            LeanLSPClient(
                "leanclient/client.py", initial_build=False, print_warnings=False
            )

        # Valid but not a lean project
        # with self.assertRaises(Exception, msg=f"Path: leanclient/"):
        #     LeanLSPClient("leanclient/", initial_build=True)


class TestSFCErrors(unittest.TestCase):
    def test_invalid_coordinates(self):
        # Check SingleFileClient
        path = get_random_fast_mathlib_files(1, 42)[0]

        client = LeanLSPClient(TEST_ENV_DIR, initial_build=False, print_warnings=False)
        sfc = client.create_file_client(path)

        # Wrong input types
        invalid = [
            {"line": -1, "character": 0},
            {"line": "0", "character": 0},
            {"line": 0, "character": 0.5},
            {"line": None, "character": 0},
        ]

        for pos in invalid:
            res = sfc.get_hover(**pos)
            assert res["error"]["message"].startswith("Cannot parse request params")

        client.close()
        # sfc = None
        # # Raising exceptions crashes lake
        # for pos in invalid[:1]:
        #     lsp = LeanLSPClient(TEST_ENV_DIR, initial_build=False, print_warnings=False)
        #     with self.assertRaises(EOFError):
        #         lsp.get_declarations(path, **pos)
        #     lsp.close()
