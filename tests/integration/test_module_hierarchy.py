"""Integration tests for module hierarchy LSP methods."""

import pytest


@pytest.mark.integration
def test_prepare_module_hierarchy(lsp_client, test_file_path):
    """Test preparing module hierarchy for a file."""
    module = lsp_client.prepare_module_hierarchy(test_file_path)

    assert module is not None
    assert isinstance(module, dict)
    assert "name" in module
    assert "uri" in module
    assert module["name"] == "LeanTestProject.Basic"
    assert module["uri"].endswith("LeanTestProject/Basic.lean")


@pytest.mark.integration
def test_prepare_module_hierarchy_main(lsp_client):
    """Test preparing module hierarchy for Main.lean."""
    module = lsp_client.prepare_module_hierarchy("Main.lean")

    assert module is not None
    assert module["name"] == "Main"
    assert module["uri"].endswith("Main.lean")


@pytest.mark.integration
def test_get_module_imports_mathlib(lsp_client):
    """Test getting imports from a Mathlib module."""
    # Use Mathlib.Init - a small foundational module with manageable imports
    module = lsp_client.prepare_module_hierarchy(
        ".lake/packages/mathlib/Mathlib/Init.lean"
    )
    imports = lsp_client.get_module_imports(module)

    assert isinstance(imports, list)
    assert len(imports) > 10  # Init has ~18 imports

    # Check structure of first import
    imp = imports[0]
    assert "module" in imp
    assert "kind" in imp
    assert "name" in imp["module"]
    assert "uri" in imp["module"]

    # Check kind structure
    kind = imp["kind"]
    assert "isPrivate" in kind
    assert "isAll" in kind
    assert "metaKind" in kind
    assert kind["metaKind"] in ["nonMeta", "meta", "full"]


@pytest.mark.integration
def test_get_module_imports_empty(lsp_client, test_file_path):
    """Test that modules without .ilean return empty (graceful degradation)."""
    module = lsp_client.prepare_module_hierarchy(test_file_path)
    imports = lsp_client.get_module_imports(module)

    assert isinstance(imports, list)
    # No .ilean files for test project, so this will be empty
    assert len(imports) == 0


@pytest.mark.integration
def test_get_module_imported_by_mathlib(lsp_client):
    """Test reverse dependencies with a Mathlib module."""
    # Mathlib.Init is imported by many other modules
    module = lsp_client.prepare_module_hierarchy(
        ".lake/packages/mathlib/Mathlib/Init.lean"
    )
    imported_by = lsp_client.get_module_imported_by(module)

    assert isinstance(imported_by, list)
    assert len(imported_by) > 20  # Init is imported by many modules

    # Check structure
    if imported_by:
        imp = imported_by[0]
        assert "module" in imp
        assert "kind" in imp


@pytest.mark.integration
def test_module_hierarchy_traversal(lsp_client):
    """Test traversing module hierarchy through Mathlib."""
    # Start with Mathlib.Init
    init_module = lsp_client.prepare_module_hierarchy(
        ".lake/packages/mathlib/Mathlib/Init.lean"
    )
    init_imports = lsp_client.get_module_imports(init_module)

    assert len(init_imports) > 10

    # Pick first import and traverse into it
    if init_imports:
        first_import = init_imports[0]["module"]
        first_import_imports = lsp_client.get_module_imports(first_import)
        assert isinstance(first_import_imports, list)
        # Can be empty or have imports - both are valid


@pytest.mark.integration
def test_module_import_kinds(lsp_client):
    """Test that import kind flags are correctly populated."""
    module = lsp_client.prepare_module_hierarchy(
        ".lake/packages/mathlib/Mathlib/Logic/Basic.lean"
    )
    imports = lsp_client.get_module_imports(module)

    # Check various kind properties
    assert len(imports) > 0  # Should have some imports
    for imp in imports[:5]:  # Check first 5
        kind = imp["kind"]
        assert isinstance(kind["isPrivate"], bool)
        assert isinstance(kind["isAll"], bool)
        assert kind["metaKind"] in ["nonMeta", "meta", "full"]


@pytest.mark.integration
def test_module_hierarchy_empty_results(lsp_client, test_file_path):
    """Test that modules without .ilean return empty lists, not errors."""
    module = lsp_client.prepare_module_hierarchy(test_file_path)

    # Basic.lean has no .ilean - should return empty, not crash
    imports = lsp_client.get_module_imports(module)
    assert imports == []
    assert isinstance(imports, list)

    imported_by = lsp_client.get_module_imported_by(module)
    assert imported_by == []
    assert isinstance(imported_by, list)
