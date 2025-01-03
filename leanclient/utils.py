import os
import sys
import cProfile


def find_lean_files_recursively(abs_path: str) -> list[str]:
    uris = []
    for root, __, files in os.walk(abs_path):
        for file in files:
            if file.endswith(".lean"):
                uris.append("file://" + os.path.join(root, file))
    return uris


class SemanticTokenProcessor:
    def __init__(self, token_legend: dict):
        self.token_types = token_legend["tokenTypes"]
        self.token_modifiers = token_legend["tokenModifiers"]
        self.num_token_modifiers = len(token_legend["tokenModifiers"])

    def __call__(self, raw_response: list[int]) -> list:
        return self._process_semantic_tokens(raw_response)

    def _process_semantic_tokens(self, raw_response: list[int]) -> list:
        """Semantic token response is converted using the token_legend

        This function is a reverse translation of:
        https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#semanticTokens_fullRequest
        """
        tokens = []
        prev_line = 0
        prev_start_char = 0
        for i in range(0, len(raw_response), 5):
            delta_line = raw_response[i]
            delta_start_char = raw_response[i + 1]
            length = raw_response[i + 2]
            token_type = raw_response[i + 3]
            token_modifiers = raw_response[i + 4]

            line = prev_line + delta_line
            start_char = (
                prev_start_char + delta_start_char
                if delta_line == 0
                else delta_start_char
            )

            token_modifiers_list = [
                self.token_modifiers[j]
                for j in range(self.num_token_modifiers)
                if token_modifiers & (1 << j)
            ]

            tokens.append(
                [
                    line,
                    start_char,
                    length,
                    self.token_types[token_type],
                    token_modifiers_list,
                ]
            )

            prev_line = line
            prev_start_char = start_char

        return tokens


# Profiling
def start_profiler() -> cProfile.Profile:
    sys.setrecursionlimit(10000)
    profiler = cProfile.Profile()
    profiler.enable()
    return profiler


def stop_profiler(profiler: cProfile.Profile, out_path: str = "profile.png"):
    profiler.disable()
    profiler.dump_stats("p.prof")
    cmd = f"gprof2dot -f pstats p.prof -n 0.005 -e 0.001 | dot -Tpng -o {out_path}"
    os.system(cmd)
    os.remove("p.prof")
