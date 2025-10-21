"""Integration tests for proper cleanup and process termination.

Tests to verify that LeanLSPClient properly terminates the 'lake serve' 
subprocess and doesn't leave lingering processes after close().
"""

import psutil
import pytest

from leanclient import LeanLSPClient


@pytest.mark.integration
def test_no_lingering_processes_after_close(test_project_dir):
    """Test that client.close() terminates the lake serve process."""
    client = LeanLSPClient(test_project_dir)
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
        client = LeanLSPClient(test_project_dir)
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
