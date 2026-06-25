"""Unit tests for BaseLeanLSPClient."""

import io
import threading
from concurrent.futures import Future

import orjson
import pytest

from leanclient.base_client import BaseLeanLSPClient, LSPProtocolError


class InlineLoop:
    """Minimal event-loop surface for reader-thread unit tests."""

    def create_future(self):
        return Future()

    def is_closed(self):
        return False

    def call_soon_threadsafe(self, callback, *args):
        callback(*args)


def make_reader_client(stdout: bytes) -> BaseLeanLSPClient:
    """Create a client shell without launching a real Lean server."""
    client = object.__new__(BaseLeanLSPClient)
    client.stdout = io.BytesIO(stdout)
    client._loop = InlineLoop()
    client._futures = {}
    client._futures_lock = threading.Lock()
    client._reader_error = None
    client.request_id = 0
    return client


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
        "LAKE_CACHE_ARTIFACT_ENDPOINT",
        "LAKE_CACHE_DIR",
        "LAKE_CACHE_KEY",
        "LAKE_CACHE_REVISION_ENDPOINT",
        "LAKE_CACHE_SERVICE",
        "LAKE_CONFIG",
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


@pytest.mark.unit
def test_read_stdout_message_accepts_additional_lsp_headers():
    """The parser accepts valid LSP frames with more than Content-Length."""
    message = {"jsonrpc": "2.0", "id": 1, "result": {}}
    body = orjson.dumps(message)
    client = make_reader_client(
        b"Content-Type: application/vscode-jsonrpc; charset=utf-8\r\n"
        + f"Content-Length: {len(body)}\r\n\r\n".encode()
        + body
    )

    assert client._read_stdout_message() == message


@pytest.mark.unit
def test_malformed_lsp_header_fails_pending_and_future_requests():
    """A bad header becomes a request error instead of killing the reader silently."""
    client = make_reader_client(b"X-Incompatible: nope\r\n\r\n{}")
    pending = Future()
    client._futures[7] = pending

    client._read_stdout_loop(threading.Event())

    error = pending.exception()
    assert isinstance(error, LSPProtocolError)
    assert "Missing Content-Length" in str(error)
    assert client._reader_error is error
    assert client._futures == {}

    next_request = client._send_request_async("textDocument/hover", {})
    assert next_request.exception() is error


@pytest.mark.unit
def test_truncated_lsp_body_fails_with_byte_counts():
    """A partial body reports the framing failure with useful counts."""
    client = make_reader_client(b"Content-Length: 5\r\n\r\n{}")

    with pytest.raises(LSPProtocolError, match="expected 5 bytes, got 2"):
        client._read_stdout_message()
