"""Tests for update_file_content and optimized open_file behavior."""

import time
import pytest

from leanclient import LeanLSPClient


@pytest.fixture
def client(test_project_dir):
    """Fresh client for each test."""
    c = LeanLSPClient(test_project_dir, prevent_cache_get=True)
    yield c
    c.close()


def test_update_file_content_basic(client, test_file_path, test_project_dir):
    """Update file content and verify diagnostics."""
    client.open_file(test_file_path)

    new_content = "def myNat : Nat := 42\ntheorem test : myNat = 42 := rfl"
    client.update_file_content(test_file_path, new_content)

    diagnostics = client.get_diagnostics(test_file_path)
    assert isinstance(diagnostics, list)


def test_update_file_content_not_open(client, test_file_path):
    """Update file that isn't open should raise error."""
    with pytest.raises(FileNotFoundError):
        client.update_file_content(test_file_path, "content")


def test_update_file_content_with_errors(client, test_file_path):
    """Update with invalid content produces diagnostics."""
    client.open_file(test_file_path)

    bad_content = "theorem broken : True := by sorry"
    client.update_file_content(test_file_path, bad_content)

    diagnostics = client.get_diagnostics(test_file_path)
    assert len(diagnostics) > 0
    assert any("sorry" in str(d) for d in diagnostics)


def test_update_file_content_multiple_times(client, test_file_path):
    """Multiple updates in sequence should all work."""
    client.open_file(test_file_path)

    contents = ["def x : Nat := 1", "def x : Nat := 2", "def x : Nat := 3"]

    for content in contents:
        client.update_file_content(test_file_path, content)
        diagnostics = client.get_diagnostics(test_file_path)
        assert isinstance(diagnostics, list)


def test_update_file_content_empty(client, test_file_path):
    """Update to empty string should work."""
    client.open_file(test_file_path)
    client.update_file_content(test_file_path, "")
    diagnostics = client.get_diagnostics(test_file_path)
    assert isinstance(diagnostics, list)


def test_open_file_first_time(client, test_file_path):
    """First time opening a file should work normally."""
    client.open_file(test_file_path)
    diagnostics = client.get_diagnostics(test_file_path)
    assert isinstance(diagnostics, list)


def test_open_file_already_open_no_disk_change(client, test_file_path):
    """Opening already-open file with no disk change uses update."""
    client.open_file(test_file_path)
    diag1 = client.get_diagnostics(test_file_path)

    client.open_file(test_file_path)
    diag2 = client.get_diagnostics(test_file_path)

    assert diag1 == diag2


def test_open_file_already_open_disk_changed(client, test_file_path, test_project_dir):
    """Opening after disk change should sync new content."""
    file_path = test_project_dir + test_file_path

    with open(file_path, "r") as f:
        original = f.read()

    try:
        client.open_file(test_file_path)
        client.get_diagnostics(test_file_path)

        with open(file_path, "w") as f:
            f.write("def changed : Nat := 999")

        client.open_file(test_file_path)
        content = client.get_file_content(test_file_path)
        assert "999" in content

    finally:
        with open(file_path, "w") as f:
            f.write(original)


def test_open_file_force_reopen_true(client, test_file_path):
    """Force reopen should close and reopen."""
    client.open_file(test_file_path)
    client.get_diagnostics(test_file_path)

    client.open_file(test_file_path, force_reopen=True)
    diagnostics = client.get_diagnostics(test_file_path)
    assert isinstance(diagnostics, list)


def test_open_file_reopen_actually_resets(client, test_file_path):
    """Force reopen should reset internal state."""
    client.open_file(test_file_path)
    client.get_diagnostics(test_file_path)

    client.open_file(test_file_path, force_reopen=True)

    with client._opened_files_lock:
        state2 = client.opened_files[test_file_path]
        version2 = state2.version

    assert version2 == 0


def test_open_file_force_reopen_false_faster(client, test_file_path):
    """Update path should be faster than reopen."""
    client.open_file(test_file_path)
    client.get_diagnostics(test_file_path)

    t0 = time.time()
    client.open_file(test_file_path, force_reopen=False)
    client.get_diagnostics(test_file_path)
    update_time = time.time() - t0

    t0 = time.time()
    client.open_file(test_file_path, force_reopen=True)
    client.get_diagnostics(test_file_path)
    reopen_time = time.time() - t0

    assert update_time < reopen_time


def test_open_file_after_close(client, test_file_path):
    """After close, open should be fresh regardless of flag."""
    client.open_file(test_file_path)
    client.close_files([test_file_path])

    client.open_file(test_file_path, force_reopen=False)
    diagnostics = client.get_diagnostics(test_file_path)
    assert isinstance(diagnostics, list)


def test_open_file_after_update_file_content(client, test_file_path, test_project_dir):
    """Open after update_file_content should sync from disk."""
    file_path = test_project_dir + test_file_path

    with open(file_path, "r") as f:
        original = f.read()

    try:
        client.open_file(test_file_path)
        client.update_file_content(test_file_path, "def updated : Nat := 123")

        with open(file_path, "w") as f:
            f.write("def from_disk : Nat := 456")

        client.open_file(test_file_path)
        content = client.get_file_content(test_file_path)
        assert "456" in content
        assert "123" not in content

    finally:
        with open(file_path, "w") as f:
            f.write(original)


def test_mixed_workflow(client, test_file_path, test_project_dir):
    """Realistic workflow with mixed operations."""
    file_path = test_project_dir + test_file_path

    with open(file_path, "r") as f:
        original = f.read()

    try:
        client.open_file(test_file_path)
        client.get_diagnostics(test_file_path)

        # Update in-memory only
        client.update_file_content(test_file_path, "def step1 : Nat := 1")
        assert "step1" in client.get_file_content(test_file_path)

        # open_file() syncs from disk (Option C), which overwrites in-memory changes
        client.open_file(test_file_path)
        assert "step1" not in client.get_file_content(
            test_file_path
        )  # Reverted to disk content

        # Now write to disk and sync
        with open(file_path, "w") as f:
            f.write("def step2 : Nat := 2")

        # Without force_reopen, should sync from disk
        client.open_file(test_file_path, force_reopen=False)
        assert "step2" in client.get_file_content(test_file_path)

        # force_reopen does close/reopen but gets same disk content
        client.open_file(test_file_path, force_reopen=True)
        assert "step2" in client.get_file_content(test_file_path)

    finally:
        with open(file_path, "w") as f:
            f.write(original)
