"""Pytest configuration and shared fixtures for leanclient tests."""

import os
import uuid
import pytest

from leanclient import LeanLSPClient
from leanclient.base_client import BaseLeanLSPClient
from leanclient.utils import DocumentContentChange

from fixtures import (
    TEST_ENV_DIR,
    TEST_PROJECT_NAME,
    TEST_FILE_PATH,
    setup_test_project,
    FAST_MATHLIB_FILES,
    get_random_fast_mathlib_files,
    get_random_mathlib_files,
)


# ============================================================================
# Session-level fixtures (setup once for all tests)
# ============================================================================


@pytest.fixture(scope="session")
def test_project_dir():
    """Setup test Lean project once for entire test session.

    Returns:
        str: Path to the test environment directory.
    """
    return setup_test_project()


@pytest.fixture(scope="session")
def test_env_dir():
    """Test environment directory path."""
    return TEST_ENV_DIR


@pytest.fixture(scope="session")
def test_project_name():
    """Test project name."""
    return TEST_PROJECT_NAME


@pytest.fixture(scope="session")
def test_file_path():
    """Test file path relative to project."""
    return TEST_FILE_PATH


@pytest.fixture(scope="session")
def fast_mathlib_files():
    """List of fast-loading mathlib files."""
    return FAST_MATHLIB_FILES


# ============================================================================
# Module-level fixtures (reused across test module)
# ============================================================================


@pytest.fixture(scope="module")
def base_client(test_project_dir):
    """Provide a BaseLeanLSPClient instance."""
    client = BaseLeanLSPClient(test_project_dir, prevent_cache_get=True)
    yield client
    client.close()


@pytest.fixture(scope="module")
def lsp_client(test_project_dir):
    """Provide a LeanLSPClient instance."""
    client = LeanLSPClient(test_project_dir, prevent_cache_get=True)
    yield client
    client.close()


# ============================================================================
# Function-level fixtures (fresh for each test)
# ============================================================================


@pytest.fixture
def clean_lsp_client(test_project_dir):
    """Fresh LeanLSPClient for each test.

    Use this when tests need to mutate the client state.

    Args:
        test_project_dir: Test project directory path.

    Yields:
        LeanLSPClient: Fresh client instance.
    """
    client = LeanLSPClient(
        test_project_dir, initial_build=False, prevent_cache_get=True
    )
    yield client
    client.close()


@pytest.fixture
def single_file_client(lsp_client, test_file_path):
    """SingleFileClient for the test file.

    Args:
        lsp_client: Shared LSP client.
        test_file_path: Path to test file.

    Returns:
        SingleFileClient: Client for test file.
    """
    return lsp_client.create_file_client(test_file_path)


@pytest.fixture
def temp_lean_file(test_project_dir):
    """Temporary Lean file that auto-cleans after test.

    Args:
        test_project_dir: Test project directory path.

    Yields:
        tuple: (relative_path, absolute_path) for temporary file.
    """
    filename = f"Temp_{uuid.uuid4().hex[:8]}.lean"
    rel_path = filename
    abs_path = os.path.join(test_project_dir, filename)

    yield rel_path, abs_path

    if os.path.exists(abs_path):
        os.remove(abs_path)


# ============================================================================
# Helper fixtures
# ============================================================================


@pytest.fixture
def sample_document_changes():
    """Sample document changes for testing.

    Returns:
        list: List of DocumentContentChange instances.
    """
    return [
        DocumentContentChange("--", [42, 20], [42, 30]),
        DocumentContentChange("/a/b/c\\", [89, 20], [93, 20]),
        DocumentContentChange("\n\n\n\n\n\n\n\n\n", [95, 100000], [105, 100000]),
    ]


@pytest.fixture
def random_fast_mathlib_files():
    """Factory fixture for random fast mathlib files.

    Returns:
        callable: Function to get random files.
    """
    return get_random_fast_mathlib_files


@pytest.fixture
def random_mathlib_files():
    """Factory fixture for random mathlib files.

    Returns:
        callable: Function to get random files.
    """
    return get_random_mathlib_files
