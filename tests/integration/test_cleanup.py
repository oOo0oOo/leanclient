"""Integration tests for proper cleanup and process termination.

Tests to verify that LeanLSPClient properly terminates the 'lake serve'
subprocess and doesn't leave lingering processes after close().
"""

import subprocess
import sys

import psutil
import pytest

from leanclient import LeanLSPClient


@pytest.mark.integration
def test_no_lingering_processes_after_close(test_project_dir):
    """Test that client.close() terminates the lake serve process."""
    client = LeanLSPClient(test_project_dir, prevent_cache_get=True)
    client_pid = client.process.pid

    assert psutil.pid_exists(client_pid), "Client process should exist"

    client.close()

    assert not psutil.pid_exists(client_pid), "Process should be terminated"


@pytest.mark.integration
@pytest.mark.unimportant
def test_multiple_clients_cleanup(test_project_dir):
    """Test that multiple clients clean up properly."""
    clients = []
    pids = []

    for _ in range(3):
        client = LeanLSPClient(test_project_dir, prevent_cache_get=True)
        clients.append(client)
        pids.append(client.process.pid)

    for pid in pids:
        assert psutil.pid_exists(pid), f"Process {pid} should be running"

    for client in clients:
        client.close()

    for pid in pids:
        assert not psutil.pid_exists(pid), f"Process {pid} should be terminated"


@pytest.mark.integration
@pytest.mark.unimportant
def test_close_already_dead_process(test_project_dir):
    """Test that close() handles a process that has already died."""
    client = LeanLSPClient(test_project_dir)
    client_pid = client.process.pid

    # Kill the process directly to simulate unexpected termination
    client.process.kill()
    client.process.wait()

    assert not psutil.pid_exists(client_pid), "Process should be dead"

    # close() should handle this gracefully without errors
    client.close(timeout=0.25)


@pytest.mark.integration
def test_automatic_cleanup_at_exit(test_project_dir):
    """Test that atexit handler cleans up if close() is not called."""
    # Run a subprocess that creates a client without closing
    test_code = f"""
import sys
sys.path.insert(0, '{sys.path[0]}')

from leanclient import LeanLSPClient

# Create client without closing
client = LeanLSPClient('{test_project_dir}')
print(f"PID={{client.process.pid}}")
# Exit without calling close() - atexit should clean up
"""

    result = subprocess.run(
        [sys.executable, "-c", test_code], capture_output=True, text=True, timeout=10
    )

    # Extract PID from output
    pid = None
    for line in result.stdout.split("\n"):
        if line.startswith("PID="):
            pid = int(line.split("=")[1])
            break

    assert pid is not None, "Should have captured process PID"
    assert result.returncode == 0, "Program should exit cleanly"
    assert not psutil.pid_exists(pid), "Process should be cleaned up at exit"
