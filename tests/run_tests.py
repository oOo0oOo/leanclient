import subprocess
import unittest
import sys
import shutil

from leanclient.utils import start_profiler, stop_profiler

# TEST CONFIG. Move?
TEST_ENV_DIR = ".lake_env/"
TEST_PROJECT_NAME = "LeanTestProject"
TEST_FILE_PATH = f"{TEST_PROJECT_NAME}/Basic.lean"

if __name__ == "__main__":
    # Setup environment
    cmd = [
        "python",
        "scripts/create_lean_project.py",
        TEST_ENV_DIR,
        TEST_PROJECT_NAME,
        "--use-mathlib",
    ]
    subprocess.run(cmd, check=True)

    # Copy the lean files required for testing
    target_dir = f"{TEST_ENV_DIR}{TEST_FILE_PATH}"
    shutil.copy("tests/tests.lean", target_dir)

    profiler = None
    if "--profile" in sys.argv:
        profiler = start_profiler()

    unittest.TextTestRunner().run(unittest.TestLoader().discover("tests"))

    if profiler:
        stop_profiler(profiler, "tests/profile.png")
