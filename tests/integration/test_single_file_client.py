"""Integration tests for SingleFileClient."""

import pytest

from leanclient import SingleFileClient, LeanLSPClient
from leanclient.utils import DocumentContentChange


@pytest.mark.integration
@pytest.mark.unimportant
def test_method_overlap():
    """Test that SingleFileClient has similar methods to LeanLSPClient."""
    method_client = dir(LeanLSPClient)
    method_single = dir(SingleFileClient)

    # Missing methods in single file client
    missing = [
        m for m in method_client if m not in method_single and not m.startswith("_")
    ]
    ok_missing = [
        "close",
        "close_files",
        "create_file_client",
        "open_files",
        "get_env",
    ]
    missing = set(missing) - set(ok_missing)
    assert not missing, f"Missing methods in SingleFileClient: {missing}"


@pytest.mark.integration
@pytest.mark.unimportant
def test_creation(lsp_client, test_file_path):
    """Test creating SingleFileClient instances."""
    # Instantiate a SingleFileClient
    sfc = SingleFileClient(lsp_client, test_file_path)
    assert sfc.file_path == test_file_path
    res = sfc.get_goal(9, 15)
    assert "⊢" in res["goals"][0]

    sfc.close_file(blocking=True)  # Just to test the method

    # Create from a client
    sfc2 = lsp_client.create_file_client(test_file_path)
    assert sfc2.file_path == test_file_path
    res2 = sfc.get_goal(9, 15)
    assert res == res2


@pytest.mark.integration
@pytest.mark.slow
def test_requests(lsp_client, test_file_path):
    """Test various request methods on SingleFileClient."""
    sfc = lsp_client.create_file_client(test_file_path)
    res = []
    res.append(sfc.get_completions(9, 15))
    res.append(sfc.get_completion_item_resolve(res[0][0]))
    res.append(sfc.get_hover(4, 4))
    res.append(sfc.get_declarations(6, 4))
    res.append(sfc.get_definitions(1, 29))
    res.append(sfc.get_references(9, 24))
    res.append(sfc.get_type_definitions(1, 36))
    res.append(sfc.get_document_symbols())
    res.append(sfc.get_document_highlights(9, 8))
    res.append(sfc.get_semantic_tokens())
    res.append(sfc.get_semantic_tokens_range(0, 0, 10, 10))
    res.append(sfc.get_folding_ranges())
    res.append(sfc.get_goal(9, 15))
    res.append(sfc.get_term_goal(9, 15))
    res.append(sfc.get_file_content())
    res.append(sfc.get_diagnostics())
    assert all(res)

    item = sfc.get_call_hierarchy_items(1, 15)[0]
    assert item["data"]["name"] == "add_zero_custom"
    inc = sfc.get_call_hierarchy_incoming(item)
    out = sfc.get_call_hierarchy_outgoing(item)
    assert inc == out == []

    sfc.update_file([DocumentContentChange("change", (0, 0), (0, 1))])
    res = sfc.get_code_actions(0, 0, 10, 10)
    res = sfc.get_code_action_resolve({})
