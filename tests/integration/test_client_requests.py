"""Integration tests for LeanLSPClient request methods."""

import os
import random
import time

import pytest


# Expected diagnostic messages from test file
EXP_DIAGNOSTIC_ERRORS = [
    "❌️ Docstring on `#guard_msgs` does not match generated message:\n\n- info: 2\n+ info: 1\n",
    "unexpected end of input; expected ':'",
]

EXP_DIAGNOSTIC_WARNINGS = ["declaration uses 'sorry'", "declaration uses 'sorry'"]


# ============================================================================
# Completion tests
# ============================================================================


@pytest.mark.integration
def test_completion(lsp_client, test_file_path):
    """Test getting completions at cursor position."""
    result = lsp_client.get_completions(test_file_path, 9, 15)
    assert isinstance(result, list)
    assert len(result) > 100


@pytest.mark.integration
def test_completion_item_resolve(lsp_client, test_file_path):
    """Test resolving completion item details."""
    result = lsp_client.get_completions(test_file_path, 9, 15)
    assert isinstance(result, list)
    resolve_res = lsp_client.get_completion_item_resolve(result[0])
    assert resolve_res == "a ∣ c → (a ∣ b + c ↔ a ∣ b)"


# ============================================================================
# Hover tests
# ============================================================================


@pytest.mark.integration
def test_hover(lsp_client, test_file_path):
    """Test getting hover information."""
    res = lsp_client.get_hover(test_file_path, 4, 4)
    assert isinstance(res, dict)
    assert "Zero, the smallest natural number" in res["contents"]["value"]


# ============================================================================
# Declaration/Definition tests
# ============================================================================


@pytest.mark.integration
def test_declaration(lsp_client, test_file_path):
    """Test getting declarations."""
    res = lsp_client.get_declarations(test_file_path, 6, 4)
    assert isinstance(res, list)
    assert "targetUri" in res[0]


@pytest.mark.integration
def test_request_definition(lsp_client, test_file_path):
    """Test getting definitions."""
    res = lsp_client.get_definitions(test_file_path, 1, 29)
    assert isinstance(res, list)
    res = res[0]
    if "uri" in res:
        assert res["uri"].endswith("Prelude.lean")
    else:
        assert res["targetUri"].endswith("Prelude.lean")


# ============================================================================
# Reference tests
# ============================================================================


@pytest.mark.integration
def test_references(lsp_client, test_file_path):
    """Test getting references."""
    res = lsp_client.get_references(test_file_path, 9, 24)
    assert isinstance(res, list)
    assert len(res) == 1


# ============================================================================
# Type definition tests
# ============================================================================


@pytest.mark.integration
def test_type_definition(lsp_client, test_file_path):
    """Test getting type definitions."""
    res = lsp_client.get_type_definitions(test_file_path, 1, 36)
    assert isinstance(res, list)
    assert res[0]["targetUri"].endswith("Prelude.lean")


# ============================================================================
# Document tests
# ============================================================================


@pytest.mark.integration
def test_document_highlight(lsp_client, test_file_path):
    """Test getting document highlights."""
    res = lsp_client.get_document_highlights(test_file_path, 9, 8)
    assert isinstance(res, list)
    assert res[0]["range"]["end"]["character"] == 20


@pytest.mark.integration
def test_document_symbol(lsp_client, test_file_path):
    """Test getting document symbols."""
    res = lsp_client.get_document_symbols(test_file_path)
    assert isinstance(res, list)
    assert res[0]["name"] == "add_zero_custom"


# ============================================================================
# Semantic tokens tests
# ============================================================================


@pytest.mark.integration
def test_semantic_tokens_full(lsp_client, test_file_path):
    """Test getting semantic tokens for full document."""
    res = lsp_client.get_semantic_tokens(test_file_path)
    assert isinstance(res, list)
    exp = [
        [1, 0, 7, "keyword"],
        [1, 25, 1, "variable"],
        [1, 36, 1, "variable"],
        [1, 44, 1, "variable"],
        [1, 49, 2, "keyword"],
    ]
    assert res[:5] == exp


@pytest.mark.integration
def test_semantic_tokens_range(lsp_client, test_file_path):
    """Test getting semantic tokens for range."""
    res = lsp_client.get_semantic_tokens_range(test_file_path, 0, 0, 2, 0)
    assert isinstance(res, list)
    exp = [
        [1, 0, 7, "keyword"],
        [1, 25, 1, "variable"],
        [1, 36, 1, "variable"],
        [1, 44, 1, "variable"],
        [1, 49, 2, "keyword"],
    ]
    assert res == exp


