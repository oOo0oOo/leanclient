"""Integration tests for LeanClientPool."""

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


@pytest.mark.integration
@pytest.mark.mathlib
def test_batch_size(test_project_dir, fast_mathlib_files):
    """Test pool with different batch sizes."""
    NUM_FILES = 10
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
@pytest.mark.parametrize("num_workers", [1, 4, 8])
def test_num_workers(test_project_dir, fast_mathlib_files, num_workers):
    """Test pool with different numbers of workers."""
    NUM_FILES = 2
    files = fast_mathlib_files[:NUM_FILES]
    
    with LeanClientPool(test_project_dir, num_workers=num_workers) as pool:
        results = pool.map(empty_task, files)
        assert all(result == "t" for result in results)


@pytest.mark.integration
@pytest.mark.mathlib
def test_verbose(test_project_dir, fast_mathlib_files):
    """Test pool with verbose output."""
    NUM_FILES = 8
    
    with LeanClientPool(test_project_dir) as pool:
        results = pool.map(
            get_num_folding_ranges, fast_mathlib_files[:NUM_FILES], verbose=True
        )
        assert all(result > 0 for result in results)
        assert len(results) == NUM_FILES
