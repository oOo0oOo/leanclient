import os
from pprint import pprint
import select
import subprocess
import cProfile
import random

from leanclient import LeanLSPClient
from run_tests import TEST_ENV_DIR, FAST_MATHLIB_FILES


# Mathlib file path utilities
def get_all_mathlib_files() -> list[str]:
    file_paths = []
    l = len(TEST_ENV_DIR)
    path = TEST_ENV_DIR + ".lake/packages/mathlib/Mathlib"
    for root, __, files in os.walk(path):
        file_paths += [root[l:] + "/" + f for f in files if f.endswith(".lean")]
    return file_paths


def get_random_mathlib_files(num: int, seed: int = None) -> list[str]:
    all_files = get_all_mathlib_files()
    if seed is not None:
        all_files = sorted(all_files)
        random.seed(seed)
    else:
        random.seed()
    random.shuffle(all_files)
    return all_files[:num]


def get_random_fast_mathlib_files(num: int, seed: int = None) -> list[str]:
    if seed is not None:
        random.seed(seed)
    else:
        random.seed()
    return random.sample(FAST_MATHLIB_FILES, num)


# Read a bit longer from stdout
def read_stdout_timeout(client: LeanLSPClient, timeout: float = 2) -> str:
    print(f"Printing stdout for {timeout}s.")
    while True:
        if select.select([client.stdout], [], [], timeout)[0]:
            res = client._read_stdout()
        else:
            break
        pprint(res)


# Profiling. This requires `gprof2dot` and `dot` to be installed.
def start_profiler() -> cProfile.Profile:
    profiler = cProfile.Profile()
    profiler.enable()
    return profiler


def stop_profiler(profiler: cProfile.Profile, out_path: str = "profile.png"):
    profiler.disable()
    profiler.dump_stats("p.prof")
    cmd = f"gprof2dot -f pstats p.prof -n 0.005 -e 0.001 | dot -Tpng -o {out_path}"
    try:
        subprocess.run(cmd, shell=True, check=True)
    except subprocess.CalledProcessError:
        print("gprof2dot or dot is not installed. Skipping profile visualization.")
    os.remove("p.prof")
