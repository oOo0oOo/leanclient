import os
import subprocess
import cProfile


def find_lean_files_recursively(abs_path: str) -> list[str]:
    uris = []
    for root, __, files in os.walk(abs_path):
        for file in files:
            if file.endswith(".lean"):
                uris.append("file://" + os.path.join(root, file))
    return uris


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


# Profiling. This requires `gprof2dot` and `dot` to be installed.
def start_profiler() -> cProfile.Profile:
    profiler = cProfile.Profile()
    profiler.enable()
    return profiler


def stop_profiler(profiler: cProfile.Profile, out_path: str = "profile.png"):
    profiler.disable()
    profiler.dump_stats("p.prof")
    cmd = f"gprof2dot -f pstats p.prof -n 0.005 -e 0.001 | dot -Tpng -o {out_path}"
    try:
        subprocess.run(cmd, shell=True, check=True)
    except subprocess.CalledProcessError:
        print("gprof2dot or dot is not installed. Skipping profile visualization.")
    os.remove("p.prof")