# ============================================================================
# Folding range tests
# ============================================================================


@pytest.mark.integration
def test_folding_range(lsp_client, test_file_path):
    """Test getting folding ranges."""
    res = lsp_client.get_folding_ranges(test_file_path)
    assert isinstance(res, list)
    assert res[0]["kind"] == "region"


# ============================================================================
# Goal tests
# ============================================================================


@pytest.mark.integration
def test_plain_goal(lsp_client, test_file_path):
    """Test getting proof goal at position."""
    res = lsp_client.get_goal(test_file_path, 9, 12)
    assert isinstance(res, dict)
    assert "⊢" in res["goals"][0]

    res = lsp_client.get_goal(test_file_path, 9, 25)
    assert len(res["goals"]) == 0


@pytest.mark.integration
def test_goal_with_delay(lsp_client, test_file_path):
    """Test getting goal with random delays between requests."""
    for _ in range(4):
        goal = lsp_client.get_goal(test_file_path, 9, 12)
        assert isinstance(goal, dict)
        assert "⊢" in goal["goals"][0]
        time.sleep(random.uniform(0, 0.5))


@pytest.mark.integration
def test_plain_term_goal(lsp_client, test_file_path):
    """Test getting term goal at position."""
    res = lsp_client.get_term_goal(test_file_path, 9, 12)
    assert isinstance(res, dict)
    assert "⊢" in res["goal"]

    res2 = lsp_client.get_term_goal(test_file_path, 9, 15)
    assert res == res2


# ============================================================================
# Code actions tests
# ============================================================================


def assert_subset(actual, expected):
    """Assert that expected keys/values are present in actual dict."""
    if isinstance(expected, dict):
        assert isinstance(actual, dict)
        for key, value in expected.items():
            assert key in actual, f"Missing key: {key}"
            assert_subset(actual[key], value)
    elif isinstance(expected, list):
        assert isinstance(actual, list)
        assert len(actual) == len(expected)
        for a, e in zip(actual, expected):
            assert_subset(a, e)
    else:
        assert actual == expected, f"Expected {expected}, got {actual}"


@pytest.mark.integration
def test_code_actions(clean_lsp_client, test_file_path, test_env_dir):
    """Test getting, resolving, and applying code actions."""
    clean_lsp_client.open_file(test_file_path)

    # Get code actions
    res = clean_lsp_client.get_code_actions(test_file_path, 12, 8, 12, 18)
    assert isinstance(res, list)

    EXP = {
        "data": {
            "params": {
                "context": {
                    "diagnostics": [
                        {
                            "fullRange": {
                                "end": {"character": 42, "line": 12},
                                "start": {"character": 37, "line": 12},
                            },
                            "message": "1",
                            "range": {
                                "end": {"character": 42, "line": 12},
                                "start": {"character": 37, "line": 12},
                            },
                            "severity": 3,
                            "source": "Lean 4",
                        },
                        {
                            "fullRange": {
                                "end": {"character": 26, "line": 12},
                                "start": {"character": 15, "line": 12},
                            },
                            "message": "❌️ Docstring on "
                            "`#guard_msgs` "
                            "does not match "
                            "generated "
                            "message:\n"
                            "\n"
                            "- info: 2\n"
                            "+ info: 1\n",
                            "range": {
                                "end": {"character": 26, "line": 12},
                                "start": {"character": 15, "line": 12},
                            },
                            "severity": 1,
                            "source": "Lean 4",
                        },
                    ],
                    "triggerKind": 1,
                },
                "range": {
                    "end": {"character": 18, "line": 12},
                    "start": {"character": 8, "line": 12},
                },
                "textDocument": {
                    "uri": f"file://{os.path.abspath(test_env_dir)}/LeanTestProject/Basic.lean"
                },
            },
            "providerName": "Lean.CodeAction.cmdCodeActionProvider",
            "providerResultIndex": 0,
        },
        "isPreferred": True,
        "kind": "quickfix",
        "title": "Update #guard_msgs with tactic output",
    }
    assert_subset(res[0], EXP)

    # Resolve code action
    res2 = clean_lsp_client.get_code_action_resolve({"title": "Test"})
    assert res2["error"]["message"].startswith("Cannot process request")

    res3 = clean_lsp_client.get_code_action_resolve(res[0])
    EXP = {
        "edit": {
            "documentChanges": [
                {
                    "edits": [
                        {
                            "newText": "/-- info: 1 -/\n",
                            "range": {
                                "end": {"character": 15, "line": 12},
                                "start": {"character": 0, "line": 12},
                            },
                        }
                    ],
                    "textDocument": {
                        "uri": f"file://{os.path.abspath(test_env_dir)}/LeanTestProject/Basic.lean",
                        "version": 0,
                    },
                }
            ]
        },
        "isPreferred": True,
        "kind": "quickfix",
        "title": "Update #guard_msgs with tactic output",
    }
    assert_subset(res3, EXP)

    # Apply the edit
    clean_lsp_client.apply_code_action_resolve(res3)
    content = clean_lsp_client.get_file_content(test_file_path)
    EXP = "-- Trigger code action\n/-- info: 1 -/\n#guard_msgs (info) in #eval 1"
    assert EXP in content, f"Expected '{EXP}' in content, got:\n{content}"


