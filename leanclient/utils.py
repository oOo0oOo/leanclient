# Varia to be sorted later...
from typing import NamedTuple


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
