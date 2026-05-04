import builtins
import threading
from pathlib import Path

import pytest

from leanclient.base_client import BaseLeanLSPClient
from leanclient.file_manager import LSPFileManager


pytestmark = pytest.mark.unit


def test_normalize_local_path_uses_forward_slashes() -> None:
    assert (
        BaseLeanLSPClient._normalize_local_path(r"src\Unicode.lean")
        == "src/Unicode.lean"
    )


def test_uri_to_local_uses_forward_slashes(tmp_path: Path) -> None:
    project = tmp_path / "project"
    target = project / "src" / "Unicode.lean"
    target.parent.mkdir(parents=True)
    target.write_text("theorem test : Nat := 1\n", encoding="utf-8")

    client = object.__new__(BaseLeanLSPClient)
    client.project_path = project.resolve()

    assert client._uri_to_local(target.resolve().as_uri()) == "src/Unicode.lean"


def test_open_new_files_reads_utf8(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    lean_file = tmp_path / "Unicode.lean"
    lean_file.write_text("theorem test : ℕ → ℕ := id\n", encoding="utf-8")

    recorded: dict[str, str | None] = {}

    def recording_open(file, mode="r", *args, **kwargs):
        recorded["encoding"] = kwargs.get("encoding")
        return builtins.open(file, mode, *args, **kwargs)

    monkeypatch.setattr("leanclient.file_manager.open", recording_open, raising=False)

    manager = object.__new__(LSPFileManager)
    manager.opened_files = {}
    manager._opened_files_lock = threading.Lock()
    manager._recently_closed = set()
    manager._locals_to_uris = lambda _paths: [lean_file.resolve().as_uri()]
    manager._uri_to_abs = lambda _uri: lean_file
    manager._send_notification = lambda *_args, **_kwargs: None

    manager._open_new_files(["src/Unicode.lean"])

    assert recorded["encoding"] == "utf-8"
    assert manager.opened_files["src/Unicode.lean"].content == (
        "theorem test : ℕ → ℕ := id\n"
    )


def test_open_files_normalizes_paths() -> None:
    manager = object.__new__(LSPFileManager)
    manager.max_opened_files = 4
    manager.opened_files = {}
    manager._opened_files_lock = threading.Lock()

    opened: list[str] = []
    manager._open_new_files = lambda paths, _mode: opened.extend(paths)

    manager.open_files([r"src\Unicode.lean"])

    assert opened == ["src/Unicode.lean"]
