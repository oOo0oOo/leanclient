"""Integration tests for LeanClientPool."""

import os
import signal
import threading
import time

import pytest

from leanclient import LeanClientPool, SingleFileClient


# Some batch tasks
def get_num_folding_ranges(client: SingleFileClient) -> int:
    """Task to get number of folding ranges."""
    return len(client.get_folding_ranges())


def empty_task(client: SingleFileClient) -> str:
    """Empty task that returns a string."""
    return "t"


def slow_task(client: SingleFileClient) -> str:
    """Task that takes some time to complete."""
    time.sleep(2)
    return "done"


@pytest.mark.integration
@pytest.mark.mathlib
@pytest.mark.slow
def test_batch_size(test_project_dir, fast_mathlib_files):
    """Test pool with different batch sizes."""
    NUM_FILES = 4
    BATCH_SIZE = 3
    files = fast_mathlib_files[:NUM_FILES]

    with LeanClientPool(test_project_dir, max_opened_files=BATCH_SIZE) as pool:
        t0 = time.time()
        results = pool.map(get_num_folding_ranges, files, batch_size=1)
        t1 = time.time()
        assert all(isinstance(result, int) for result in results)
        assert all(result > 0 for result in results)
        print(f"Batch size 1: {NUM_FILES / (t1 - t0):.2f} files/s")

        results2 = pool.map(get_num_folding_ranges, files, batch_size=BATCH_SIZE)
        t2 = time.time()
        assert results == results2
        print(f"Batch size {BATCH_SIZE}: {NUM_FILES / (t2 - t1):.2f} files/s")


@pytest.mark.integration
@pytest.mark.mathlib
@pytest.mark.slow
def test_creation(test_project_dir, fast_mathlib_files):
    """Test creating pool with different methods."""
    NUM_FILES = 2
    files = fast_mathlib_files[:NUM_FILES]

    # Test with context manager
    with LeanClientPool(test_project_dir) as pool:
        results = pool.map(empty_task, files)
        assert all(result == "t" for result in results)
        assert len(results) == NUM_FILES

    # Test without context manager
    pool = LeanClientPool(test_project_dir)
    with pool:
        results = pool.map(empty_task, files)
        assert all(result == "t" for result in results)
        assert len(results) == NUM_FILES


@pytest.mark.integration
@pytest.mark.mathlib
def test_submit(test_project_dir, fast_mathlib_files):
    """Test submitting individual tasks to pool."""
    NUM_FILES = 2
    files = fast_mathlib_files[-NUM_FILES:]

    with LeanClientPool(test_project_dir) as pool:
        futures = [pool.submit(empty_task, file) for file in files]
        results = [fut.get() for fut in futures]
        assert all(result == "t" for result in results)
        assert len(results) == NUM_FILES


@pytest.mark.integration
@pytest.mark.mathlib
@pytest.mark.parametrize("num_workers", [1, 4])
@pytest.mark.slow
def test_num_workers(test_project_dir, fast_mathlib_files, num_workers):
    """Test pool with different numbers of workers."""
    NUM_FILES = 2
    files = fast_mathlib_files[:NUM_FILES]

    with LeanClientPool(test_project_dir, num_workers=num_workers) as pool:
        results = pool.map(empty_task, files)
        assert all(result == "t" for result in results)


@pytest.mark.integration
@pytest.mark.mathlib
@pytest.mark.slow
def test_verbose(test_project_dir, fast_mathlib_files):
    """Test pool with verbose output."""
    NUM_FILES = 4

    with LeanClientPool(test_project_dir) as pool:
        results = pool.map(
            get_num_folding_ranges, fast_mathlib_files[:NUM_FILES], verbose=True
        )
        assert all(result > 0 for result in results)
        assert len(results) == NUM_FILES


@pytest.mark.integration
@pytest.mark.mathlib
@pytest.mark.slow
def test_keyboard_interrupt_cleanup(test_project_dir, fast_mathlib_files):
    """Test that KeyboardInterrupt during processing triggers cleanup without hanging."""
    NUM_FILES = 2
    files = fast_mathlib_files[:NUM_FILES]

    pool = LeanClientPool(test_project_dir, num_workers=2)

    start_time = time.time()

    def interrupt_soon():
        time.sleep(0.05)
        os.kill(os.getpid(), signal.SIGINT)

    interrupt_thread = threading.Thread(target=interrupt_soon)
    interrupt_thread.start()

    # This should be interrupted and cleanup should complete
    with pytest.raises(KeyboardInterrupt):
        with pool:
            # This will be interrupted mid-execution
            pool.map(slow_task, files)

    interrupt_thread.join()
    elapsed = time.time() - start_time

    # Should complete reasonably fast
    assert elapsed < 10.0, f"Cleanup took too long: {elapsed:.2f}s"
    print(f"Interrupt and cleanup completed in {elapsed:.2f}s")
