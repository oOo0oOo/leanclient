# Varia to be sorted later...
from functools import wraps
from typing import NamedTuple


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


class DocumentContentChange(NamedTuple):
    """Represents a change in a document.

    Class attributes:

    - text (str): The new text to insert.
    - start (list[int]): The start position of the change: [line, character]
    - end (list[int]): The end position of the change: [line, character]
    """

    text: str
    start: list[int]
    end: list[int]

    def get_dict(self) -> dict:
        """Get dictionary representation of the change.

        Returns:
            dict: The change as an lsp dict.
        """
        return {
            "text": self.text,
            "range": {
                "start": {"line": self.start[0], "character": self.start[1]},
                "end": {"line": self.end[0], "character": self.end[1]},
            },
        }


def apply_changes_to_text(text: str, changes: list[DocumentContentChange]) -> str:
    """Apply changes to a text."""
    for change in changes:
        start = get_index_from_line_character(text, *change.start)
        end = get_index_from_line_character(text, *change.end)
        text = text[:start] + change.text + text[end:]
    return text


def get_index_from_line_character(text: str, line: int, char: int) -> int:
    """Convert line and character to flat index."""
    lines = text.split("\n")
    return sum(len(lines[i]) + 1 for i in range(line)) + char


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


def experimental(func):
    """Decorator to mark a method as experimental."""

    @wraps(func)
    def wrapper(self, *args, **kwargs):
        if self.print_warnings:
            print(
                f"Warning: {func.__name__}() is experimental! Set print_warnings=False to mute."
            )
        return func(self, *args, **kwargs)

    # Change __doc__ to include a sphinx warning
    warning = "\n        .. admonition:: Experimental\n\n            This method is experimental. Use with caution.\n"
    doc_lines = wrapper.__doc__.split("\n")
    doc_lines.insert(1, warning)
    wrapper.__doc__ = "\n".join(doc_lines)
    return wrapper