# ============================================================================
# Mathlib file tests
# ============================================================================


def find_position(lines, search_str, target_str, offset=0):
    """Find line and character position of target_str in line containing search_str."""
    for i, line in enumerate(lines):
        if search_str in line:
            return i, line.index(target_str) + offset
    return None, None


@pytest.mark.integration
@pytest.mark.mathlib
@pytest.mark.slow
def test_mathlib_file(lsp_client):
    """Test various operations on a mathlib file."""
    path = ".lake/packages/mathlib/Mathlib/Data/Finset/SDiff.lean"

    # Read file to find positions dynamically
    with open(os.path.join(lsp_client.project_path, path)) as f:
        lines = f.readlines()

    # Find positions
    finset_line, finset_char = find_position(
        lines, "instance instSDiff : SDiff (Finset", "Finset"
    )
    assert finset_line is not None, "Could not find 'instance instSDiff' line"

    sdiff_val_line, sdiff_val_char = find_position(
        lines, "theorem mem_sdiff", "mem_sdiff", offset=4
    )
    assert sdiff_val_line is not None, "Could not find 'theorem mem_sdiff' line"

    lsp_client.open_file(path)

    # Test Finset type reference
    res = lsp_client.get_definitions(path, finset_line, finset_char)
    assert len(res) == 1
    uri = res[0]["uri"] if "uri" in res[0] else res[0]["targetUri"]
    assert "Finset" in uri  # Finset is defined in a Finset file

    def flatten(ref):
        return tuple(
            [
                ref["uri"],
                ref["range"]["start"]["line"],
                ref["range"]["start"]["character"],
                ref["range"]["end"]["line"],
                ref["range"]["end"]["character"],
            ]
        )

    references = lsp_client.get_references(path, finset_line, finset_char)
    flat = set([flatten(ref) for ref in references])
    # Reference count can vary between mathlib versions
    flat_count = len(flat)
    assert flat_count > 200, (
        f"Expected > 200 unique Finset references, got {flat_count}"
    )

    res = lsp_client.get_declarations(path, finset_line, finset_char)
    assert len(res) == 1

    # Local theorem: mem_sdiff
    res = lsp_client.get_definitions(path, sdiff_val_line, sdiff_val_char)
    uri = res[0]["uri"] if "uri" in res[0] else res[0]["targetUri"]
    assert uri == lsp_client._local_to_uri(path)

    res = lsp_client.get_references(path, sdiff_val_line, sdiff_val_char)
    assert len(res) >= 1, f"Expected at least 1 reference to mem_sdiff, got {len(res)}"

    res = lsp_client.get_references(
        path, sdiff_val_line, sdiff_val_char, include_declaration=True
    )
    assert len(res) >= 2, (
        f"Expected at least 2 references (with declaration) to mem_sdiff, got {len(res)}"
    )

    res = lsp_client.get_references(
        path,
        sdiff_val_line,
        sdiff_val_char,
        include_declaration=True,
        max_retries=1,
        retry_delay=0,
    )
    assert len(res) >= 2


# ============================================================================
# Call hierarchy tests
# ============================================================================


@pytest.mark.integration
@pytest.mark.mathlib
@pytest.mark.skip(reason="Call hierarchy API is unreliable")
def test_call_hierarchy(lsp_client):
    """Test call hierarchy operations."""
    path = ".lake/packages/mathlib/Mathlib/Data/Finset/SDiff.lean"
    lsp_client.open_file(path)

    ch_item = lsp_client.get_call_hierarchy_items(path, 46, 30)[0]
    assert ch_item["data"]["name"] == "Multiset.nodup_of_le"

    lsp_client.get_call_hierarchy_incoming(ch_item)
    # Note: Result count may vary

    lsp_client.get_call_hierarchy_outgoing(ch_item)
    # Note: Result count may vary


