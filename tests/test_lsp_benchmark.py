import random
from pprint import pprint
import time
import unittest

from leanclient.language_server import LeanLanguageServer
from leanclient.utils import find_lean_files_recursively, start_profiler, stop_profiler
from leanclient.config import MAX_SYNCED_FILES

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

    def ttest_bench_opening_files(self):
        path = self.lsp.lake_dir + BENCH_MATHLIB_ROOT_FOLDERS[0]
        all_files = find_lean_files_recursively(path)
        all_files = sorted(all_files)
        random.seed(3.142)
        random.shuffle(all_files)

        NUM_FILES = 8
        files = all_files[:NUM_FILES]

        LOCAL_PROFILE = False
        if LOCAL_PROFILE:
            profiler = start_profiler()

        t0 = time.time()
        diagnostics = self.lsp.sync_files(files)
        # for file in files:
        #     self.lsp.sync_file(file)
        duration = time.time() - t0

        self.assertEqual(len(diagnostics), NUM_FILES)

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
        msg = f"Loaded {len(files)} files: {fps:.2f} files/s, {lps:.2f} lines/s, {cps:.2f} chars/s"
        print(msg)

        # Load overlapping files
        EXTRA_FILES = 2
        if MAX_SYNCED_FILES > NUM_FILES:
            msg = f"TEST WARNING: Decrease MAX_SYNCED_FILES to {NUM_FILES} to test overlapping files."
            print(msg)
        new_files = all_files[NUM_FILES - EXTRA_FILES : NUM_FILES + EXTRA_FILES]
        t0 = time.time()
        diagnostics2 = self.lsp.sync_files(new_files)
        extra_duration = time.time() - t0
        self.assertEqual(diagnostics[-EXTRA_FILES:], diagnostics2[:EXTRA_FILES])
        msg = f"Loaded {len(new_files)} files ({EXTRA_FILES} overlapping files): {len(new_files) / extra_duration:.2f} files/s"
        print(msg)

        self.lsp._close_files(files)

        # Layout profile using dot and gprof2dot
        if LOCAL_PROFILE:
            stop_profiler(profiler, "tests/profile_load.png")

    def test_bench_all_functions(self):
        file = self.lsp.local_to_uri(
            ".lake/packages/mathlib/Mathlib/Topology/MetricSpace/Infsep.lean"
        )

        self.lsp.sync_file(file)

        LOCAL_PROFILE = False
        NUM_REPEATS = 32

        if LOCAL_PROFILE:
            profiler = start_profiler()

        LINE = 380
        COL = 4

        items = self.lsp.request_completion(file, LINE, COL + 20)
        completion_item = items["items"][8]

        requests = [
            ("plain_goal", self.lsp.request_plain_goal, (file, LINE, COL)),
            (
                "plain_term_goal",
                self.lsp.request_plain_term_goal,
                (file, LINE, COL + 20),
            ),
            ("completion", self.lsp.request_completion, (file, LINE, COL + 20)),
            (
                "completion_item_resolve",
                self.lsp.request_completion_item_resolve,
                (completion_item,),
            ),
            ("definition", self.lsp.request_definition, (file, LINE, COL)),
            ("hover", self.lsp.request_hover, (file, LINE, COL)),
            ("declaration", self.lsp.request_declaration, (file, LINE, COL)),
            ("references", self.lsp.request_references, (file, LINE, COL + 20)),
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
        ]

        print(f"Requesting {NUM_REPEATS} each:")
        for name, func, args in requests:
            start_time = time.time()
            for _ in range(NUM_REPEATS):
                func(*args)
            total_time = time.time() - start_time
            print(f"{name}: {NUM_REPEATS / (1e-9 + total_time):.2f} requests/s")

        # Layout profile using dot and gprof2dot
        if LOCAL_PROFILE:
            stop_profiler(profiler, "test/profile_requests.png")
