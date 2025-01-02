import unittest
import sys

from leanclient.utils import start_profiler, stop_profiler

if __name__ == "__main__":
    profiler = None
    if "--profile" in sys.argv:
        profiler = start_profiler()

    unittest.TextTestRunner().run(unittest.TestLoader().discover("tests"))

    if profiler:
        stop_profiler(profiler, "tests/profile.png")