# ============================================================================
# Empty response tests
# ============================================================================


@pytest.mark.integration
@pytest.mark.parametrize(
    "method,args,expected",
    [
        ("get_goal", (0, 0), None),
        ("get_term_goal", (0, 0), None),
        ("get_hover", (0, 0), None),
        ("get_declarations", (0, 0), []),
        ("get_definitions", (0, 0), []),
        ("get_references", (0, 0), []),
        ("get_type_definitions", (0, 0), []),
        ("get_document_highlights", (0, 0), []),
        ("get_semantic_tokens_range", (0, 0, 0, 0), []),
    ],
)
def test_empty_response(lsp_client, test_file_path, method, args, expected):
    """Test methods return expected empty values at invalid positions."""
    func = getattr(lsp_client, method)
    res = func(test_file_path, *args)
    assert res == expected


@pytest.mark.integration
def test_empty_response_for_empty_file(clean_lsp_client, test_env_dir):
    """Test methods on empty file return empty results."""
    # Create an empty file in the project directory
    path = "TestEmpty.lean"
    with open(test_env_dir + path, "w") as f:
        f.write("")

    try:
        res = clean_lsp_client.get_document_symbols(path)
        assert res == []

        res = clean_lsp_client.get_semantic_tokens(path)
        assert res == []

        res = clean_lsp_client.get_folding_ranges(path)
        assert res == []
    finally:
        # Remove the empty file
        os.remove(test_env_dir + path)


# ============================================================================
# Info trees tests
# ============================================================================


@pytest.mark.integration
def test_info_trees(lsp_client, test_file_path):
    """Test getting info trees."""
    res = lsp_client.get_info_trees(test_file_path)
    assert isinstance(res, list)
    assert len(res) == 3
    for tree in res:
        assert tree.startswith("• [Command] @")


@pytest.mark.integration
@pytest.mark.mathlib
@pytest.mark.slow
def test_info_trees_mathlib(lsp_client):
    """Test getting info trees from mathlib file."""
    path = ".lake/packages/mathlib/Mathlib/MeasureTheory/Topology.lean"
    res = lsp_client.get_info_trees(path)
    assert isinstance(res, list)
    assert len(res) == 1
    assert res[0].startswith("• [Command] @ ")


@pytest.mark.integration
def test_info_tree_parse(lsp_client, test_file_path):
    """Test parsing info trees into structured format."""
    res = lsp_client.get_info_trees(test_file_path, parse=True)
    assert isinstance(res, list)
    assert len(res) == 3

    allowed_keys = {
        "text",
        "type",
        "range",
        "elaborator",
        "goals_before",
        "goals_after",
        "extra",
        "children",
    }

    def check_node(node):
        assert isinstance(node, dict)
        assert "children" in node
        assert "text" in node
        assert set(node.keys()).issubset(allowed_keys), (
            f"Unexpected keys: {set(node.keys()) - allowed_keys}"
        )
        for child in node["children"]:
            check_node(child)

    for tree in res:
        check_node(tree)

    # Find maximum nesting level
    def max_nesting(node, level=0):
        if "children" not in node or not node["children"]:
            return level
        return max(max_nesting(child, level + 1) for child in node["children"])

    assert max_nesting(res[0]) == 48
    assert max_nesting(res[1]) == 14
    assert max_nesting(res[2]) == 16


@pytest.mark.integration
@pytest.mark.mathlib
@pytest.mark.slow
def test_info_tree_parse_mathlib(lsp_client):
    """Test parsing info trees from mathlib file."""
    path = ".lake/packages/mathlib/Mathlib/MeasureTheory/Topology.lean"
    res = lsp_client.get_info_trees(path, parse=True)
    assert isinstance(res, list)

    allowed_keys = {
        "text",
        "type",
        "range",
        "elaborator",
        "goals_before",
        "goals_after",
        "extra",
        "children",
    }

    def check_node(node):
        assert isinstance(node, dict)
        assert "children" in node
        assert "text" in node
        assert set(node.keys()).issubset(allowed_keys)
        for child in node["children"]:
            check_node(child)

    for tree in res:
        check_node(tree)
