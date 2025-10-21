"""Project setup utilities for tests."""

import subprocess
import shutil
import os

TEST_ENV_DIR = ".test_env/"
TEST_PROJECT_NAME = "LeanTestProject"
TEST_FILE_PATH = f"{TEST_PROJECT_NAME}/Basic.lean"


def _get_lean_version():
    """Get Lean version from tests/.lean-version file."""
    version_file = os.path.join(os.path.dirname(__file__), "..", ".lean-version")
    with open(version_file) as f:
        return f.read().strip()


def _needs_rebuild():
    """Check if test project needs rebuild."""
    if not os.path.exists(TEST_ENV_DIR):
        return True

    marker = os.path.join(TEST_ENV_DIR, ".lean-version")
    if not os.path.exists(marker):
        return True

    with open(marker) as f:
        current = f.read().strip()

    desired = _get_lean_version()
    if current != desired:
        print(f"Lean version changed: {current} → {desired}")
        return True

    return not os.path.exists(os.path.join(TEST_ENV_DIR, TEST_FILE_PATH))


def _create_project(path, name, version, use_mathlib=False, force=False):
    """Create Lean project with lake."""
    # Setup elan environment
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)
        subprocess.run("elan self update", shell=True, cwd=path, capture_output=True)
        subprocess.run(
            f"elan toolchain install leanprover/lean4:{version}", shell=True, cwd=path
        )
        subprocess.run(
            f"elan override set leanprover/lean4:{version}", shell=True, cwd=path
        )

    # Create project
    full_path = os.path.join(path, name)
    if os.path.exists(full_path) and force:
        subprocess.run(f"rm -rf {full_path}", shell=True)

    if not os.path.exists(full_path):
        subprocess.run(f"lake init {name}", shell=True, cwd=path)

        # Configure project files
        with open(os.path.join(path, "Main.lean"), "w") as f:
            f.write(("import Mathlib\n" if use_mathlib else "") + f"import {name}")

        toml = f'name = "{name}"\nversion = "0.1.0"\n\n[[lean_lib]]\nname = "{name}"\n'
        if use_mathlib:
            toml += f'[[require]]\nname = "mathlib"\nscope = "leanprover-community"\nrev = "{version}"\n'

        with open(os.path.join(path, "lakefile.toml"), "w") as f:
            f.write(toml)

        subprocess.run("lake update", shell=True, cwd=path)
        subprocess.run("lake exe cache get", shell=True, cwd=path)
        subprocess.run("lake build", shell=True, cwd=path)


def setup_test_project():
    """Setup test Lean project with mathlib (rebuilds only if version changed)."""
    version = _get_lean_version()

    if not _needs_rebuild():
        return TEST_ENV_DIR

    print(f"Setting up test project with Lean {version}...")

    _create_project(
        TEST_ENV_DIR, TEST_PROJECT_NAME, version, use_mathlib=True, force=True
    )

    # Copy test file
    shutil.copy("tests/data/tests.lean", f"{TEST_ENV_DIR}{TEST_FILE_PATH}")
    subprocess.run(["lake", "build"], cwd=TEST_ENV_DIR, check=True)

    # Mark version
    with open(os.path.join(TEST_ENV_DIR, ".lean-version"), "w") as f:
        f.write(version)

    print(f"✓ Test project built successfully with Lean {version}")
    return TEST_ENV_DIR
