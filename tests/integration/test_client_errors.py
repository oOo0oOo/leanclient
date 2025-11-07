"""Integration tests for LeanLSPClient error handling."""

import os

import pytest
import orjson

from leanclient import LeanLSPClient
from leanclient.utils import DocumentContentChange


# Expected diagnostic messages
EXP_DIAGNOSTIC_ERRORS = [
    "❌️ Docstring on `#guard_msgs` does not match generated message:\n\n- info: 2\n+ info: 1\n",
    "unexpected end of input; expected ':'",
]

EXP_DIAGNOSTIC_WARNINGS = ["declaration uses 'sorry'", "declaration uses 'sorry'"]


# ============================================================================
# Diagnostics tests
# ============================================================================


@pytest.mark.integration
def test_open_diagnostics(clean_lsp_client, test_file_path):
    """Test getting diagnostics when opening file."""
    clean_lsp_client.open_file(test_file_path)
    diagnostics = clean_lsp_client.get_diagnostics(test_file_path)
    errors = [d["message"] for d in diagnostics if d["severity"] == 1]
    assert errors == EXP_DIAGNOSTIC_ERRORS

    warnings = [d["message"] for d in diagnostics if d["severity"] == 2]
    assert warnings == EXP_DIAGNOSTIC_WARNINGS


@pytest.mark.integration
def test_get_diagnostics(lsp_client, test_file_path):
    """Test getting diagnostics for file."""
    diag = lsp_client.get_diagnostics(test_file_path)
    errors = [d["message"] for d in diag if d["severity"] == 1]
    assert errors == EXP_DIAGNOSTIC_ERRORS

    warnings = [d["message"] for d in diag if d["severity"] == 2]
    assert warnings == EXP_DIAGNOSTIC_WARNINGS


@pytest.mark.integration
def test_inactivity_timeout_parameter(clean_lsp_client, test_file_path):
    """Test that inactivity_timeout parameter is accepted and works."""
    # Should complete successfully with sufficient timeout
    diag = clean_lsp_client.get_diagnostics(test_file_path, inactivity_timeout=5.0)
    assert len(diag) > 0
    assert any(d["severity"] == 1 for d in diag)  # Has errors

    # Test that parameter is properly passed (no TypeError)
    clean_lsp_client.close_files([test_file_path])
    diag2 = clean_lsp_client.get_diagnostics(test_file_path, inactivity_timeout=3.0)
    assert diag2 == diag  # Same file, same diagnostics


@pytest.mark.integration
@pytest.mark.slow
def test_non_terminating_waitForDiagnostics(clean_lsp_client, test_env_dir):
    """Test handling of files with unterminated comments."""
    # Create a file with an unterminated block comment
    content = "/- Unclosed comment"
    path = "BadFile.lean"
    with open(test_env_dir + path, "w") as f:
        f.write(content)

    try:
        clean_lsp_client.open_file(path)
        diag = clean_lsp_client.get_diagnostics(path)
        # Should get diagnostics for the unterminated comment
        assert len(diag) > 0
        assert diag[0]["message"] == "unterminated comment"

        clean_lsp_client.close_files([path])

        # Doc comments (/-!) with no closing
        content = "/-! Unterminated comment 2"
        with open(test_env_dir + path, "w") as f:
            f.write(content)

        clean_lsp_client.open_file(path)
        diag = clean_lsp_client.get_diagnostics(path)
        assert diag[0]["message"] == "unterminated comment"
    finally:
        if os.path.exists(test_env_dir + path):
            os.remove(test_env_dir + path)


@pytest.mark.integration
def test_add_comment_at_the_end(clean_lsp_client, test_file_path, test_env_dir):
    """Test updating file by adding comment at end."""
    # Add comment to end of test file
    with open(test_env_dir + test_file_path, "r") as f:
        content = f.readlines()

    end = len(content)
    change = DocumentContentChange(
        text="\n-- new comment at the end of the file", start=[end, 0], end=[end, 0]
    )
    clean_lsp_client.open_file(test_file_path)
    clean_lsp_client.update_file(test_file_path, [change])
    diag = clean_lsp_client.get_diagnostics(test_file_path)

    errors = [d["message"] for d in diag if d["severity"] == 1]
    assert errors == EXP_DIAGNOSTIC_ERRORS

    warnings = [d["message"] for d in diag if d["severity"] == 2]
    assert warnings == EXP_DIAGNOSTIC_WARNINGS


