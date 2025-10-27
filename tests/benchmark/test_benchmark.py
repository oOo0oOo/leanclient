"""Benchmark tests for LeanLSPClient performance."""

import time

import pytest

from leanclient import LeanLSPClient


@pytest.fixture(scope="module")
def benchmark_client(test_project_dir):
    """Client for benchmark tests with limited opened files.

    Yields:
        LeanLSPClient: Client configured for benchmarking.
    """
    client = LeanLSPClient(test_project_dir, max_opened_files=4, prevent_cache_get=True)
    yield client
    client.close()


# ============================================================================
# File opening benchmarks
# ============================================================================


@pytest.mark.benchmark
@pytest.mark.mathlib
@pytest.mark.skip(reason="Benchmark test, run manually as needed")
def test_bench_opening_files(benchmark_client, random_fast_mathlib_files, test_env_dir):
    """Benchmark opening multiple files."""
    NUM_FILES = 4

    all_files = random_fast_mathlib_files(NUM_FILES * 2, seed=3142)
    files = all_files[:NUM_FILES]

    t0 = time.time()
    benchmark_client.open_files(files)
    diagnostics = [benchmark_client.get_diagnostics(f) for f in files]
    duration = time.time() - t0

    assert len(diagnostics) == NUM_FILES

    # Open all files and count number of lines and total number of characters
    lines = 0
    chars = 0
    for file in files:
        with open(test_env_dir + file, "r") as f:
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
    if benchmark_client.max_opened_files > NUM_FILES:
        msg = f"TEST WARNING: Decrease `max_opened_files` to {NUM_FILES} to test overlapping files."
        print(msg)
    new_files = all_files[NUM_FILES - EXTRA_FILES : NUM_FILES + EXTRA_FILES]
    t0 = time.time()
    benchmark_client.open_files(new_files)
    diagnostics2 = [benchmark_client.get_diagnostics(f) for f in new_files]
    extra_duration = time.time() - t0
    assert diagnostics[-EXTRA_FILES:] == diagnostics2[:EXTRA_FILES]
    msg = f"Loaded {len(new_files)} files ({EXTRA_FILES} overlapping files): {len(new_files) / extra_duration:.2f} files/s"
    print(msg)

    benchmark_client.close_files(new_files)


# ============================================================================
# Request benchmarks
# ============================================================================


@pytest.mark.benchmark
@pytest.mark.mathlib
@pytest.mark.skip(reason="Benchmark test, run manually as needed")
def test_bench_all_functions(benchmark_client):
    """Benchmark all LSP request methods."""
    file_path = ".lake/packages/mathlib/Mathlib/Topology/MetricSpace/Infsep.lean"

    benchmark_client.open_file(file_path)

    NUM_REPEATS = 32

    LINE = 380
    COL = 4

    items = benchmark_client.get_completions(file_path, LINE, COL + 20)
    completion_item = items[8]

    items = benchmark_client.get_call_hierarchy_items(file_path, LINE - 2, COL + 20)
    call_hierarchy_item = items[0]

    results = []

    requests = [
        ("get_goal", benchmark_client.get_goal, (file_path, LINE, COL)),
        (
            "get_term_goal",
            benchmark_client.get_term_goal,
            (file_path, LINE, COL + 20),
        ),
        (
            "get_completions",
            benchmark_client.get_completions,
            (file_path, LINE, COL + 20),
        ),
        (
            "get_completion_item_resolve",
            benchmark_client.get_completion_item_resolve,
            (completion_item,),
        ),
        ("get_definitions", benchmark_client.get_definitions, (file_path, LINE, COL)),
        ("get_hover", benchmark_client.get_hover, (file_path, LINE, COL)),
        ("get_declarations", benchmark_client.get_declarations, (file_path, LINE, COL)),
        (
            "get_references",
            benchmark_client.get_references,
            (file_path, LINE, COL + 20),
        ),
        (
            "get_type_definitions",
            benchmark_client.get_type_definitions,
            (file_path, LINE, COL + 10),
        ),
        (
            "get_document_highlights",
            benchmark_client.get_document_highlights,
            (file_path, LINE, COL + 20),
        ),
        ("get_document_symbols", benchmark_client.get_document_symbols, (file_path,)),
        ("get_semantic_tokens", benchmark_client.get_semantic_tokens, (file_path,)),
        (
            "get_semantic_tokens_range",
            benchmark_client.get_semantic_tokens_range,
            (file_path, 0, 0, LINE, COL),
        ),
        ("get_folding_ranges", benchmark_client.get_folding_ranges, (file_path,)),
        (
            "get_call hierarchy items",
            benchmark_client.get_call_hierarchy_items,
            (file_path, LINE, COL + 20),
        ),
        (
            "get_call hierarchy incoming",
            benchmark_client.get_call_hierarchy_incoming,
            (call_hierarchy_item,),
        ),
        (
            "get_call hierarchy outgoing",
            benchmark_client.get_call_hierarchy_outgoing,
            (call_hierarchy_item,),
        ),
    ]

    print(f"\n{NUM_REPEATS} identical requests each:")
    for name, func, args in requests:
        start_time = time.time()
        for _ in range(NUM_REPEATS):
            res = func(*args)
            if not res:
                print(f"Empty response for {name}: '{res}' type: {type(res)}")
        total_time = time.time() - start_time
        results.append((name, NUM_REPEATS / total_time))

    # Print results sorted by fastest to slowest
    results.sort(key=lambda x: x[1], reverse=True)
    print("\nResults:")
    for res in results:
        print(f"{res[0]}: {res[1]:.2f} queries/s")
