"""Unit tests for utility functions."""

import pytest
from leanclient.utils import (
    apply_changes_to_text,
    DocumentContentChange,
    normalize_newlines,
    _utf16_pos_to_utf8_pos,
    has_mathlib_dependency,
)


@pytest.mark.unit
def test_normalize_crlf_to_lf():
    assert normalize_newlines("hello\r\nworld") == "hello\nworld"
    assert normalize_newlines("a\r\nb\r\nc") == "a\nb\nc"


@pytest.mark.unit
def test_normalize_already_lf():
    assert normalize_newlines("hello\nworld") == "hello\nworld"


@pytest.mark.unit
def test_normalize_no_newlines():
    assert normalize_newlines("hello") == "hello"


@pytest.mark.unit
def test_utf16_pos_ascii_only():
    """ASCII characters are 1 UTF-16 code unit and 1 UTF-8 byte."""
    text = "hello\nworld"
    # Line 0, char 2 should be the 'l' in "hello"
    assert _utf16_pos_to_utf8_pos(text, 0, 2) == 2
    # Line 1, char 3 should be the 'l' in "world"
    assert _utf16_pos_to_utf8_pos(text, 1, 3) == 9  # 6 bytes for "hello\n" + 3


@pytest.mark.unit
def test_utf16_pos_unicode_bmp():
    """Unicode chars in BMP are 1 UTF-16 code unit but may be >1 UTF-8 byte."""
    text = "hełło\nworld"  # ł is U+0142, in BMP
    # Line 0, char 4 should be after "hełł"
    # "hełło" = 'h'(1) + 'e'(1) + 'ł'(2 UTF-8) + 'ł'(2 UTF-8) + 'o'(1) = 7 UTF-8 bytes
    # But in UTF-16: 'h'(1) + 'e'(1) + 'ł'(1) + 'ł'(1) + 'o'(1) = 5 code units
    assert _utf16_pos_to_utf8_pos(text, 0, 4) == 6  # After "hełł" in UTF-8


@pytest.mark.unit
def test_utf16_pos_emoji_surrogate_pair():
    """Emoji outside BMP need 2 UTF-16 code units (surrogate pair)."""
    text = "hi😀"  # 😀 is U+1F600, needs surrogate pair in UTF-16
    # UTF-16: 'h'(1) + 'i'(1) + '😀'(2) = 4 code units
    # UTF-8: 'h'(1) + 'i'(1) + '😀'(4) = 6 bytes
    assert _utf16_pos_to_utf8_pos(text, 0, 2) == 2  # After "hi"
    assert _utf16_pos_to_utf8_pos(text, 0, 4) == 6  # After "hi😀"


@pytest.mark.unit
def test_utf16_pos_character_beyond_line_length():
    """LSP accepts character positions beyond line length liberally."""
    text = "short\nline"
    # Line 0 has 5 chars, but asking for position 100 should clamp to end of line
    assert _utf16_pos_to_utf8_pos(text, 0, 100) == 5  # End of "short"
    assert _utf16_pos_to_utf8_pos(text, 0, 100000) == 5  # Still end of "short"


@pytest.mark.unit
def test_utf16_pos_negative_line():
    """Negative line numbers should clamp to 0."""
    text = "hello\nworld"
    assert _utf16_pos_to_utf8_pos(text, -1, 0) == 0


@pytest.mark.unit
def test_utf16_pos_line_beyond_file():
    """Line numbers beyond file should return file length."""
    text = "hello\nworld"
    assert _utf16_pos_to_utf8_pos(text, 100, 0) == len(text)


@pytest.mark.unit
def test_document_change_full_change():
    """Test creating a full document change (no range)."""
    change = DocumentContentChange("new text")
    assert change.text == "new text"
    assert change.start is None
    assert change.end is None
    assert change.is_full_change()


@pytest.mark.unit
def test_document_change_ranged_change():
    """Test creating a ranged change."""
    change = DocumentContentChange("replacement", [0, 0], [0, 5])
    assert change.text == "replacement"
    assert change.start == (0, 0)
    assert change.end == (0, 5)
    assert not change.is_full_change()


@pytest.mark.unit
def test_document_change_invalid_range_single_position():
    """Range must be None or a pair of [line, char] positions."""
    with pytest.raises(ValueError, match="requires both start and end"):
        DocumentContentChange("text", [0, 0])  # Missing end position


@pytest.mark.unit
def test_document_change_invalid_position_format():
    """Each position must be [line, character]."""
    with pytest.raises(ValueError, match="must be a .* pair"):
        DocumentContentChange("text", [0, 0, 0], [0, 5])  # Too many elements


@pytest.mark.unit
def test_apply_full_change():
    original = "hello\nworld"
    changes = [DocumentContentChange("goodbye")]
    result = apply_changes_to_text(original, changes)
    assert result == "goodbye"


@pytest.mark.unit
def test_apply_simple_ranged_change():
    original = "hello world"
    changes = [DocumentContentChange("cruel", [0, 6], [0, 11])]
    result = apply_changes_to_text(original, changes)
    assert result == "hello cruel"


@pytest.mark.unit
def test_apply_multiple_changes():
    """Changes are applied in sequence."""
    original = "line1\nline2\nline3"
    changes = [
        DocumentContentChange("LINE1", [0, 0], [0, 5]),
        DocumentContentChange("LINE2", [1, 0], [1, 5]),
    ]
    result = apply_changes_to_text(original, changes)
    assert result == "LINE1\nLINE2\nline3"


@pytest.mark.unit
def test_apply_change_with_extreme_position():
    """Test the bug fix: extreme character positions should be handled."""
    original = "short line\nlonger line here\nend"
    # Character position 100000 is way beyond line length
    changes = [DocumentContentChange("X", [1, 100000], [1, 100000])]
    result = apply_changes_to_text(original, changes)
    # Should append at end of line 1
    assert result == "short line\nlonger line hereX\nend"


@pytest.mark.unit
def test_apply_multiline_replacement():
    original = "line1\nline2\nline3\nline4"
    changes = [DocumentContentChange("NEW\nSTUFF", [1, 0], [2, 5])]
    result = apply_changes_to_text(original, changes)
    assert result == "line1\nNEW\nSTUFF\nline4"


@pytest.mark.unit
def test_apply_empty_changes():
    original = "unchanged"
    result = apply_changes_to_text(original, [])
    assert result == "unchanged"


@pytest.mark.unit
def test_apply_normalizes_input():
    """Input text should have CRLF normalized to LF."""
    original = "hello\r\nworld"
    changes = [DocumentContentChange("X", [1, 0], [1, 0])]
    result = apply_changes_to_text(original, changes)
    assert result == "hello\nXworld"


@pytest.mark.unit
def test_has_mathlib_dependency_with_mathlib(test_project_dir):
    """Test detection when mathlib is present in lake-manifest.json."""
    assert has_mathlib_dependency(test_project_dir) is True


@pytest.mark.unit
def test_has_mathlib_dependency_without_manifest(tmp_path):
    """Test when lake-manifest.json doesn't exist."""
    assert has_mathlib_dependency(tmp_path) is False


@pytest.mark.unit
def test_has_mathlib_dependency_without_mathlib(tmp_path):
    """Test when manifest exists but mathlib is not listed."""
    manifest_path = tmp_path / "lake-manifest.json"
    manifest_path.write_text('{"packages": [{"name": "batteries"}]}')
    assert has_mathlib_dependency(tmp_path) is False
