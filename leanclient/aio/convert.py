"""UTF-16 <-> codepoint position conversion.

LSP positions count UTF-16 code units; Python strings count codepoints.
Lean/Mathlib code is full of astral-plane characters (e.g. ``𝕜`` = 2 UTF-16
units, 1 codepoint), so the two disagree on real lines.

The public :class:`AsyncLeanLSPClient` API uses **codepoint columns**
everywhere; these helpers are applied once at the transport boundary.
"""

from __future__ import annotations


def codepoint_to_utf16(line: str, col: int) -> int:
    """Convert a codepoint column to a UTF-16 code-unit column on ``line``.

    ``col`` is clamped to ``len(line)``.
    """
    col = max(0, min(col, len(line)))
    if line.isascii():
        return col
    units = 0
    for ch in line[:col]:
        units += 2 if ord(ch) > 0xFFFF else 1
    return units


def utf16_to_codepoint(line: str, col: int) -> int:
    """Convert a UTF-16 code-unit column to a codepoint column on ``line``.

    Columns beyond the end of the line are clamped; a column landing inside a
    surrogate pair maps to that character's index.
    """
    if col <= 0:
        return 0
    if line.isascii():
        return min(col, len(line))
    units = 0
    for i, ch in enumerate(line):
        if units >= col:
            return i
        units += 2 if ord(ch) > 0xFFFF else 1
        if units > col:  # col lands inside this char's surrogate pair
            return i
    return len(line)


def position_to_utf16(text_lines: list[str], line: int, col: int) -> dict:
    """Build an LSP position (UTF-16) from 0-indexed line + codepoint column."""
    line_str = text_lines[line] if 0 <= line < len(text_lines) else ""
    return {"line": line, "character": codepoint_to_utf16(line_str, col)}


def position_from_utf16(text_lines: list[str], pos: dict) -> tuple[int, int]:
    """Convert an LSP position (UTF-16) to 0-indexed (line, codepoint column)."""
    line = pos.get("line", 0)
    line_str = text_lines[line] if 0 <= line < len(text_lines) else ""
    return line, utf16_to_codepoint(line_str, pos.get("character", 0))


def range_from_utf16(text_lines: list[str], rng: dict) -> dict:
    """Convert an LSP range's columns from UTF-16 to codepoints (0-indexed)."""
    sl, sc = position_from_utf16(text_lines, rng.get("start", {}))
    el, ec = position_from_utf16(text_lines, rng.get("end", {}))
    return {
        "start": {"line": sl, "character": sc},
        "end": {"line": el, "character": ec},
    }
