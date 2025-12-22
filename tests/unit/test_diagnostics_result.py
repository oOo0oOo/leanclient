"""Unit tests for DiagnosticsResult dataclass."""

import pytest

from leanclient.file_manager import DiagnosticsResult


@pytest.mark.unit
def test_diagnostics_result_basic_construction():
    """Test basic construction with all attributes."""
    result = DiagnosticsResult(
        success=True,
        diagnostics=[{"message": "test"}],
    )
    assert result.success is True
    assert result.diagnostics == [{"message": "test"}]


@pytest.mark.unit
def test_diagnostics_result_iteration():
    """Test that DiagnosticsResult can be iterated like a list."""
    diagnostics = [
        {"message": "first", "severity": 1},
        {"message": "second", "severity": 2},
    ]
    result = DiagnosticsResult(success=False, diagnostics=diagnostics)

    collected = list(result)
    assert collected == diagnostics


@pytest.mark.unit
def test_diagnostics_result_len():
    """Test that len() works on DiagnosticsResult."""
    result_empty = DiagnosticsResult(success=True, diagnostics=[])
    result_with_items = DiagnosticsResult(
        success=False, diagnostics=[{"a": 1}, {"b": 2}, {"c": 3}]
    )

    assert len(result_empty) == 0
    assert len(result_with_items) == 3


@pytest.mark.unit
def test_diagnostics_result_indexing():
    """Test that indexing works on DiagnosticsResult."""
    diagnostics = [{"index": 0}, {"index": 1}, {"index": 2}]
    result = DiagnosticsResult(success=True, diagnostics=diagnostics)

    assert result[0] == {"index": 0}
    assert result[1] == {"index": 1}
    assert result[2] == {"index": 2}
    assert result[-1] == {"index": 2}


@pytest.mark.unit
def test_diagnostics_result_bool_empty():
    """Test truthiness when diagnostics list is empty."""
    result = DiagnosticsResult(success=True, diagnostics=[])
    assert bool(result) is False


@pytest.mark.unit
def test_diagnostics_result_bool_nonempty():
    """Test truthiness when diagnostics list has items."""
    result = DiagnosticsResult(success=False, diagnostics=[{"message": "error"}])
    assert bool(result) is True


@pytest.mark.unit
def test_diagnostics_result_success_with_warnings_only():
    """Test that success can be True even with warnings (severity != 1)."""
    # Severity 2 = warning in LSP
    diagnostics = [{"message": "warning", "severity": 2}]
    result = DiagnosticsResult(success=True, diagnostics=diagnostics)
    assert result.success is True


@pytest.mark.unit
def test_diagnostics_result_for_loop_compatibility():
    """Test using DiagnosticsResult in a for loop - common use case."""
    diagnostics = [{"line": 1}, {"line": 5}, {"line": 10}]
    result = DiagnosticsResult(success=True, diagnostics=diagnostics)

    lines = []
    for diag in result:
        lines.append(diag["line"])

    assert lines == [1, 5, 10]


@pytest.mark.unit
def test_diagnostics_result_list_comprehension():
    """Test using DiagnosticsResult in list comprehension."""
    diagnostics = [
        {"message": "error1", "severity": 1},
        {"message": "warning", "severity": 2},
        {"message": "error2", "severity": 1},
    ]
    result = DiagnosticsResult(success=False, diagnostics=diagnostics)

    errors = [d for d in result if d.get("severity") == 1]
    assert len(errors) == 2
    assert errors[0]["message"] == "error1"
    assert errors[1]["message"] == "error2"