# ============================================================================
# RPC error tests
# ============================================================================


@pytest.mark.integration
def test_rpc_errors(clean_lsp_client, test_file_path):
    """Test various RPC error conditions."""
    # Invalid method
    resp = clean_lsp_client._send_request(test_file_path, "garbageMethod", {})
    exp = "No request handler found for 'garbageMethod'"
    assert resp["error"]["message"] == exp

    # Invalid params
    resp = clean_lsp_client._send_request(test_file_path, "textDocument/hover", {})
    resp = resp["error"]["message"]
    exp = "Cannot parse request params:"
    assert resp.startswith(exp)

    # Invalid params2
    resp = clean_lsp_client._send_request(
        test_file_path, "textDocument/hover", {"textDocument": {}}
    )
    resp = resp["error"]["message"]
    exp = 'Cannot parse request params: {"textDocument"'
    assert resp.startswith(exp)

    # Unopened file
    clean_lsp_client.close_files([test_file_path])
    uri = clean_lsp_client._local_to_uri(test_file_path)
    body = orjson.dumps(
        {
            "jsonrpc": "2.0",
            "method": "textDocument/hover",
            "params": {
                "textDocument": {"uri": uri},
                "position": {"line": 9, "character": 4},
            },
        }
    )
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    clean_lsp_client.stdin.write(header + body)
    clean_lsp_client.stdin.flush()
    # File is reopened automatically by get_diagnostics
    resp = clean_lsp_client.get_diagnostics(test_file_path)
    assert resp is not None  # File gets reopened, returns diagnostics


@pytest.mark.integration
def test_lake_error_invalid_rpc(clean_lsp_client, test_file_path):
    """Test lake error handling for invalid RPC."""
    uri = clean_lsp_client._local_to_uri(test_file_path)
    body = orjson.dumps({"jsonrpc": "2.0"})
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    clean_lsp_client.stdin.write(header + body)
    clean_lsp_client.stdin.flush()

    with pytest.raises(FileNotFoundError):
        clean_lsp_client._wait_for_diagnostics([uri])


@pytest.mark.integration
def test_lake_error_end_of_input(clean_lsp_client, test_file_path):
    """Test lake error handling for end of input."""
    uri = clean_lsp_client._local_to_uri(test_file_path)
    body = orjson.dumps({})
    header = f"Content-Length: {len(body) + 1}\r\n\r\n".encode("ascii")
    clean_lsp_client.stdin.write(header + body)
    clean_lsp_client.stdin.flush()

    with pytest.raises(FileNotFoundError):
        clean_lsp_client._wait_for_diagnostics([uri])


@pytest.mark.integration
def test_lake_error_content_length(clean_lsp_client, test_file_path):
    """Test lake error handling for invalid content length."""
    uri = clean_lsp_client._local_to_uri(test_file_path)
    request = {
        "jsonrpc": "2.0",
        "method": "textDocument/hover",
        "params": {
            "textDocument": {"uri": uri},
            "position": {"line": 9, "character": 4},
        },
    }
    body = orjson.dumps(request)
    header = "Content-Length: 3.14\r\n\r\n".encode("ascii")
    clean_lsp_client.stdin.write(header + body)
    clean_lsp_client.stdin.flush()

    with pytest.raises(FileNotFoundError):
        clean_lsp_client._wait_for_diagnostics(uri)


# ============================================================================
# Invalid path tests
# ============================================================================


