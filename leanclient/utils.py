# Varia to be sorted later...
from dataclasses import dataclass
from functools import wraps
from typing import Tuple
from pathlib import Path
import logging

import orjson

logger = logging.getLogger(__name__)

# Mapping SymbolKinds ints to string names:
# https://github.com/leanprover/lean4/blob/8422d936cff3b609bd2a1396e82356c82c383386/src/Lean/Data/Lsp/LanguageFeatures.lean#L202C1-L229C27
SYMBOL_KIND_MAP = {
    1: "file",
    2: "module",
    3: "namespace",
    4: "package",
    5: "class",
    6: "method",
    7: "property",
    8: "field",
    9: "constructor",
    10: "enum",
    11: "interface",
    12: "function",
    13: "variable",
    14: "constant",
    15: "string",
    16: "number",
    17: "boolean",
    18: "array",
    19: "object",
    20: "key",
    21: "null",
    22: "enumMember",
    23: "struct",
    24: "event",
    25: "operator",
    26: "typeParameter",
}


class SemanticTokenProcessor:
    """Converts semantic token response using a token legend.

    This function is a reverse translation of the LSP specification:
    `Semantic Tokens Full Request <https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#semanticTokens_fullRequest>`_

    Token modifiers are ignored for speed gains, since they are not used. See: `LanguageFeatures.lean <https://github.com/leanprover/lean4/blob/10b2f6b27e79e2c38d4d613f18ead3323a58ba4b/src/Lean/Data/Lsp/LanguageFeatures.lean#L360>`_
    """

    def __init__(self, token_types: list[str]):
        self.token_types = token_types

    def __call__(self, raw_response: list[int]) -> list:
        return self._process_semantic_tokens(raw_response)

    def _process_semantic_tokens(self, raw_response: list[int]) -> list:
        tokens = []
        line = char = 0
        it = iter(raw_response)
        types = self.token_types
        for d_line, d_char, length, token, __ in zip(it, it, it, it, it):
            line += d_line
            char = char + d_char if d_line == 0 else d_char
            tokens.append([line, char, length, types[token]])
        return tokens


def normalize_newlines(text: str) -> str:
    """Convert CRLF sequences to LF for stable indexing."""
    return text.replace("\r\n", "\n")


def _utf16_len(char: str) -> int:
    """Return the UTF-16 length of a single character (1 or 2 code units)."""
    code_point = ord(char)
    # Characters outside the BMP (Basic Multilingual Plane) need 2 UTF-16 code units (surrogate pairs)
    return 2 if code_point > 0xFFFF else 1


def _utf16_pos_to_utf8_pos(text: str, line: int, utf16_character: int) -> int:
    """
    Convert LSP position (line, UTF-16 character offset) to UTF-8 byte index.

    This matches the Lean LSP server implementation:
    - line is 0-indexed
    - character is a UTF-16 code unit offset
    - character is accepted liberally: actual character := min(line length, character)

    Args:
        text: The text content (UTF-8 encoded, with LF newlines)
        line: 0-indexed line number
        utf16_character: UTF-16 code unit offset within the line

    Returns:
        UTF-8 byte offset into text
    """
    if line < 0:
        return 0

    lines = text.split("\n")
    if line >= len(lines):
        return len(text)

    # Get byte offset to start of line
    line_start_byte = sum(len(lines[i]) + 1 for i in range(line))  # +1 for '\n'

    # Convert UTF-16 character offset to UTF-8 byte offset within the line
    line_content = lines[line]
    utf16_offset = 0
    utf8_offset = 0

    for char in line_content:
        if utf16_offset >= utf16_character:
            break
        utf16_offset += _utf16_len(char)
        utf8_offset += len(char.encode("utf-8"))

    return line_start_byte + utf8_offset


def _index_from_line_character(text: str, line: int, character: int) -> int:
    """
    Convert LSP position to UTF-8 byte index.

    Args:
        text: The text content
        line: 0-indexed line number
        character: UTF-16 code unit offset

    Returns:
        UTF-8 byte index
    """
    return _utf16_pos_to_utf8_pos(text, line, character)


@dataclass(frozen=True)
class DocumentContentChange:
    """Represents a change in a document."""

    text: str
    start: Tuple[int, int] | None = None
    end: Tuple[int, int] | None = None

    def __post_init__(self) -> None:
        normalized_text = normalize_newlines(self.text)
        object.__setattr__(self, "text", normalized_text)

        if (self.start is None) != (self.end is None):
            raise ValueError(
                "DocumentContentChange requires both start and end for ranged edits."
            )

        if self.start is not None:
            start = tuple(int(v) for v in self.start)
            if len(start) != 2:
                raise ValueError("start must be a (line, character) pair")
            object.__setattr__(self, "start", start)
        if self.end is not None:
            end = tuple(int(v) for v in self.end)
            if len(end) != 2:
                raise ValueError("end must be a (line, character) pair")
            object.__setattr__(self, "end", end)

    def is_full_change(self) -> bool:
        return self.start is None

    def get_dict(self) -> dict:
        if self.is_full_change():
            return {"text": self.text}

        assert self.start is not None and self.end is not None
        return {
            "text": self.text,
            "range": {
                "start": {"line": self.start[0], "character": self.start[1]},
                "end": {"line": self.end[0], "character": self.end[1]},
            },
        }


def apply_changes_to_text(text: str, changes: list[DocumentContentChange]) -> str:
    """Apply LSP-style incremental changes to ``text``."""

    text = normalize_newlines(text)
    if not changes:
        return text

    for change in changes:
        if change.is_full_change():
            text = change.text
            continue

        assert change.start is not None and change.end is not None
        start_idx = _index_from_line_character(text, change.start[0], change.start[1])
        end_idx = _index_from_line_character(text, change.end[0], change.end[1])
        text = text[:start_idx] + change.text + text[end_idx:]

    return text


def get_diagnostics_in_range(
    diagnostics: list,
    start_line: int,
    end_line: int,
) -> list:
    """Find overlapping diagnostics for a range of lines.

    Args:
        diagnostics (list): List of diagnostics.
        start_line (int): Start line.
        end_line (int): End line.

    Returns:
        list: Overlapping diagnostics.
    """
    return [
        diag
        for diag in diagnostics
        if diag["range"]["start"]["line"] <= end_line
        and diag["range"]["end"]["line"] >= start_line
    ]


def has_mathlib_dependency(project_path: str | Path) -> bool:
    """Check if the project has mathlib as a dependency.

    Args:
        project_path: Path to the Lean project root directory.

    Returns:
        bool: True if mathlib is found in lake-manifest.json.
    """
    manifest_path = Path(project_path) / "lake-manifest.json"
    if not manifest_path.exists():
        return False

    try:
        with open(manifest_path, "r") as f:
            manifest = orjson.loads(f.read())
        packages = manifest.get("packages", [])
        return any(pkg.get("name") == "mathlib" for pkg in packages)
    except Exception:
        return False


def experimental(func):
    """Decorator to mark a method as experimental."""

    @wraps(func)
    def wrapper(self, *args, **kwargs):
        logger.warning("%s() is experimental! Use with caution.", func.__name__)
        return func(self, *args, **kwargs)

    # Change __doc__ to include a sphinx warning
    warning = "\n        .. admonition:: Experimental\n\n            This method is experimental. Use with caution.\n            Warnings are logged via the 'leanclient' logger.\n"
    doc_lines = wrapper.__doc__.split("\n")
    doc_lines.insert(1, warning)
    wrapper.__doc__ = "\n".join(doc_lines)
    return wrapper
