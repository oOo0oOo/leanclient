"""Regression tests for diagnostics bugs found in real-world usage.

Bug 1: get_diagnostics could return empty diagnostics if diagnostics_version < 0 wasn't checked
Bug 2: is_line_range_complete returned True for newly opened files with empty current_processing
Bug 3: Short inactivity_timeout causes premature return before diagnostics arrive (Issue #62)
Bug 4: Kernel errors take longer to compute, missed with short timeout (Issue #63)
"""

import pytest
import time


def _create_test_file(test_env_dir, filename, content):
    """Helper to create test file."""
    with open(test_env_dir + filename, "w") as f:
        f.write(content)


def _has_errors(diagnostics):
    """Check if diagnostics contain errors."""
    return any(d.get("severity") == 1 for d in diagnostics)


def _has_kernel_error(diagnostics):
    """Check if diagnostics contain kernel error."""
    return any(
        "kernel" in d.get("message", "").lower() or 
        "unsafe declaration" in d.get("message", "").lower()
        for d in diagnostics if d.get("severity") == 1
    )


@pytest.mark.integration
def test_diagnostics_version_checked_in_wait_logic(clean_lsp_client, test_file_path):
    """Newly opened files should have diagnostics_version=-1 and wait for diagnostics."""
    assert test_file_path not in clean_lsp_client.opened_files

    clean_lsp_client.open_file(test_file_path)
    state = clean_lsp_client.opened_files[test_file_path]

    assert state.diagnostics_version == -1
    assert not state.complete

    diagnostics = clean_lsp_client.get_diagnostics(
        test_file_path, inactivity_timeout=10.0
    )

    state = clean_lsp_client.opened_files[test_file_path]
    assert state.diagnostics_version >= 0
    assert len(diagnostics) > 0


@pytest.mark.integration
def test_is_line_range_complete_checks_diagnostics_version(
    clean_lsp_client, test_env_dir
):
    """is_line_range_complete should return False for files without diagnostics yet."""
    test_file = "LineRangeTest.lean"
    with open(test_env_dir + test_file, "w") as f:
        f.write("theorem test : 1 = 1 := by rfl\n")

    clean_lsp_client.open_file(test_file)
    state = clean_lsp_client.opened_files[test_file]

    assert state.diagnostics_version == -1
    assert not state.is_line_range_complete(0, 10)

    clean_lsp_client.get_diagnostics(test_file, inactivity_timeout=10.0)

    assert state.is_line_range_complete(0, 10)

    clean_lsp_client.close_files([test_file])


@pytest.mark.integration
def test_fresh_file_with_line_range(clean_lsp_client, test_env_dir):
    """get_diagnostics with line range should wait on freshly opened files."""
    test_file = "RangeTest.lean"
    test_content = """
-- Line 1
-- Line 2
-- Line 3
-- Line 4
theorem test : 1 = 2 := by sorry  -- Line 5, has error
-- Line 6
"""
    with open(test_env_dir + test_file, "w") as f:
        f.write(test_content)

    assert test_file not in clean_lsp_client.opened_files

    start_time = time.time()
    diagnostics = clean_lsp_client.get_diagnostics(
        test_file, start_line=3, end_line=7, inactivity_timeout=10.0
    )
    elapsed = time.time() - start_time

    assert elapsed > 0.01, f"Returned too quickly ({elapsed:.3f}s)"
    assert len(diagnostics) > 0

    clean_lsp_client.close_files([test_file])


@pytest.mark.integration
def test_open_then_immediate_get_diagnostics_no_sleep(clean_lsp_client, test_env_dir):
    """open_file() + immediate get_diagnostics() should work without manual sleep."""
    test_file = "ImmediateTest.lean"
    with open(test_env_dir + test_file, "w") as f:
        f.write("theorem broken : 1 = 2 := by\n  sorry\n")

    clean_lsp_client.open_file(test_file)
    diagnostics = clean_lsp_client.get_diagnostics(test_file, inactivity_timeout=10.0)

    assert len(diagnostics) > 0
    assert any("sorry" in d.get("message", "").lower() for d in diagnostics)

    clean_lsp_client.close_files([test_file])


