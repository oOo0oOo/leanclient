import asyncio
import builtins
import nturl2path
import threading
from pathlib import Path

import pytest

from leanclient.aio import client as aio_client
from leanclient.aio.client import AsyncLeanLSPClient
from leanclient.aio.document import DocState
from leanclient.base_client import BaseLeanLSPClient
from leanclient.file_manager import LSPFileManager


pytestmark = pytest.mark.unit


UNICODE_SOURCE = "-- ∀ α ℕ\ntheorem test : ℕ → ℕ := id\n"


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


# Async client


def _aio_client(project_path: Path) -> AsyncLeanLSPClient:
    client = object.__new__(AsyncLeanLSPClient)
    client.project_path = str(project_path)
    client._docs = {}
    client._docs_by_uri = {}
    client._file_lines_cache = {}
    return client


def _record_read_text(monkeypatch: pytest.MonkeyPatch) -> dict[str, str | None]:
    recorded: dict[str, str | None] = {}
    read_text = Path.read_text

    def recording_read_text(self, *args, **kwargs):
        recorded["encoding"] = kwargs.get("encoding")
        return read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", recording_read_text)
    return recorded


def test_aio_uri_roundtrip(tmp_path: Path) -> None:
    client = _aio_client(tmp_path)
    uri = client._path_to_uri("src/Unicode.lean")

    assert uri == (tmp_path / "src" / "Unicode.lean").as_uri()
    assert client._uri_to_relpath(uri) == str(Path("src/Unicode.lean"))


def test_aio_uri_to_abs_restores_windows_drive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # url2pathname is platform specific: use the Windows one to check that the
    # drive letter survives, both for standard file URIs and for the
    # "file://///C:/..." form older leanclient versions produced.
    monkeypatch.setattr(aio_client, "url2pathname", nturl2path.url2pathname)
    client = _aio_client(tmp_path)

    for uri in (
        "file:///C:/Users/11388/HighDimProb/Main.lean",
        "file:///C%3A/Users/11388/HighDimProb/Main.lean",
        "file://///C:/Users/11388/HighDimProb/Main.lean",
    ):
        assert client._uri_to_abs(uri) == r"C:\Users\11388\HighDimProb\Main.lean"


def test_aio_reload_from_disk_reads_utf8(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "Unicode.lean").write_text(UNICODE_SOURCE, encoding="utf-8")
    recorded = _record_read_text(monkeypatch)

    client = _aio_client(tmp_path)
    doc = DocState(path="Unicode.lean", uri="file:///Unicode.lean", text="stale")
    client._docs["Unicode.lean"] = doc

    updated: dict[str, str] = {}

    async def fake_update(path: str, text: str, wait: bool = False) -> DocState:
        updated["text"] = text
        return doc

    monkeypatch.setattr(client, "update", fake_update)
    asyncio.run(client.reload_from_disk("Unicode.lean"))

    assert recorded["encoding"] == "utf-8"
    assert updated["text"] == UNICODE_SOURCE


def test_aio_disk_lines_reads_utf8(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    lean_file = tmp_path / "Unicode.lean"
    lean_file.write_text(UNICODE_SOURCE, encoding="utf-8")
    recorded = _record_read_text(monkeypatch)

    client = _aio_client(tmp_path)
    lines = client._disk_lines(lean_file.as_uri())

    assert recorded["encoding"] == "utf-8"
    assert lines == UNICODE_SOURCE.splitlines()
