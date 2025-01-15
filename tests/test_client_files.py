import os
import random
from pprint import pprint
import time
import unittest

from leanclient import LeanLSPClient, DocumentContentChange

from leanclient.utils import apply_changes_to_text
from tests.utils import read_stdout_timeout
from utils import get_random_fast_mathlib_files, get_random_mathlib_files
from run_tests import FAST_MATHLIB_FILES, TEST_ENV_DIR


class TestLSPClientFiles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lsp = LeanLSPClient(TEST_ENV_DIR, initial_build=False, print_warnings=False)

    @classmethod
    def tearDownClass(cls):
        cls.lsp.close()

    def _test_open_files_bench(self):
        """Not a test. Used to find fast opening mathlib files."""
        paths = get_random_mathlib_files(4)

        paths = FAST_MATHLIB_FILES

        # Open files and benchmark each time
        benchs = []
        for path in paths:
            t0 = time.time()
            print(f"Opening {path}")
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
        diags = self.lsp.open_file(path)
        assert len(diags) <= 1

        # Make some random changes
        # random.seed(6.28)
        NUM_CHANGES = 8
        changes = []
        t0 = time.time()
        text = self.lsp.get_file_content(path)
        for _ in range(NUM_CHANGES):
            line = random.randint(10, 200)
            d = DocumentContentChange(
                "inv#lid", [line, random.randint(0, 4)], [line, random.randint(4, 8)]
            )
            changes.append(d)
            text = apply_changes_to_text(text, [d])
        diags2 = self.lsp.update_file(path, changes)
        self.assertTrue(len(diags2) > NUM_CHANGES)
        print(f"Updated {len(changes)} changes in one call: {(time.time() - t0):.2f} s")

        new_text = self.lsp.get_file_content(path)
        self.assertEqual(text, new_text)

        # Rerun with the altered text and compare diagnostics
        fpath = path.replace(".lean", "_test.lean")
        with open(TEST_ENV_DIR + fpath, "w") as f:
            f.write(text)
        diags3 = self.lsp.open_file(fpath)
        os.remove(TEST_ENV_DIR + fpath)

        self.assertEqual(diags2, diags3)

    def test_file_update_line_by_line(self):
        START = 100
        NUM_LINES = 2
        # path = ".lake/packages/mathlib/Mathlib/NumberTheory/FLT/Basic.lean"
        # path = ".lake/packages/mathlib/Mathlib/AlgebraicTopology/DoldKan/Degeneracies.lean"
        path = ".lake/packages/mathlib/Mathlib/FieldTheory/Galois/GaloisClosure.lean"

        with open(TEST_ENV_DIR + path, "r") as f:
            lines = f.readlines()

        fantasy = "Fantasy.lean"
        fantasy_path = TEST_ENV_DIR + fantasy
        text = "".join(lines[:START])
        with open(fantasy_path, "w") as f:
            f.write(text)

        self.lsp.open_file(fantasy)

        count = 0
        lines = lines[START : START + NUM_LINES]
        t0 = time.time()
        for i, line in enumerate(lines):
            text += line
            diag = self.lsp.update_file(
                fantasy,
                [DocumentContentChange(line, [i + START, 0], [i + START, len(line)])],
            )
            content = self.lsp.get_file_content(fantasy)
            self.assertEqual(content, text)
            count += len(diag)

        self.assertTrue(count > NUM_LINES / 2)
        # self.assertEqual(len(diag), 0)
        speed = len(lines) / (time.time() - t0)
        os.remove(fantasy_path)
        print(f"Updated {len(lines)} lines one by one: {speed:.2f} lines/s")

    def test_update_file_mathlib(self):
        file = ".lake/packages/mathlib/Mathlib/Data/Num/Prime.lean"
        diag = self.lsp.open_file(file)
        assert diag == [], f"Expected no diagnostics, got {diag}"

        changes = [
            DocumentContentChange("--", [42, 20], [42, 30]),
            DocumentContentChange("/a/b/c\\", [89, 20], [93, 20]),
        ]

        exp_text = apply_changes_to_text(self.lsp.get_file_content(file), changes)

        diag2 = self.lsp.update_file(file, changes)
        assert len(diag2) > 0, f"Expected diagnostics, got {diag2}"
        assert self.lsp.get_file_content(file) == exp_text

        # Load new file with content and compare
        fpath = file.replace(".lean", "_test.lean")
        with open(TEST_ENV_DIR + fpath, "w") as f:
            f.write(exp_text)
        diag3 = self.lsp.open_file(fpath)
        diag4 = self.lsp.get_diagnostics(fpath)

        assert diag2 == diag3 == diag4

        os.remove(TEST_ENV_DIR + fpath)
