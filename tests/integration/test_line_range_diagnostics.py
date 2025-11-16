"""Tests for line range diagnostics feature."""

import pytest
from unittest.mock import Mock, patch
from leanclient.file_manager import LSPFileManager, FileState


# ============================================================================
# Unit tests for FileState methods
# ============================================================================


def test_is_line_range_complete_empty_processing():
    """Empty processing list means complete."""
    state = FileState(
        uri="file:///test.lean",
        content="test",
        current_processing=[],
        diagnostics_version=0,
    )
    assert state.is_line_range_complete(10, 20)


def test_is_line_range_complete_basic():
    """Range completes before full file."""
    state = FileState(uri="file:///test.lean", content="test", diagnostics_version=0)

    # Processing lines 0-50: line range 10-20 is still processing
    state.current_processing = [{"range": {"start": {"line": 0}, "end": {"line": 50}}}]
    assert not state.is_line_range_complete(10, 20)

    # Processing lines 30-50: line range 10-20 is complete
    state.current_processing = [{"range": {"start": {"line": 30}, "end": {"line": 50}}}]
    assert state.is_line_range_complete(10, 20)

    state.current_processing = []
    assert state.is_line_range_complete(10, 20)


def test_is_line_range_complete_single_line():
    """Single line range works."""
    state = FileState(uri="file:///test.lean", content="test", diagnostics_version=0)

    state.current_processing = [{"range": {"start": {"line": 5}, "end": {"line": 15}}}]

    assert not state.is_line_range_complete(10, 10)
    assert state.is_line_range_complete(20, 20)


def test_is_line_range_complete_sequential():
    """Sequential processing pattern works."""
    state = FileState(uri="file:///test.lean", content="test", diagnostics_version=0)

    processing_states = [
        [{"range": {"start": {"line": 0}, "end": {"line": 50}}}],
        [{"range": {"start": {"line": 20}, "end": {"line": 50}}}],
        [{"range": {"start": {"line": 40}, "end": {"line": 50}}}],
        [],
    ]

    # First two states overlap range 10-30
    for processing in processing_states[:2]:
        state.current_processing = processing
        assert not state.is_line_range_complete(10, 30)

    # Last two states don't overlap range 10-30
    for processing in processing_states[2:]:
        state.current_processing = processing
        assert state.is_line_range_complete(10, 30)


def test_is_line_range_complete_parallel():
    """Multiple simultaneous ranges work."""
    state = FileState(uri="file:///test.lean", content="test", diagnostics_version=0)

    state.current_processing = [
        {"range": {"start": {"line": 5}, "end": {"line": 10}}},
        {"range": {"start": {"line": 20}, "end": {"line": 25}}},
        {"range": {"start": {"line": 40}, "end": {"line": 45}}},
    ]

    # Range 8-12 overlaps first processing range
    assert not state.is_line_range_complete(8, 12)

    # Range 15-18 is between processing ranges
    assert state.is_line_range_complete(15, 18)

    # Range 22-28 overlaps second processing range
    assert not state.is_line_range_complete(22, 28)


def test_filter_diagnostics_by_range_basic():
    """Filtering diagnostics by range works."""
    diagnostics = [
        {"range": {"start": {"line": 5}, "end": {"line": 5}}, "message": "before"},
        {"range": {"start": {"line": 15}, "end": {"line": 15}}, "message": "inside"},
        {"range": {"start": {"line": 25}, "end": {"line": 25}}, "message": "after"},
    ]

    state = FileState(uri="file:///test.lean", content="test", diagnostics=diagnostics)

    filtered = state.filter_diagnostics_by_range(10, 20)

    assert len(filtered) == 1
    assert filtered[0]["message"] == "inside"


def test_filter_diagnostics_by_range_overlapping():
    """Diagnostics that overlap the range are included."""
    diagnostics = [
        {
            "range": {"start": {"line": 5}, "end": {"line": 12}},
            "message": "overlaps_start",
        },
        {
            "range": {"start": {"line": 15}, "end": {"line": 25}},
            "message": "overlaps_end",
        },
        {
            "range": {"start": {"line": 8}, "end": {"line": 22}},
            "message": "spans_range",
        },
        {"range": {"start": {"line": 30}, "end": {"line": 35}}, "message": "after"},
    ]

    state = FileState(uri="file:///test.lean", content="test", diagnostics=diagnostics)
    filtered = state.filter_diagnostics_by_range(10, 20)

    # Should include first 3 diagnostics
    assert len(filtered) == 3
    messages = {d["message"] for d in filtered}
    assert messages == {"overlaps_start", "overlaps_end", "spans_range"}


