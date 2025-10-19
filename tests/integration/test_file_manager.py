"""Integration tests for LSPFileManager."""

import os
import random
import time

import pytest

from leanclient import DocumentContentChange
from leanclient.base_client import BaseLeanLSPClient
from leanclient.file_manager import LSPFileManager
from leanclient.utils import apply_changes_to_text


class WrappedFileManager(LSPFileManager, BaseLeanLSPClient):
    """Test wrapper combining FileManager and BaseClient."""
    def __init__(self, *args, **kwargs):
        BaseLeanLSPClient.__init__(self, *args, **kwargs)
        LSPFileManager.__init__(self)


@pytest.fixture
def file_manager(test_project_dir):
    """Create WrappedFileManager for testing.
    
    Yields:
        WrappedFileManager: Test file manager instance.
    """
    manager = WrappedFileManager(
        test_project_dir, initial_build=False, print_warnings=False
    )
    yield manager
    manager.close()


# ============================================================================
# File opening tests
# ============================================================================

@pytest.mark.integration
@pytest.mark.mathlib
def test_open_files(file_manager, random_fast_mathlib_files):
    """Test opening files with caching."""
    paths = random_fast_mathlib_files(3)
    diag = file_manager.open_file(paths[0])
    diag2 = file_manager.open_file(paths[0])  # One file overlap
    diags = file_manager.open_files(paths[:2])  # Two files, 1 overlap
    diags2 = file_manager.open_files(paths[:2])  # Cache

    assert diag == diag2
    assert diag == diags[0]
    assert diags == diags2


# ============================================================================
# File update tests
# ============================================================================

@pytest.mark.integration
@pytest.mark.mathlib
def test_file_update(file_manager, random_fast_mathlib_files, test_env_dir):
    """Test updating file with multiple changes."""
    path = random_fast_mathlib_files(1, 42)[0]
    diags = file_manager.open_file(path)
    assert len(diags) <= 1, f"Expected 0 or 1 diagnostics, got {len(diags)}"

    NUM_CHANGES = 16
    changes = []
    t0 = time.time()
    text = file_manager.get_file_content(path)
    for _ in range(NUM_CHANGES):
        line = random.randint(10, 50)
        d = DocumentContentChange(
            "inv#lid\n", [line, random.randint(0, 4)], [line, random.randint(4, 8)]
        )
        changes.append(d)
        text = apply_changes_to_text(text, [d])
    diags2 = file_manager.update_file(path, changes)

    if len(diags2) == 1:
        assert diags2[0]["message"] == "unterminated comment"
    else:
        assert len(diags2) >= NUM_CHANGES // 2, \
            f"Expected {NUM_CHANGES // 2} diagnostics got {len(diags2)}:\n\n{diags2}\n\n"
    
    duration = time.time() - t0
    print(f"Updated {len(changes)} changes in one call: {duration:.2f} s")

    new_text = file_manager.get_file_content(path)
    assert text == new_text

    fpath = path.replace(".lean", "_test.lean")
    with open(test_env_dir + fpath, "w") as f:
        f.write(text)
    diags3 = file_manager.open_file(fpath)
    os.remove(test_env_dir + fpath)

    assert diags2 == diags3

    file_manager.close_files([path])