@pytest.mark.integration
def test_line_range_partial_file_processing(clean_lsp_client, test_env_dir):
    """Line range filtering should work correctly across different ranges."""
    test_file = "PartialTest.lean"
    test_content = """
-- Line 0
theorem early : 1 = 2 := by sorry  -- Line 1

-- Some space

-- Line 5
theorem middle : 1 = 2 := by sorry  -- Line 6

-- More space

-- Line 10
theorem late : 1 = 2 := by sorry  -- Line 11
"""
    with open(test_env_dir + test_file, "w") as f:
        f.write(test_content)

    clean_lsp_client.open_file(test_file)
    all_diags = clean_lsp_client.get_diagnostics(test_file, inactivity_timeout=10.0)

    early_diags = clean_lsp_client.get_diagnostics(test_file, start_line=0, end_line=3)
    middle_diags = clean_lsp_client.get_diagnostics(test_file, start_line=4, end_line=8)
    late_diags = clean_lsp_client.get_diagnostics(test_file, start_line=9, end_line=12)

    assert len(early_diags) >= 1
    assert len(middle_diags) >= 1
    assert len(late_diags) >= 1

    total_filtered = len(early_diags) + len(middle_diags) + len(late_diags)
    assert total_filtered == len(all_diags)

    clean_lsp_client.close_files([test_file])


@pytest.mark.integration
def test_diagnostics_version_tracking(clean_lsp_client, test_file_path):
    """diagnostics_version should be -1 initially and >= 0 after diagnostics arrive."""
    clean_lsp_client.open_file(test_file_path)
    clean_lsp_client.get_diagnostics(test_file_path, inactivity_timeout=10.0)

    state = clean_lsp_client.opened_files[test_file_path]
    assert state.diagnostics_version >= 0
    assert len(state.diagnostics) > 0


@pytest.mark.integration
def test_empty_file_returns_quickly(clean_lsp_client, test_env_dir):
    """Clean files should still return quickly with the fix."""
    test_file = "CleanFile.lean"
    with open(test_env_dir + test_file, "w") as f:
        f.write("-- Just a comment\n-- Another comment\n")

    start_time = time.time()
    diagnostics = clean_lsp_client.get_diagnostics(test_file, inactivity_timeout=5.0)
    elapsed = time.time() - start_time

    assert elapsed < 2.0, f"Clean file took too long: {elapsed:.3f}s"
    assert diagnostics == []

    clean_lsp_client.close_files([test_file])


@pytest.mark.integration
def test_get_diagnostics_idempotent(clean_lsp_client, test_file_path):
    """Repeated get_diagnostics calls should return cached results immediately."""
    diag1 = clean_lsp_client.get_diagnostics(test_file_path, inactivity_timeout=10.0)

    start_time = time.time()
    diag2 = clean_lsp_client.get_diagnostics(test_file_path, inactivity_timeout=10.0)
    elapsed = time.time() - start_time

    assert elapsed < 0.01, f"Cached diagnostics took too long: {elapsed:.3f}s"
    assert diag1 == diag2


@pytest.mark.integration
def test_open_ended_range_start_only(clean_lsp_client, test_env_dir):
    """start_line without end_line should filter from start_line to end of file."""
    test_file = "OpenEndedStart.lean"
    test_content = """
-- Line 0
theorem early : 1 = 2 := by sorry  -- Line 1
-- Line 2
-- Line 3
-- Line 4
theorem late : 1 = 2 := by sorry  -- Line 5
-- Line 6
"""
    with open(test_env_dir + test_file, "w") as f:
        f.write(test_content)

    clean_lsp_client.open_file(test_file)
    all_diags = clean_lsp_client.get_diagnostics(test_file, inactivity_timeout=10.0)

    # Get diagnostics from line 4 to end (should only include line 5)
    from_line_4 = clean_lsp_client.get_diagnostics(test_file, start_line=4)

    # Should have fewer diagnostics than full file
    assert len(from_line_4) < len(all_diags)
    # Should have at least the error on line 5
    assert len(from_line_4) >= 1

    clean_lsp_client.close_files([test_file])


@pytest.mark.integration
def test_open_ended_range_end_only(clean_lsp_client, test_env_dir):
    """end_line without start_line should filter from beginning to end_line."""
    test_file = "OpenEndedEnd.lean"
    test_content = """
-- Line 0
theorem early : 1 = 2 := by sorry  -- Line 1
-- Line 2
-- Line 3
-- Line 4
theorem late : 1 = 2 := by sorry  -- Line 5
-- Line 6
"""
    with open(test_env_dir + test_file, "w") as f:
        f.write(test_content)

    clean_lsp_client.open_file(test_file)
    all_diags = clean_lsp_client.get_diagnostics(test_file, inactivity_timeout=10.0)

    # Get diagnostics from beginning to line 3 (should only include line 1)
    to_line_3 = clean_lsp_client.get_diagnostics(test_file, end_line=3)

    # Should have fewer diagnostics than full file
    assert len(to_line_3) < len(all_diags)
    # Should have at least the error on line 1
    assert len(to_line_3) >= 1

    clean_lsp_client.close_files([test_file])