def test_filter_diagnostics_by_range_empty():
    """Empty diagnostics list returns empty."""
    state = FileState(uri="file:///test.lean", content="test", diagnostics=[])
    filtered = state.filter_diagnostics_by_range(10, 20)
    assert filtered == []


# ============================================================================
# Integration-style tests with mocked file manager
# ============================================================================


class MockFileManager(LSPFileManager):
    """Test file manager with mocked base client."""

    def __init__(self):
        self.project_path = "/test"
        self.max_opened_files = 4
        self.opened_files = {}
        self._opened_files_lock = Mock()
        self._close_condition = Mock()
        self._recently_closed = set()
        self._setup_global_handlers = Mock()


@pytest.fixture
def mock_file_manager():
    return MockFileManager()


def test_get_diagnostics_invalid_range(mock_file_manager):
    """Invalid range raises ValueError."""
    with pytest.raises(ValueError, match="start_line must be <= end_line"):
        with patch.object(mock_file_manager, "open_files"):
            mock_file_manager.opened_files["test.lean"] = FileState(
                uri="file:///test.lean", content="test", complete=True
            )
            mock_file_manager.get_diagnostics("test.lean", start_line=20, end_line=10)


def test_get_diagnostics_backward_compatibility(mock_file_manager):
    """get_diagnostics without range parameters works as before."""
    state = FileState(
        uri="file:///test.lean",
        content="test content",
        diagnostics=[{"message": "test"}],
        complete=True,
        diagnostics_version=0,
    )
    mock_file_manager.opened_files["test.lean"] = state

    with patch.object(mock_file_manager, "_opened_files_lock"):
        result = mock_file_manager.get_diagnostics("test.lean")

    assert result == [{"message": "test"}]


def test_get_diagnostics_fatal_error_no_diagnostics(mock_file_manager):
    """Fatal error with no diagnostics returns error message."""
    state = FileState(
        uri="file:///test.lean",
        content="test",
        fatal_error=True,
        diagnostics=[],
        complete=True,
        diagnostics_version=0,
    )
    mock_file_manager.opened_files["test.lean"] = state

    with patch.object(mock_file_manager, "_opened_files_lock"):
        result = mock_file_manager.get_diagnostics("test.lean")

    assert len(result) == 1
    assert "fatalError" in result[0]["message"]


def test_get_diagnostics_with_range_filters(mock_file_manager):
    """get_diagnostics with range filters diagnostics."""
    diagnostics = [
        {"range": {"start": {"line": 5}, "end": {"line": 5}}, "message": "before"},
        {"range": {"start": {"line": 15}, "end": {"line": 15}}, "message": "inside"},
        {"range": {"start": {"line": 25}, "end": {"line": 25}}, "message": "after"},
    ]

    state = FileState(
        uri="file:///test.lean",
        content="test",
        diagnostics=diagnostics,
        complete=True,
        current_processing=[],
        diagnostics_version=0,
    )
    mock_file_manager.opened_files["test.lean"] = state

    with patch.object(mock_file_manager, "_opened_files_lock"):
        result = mock_file_manager.get_diagnostics(
            "test.lean", start_line=10, end_line=20
        )

    assert len(result) == 1
    assert result[0]["message"] == "inside"

@pytest.mark.integration
@pytest.mark.parametrize("method_name", [
    "get_document_symbols",
    "get_folding_ranges",
])
def test_file_level_requests_wait_for_elaboration(lsp_client, method_name):
    """File-level requests wait for elaboration to complete (fix for bug #61).

    Verifies that get_document_symbols and get_folding_ranges block until
    file elaboration is complete, ensuring consistent non-empty results.
    """
    import os
    import tempfile

    lean_code = """import Mathlib.Algebra.Ring.Basic

theorem test_wait : 1 + 1 = 2 := rfl
"""

    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.lean', dir=lsp_client.project_path, delete=False
    ) as f:
        f.write(lean_code)
        temp_path = f.name

    try:
        rel_path = os.path.relpath(temp_path, lsp_client.project_path)
        method = getattr(lsp_client, method_name)

        result = method(rel_path)

        assert isinstance(result, list), f"{method_name} should return list"

        # For document_symbols, verify we got the expected symbol
        if method_name == "get_document_symbols":
            assert result, f"{method_name} should return non-empty"
            symbol_names = [s.get("name") for s in result]
            assert "test_wait" in symbol_names, f"Expected 'test_wait' in {symbol_names}"

    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)




