from pprint import pprint
import time
import unittest

from leanclient import LeanClientPool, SingleFileClient

from run_tests import TEST_ENV_DIR, FAST_MATHLIB_FILES


# Some batch tasks
def get_num_folding_ranges(client: SingleFileClient) -> any:
    return len(client.get_folding_range())


def empty_task(client: SingleFileClient) -> any:
    return "t"


class TestLeanClientPool(unittest.TestCase):
    def test_batch_size(self):
        NUM_FILES = 10
        BATCH_SIZE = 3
        files = FAST_MATHLIB_FILES[:NUM_FILES]
        with LeanClientPool(TEST_ENV_DIR) as pool:
            t0 = time.time()
            results = pool.map(get_num_folding_ranges, files, batch_size=1)
            t1 = time.time()
            assert all(isinstance(result, int) for result in results)
            assert all(result > 0 for result in results)
            print(f"Batch size 1: { NUM_FILES / (t1 - t0):.2f} files/s")

            results2 = pool.map(get_num_folding_ranges, files, batch_size=BATCH_SIZE)
            t2 = time.time()
            self.assertEqual(results, results2)
            print(f"Batch size {BATCH_SIZE}: {NUM_FILES / (t2 - t1):.2f} files/s")

    def test_creation(self):
        # Test with: also test Pool creation
        NUM_FILES = 2
        files = FAST_MATHLIB_FILES[:NUM_FILES]
        with LeanClientPool(TEST_ENV_DIR) as pool:
            results = pool.map(empty_task, files)
            assert all(result == "t" for result in results)
            assert len(results) == NUM_FILES

        pool = LeanClientPool(TEST_ENV_DIR)
        with pool:
            results = pool.map(empty_task, files)
            assert all(result == "t" for result in results)
            assert len(results) == NUM_FILES

    def test_submit(self):
        # Test with: also test Pool creation
        NUM_FILES = 2
        files = FAST_MATHLIB_FILES[-NUM_FILES:]
        with LeanClientPool(TEST_ENV_DIR) as pool:
            futures = [pool.submit(empty_task, file) for file in files]
            results = [fut.get() for fut in futures]
            assert all(result == "t" for result in results)
            assert len(results) == NUM_FILES

    def test_num_workers(self):
        NUM_FILES = 2
        files = FAST_MATHLIB_FILES[:NUM_FILES]
        for num_workers in [1, 4, 8]:
            with LeanClientPool(TEST_ENV_DIR, num_workers=num_workers) as pool:
                pool.map(empty_task, files)
