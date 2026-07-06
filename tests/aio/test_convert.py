"""Unit tests for UTF-16 <-> codepoint conversion (no server needed)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from leanclient.aio.convert import (  # noqa: E402
    codepoint_to_utf16,
    range_from_utf16,
    utf16_to_codepoint,
)

KLINE = "theorem uni {𝕜 : Type*} [Field 𝕜] (x : 𝕜) : x = x"


def test_ascii_identity():
    line = "def foo : Nat := 42"
    for col in range(len(line) + 2):
        assert codepoint_to_utf16(line, col) == min(col, len(line))
        assert utf16_to_codepoint(line, col) == min(col, len(line))


def test_astral_roundtrip():
    # 𝕜 (U+1D55C) is 2 UTF-16 units, 1 codepoint
    for cp_col in range(len(KLINE) + 1):
        u16 = codepoint_to_utf16(KLINE, cp_col)
        assert utf16_to_codepoint(KLINE, u16) == cp_col


def test_known_offsets():
    i = KLINE.index("(x") + 1  # codepoint index of the binder x
    # two 𝕜 before it -> +2 utf16 units
    assert codepoint_to_utf16(KLINE, i) == i + 2
    assert utf16_to_codepoint(KLINE, i + 2) == i


def test_bmp_unicode_is_one_unit():
    line = "abbrev n : ℕ := 42"  # ℕ is BMP: 1 unit, 1 codepoint
    assert codepoint_to_utf16(line, len(line)) == len(line)


def test_clamping():
    assert codepoint_to_utf16("ab", 99) == 2
    assert utf16_to_codepoint("ab", 99) == 2
    assert utf16_to_codepoint("ab", -1) == 0


def test_mid_surrogate_maps_to_char():
    line = "𝕜x"
    assert utf16_to_codepoint(line, 1) == 0  # inside the surrogate pair
    assert utf16_to_codepoint(line, 2) == 1


def test_range_from_utf16():
    lines = [KLINE]
    i = KLINE.index("(x") + 1
    rng = {
        "start": {"line": 0, "character": i + 2},
        "end": {"line": 0, "character": i + 3},
    }
    out = range_from_utf16(lines, rng)
    assert out["start"]["character"] == i
    assert out["end"]["character"] == i + 1


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"  [ok] {name}")
    print("convert tests passed")