@pytest.mark.integration
@pytest.mark.parametrize(
    "invalid_path",
    [
        "g.lean",
        "garbage",
        "g.txt",
        "fantasy/f.lean",
        "../e.lean",
        " ",
    ],
)
def test_invalid_path(clean_lsp_client, invalid_path, test_file_path):
    """Test various operations with invalid file paths."""

    # Random path for each method call
    def p():
        return invalid_path

    # Check all methods
    with pytest.raises(FileNotFoundError):
        clean_lsp_client._send_request(
            p(), "textDocument/hover", {"position": {"line": 9, "character": 4}}
        )

    with pytest.raises(FileNotFoundError):
        clean_lsp_client._open_new_files([p()])

    with pytest.raises(FileNotFoundError):
        clean_lsp_client.open_files([p()])

    with pytest.raises(FileNotFoundError):
        clean_lsp_client.open_file(p())

    with pytest.raises(FileNotFoundError):
        clean_lsp_client.update_file(p(), [])

    with pytest.raises(FileNotFoundError):
        clean_lsp_client.close_files([p()])

    with pytest.raises(FileNotFoundError):
        clean_lsp_client.get_diagnostics(p())

    # with pytest.raises(FileNotFoundError):
    #     clean_lsp_client.get_diagnostics_multi([p()])

    with pytest.raises(FileNotFoundError):
        clean_lsp_client.create_file_client(p())

    with pytest.raises(FileNotFoundError):
        clean_lsp_client.get_completions(p(), 9, 4)

    with pytest.raises(FileNotFoundError):
        clean_lsp_client.get_hover(p(), 9, 4)

    with pytest.raises(FileNotFoundError):
        clean_lsp_client.get_declarations(p(), 9, 4)

    with pytest.raises(FileNotFoundError):
        clean_lsp_client.get_definitions(p(), 9, 4)

    with pytest.raises(FileNotFoundError):
        clean_lsp_client.get_references(p(), 9, 4)

    with pytest.raises(FileNotFoundError):
        clean_lsp_client.get_type_definitions(p(), 9, 4)

    with pytest.raises(FileNotFoundError):
        clean_lsp_client.get_document_symbols(p())

    with pytest.raises(FileNotFoundError):
        clean_lsp_client.get_document_highlights(p(), 9, 4)

    with pytest.raises(FileNotFoundError):
        clean_lsp_client.get_semantic_tokens(p())

    with pytest.raises(FileNotFoundError):
        clean_lsp_client.get_semantic_tokens_range(p(), 0, 0, 10, 10)

    with pytest.raises(FileNotFoundError):
        clean_lsp_client.get_folding_ranges(p())

    with pytest.raises(FileNotFoundError):
        clean_lsp_client.get_goal(p(), 9, 4)

    with pytest.raises(FileNotFoundError):
        clean_lsp_client.get_term_goal(p(), 9, 4)


@pytest.mark.integration
@pytest.mark.parametrize(
    "path_with_spaces",
    [
        " " + "LeanTestProject/Basic.lean",
        "LeanTestProject/Basic.lean" + " ",
    ],
)
def test_invalid_path_with_spaces(clean_lsp_client, test_file_path, path_with_spaces):
    """Test paths with leading/trailing spaces raise errors."""
    with pytest.raises(FileNotFoundError):
        clean_lsp_client.open_file(path_with_spaces)


# ============================================================================
# Invalid root tests
# ============================================================================


@pytest.mark.unit
def test_invalid_root_not_found():
    """Test initialization with non-existent path."""
    with pytest.raises(FileNotFoundError):
        LeanLSPClient("invalid_path")


@pytest.mark.unit
def test_invalid_root_not_directory():
    """Test initialization with file instead of directory."""
    with pytest.raises(NotADirectoryError):
        LeanLSPClient("leanclient/client.py")


@pytest.mark.unit
def test_invalid_root_not_lean_project():
    """Test initialization with non-Lean project directory."""
    with pytest.raises(Exception):
        LeanLSPClient("leanclient/", initial_build=True)


# ============================================================================
# Invalid coordinates tests
# ============================================================================


@pytest.mark.integration
@pytest.mark.parametrize(
    "position",
    [
        {"line": -1, "character": 0},
        {"line": "0", "character": 0},
        {"line": 0, "character": 0.5},
        {"line": None, "character": 0},
    ],
)
def test_invalid_coordinates(lsp_client, random_fast_mathlib_files, position):
    """Test invalid position coordinates."""
    path = random_fast_mathlib_files(1, 42)[0]
    sfc = lsp_client.create_file_client(path)

    res = sfc.get_hover(**position)
    assert res["error"]["message"].startswith("Cannot parse request params")


@pytest.mark.integration
def test_invalid_coordinates_crashes_lake(test_project_dir, random_fast_mathlib_files):
    """Test that invalid coordinates can crash lake."""
    path = random_fast_mathlib_files(1, 42)[0]
    position = {"line": -1, "character": 0}

    lsp = LeanLSPClient(test_project_dir, prevent_cache_get=True)
    res = lsp.get_declarations(path, **position)
    assert "Cannot parse request params:" in res["error"]["message"]
    lsp.close()
