from pprint import pprint
import time
import unittest

from leanclient import LeanLSPClient

from utils import get_random_fast_mathlib_files, start_profiler, stop_profiler
from run_tests import TEST_ENV_DIR


class TestLSPClientBenchmark(unittest.TestCase):
    def setUp(self):
        self.lsp = LeanLSPClient(TEST_ENV_DIR, initial_build=False)

    def tearDown(self):
        self.lsp.close()

    def test_bench_opening_files(self):
        NUM_FILES = 8

        all_files = get_random_fast_mathlib_files(NUM_FILES * 2, seed=3142)
        files = all_files[:NUM_FILES]

        LOCAL_PROFILE = False
        if LOCAL_PROFILE:
            profiler = start_profiler()

        t0 = time.time()
        diagnostics = self.lsp.open_files(files)
        # for file in files:
        #     self.lsp.open_file(file)
        duration = time.time() - t0

        self.assertEqual(len(diagnostics), NUM_FILES)

        # Open all files and count number of lines and total number of characters
        lines = 0
        chars = 0
        for file in files:
            with open(TEST_ENV_DIR + file, "r") as f:
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
        if self.lsp.max_opened_files > NUM_FILES:
            msg = f"TEST WARNING: Decrease `max_opened_files` to {NUM_FILES} to test overlapping files."
            print(msg)
        new_files = all_files[NUM_FILES - EXTRA_FILES : NUM_FILES + EXTRA_FILES]
        t0 = time.time()
        diagnostics2 = self.lsp.open_files(new_files)
        extra_duration = time.time() - t0
        self.assertEqual(diagnostics[-EXTRA_FILES:], diagnostics2[:EXTRA_FILES])
        msg = f"Loaded {len(new_files)} files ({EXTRA_FILES} overlapping files): {len(new_files) / extra_duration:.2f} files/s"
        print(msg)

        self.lsp.close_files(files)

        # Layout profile using dot and gprof2dot
        if LOCAL_PROFILE:
            stop_profiler(profiler, "tests/profile_load.png")

    def test_bench_all_functions(self):
        file_path = ".lake/packages/mathlib/Mathlib/Topology/MetricSpace/Infsep.lean"

        self.lsp.open_file(file_path)

        LOCAL_PROFILE = False
        NUM_REPEATS = 32

        if LOCAL_PROFILE:
            profiler = start_profiler()

        LINE = 380
        COL = 4

        items = self.lsp.get_completions(file_path, LINE, COL + 20)
        completion_item = items[8]

        items = self.lsp.get_call_hierarchy_items(file_path, LINE, COL + 20)
        call_hierarchy_item = items[0]

        requests = [
            ("plain_goal", self.lsp.get_goal, (file_path, LINE, COL)),
            (
                "plain_term_goal",
                self.lsp.get_term_goal,
                (file_path, LINE, COL + 20),
            ),
            ("completion", self.lsp.get_completions, (file_path, LINE, COL + 20)),
            (
                "completion_item_resolve",
                self.lsp.get_completion_item_resolve,
                (completion_item,),
            ),
            ("definition", self.lsp.get_definitions, (file_path, LINE, COL)),
            ("hover", self.lsp.get_hover, (file_path, LINE, COL)),
            ("declaration", self.lsp.get_declarations, (file_path, LINE, COL)),
            ("references", self.lsp.get_references, (file_path, LINE, COL + 20)),
            (
                "type_definition",
                self.lsp.get_type_definitions,
                (file_path, LINE, COL + 10),
            ),
            (
                "document_highlight",
                self.lsp.get_document_highlights,
                (file_path, LINE, COL + 20),
            ),
            ("document_symbol", self.lsp.get_document_symbols, (file_path,)),
            ("semantic_tokens_full", self.lsp.get_semantic_tokens, (file_path,)),
            (
                "semantic_tokens_range",
                self.lsp.get_semantic_tokens_range,
                (file_path, 0, 0, LINE, COL),
            ),
            ("folding_range", self.lsp.get_folding_ranges, (file_path,)),
            (
                "call hierarchy items",
                self.lsp.get_call_hierarchy_items,
                (file_path, LINE, COL + 20),
            ),
            (
                "call hierarchy incoming",
                self.lsp.get_call_hierarchy_incoming,
                (call_hierarchy_item,),
            ),
            (
                "call hierarchy outgoing",
                self.lsp.get_call_hierarchy_outgoing,
                (call_hierarchy_item,),
            ),
        ]

        print(f"{NUM_REPEATS} identical requests each:")
        for name, func, args in requests:
            start_time = time.time()
            for _ in range(NUM_REPEATS):
                res = func(*args)
                if not res:
                    print(f"Empty response for {name}: '{res}' type: {type(res)}")
            total_time = time.time() - start_time
            print(f"{name}: {NUM_REPEATS / (1e-9 + total_time):.2f} requests/s")

        # Layout profile using dot and gprof2dot
        if LOCAL_PROFILE:
            stop_profiler(profiler, "test/profile_requests.png")
