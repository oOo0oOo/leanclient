"""Integration test for applying all code actions in a file."""

import os
import shutil

import pytest


CODE_ACTION_FILE = "CodeActionDemo.lean"

# Expected replacements after applying all code actions
EXPECTED_REPLACEMENTS = {
    "simp?": "simp only",
    "exact?": "exact ",
    "/-- info: 2 -/ #guard_msgs": "/-- info: 3 -/",
    '/-- info: "hello" -/ #guard_msgs': '/-- info: "world" -/',
}


@pytest.mark.integration
def test_apply_all_code_actions(clean_lsp_client, test_env_dir):
    """Apply all code actions iteratively and verify the result.

    Uses CodeActionDemo.lean which contains simp?, exact?, and
    #guard_msgs mismatches that each produce a code action.
    """
    path = CODE_ACTION_FILE

    # Work on a copy so we don't mutate the shared test file
    src = os.path.join(test_env_dir, CODE_ACTION_FILE)
    assert os.path.exists(src), f"Missing test file: {src}"

    clean_lsp_client.get_diagnostics(path)
    original = clean_lsp_client.get_file_content(path)

    # Collect and apply all code actions iteratively
    applied = []
    for _ in range(20):  # safety cap
        diags = clean_lsp_client.get_diagnostics(path)
        found = False
        for d in diags:
            r = d["range"]
            actions = clean_lsp_client.get_code_actions(
                path,
                r["start"]["line"],
                r["start"]["character"],
                r["end"]["line"],
                r["end"]["character"],
            )
            if actions:
                action = actions[0]
                if "edit" not in action:
                    action = clean_lsp_client.get_code_action_resolve(action)
                clean_lsp_client.apply_code_action_resolve(action)
                applied.append(action["title"])
                found = True
                break
        if not found:
            break

    after = clean_lsp_client.get_file_content(path)

    # Verify code actions were applied
    assert len(applied) >= 8, (
        f"Expected >= 8 code actions, got {len(applied)}: {applied}"
    )

    # Verify specific replacements
    assert "simp?" not in after, "simp? should have been replaced"
    assert "exact?" not in after, "exact? should have been replaced"
    assert "simp only" in after, "simp only should be present"

    # Verify #guard_msgs fixes
    assert "/-- info: 3 -/" in after, "#guard_msgs for 1+1+1 should show 3"
    assert '/-- info: "world" -/' in after, '#guard_msgs for "world" should be fixed'

    # Verify file actually changed
    assert after != original

    # Verify the result is valid (no errors after applying all actions)
    final_diags = clean_lsp_client.get_diagnostics(path)
    errors = [d for d in final_diags if d.get("severity") == 1]
    assert len(errors) == 0, f"Unexpected errors after applying code actions: {errors}"


@pytest.mark.integration
def test_apply_code_actions_and_save(clean_lsp_client, test_env_dir):
    """Full MWE: apply code actions and save to disk."""
    path = CODE_ACTION_FILE
    backup = os.path.join(test_env_dir, CODE_ACTION_FILE + ".bak")
    real_file = os.path.join(test_env_dir, CODE_ACTION_FILE)

    # Backup the original
    shutil.copy2(real_file, backup)

    try:
        clean_lsp_client.get_diagnostics(path)

        # Apply all code actions
        for _ in range(20):
            diags = clean_lsp_client.get_diagnostics(path)
            found = False
            for d in diags:
                r = d["range"]
                actions = clean_lsp_client.get_code_actions(
                    path,
                    r["start"]["line"],
                    r["start"]["character"],
                    r["end"]["line"],
                    r["end"]["character"],
                )
                if actions:
                    action = actions[0]
                    if "edit" not in action:
                        action = clean_lsp_client.get_code_action_resolve(action)
                    clean_lsp_client.apply_code_action_resolve(action)
                    found = True
                    break
            if not found:
                break

        # Save to disk
        with open(real_file, "w") as f:
            f.write(clean_lsp_client.get_file_content(path))

        # Verify file on disk
        with open(real_file) as f:
            saved = f.read()

        assert "simp?" not in saved
        assert "exact?" not in saved
        assert "simp only" in saved

    finally:
        # Restore original
        shutil.move(backup, real_file)
