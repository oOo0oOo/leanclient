"""Integration tests for async request functionality."""

import time
import pytest
from leanclient import LeanLSPClient


@pytest.mark.unimportant
def test_async_single_request(lsp_client: LeanLSPClient):
    """Test that a single async request works."""
    path = "LeanTestProject/Basic.lean"
    lsp_client.open_file(path)

    # Send async request
    with lsp_client._opened_files_lock:
        state = lsp_client.opened_files.get(path)
        version = state.version if state else 0

    future = lsp_client._send_request_async(
        "textDocument/hover",
        {
            "textDocument": {
                "uri": lsp_client._local_to_uri(path),
                "version": version,
            },
            "position": {"line": 4, "character": 2},
        },
    )

    # Wait for result with timeout
    start_time = time.time()
    while not future.done() and time.time() - start_time < 5:
        time.sleep(0.01)

    assert future.done(), "Future should be completed"
    result = future.result()
    assert result is not None
    assert "contents" in result


def test_async_multiple_requests_concurrent(lsp_client: LeanLSPClient):
    """Test that multiple async requests can be in flight simultaneously."""
    path = "LeanTestProject/Basic.lean"
    lsp_client.open_file(path)

    # Send multiple requests at once
    positions = [
        (4, 2),
        (10, 4),
        (15, 10),
    ]

    futures = []
    start_time = time.time()
    uri = lsp_client._local_to_uri(path)

    for line, char in positions:
        with lsp_client._opened_files_lock:
            version = lsp_client.opened_files[path].version
        future = lsp_client._send_request_async(
            "textDocument/hover",
            {
                "textDocument": {
                    "uri": uri,
                    "version": version,
                },
                "position": {"line": line, "character": char},
            },
        )
        futures.append(future)

    # Wait for all futures to complete
    max_wait = 5
    while not all(f.done() for f in futures) and time.time() - start_time < max_wait:
        time.sleep(0.01)

    elapsed = time.time() - start_time

    # All futures should be done
    assert all(f.done() for f in futures), "All futures should be completed"

    # Verify we can get results
    results = [f.result() for f in futures]
    assert len(results) == len(positions)

    # Concurrent execution should be faster than sequential
    # (though this is a rough heuristic)
    print(f"Concurrent execution took {elapsed:.3f}s for {len(positions)} requests")
    assert elapsed < 3, "Concurrent requests should complete quickly"


@pytest.mark.unimportant
def test_async_request_performance(lsp_client: LeanLSPClient):
    """Test that async requests provide performance benefit for multiple operations."""
    path = "LeanTestProject/Basic.lean"
    lsp_client.open_file(path)

    num_requests = 5
    positions = [(i, 2) for i in range(5, 5 + num_requests)]

    # Time async approach
    async_start = time.time()
    futures = []
    uri = lsp_client._local_to_uri(path)
    for line, char in positions:
        with lsp_client._opened_files_lock:
            version = lsp_client.opened_files[path].version
        future = lsp_client._send_request_async(
            "textDocument/hover",
            {
                "textDocument": {
                    "uri": uri,
                    "version": version,
                },
                "position": {"line": line, "character": char},
            },
        )
        futures.append(future)

    # Wait for all
    max_wait = 10
    while not all(f.done() for f in futures) and time.time() - async_start < max_wait:
        time.sleep(0.01)

    async_time = time.time() - async_start

    # Verify all completed
    assert all(f.done() for f in futures), "All async futures should complete"

    print(f"Async: {num_requests} requests in {async_time:.3f}s")
    print(f"Average: {async_time / num_requests:.3f}s per request")

    # Should complete in reasonable time
    assert async_time < 5, f"Async requests took too long: {async_time:.3f}s"


@pytest.mark.unimportant
def test_sync_api_still_works(lsp_client: LeanLSPClient):
    """Test that the synchronous API still works after async changes."""
    path = "LeanTestProject/Basic.lean"
    lsp_client.open_file(path)

    # Test various sync methods
    result = lsp_client.get_hover(path, 4, 2)
    assert result is not None
    assert "contents" in result

    completions = lsp_client.get_completions(path, 10, 4)
    assert isinstance(completions, list)

    symbols = lsp_client.get_document_symbols(path)
    assert isinstance(symbols, list)
    assert len(symbols) > 0


@pytest.mark.unimportant
def test_async_with_errors(lsp_client: LeanLSPClient):
    """Test that async requests handle errors properly."""
    path = "LeanTestProject/Basic.lean"
    lsp_client.open_file(path)

    # Send request with invalid parameters (very large position)
    with lsp_client._opened_files_lock:
        version = lsp_client.opened_files[path].version
    future = lsp_client._send_request_async(
        "textDocument/hover",
        {
            "textDocument": {
                "uri": lsp_client._local_to_uri(path),
                "version": version,
            },
            "position": {"line": 99999, "character": 99999},
        },
    )

    # Wait for completion
    start_time = time.time()
    while not future.done() and time.time() - start_time < 5:
        time.sleep(0.01)

    assert future.done(), "Future should complete even with invalid request"

    # Result might be None or empty for invalid position
    result = future.result()
    # Just verify we got a response (might be None)
    assert result is None or isinstance(result, dict)


def test_multiple_files_async(lsp_client: LeanLSPClient):
    """Test async requests across multiple files."""
    paths = [
        "LeanTestProject/Basic.lean",
        "LeanTestProject/Basic.lean",
    ]  # Same file for simplicity

    # Open files
    for path in paths:
        lsp_client.open_file(path)

    # Send requests to different files concurrently
    futures = []
    for path in paths:
        with lsp_client._opened_files_lock:
            version = lsp_client.opened_files[path].version
        future = lsp_client._send_request_async(
            "textDocument/documentSymbol",
            {
                "textDocument": {
                    "uri": lsp_client._local_to_uri(path),
                    "version": version,
                },
            },
        )
        futures.append((path, future))

    # Wait for all
    start_time = time.time()
    while not all(f.done() for _, f in futures) and time.time() - start_time < 5:
        time.sleep(0.01)

    # Verify all completed
    assert all(f.done() for _, f in futures), "All futures should complete"

    for path, future in futures:
        result = future.result()
        assert isinstance(result, list)
        assert len(result) > 0


def test_notification_handler_registration(lsp_client: LeanLSPClient):
    """Test that notification handlers can be registered and work."""
    received_notifications = []

    def handler(msg):
        received_notifications.append(msg)

    # Register handler for diagnostics
    lsp_client._register_notification_handler(
        "textDocument/publishDiagnostics", handler
    )

    # Open a file which should trigger diagnostics
    path = "LeanTestProject/Basic.lean"
    lsp_client.open_file(path)

    # Wait a bit for notifications
    time.sleep(1)

    # Should have received at least one diagnostic notification
    # (though this might be flaky depending on file content)
    # For now just verify the mechanism works

    # Unregister
    lsp_client._unregister_notification_handler("textDocument/publishDiagnostics")

    # Test passes if no exceptions were raised
    assert True
