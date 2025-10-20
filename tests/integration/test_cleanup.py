"""Integration tests for proper cleanup and process termination.

Tests to verify that LeanLSPClient properly terminates the 'lake serve' 
subprocess and doesn't leave lingering processes after close().
"""

import signal
import threading
import time
import psutil
import pytest

from leanclient import LeanLSPClient


def _get_lake_serve_processes():
    """Get all 'lake serve' processes."""
    processes = []
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = proc.info['cmdline']
            if cmdline and len(cmdline) >= 2 and 'lake' in cmdline[0] and 'serve' in cmdline[1]:
                processes.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return processes


def _assert_no_lingering_processes(client_pid, initial_count):
    """Assert process is terminated and no lingering processes remain."""
    time.sleep(0.1)
    assert not psutil.pid_exists(client_pid), "Process should be terminated"
    assert len(_get_lake_serve_processes()) == initial_count, "No lingering processes"


def _send_signal_during_operation(client, test_file_path, sig, delay=0.05):
    """Send signal to client process during operation."""
    def signal_sender():
        time.sleep(delay)
        client.process.send_signal(sig)
    
    thread = threading.Thread(target=signal_sender, daemon=True)
    thread.start()
    
    try:
        client.open_file(test_file_path)
        client.get_diagnostics(test_file_path)
    except (KeyboardInterrupt, BrokenPipeError, EOFError, OSError):
        pass  # Expected when interrupted/killed


@pytest.mark.integration
@pytest.mark.unimportant
def test_no_lingering_processes_after_close(test_project_dir):
    """Test that client.close() terminates the lake serve process."""
    initial_count = len(_get_lake_serve_processes())
    
    client = LeanLSPClient(test_project_dir, initial_build=False, print_warnings=False)
    client_pid = client.process.pid
    
    assert psutil.pid_exists(client_pid), "Client process should exist"
    
    client.close()
    _assert_no_lingering_processes(client_pid, initial_count)


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.unimportant
def test_multiple_clients_cleanup(test_project_dir):
    """Test that multiple clients clean up properly."""
    initial_count = len(_get_lake_serve_processes())
    
    clients = []
    pids = []
    for _ in range(3):
        client = LeanLSPClient(test_project_dir, initial_build=False, print_warnings=False)
        clients.append(client)
        pids.append(client.process.pid)
    
    assert len(_get_lake_serve_processes()) == initial_count + 3, "All processes running"
    
    for client in clients:
        client.close()
    
    time.sleep(0.1)
    
    for pid in pids:
        assert not psutil.pid_exists(pid), f"Process {pid} should be terminated"
    
    assert len(_get_lake_serve_processes()) == initial_count, "All processes cleaned up"


@pytest.mark.integration
@pytest.mark.parametrize("sig,timeout", [
    (signal.SIGINT, 0.1),      # CTRL+C with short timeout
    (signal.SIGINT, None),     # CTRL+C with immediate termination
    (signal.SIGKILL, 0.25),     # Force kill
    (signal.SIGTERM, 0.25),     # Graceful terminate
])
@pytest.mark.slow
@pytest.mark.unimportant
def test_signal_during_operation(test_project_dir, test_file_path, sig, timeout):
    """Test cleanup when process receives various signals during operation."""
    initial_count = len(_get_lake_serve_processes())
    
    client = LeanLSPClient(test_project_dir, initial_build=False, print_warnings=False)
    client_pid = client.process.pid
    
    _send_signal_during_operation(client, test_file_path, sig)
    
    client.close(timeout=timeout)
    _assert_no_lingering_processes(client_pid, initial_count)


@pytest.mark.integration
@pytest.mark.unimportant
def test_close_already_dead_process(test_project_dir):
    """Test cleanup when process has already died before close() is called."""
    initial_count = len(_get_lake_serve_processes())
    
    client = LeanLSPClient(test_project_dir, initial_build=False, print_warnings=False)
    client_pid = client.process.pid
    
    # Kill the process directly
    client.process.kill()
    client.process.wait()
    
    time.sleep(0.05)
    assert not psutil.pid_exists(client_pid), "Process should be dead"
    
    # Should handle cleanup gracefully
    client.close(timeout=0.25)
    
    time.sleep(0.05)
    assert len(_get_lake_serve_processes()) == initial_count, "No lingering processes"


@pytest.mark.integration
@pytest.mark.unimportant
def test_force_kill_on_timeout(test_project_dir):
    """Test that process is force killed if it doesn't terminate gracefully."""
    initial_count = len(_get_lake_serve_processes())
    
    client = LeanLSPClient(test_project_dir, initial_build=False, print_warnings=False)
    client_pid = client.process.pid
    
    # Close with very short timeout to trigger force kill
    client.close(timeout=0.001)
    _assert_no_lingering_processes(client_pid, initial_count)