@pytest.mark.integration
@pytest.mark.mathlib
@pytest.mark.slow
def test_file_update_line_by_line(file_manager, test_env_dir):
    """Test updating file line by line."""
    NUM_LINES = 24
    path = ".lake/packages/mathlib/Mathlib/NumberTheory/FLT/Basic.lean"

    with open(test_env_dir + path, "r") as f:
        lines = f.readlines()
    START = len(lines) - NUM_LINES

    fantasy = "Fantasy.lean"
    fantasy_path = test_env_dir + fantasy
    text = "".join(lines[:START])
    with open(fantasy_path, "w") as f:
        f.write(text)

    try:
        file_manager.open_file(fantasy)

        lines = lines[-NUM_LINES:]
        t0 = time.time()
        diagnostics = []
        for i, line in enumerate(lines):
            text += line
            diag = file_manager.update_file(
                fantasy,
                [DocumentContentChange(line, [i + START, 0], [i + START, len(line)])],
            )
            content = file_manager.get_file_content(fantasy)
            assert content == text
            diagnostics.extend(diag)

        assert len(diagnostics) > NUM_LINES / 2
        speed = len(lines) / (time.time() - t0)
        print(f"Updated {len(lines)} lines one by one: {speed:.2f} lines/s")
    finally:
        if os.path.exists(fantasy_path):
            os.remove(fantasy_path)
        file_manager.close_files([fantasy])


@pytest.mark.integration
@pytest.mark.mathlib
def test_update_file_mathlib(file_manager, test_env_dir):
    """Test updating multiple mathlib files."""
    files = [
        ".lake/packages/mathlib/Mathlib/Data/Num/Prime.lean",
        ".lake/packages/mathlib/Mathlib/Data/Finset/SDiff.lean",
    ]
    diag = file_manager.open_files(files)
    assert diag == [[], []], f"Expected no diagnostics, got {diag}"

    changes = [
        DocumentContentChange("--", [42, 20], [42, 30]),
        DocumentContentChange("/a/b/c\\", [89, 20], [93, 20]),
        DocumentContentChange("\n\n\n\n\n\n\n\n\n", [95, 100000], [105, 100000]),
    ]

    exp_texts = [
        apply_changes_to_text(file_manager.get_file_content(f), changes) for f in files
    ]

    for file, exp_text in zip(files, exp_texts):
        diag2 = file_manager.update_file(file, changes)
        assert len(diag2) > 0, f"Expected diagnostics, got []"
        assert file_manager.get_file_content(file) == exp_text

        # Load new file with content and compare
        fpath = file.replace(".lean", "_test.lean")
        with open(test_env_dir + fpath, "w") as f:
            f.write(exp_text)
        diag3 = file_manager.open_file(fpath)
        diag4 = file_manager.get_diagnostics(fpath)
        assert diag2 == diag3
        assert diag3 == diag4

        os.remove(test_env_dir + fpath)

        file_manager.close_files([file, fpath])


@pytest.mark.integration
@pytest.mark.mathlib
def test_update_try_tactics(file_manager):
    """Test updating file to try different tactics."""
    file_path = ".lake/packages/mathlib/Mathlib/MeasureTheory/Covering/OneDim.lean"
    diag_init = file_manager.open_file(file_path)
    assert diag_init == [], f"Expected no diagnostics, got {diag_init}"

    line, character = (26, 61)
    tactics = ["simp", "aesop", "norm_num", "omega", "linarith"]
    l_tactic = len("linarith")
    messages = {}
    for tactic in tactics:
        change = DocumentContentChange(
            start=[line, character],
            end=[line, character + l_tactic],
            text=tactic,
        )
        l_tactic = len(tactic)
        messages[tactic] = file_manager.update_file(
            file_path,
            [change],
        )

    exp_len = {
        "aesop": 0,
        "linarith": 0,
        "ring": 1,
        "norm_num": 1,
        "omega": 1,
        "simp": 1,
    }

    for tactic in tactics:
        assert len(messages[tactic]) == exp_len[tactic], f"{messages}"


# ============================================================================
# File close tests
# ============================================================================

@pytest.mark.integration
@pytest.mark.mathlib
def test_close(file_manager):
    """Test closing file and terminating process."""
    # Open large file, then close: Expecting process kill
    fpath = ".lake/packages/mathlib/Mathlib/MeasureTheory/Covering/OneDim.lean"
    file_manager.open_file(fpath)
    file_manager.close_files([fpath], blocking=False)
    file_manager.close(timeout=0.01)
    assert file_manager.process.poll() == -15  # SIGTERM despite kill?
