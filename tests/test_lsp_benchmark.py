import cProfile
import os
import random
from pprint import pprint
import time
import sys
import unittest

from leanclient.language_server import LeanLanguageServer
from leanclient.utils import find_lean_files_recursively

BENCH_MATHLIB_ROOT_FOLDERS = [
    ".lake/packages/mathlib/Mathlib",
    ".lake/packages/batteries/Batteries",
    ".lake/packages/mathlib/Archive",
    ".lake/packages/mathlib/Cache",
    ".lake/packages/mathlib/Counterexamples",
    ".lake/packages/mathlib/LongestPole",
    ".lake/packages/mathlib/Shake",
]


class TestLanguageServer(unittest.TestCase):
    def setUp(self):
        self.lsp = LeanLanguageServer(
            use_mathlib=True, starting_file_path="tests/tests.lean"
        )

    def tearDown(self):
        self.lsp.close()

    def test_bench_opening_files(self):
        path = self.lsp.lake_dir + BENCH_MATHLIB_ROOT_FOLDERS[0]
        files = find_lean_files_recursively(path)
        # files = sorted(files)
        # random.seed(3.14159)
        random.shuffle(files)
        files = files[:10]

        PROFILE = False
        if PROFILE:
            sys.setrecursionlimit(10000)
            profiler = cProfile.Profile()
            profiler.enable()

        t0 = time.time()
        self.lsp.sync_files(files)
        # for file in files:
        #     self.lsp.sync_file(file)
        duration = time.time() - t0

        # Layout profile using dot and gprof2dot
        if PROFILE:
            profiler.disable()
            profiler.dump_stats("profile.prof")
            os.system(
                "gprof2dot -f pstats profile.prof -n 0.01 -e 0.002 | dot -Tpng -o profile_load.png"
            )
            os.remove("profile.prof")

        # Open all files and count number of lines and total number of characters
        lines = 0
        chars = 0
        for file in files:
            with open(file[7:], "r") as f:
                lines += len(f.readlines())
                f.seek(0)
                chars += len(f.read())

        fps = len(files) / duration
        lps = lines / duration
        cps = chars / duration

        print(
            f"Loaded {len(files)} files: {fps:.2f} files/s, {lps:.2f} lines/s, {cps:.2f} chars/s"
        )

        self.lsp._close_files(files)

    def test_bench_all_functions(self):
        file = self.lsp.local_to_uri(
            ".lake/packages/mathlib/Mathlib/Topology/MetricSpace/Infsep.lean"
        )

        self.lsp.sync_file(file)

        PROFILE = False
        NUM_REPEATS = 50

        if PROFILE:
            sys.setrecursionlimit(10000)
            profiler = cProfile.Profile()
            profiler.enable()

        LINE = 380
        COL = 4

        requests = [
            ("completion", self.lsp.request_completion, (file, LINE, COL + 20)),
            ("definition", self.lsp.request_definition, (file, LINE, COL)),
            ("hover", self.lsp.request_hover, (file, LINE, COL)),
            ("declaration", self.lsp.request_declaration, (file, LINE, COL)),
            (
                "type_definition",
                self.lsp.request_type_definition,
                (file, LINE, COL + 10),
            ),
            (
                "document_highlight",
                self.lsp.request_document_highlight,
                (file, LINE, COL + 20),
            ),
            ("document_symbol", self.lsp.request_document_symbol, (file,)),
            ("semantic_tokens_full", self.lsp.request_semantic_tokens_full, (file,)),
            (
                "semantic_tokens_range",
                self.lsp.request_semantic_tokens_range,
                (file, 0, 0, LINE, COL),
            ),
            ("folding_range", self.lsp.request_folding_range, (file,)),
            ("plain_goal", self.lsp.request_plain_goal, (file, LINE, COL)),
            (
                "plain_term_goal",
                self.lsp.request_plain_term_goal,
                (file, LINE, COL + 20),
            ),
        ]

        print(f"Running {NUM_REPEATS} repeats of each request:")
        for name, func, args in requests:
            start_time = time.time()
            for _ in range(NUM_REPEATS):
                func(*args)
            total_time = time.time() - start_time
            print(f"{name}: {NUM_REPEATS / (1e-9 + total_time):.2f} requests/s")

        # Layout profile using dot and gprof2dot
        if PROFILE:
            profiler.disable()
            profiler.dump_stats("profile.prof")
            os.system(
                "gprof2dot -f pstats profile.prof -n 0.01 -e 0.002 | dot -Tpng -o profile.png"
            )
            os.remove("profile.prof")