@pytest.mark.integration
def test_wait_for_diagnostics_race_condition(clean_lsp_client, test_env_dir):
    """Race: waitForDiagnostics completes before publishDiagnostics arrives."""
    import time

    test_file = "RaceTest.lean"
    with open(test_env_dir + test_file, "w") as f:
        f.write("theorem test : 1 = 2 := by sorry\n")

    original_handler = clean_lsp_client._notification_handlers[
        "textDocument/publishDiagnostics"
    ]

    def delayed_handler(msg):
        time.sleep(0.05)
        original_handler(msg)

    clean_lsp_client._notification_handlers["textDocument/publishDiagnostics"] = (
        delayed_handler
    )

    try:
        clean_lsp_client.open_file(test_file)
        diags = clean_lsp_client.get_diagnostics(test_file, inactivity_timeout=1.0)
        state = clean_lsp_client.opened_files[test_file]

        assert state.diagnostics_version >= 0
        assert len(diags) > 0
    finally:
        clean_lsp_client._notification_handlers["textDocument/publishDiagnostics"] = (
            original_handler
        )
        if test_file in clean_lsp_client.opened_files:
            clean_lsp_client.close_files([test_file])


@pytest.mark.integration  
def test_lean_4_22_prebuilt_diagnostics():
    """Lean 4.22 LSP bug: publishDiagnostics sends empty array for pre-built files."""
    from leanclient import LeanLSPClient
    from tests.fixtures.project_setup import TEST_ENV_DIR
    import subprocess
    
    test_file = "LeanTestProject/Clean.lean"
    subprocess.run(["lake", "build", "LeanTestProject.Clean"], cwd=TEST_ENV_DIR,
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    client = LeanLSPClient(TEST_ENV_DIR, initial_build=False, prevent_cache_get=True)
    try:
        diags = client.get_diagnostics(test_file, inactivity_timeout=3.0)
        assert len(diags) > 0, "Lean 4.22 sends empty publishDiagnostics for pre-built files"
    finally:
        client.close()


# ============================================================================
# Timeout and timing regression tests
# ============================================================================


@pytest.mark.integration
@pytest.mark.xfail(reason="Known issue #62: Short timeouts miss errors during slow imports. Fixed with default 15s timeout.")
def test_insufficient_timeout_with_slow_imports(clean_lsp_client, test_env_dir):
    """Regression test for #62: Short timeout returns before errors arrive.
    
    https://github.com/oOo0oOo/lean-lsp-mcp/issues/62
    Demonstrates that extremely short timeouts (0.5s) can miss errors.
    Default timeout (15s) now handles this correctly.
    """
    test_file = "SlowImports.lean"
    _create_test_file(test_env_dir, test_file, """import Mathlib.Data.Real.Basic

theorem broken : (1 : ℝ) = 2 := by rfl
""")
    
    try:
        diags_short = clean_lsp_client.get_diagnostics(test_file, inactivity_timeout=0.5)
        # With unreasonably short timeout, errors may be missed
        assert _has_errors(diags_short), "Short timeout should still find errors (will fail, documenting the issue)"
    finally:
        if test_file in clean_lsp_client.opened_files:
            clean_lsp_client.close_files([test_file])


@pytest.mark.integration
@pytest.mark.xfail(reason="Known issue #62: Race condition with delayed publishDiagnostics. Mitigated by longer default timeout.")
def test_publishDiagnostics_delay_race_condition(clean_lsp_client, test_env_dir):
    """Regression test for #62: Race between waitForDiagnostics and publishDiagnostics.
    
    https://github.com/oOo0oOo/lean-lsp-mcp/issues/62
    Artificially delays notifications to trigger race condition.
    """
    test_file = "DelayedNotification.lean"
    _create_test_file(test_env_dir, test_file, "theorem broken : 1 = 2 := by rfl\n")
    
    original = clean_lsp_client._notification_handlers.get("textDocument/publishDiagnostics")
    
    def delayed_handler(msg):
        time.sleep(1.0)
        if original:
            original(msg)
    
    try:
        clean_lsp_client._register_notification_handler("textDocument/publishDiagnostics", delayed_handler)
        diags = clean_lsp_client.get_diagnostics(test_file, inactivity_timeout=0.3)
        assert _has_errors(diags), "Should find errors even with delayed notifications"
    finally:
        if original:
            clean_lsp_client._register_notification_handler("textDocument/publishDiagnostics", original)
        if test_file in clean_lsp_client.opened_files:
            clean_lsp_client.close_files([test_file])


@pytest.mark.integration
@pytest.mark.xfail(reason="Known issue #62: Dependency builds can delay diagnostics beyond short timeouts. Fixed with default 15s timeout.")
def test_dependency_build_timing(clean_lsp_client, test_env_dir):
    """Regression test for #62: Dependency building delays diagnostic availability.
    
    https://github.com/oOo0oOo/lean-lsp-mcp/issues/62
    """
    test_file = "DependencyBuild.lean"
    _create_test_file(test_env_dir, test_file, """import Mathlib.Data.Finset.Basic

theorem broken : Finset.card ∅ = 1 := by rfl
""")
    
    try:
        diags_short = clean_lsp_client.get_diagnostics(test_file, inactivity_timeout=0.5)
        assert _has_errors(diags_short), "Short timeout may miss errors during dependency builds"
    finally:
        if test_file in clean_lsp_client.opened_files:
            clean_lsp_client.close_files([test_file])


@pytest.mark.integration
@pytest.mark.xfail(reason="Known issue #63: Kernel errors take longer to compute. Fixed with default 15s timeout and improved activity tracking.")
def test_kernel_errors_slower_than_normal_errors(clean_lsp_client, test_env_dir):
    """Regression test for #63: Kernel errors take longer to compute/report.
    
    https://github.com/oOo0oOo/lean-lsp-mcp/issues/63
    """
    test_file = "KernelError.lean"
    _create_test_file(test_env_dir, test_file, """import Mathlib.Data.Real.Basic

structure test where
  x : ℝ
  deriving Repr

lemma test_lemma : False := by rfl
""")
    
    try:
        diags_short = clean_lsp_client.get_diagnostics(test_file, inactivity_timeout=0.5)
        assert _has_kernel_error(diags_short), "Short timeout may miss kernel errors"
    finally:
        if test_file in clean_lsp_client.opened_files:
            clean_lsp_client.close_files([test_file])


@pytest.mark.integration
def test_kernel_error_works_with_prior_error(clean_lsp_client, test_env_dir):
    """Control test: kernel errors are reported when there's a previous error."""
    test_file = "KernelWithPrior.lean"
    _create_test_file(test_env_dir, test_file, """import Mathlib.Data.Real.Basic

lemma first_error : False := by rfl

structure test where
  x : ℝ
  deriving Repr
""")
    
    try:
        diags = clean_lsp_client.get_diagnostics(test_file, inactivity_timeout=10.0)
        
        # Should have both errors
        assert _has_errors(diags), "Should have errors"
        assert _has_kernel_error(diags), f"Should have kernel error even with prior error: {diags}"
    finally:
        if test_file in clean_lsp_client.opened_files:
            clean_lsp_client.close_files([test_file])


@pytest.mark.integration
@pytest.mark.xfail(reason="Known issue #63: Multiple kernel errors timing. Fixed with default 15s timeout.")
def test_multiple_kernel_errors_timing(clean_lsp_client, test_env_dir):
    """Regression test for #63: Multiple kernel errors all require sufficient timeout.
    
    https://github.com/oOo0oOo/lean-lsp-mcp/issues/63
    """
    test_file = "MultipleKernel.lean"
    _create_test_file(test_env_dir, test_file, """import Mathlib.Data.Real.Basic
import Mathlib.Data.Complex.Basic

structure First where
  x : ℝ
  deriving Repr

structure Second where
  z : ℂ
  deriving Repr
""")
    
    try:
        diags = clean_lsp_client.get_diagnostics(test_file, inactivity_timeout=0.5)
        kernel_count = sum(1 for d in diags if _has_kernel_error([d]))
        assert kernel_count >= 2, f"Short timeout may miss some kernel errors, found {kernel_count}"
    finally:
        if test_file in clean_lsp_client.opened_files:
            clean_lsp_client.close_files([test_file])


@pytest.mark.integration
@pytest.mark.xfail(reason="Known issue #63: Immediate queries with short timeout miss kernel errors. Fixed with default 15s timeout.")
def test_immediate_query_after_open(clean_lsp_client, test_env_dir):
    """Regression test for #63: Immediate query timing with kernel errors.
    
    https://github.com/oOo0oOo/lean-lsp-mcp/issues/63
    """
    test_file = "ImmediateQuery.lean"
    _create_test_file(test_env_dir, test_file, """import Mathlib.Data.Real.Basic

structure test where
  x : ℝ
  deriving Repr
""")
    
    try:
        clean_lsp_client.open_file(test_file)
        time.sleep(0.05)
        diags = clean_lsp_client.get_diagnostics(test_file, inactivity_timeout=0.3)
        assert _has_kernel_error(diags), "Immediate query with short timeout may miss kernel errors"
    finally:
        if test_file in clean_lsp_client.opened_files:
            clean_lsp_client.close_files([test_file])

