import os
import sys
import cProfile


def find_lean_files_recursively(abs_path: str) -> list[str]:
    uris = []
    for root, __, files in os.walk(abs_path):
        for file in files:
            if file.endswith(".lean"):
                uris.append("file://" + os.path.join(root, file))
    return uris


# Profiling
def start_profiler() -> cProfile.Profile:
    sys.setrecursionlimit(10000)
    profiler = cProfile.Profile()
    profiler.enable()
    return profiler


def stop_profiler(profiler: cProfile.Profile, out_path: str = "profile.png"):
    profiler.disable()
    profiler.dump_stats("p.prof")
    cmd = f"gprof2dot -f pstats p.prof -n 0.005 -e 0.001 | dot -Tpng -o {out_path}"
    os.system(cmd)
    os.remove("p.prof")
