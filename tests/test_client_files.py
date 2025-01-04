import os
import random
from pprint import pprint
import time
import unittest

from leanclient import LeanLSPClient, DocumentContentChange

from utils import get_random_fast_mathlib_files, get_random_mathlib_files
from run_tests import TEST_ENV_DIR

class TestLSPClientFiles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lsp = LeanLSPClient(TEST_ENV_DIR)

    @classmethod
    def tearDownClass(cls):
        cls.lsp.close()

    def _test_open_files_bench(self):
        """Not a test. Used to find fast opening mathlib files."""
        paths = get_random_mathlib_files(4)

        # Open files and benchmark each time
        benchs = []
        for path in paths:
            t0 = time.time()
            self.lsp.open_file(path)
            benchs.append([time.time() - t0, path])

        benchs.sort()
        disp = [f'"{b[1]}", # {b[0]:.2f}s' for b in benchs]
        print("\n".join(disp))

    def test_open_files(self):
        paths = get_random_fast_mathlib_files(3)
        diag = self.lsp.open_file(paths[0])
        diag2 = self.lsp.open_file(paths[0])  # One file overlap
        diags = self.lsp.open_files(paths[:2])  # Two files, 1 overlap
        diags2 = self.lsp.open_files(paths[:2])  # Cache

        self.assertEqual(diag, diag2)
        self.assertEqual(diag, diags[0])
        self.assertEqual(diags, diags2)

    def test_file_update(self):
        path = ".lake/packages/mathlib/Mathlib/NumberTheory/FLT/Basic.lean"
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

        with open(TEST_ENV_DIR + path, "r") as f:
            lines = f.readlines()

        fantasy = "Fantasy.lean"
        start = len(lines) - 24
        text = "".join(lines[:start])
        with open(fantasy, "w") as f:
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
        os.remove(fantasy)
        print(f"Updated {len(lines)} lines one by one: {speed:.2f} lines/s")
