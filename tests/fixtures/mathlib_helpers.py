"""Mathlib file utilities for tests."""

import os
import random
from typing import List

from .project_setup import TEST_ENV_DIR


# Fast-loading mathlib files for tests
FAST_MATHLIB_FILES = [
    ".lake/packages/mathlib/Mathlib/Combinatorics/Quiver/Subquiver.lean",  # 1.13s
    ".lake/packages/mathlib/Mathlib/Combinatorics/Quiver/Push.lean",  # 1.19s
    ".lake/packages/mathlib/Mathlib/Algebra/Order/Ring/Synonym.lean",  # 1.19s
    ".lake/packages/mathlib/Mathlib/Algebra/Order/Monoid/ToMulBot.lean",  # 1.20s
    ".lake/packages/mathlib/Mathlib/Tactic/Find.lean",  # 1.20s
    ".lake/packages/mathlib/Mathlib/Algebra/Ring/Subring/Units.lean",  # 1.23s
    ".lake/packages/mathlib/Mathlib/Algebra/Module/Opposite.lean",  # 1.26s
    ".lake/packages/mathlib/Mathlib/Algebra/Group/Action/TypeTags.lean",  # 1.30s
    ".lake/packages/mathlib/Mathlib/Order/Monotone/Odd.lean",  # 1.33s
    ".lake/packages/mathlib/Mathlib/GroupTheory/Congruence/Opposite.lean",  # 1.33s
    ".lake/packages/mathlib/Mathlib/Data/Subtype.lean",  # 1.38s
    ".lake/packages/mathlib/Mathlib/Dynamics/FixedPoints/Topology.lean",  # 1.39s
    ".lake/packages/mathlib/Mathlib/Tactic/FunProp/ToBatteries.lean",  # 1.43s
    ".lake/packages/mathlib/Mathlib/RingTheory/TwoSidedIdeal/BigOperators.lean",  # 1.44s
    ".lake/packages/mathlib/Mathlib/Algebra/Field/Defs.lean",  # 1.44s
    ".lake/packages/mathlib/Mathlib/MeasureTheory/MeasurableSpace/Instances.lean",  # 1.45s
    ".lake/packages/mathlib/Mathlib/Algebra/Order/Group/OrderIso.lean",  # 1.55s
    ".lake/packages/mathlib/Mathlib/Topology/Category/CompHausLike/EffectiveEpi.lean",  # 1.62s
    ".lake/packages/mathlib/Mathlib/Data/ZMod/Factorial.lean",  # 1.63s
    ".lake/packages/mathlib/Mathlib/Data/BitVec.lean",  # 1.63s
    ".lake/packages/mathlib/Mathlib/Algebra/Divisibility/Basic.lean",  # 1.67s
    ".lake/packages/mathlib/Mathlib/Algebra/GroupWithZero/Divisibility.lean",  # 1.73s
    ".lake/packages/mathlib/Mathlib/SetTheory/Ordinal/CantorNormalForm.lean",  # 1.73s
    ".lake/packages/mathlib/Mathlib/Data/List/Defs.lean",  # 1.74s
    ".lake/packages/mathlib/Mathlib/NumberTheory/LucasPrimality.lean",  # 1.82s
    ".lake/packages/mathlib/Mathlib/RingTheory/Polynomial/Tower.lean",  # 1.88s
    ".lake/packages/mathlib/Mathlib/LinearAlgebra/Matrix/FixedDetMatrices.lean",  # 1.88s
    ".lake/packages/mathlib/Mathlib/MeasureTheory/Function/SpecialFunctions/Arctan.lean",  # 1.91s
    ".lake/packages/mathlib/Mathlib/ModelTheory/Bundled.lean",  # 1.99s
    ".lake/packages/mathlib/Mathlib/Data/Finset/SDiff.lean",  # 2.07s
    ".lake/packages/mathlib/Mathlib/Topology/Category/CompactlyGenerated.lean",  # 2.07s
    ".lake/packages/mathlib/Mathlib/Combinatorics/SetFamily/Shatter.lean",  # 2.10s
]


def get_all_mathlib_files() -> List[str]:
    """Get all mathlib files in the test environment.

    Returns:
        List[str]: List of relative paths to mathlib files.
    """
    file_paths = []
    base_path_len = len(TEST_ENV_DIR)
    path = TEST_ENV_DIR + ".lake/packages/mathlib/Mathlib"

    if not os.path.exists(path):
        return []

    for root, __, files in os.walk(path):
        file_paths += [
            root[base_path_len:] + "/" + f for f in files if f.endswith(".lean")
        ]
    return file_paths


def get_random_mathlib_files(num: int, seed: int = None) -> List[str]:
    """Get random mathlib files.

    Args:
        num: Number of files to return.
        seed: Random seed for reproducibility.

    Returns:
        List[str]: List of random mathlib file paths.
    """
    all_files = get_all_mathlib_files()
    if seed is not None:
        all_files = sorted(all_files)
        random.seed(seed)
    else:
        random.seed()
    random.shuffle(all_files)
    return all_files[:num]


def get_random_fast_mathlib_files(num: int, seed: int = None) -> List[str]:
    """Get random fast-loading mathlib files.

    Args:
        num: Number of files to return.
        seed: Random seed for reproducibility.

    Returns:
        List[str]: List of random fast mathlib file paths.
    """
    if seed is not None:
        random.seed(seed)
    else:
        random.seed()
    return random.sample(FAST_MATHLIB_FILES, num)
