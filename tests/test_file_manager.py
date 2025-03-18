import os
import random
from pprint import pprint
import time
import unittest

from leanclient import DocumentContentChange
from leanclient.base_client import BaseLeanLSPClient
from leanclient.file_manager import LSPFileManager

from leanclient.utils import apply_changes_to_text
from tests.utils import (
    read_stdout_timeout,
    get_random_fast_mathlib_files,
    get_random_mathlib_files,
)

from run_tests import FAST_MATHLIB_FILES, TEST_ENV_DIR


class WrappedFileManager(LSPFileManager, BaseLeanLSPClient):
    def __init__(self, *args, **kwargs):
        BaseLeanLSPClient.__init__(self, *args, **kwargs)
        LSPFileManager.__init__(self)


class TestLSPFileManager(unittest.TestCase):
    def setUp(self):
        self.lsp = WrappedFileManager(
            TEST_ENV_DIR, initial_build=False, print_warnings=False
        )

    def tearDown(self):
        self.lsp.close()

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
        path = get_random_fast_mathlib_files(1, 42)[0]
        diags = self.lsp.open_file(path)
        assert len(diags) <= 1, f"Expected 0 or 1 diagnostics, got {len(diags)}"

        # Make some random changes
        # random.seed(6.28)
        NUM_CHANGES = 16
        changes = []
        t0 = time.time()
        text = self.lsp.get_file_content(path)
        for _ in range(NUM_CHANGES):
            line = random.randint(10, 50)
            d = DocumentContentChange(
                "inv#lid\n", [line, random.randint(0, 4)], [line, random.randint(4, 8)]
            )
            changes.append(d)
            text = apply_changes_to_text(text, [d])
        diags2 = self.lsp.update_file(path, changes)

        if len(diags2) == 1:
            self.assertEqual(diags2[0]["message"], "unterminated comment")
        else:
            self.assertTrue(
                len(diags2) >= NUM_CHANGES // 2,
                f"Expected {NUM_CHANGES // 2} diagnostics got {len(diags2)}:\n\n{diags2}\n\n",
            )
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

        self.lsp.close_files([path])

    def test_file_update_line_by_line(self):
        NUM_LINES = 24
        path = ".lake/packages/mathlib/Mathlib/NumberTheory/FLT/Basic.lean"
        # path = ".lake/packages/mathlib/Mathlib/AlgebraicTopology/DoldKan/Degeneracies.lean"
        # path = ".lake/packages/mathlib/Mathlib/FieldTheory/Galois/GaloisClosure.lean"

        with open(TEST_ENV_DIR + path, "r") as f:
            lines = f.readlines()
        START = len(lines) - NUM_LINES

        fantasy = "Fantasy.lean"
        fantasy_path = TEST_ENV_DIR + fantasy
        text = "".join(lines[:START])
        with open(fantasy_path, "w") as f:
            f.write(text)

        self.lsp.open_file(fantasy)

        lines = lines[-NUM_LINES:]
        t0 = time.time()
        diagnostics = []
        for i, line in enumerate(lines):
            text += line
            diag = self.lsp.update_file(
                fantasy,
                [DocumentContentChange(line, [i + START, 0], [i + START, len(line)])],
            )
            content = self.lsp.get_file_content(fantasy)
            self.assertEqual(content, text)
            diagnostics.extend(diag)

        self.assertTrue(len(diagnostics) > NUM_LINES / 2)
        # self.assertEqual(len(diag), 0)
        speed = len(lines) / (time.time() - t0)
        os.remove(fantasy_path)
        print(f"Updated {len(lines)} lines one by one: {speed:.2f} lines/s")

        self.lsp.close_files([fantasy])

    def test_update_file_mathlib(self):
        files = [
            ".lake/packages/mathlib/Mathlib/Data/Num/Prime.lean",
            ".lake/packages/mathlib/Mathlib/AlgebraicTopology/DoldKan/Degeneracies.lean",
        ]
        diag = self.lsp.open_files(files)
        assert diag == [[], []], f"Expected no diagnostics, got {diag}"

        changes = [
            DocumentContentChange("--", [42, 20], [42, 30]),
            DocumentContentChange("/a/b/c\\", [89, 20], [93, 20]),
            DocumentContentChange("\n\n\n\n\n\n\n\n\n", [100, 100000], [120, 100000]),
        ]

        exp_texts = [
            apply_changes_to_text(self.lsp.get_file_content(f), changes) for f in files
        ]

        for file, exp_text in zip(files, exp_texts):
            diag2 = self.lsp.update_file(file, changes)
            assert len(diag2) > 0, f"Expected diagnostics, got []"
            assert self.lsp.get_file_content(file) == exp_text

            # Load new file with content and compare
            fpath = file.replace(".lean", "_test.lean")
            with open(TEST_ENV_DIR + fpath, "w") as f:
                f.write(exp_text)
            diag3 = self.lsp.open_file(fpath)
            diag4 = self.lsp.get_diagnostics(fpath)

            assert diag2 == diag3 == diag4

            os.remove(TEST_ENV_DIR + fpath)

            self.lsp.close_files([file, fpath])

    def test_update_try_tactics(self):

        file_path = ".lake/packages/mathlib/Mathlib/MeasureTheory/Covering/OneDim.lean"
        diag_init = self.lsp.open_file(file_path)
        assert diag_init == [], f"Expected no diagnostics, got {diag_init}"

        # [(26, 61) , (27, 50), (42, 39)]
        line, character = (26, 61)
        tactics = ["simp", "aesop", "norm_num", "omega", "linarith"]
        l_tactic = len("linarith")
        messages = {}
        for tactic in tactics:
            change = DocumentContentChange(
                start=[line, character],
                end=[line, character + l_tactic],
                text=tactic,
            )
            l_tactic = len(tactic)
            messages[tactic] = self.lsp.update_file(
                file_path,
                [change],
            )

        exp_len = {
            "aesop": 0,
            "linarith": 0,
            "ring": 1,
            "norm_num": 1,
            "omega": 1,
            "simp": 1,
        }

        for tactic in tactics:
            assert len(messages[tactic]) == exp_len[tactic], f"{messages}"

    def test_close(self):
        # Open large file, then close: Expecting process kill
        fpath = ".lake/packages/mathlib/Mathlib/MeasureTheory/Covering/OneDim.lean"
        self.lsp.open_file(fpath)
        self.lsp.close_files([fpath], blocking=False)
        self.lsp.close(timeout=0.01)
        self.assertEqual(self.lsp.process.poll(), -15)  # SIGTERM despite kill?
