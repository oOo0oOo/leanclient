"""Project setup utilities for tests."""

import subprocess
import shutil
import os

# TEST CONFIG
TEST_ENV_DIR = ".test_env/"
TEST_PROJECT_NAME = "LeanTestProject"
TEST_FILE_PATH = f"{TEST_PROJECT_NAME}/Basic.lean"


def setup_test_project():
    """Setup test Lean project with mathlib.
    
    Returns:
        str: Path to the test environment directory.
    """
    # Setup environment
    cmd = [
        "python",
        "scripts/create_lean_project.py",
        TEST_ENV_DIR,
        TEST_PROJECT_NAME,
        "v4.24.0",
        "--use-mathlib",
    ]
    subprocess.run(cmd, check=True)

    # Copy the lean files required for testing
    target_dir = f"{TEST_ENV_DIR}{TEST_FILE_PATH}"
    source_file = "tests/data/tests.lean"
    shutil.copy(source_file, target_dir)

    # Build the project
    subprocess.run(["lake", "build"], cwd=TEST_ENV_DIR, check=True)
    
    return TEST_ENV_DIR
