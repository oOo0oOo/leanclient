import subprocess
import unittest
import sys
import shutil


# TEST CONFIG. Move?
TEST_ENV_DIR = ".test_env/"
TEST_PROJECT_NAME = "LeanTestProject"
TEST_FILE_PATH = f"{TEST_PROJECT_NAME}/Basic.lean"

FAST_MATHLIB_FILES = [
    ".lake/packages/mathlib/Mathlib/Combinatorics/Quiver/Subquiver.lean",  # 1.13s
    ".lake/packages/mathlib/Mathlib/Combinatorics/Quiver/Push.lean",  # 1.19s
    ".lake/packages/mathlib/Mathlib/Algebra/Order/Ring/Synonym.lean",  # 1.19s
    ".lake/packages/mathlib/Mathlib/Algebra/Order/Monoid/ToMulBot.lean",  # 1.20s
    ".lake/packages/mathlib/Mathlib/Tactic/Find.lean",  # 1.20s
    ".lake/packages/mathlib/Mathlib/Algebra/Ring/Subring/Units.lean",  # 1.23s
    ".lake/packages/mathlib/Mathlib/Algebra/Module/Opposite.lean",  # 1.26s
    ".lake/packages/mathlib/Mathlib/Algebra/PUnitInstances/GCDMonoid.lean",  # 1.26s
    ".lake/packages/mathlib/Mathlib/Algebra/Group/Action/TypeTags.lean",  # 1.30s
    ".lake/packages/mathlib/Mathlib/Order/Monotone/Odd.lean",  # 1.33s
    ".lake/packages/mathlib/Mathlib/GroupTheory/Congruence/Opposite.lean",  # 1.33s
    ".lake/packages/mathlib/Mathlib/Order/RelIso/Group.lean",  # 1.36s
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


if __name__ == "__main__":
    from tests.utils import start_profiler, stop_profiler

    # Setup environment
    cmd = [
        "python",
        "scripts/create_lean_project.py",
        TEST_ENV_DIR,
        TEST_PROJECT_NAME,
        "stable",
        "--use-mathlib",
    ]
    subprocess.run(cmd, check=True)

    # Copy the lean files required for testing
    target_dir = f"{TEST_ENV_DIR}{TEST_FILE_PATH}"
    shutil.copy("tests/tests.lean", target_dir)

    subprocess.run(["lake", "build"], cwd=TEST_ENV_DIR, check=True)

    # Collect tests
    white_list = [
        # "test_client_benchmark.TestLSPClientBenchmark.test_bench_all_functions",
        "test_base_client",
        "test_client_files",
        "test_client_requests",
        "test_client_requests_async",
        "test_client_errors",
        "test_single_file_client",
        "test_pool",
        "test_client_benchmark",
    ]

    if "--all" in sys.argv:
        white_list = []
    elif "--benchmark" in sys.argv:
        white_list = ["test_client_benchmark"]

    if not white_list:
        suite = unittest.TestLoader().discover("tests")
    else:
        suite = unittest.TestSuite()
        loader = unittest.TestLoader()
        for test in white_list:
            suite.addTests(loader.loadTestsFromName(test))
    runner = unittest.TextTestRunner()

    # Run tests
    profiler = None
    if "--profile" in sys.argv:
        profiler = start_profiler()

    runner.run(suite)

    if profiler:
        stop_profiler(profiler, "tests/profile.png")
