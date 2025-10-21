"""Unit tests for BaseLeanLSPClient."""

import pytest

from leanclient.base_client import BaseLeanLSPClient


@pytest.mark.unit
@pytest.mark.slow
def test_initial_build(test_project_dir):
    """Test BaseLeanLSPClient initialization with initial build."""
    lsp = BaseLeanLSPClient(test_project_dir, initial_build=True)
    lsp.close()


@pytest.mark.unit
def test_get_env_as_dict(base_client):
    """Test getting environment variables as dictionary."""
    env = base_client.get_env()

    expected_keys = [
        "ELAN",
        "ELAN_HOME",
        "ELAN_TOOLCHAIN",
        "LAKE",
        "LAKE_ARTIFACT_CACHE",
        "LAKE_CACHE_DIR",
        "LAKE_HOME",
        "LAKE_NO_CACHE",
        "LAKE_PKG_URL_MAP",
        "LD_LIBRARY_PATH",
        "LEAN",
        "LEAN_AR",
        "LEAN_CC",
        "LEAN_GITHASH",
        "LEAN_PATH",
        "LEAN_SRC_PATH",
        "LEAN_SYSROOT",
        "PATH",
    ]
    assert sorted(list(env.keys())) == sorted(expected_keys)


@pytest.mark.unit
def test_get_env_as_string(base_client):
    """Test getting environment variables as string."""
    env = base_client.get_env(return_dict=False)
    assert isinstance(env, str)
    assert "LEAN=" in env or "ELAN=" in env
