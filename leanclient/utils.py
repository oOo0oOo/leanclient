# Varia to be sorted later...
from typing import NamedTuple


class DocumentContentChange(NamedTuple):
    text: str
    start: list[int]
    end: list[int]

    def get_dict(self) -> dict:
        return {
            "text": self.text,
            "range": {
                "start": {"line": self.start[0], "character": self.start[1]},
                "end": {"line": self.end[0], "character": self.end[1]},
            },
        }


class SemanticTokenProcessor:
    def __init__(self, token_types: list[str]):
        self.token_types = token_types

    def __call__(self, raw_response: list[int]) -> list:
        return self._process_semantic_tokens(raw_response)

    def _process_semantic_tokens(self, raw_response: list[int]) -> list:
        """Semantic token response is converted using the token_legend

        This function is a reverse translation of:
        https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#semanticTokens_fullRequest

        NOTE: Token modifiers are ignored (speed gains). They are not used in lean core. See here:
        https://github.com/leanprover/lean4/blob/10b2f6b27e79e2c38d4d613f18ead3323a58ba4b/src/Lean/Data/Lsp/LanguageFeatures.lean#L360
        """
        tokens = []
        line = char = 0
        it = iter(raw_response)
        types = self.token_types
        for d_line, d_char, length, token, __ in zip(it, it, it, it, it):
            line += d_line
            char = char + d_char if d_line == 0 else d_char
            tokens.append([line, char, length, types[token]])
        return tokens
