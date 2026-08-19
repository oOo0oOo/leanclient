"""Live async-client coverage for transitive stale-import recovery."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from leanclient.aio import AsyncLeanLSPClient


def _write_project(project: Path) -> None:
    (project / "lakefile.toml").write_text(
        'name = "stale-import-test"\n'
        'version = "0.1.0"\n'
        'defaultTargets = ["StaleImport"]\n'
        "\n"
        "[[lean_lib]]\n"
        'name = "StaleImport"\n',
        encoding="utf-8",
    )
    sources = project / "StaleImport"
    sources.mkdir()
    (sources / "B.lean").write_text("def value : Nat := 1\n", encoding="utf-8")
    (sources / "C.lean").write_text(
        "import StaleImport.B\n\ndef viaC : Nat := value\n", encoding="utf-8"
    )
    (sources / "A.lean").write_text(
        "import StaleImport.C\n\nexample : viaC = 1 := rfl\n", encoding="utf-8"
    )


async def _wait_until(predicate, timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError("condition was not met")
        await asyncio.sleep(0.02)


@pytest.mark.integration
def test_transitive_dependency_change_rebuilds_open_importer(tmp_path: Path):
    _write_project(tmp_path)
    build = subprocess.run(
        ["lake", "build", "StaleImport.A"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, build.stdout + build.stderr

    async def run():
        client = AsyncLeanLSPClient(str(tmp_path), request_timeout=30)
        await client.start()
        try:
            await _wait_until(lambda: client._watch_task is not None)
            initial = await client.open("StaleImport/A.lean")
            assert not (await client.diagnostics("StaleImport/A.lean")).has_errors

            dependency = tmp_path / "StaleImport" / "B.lean"
            dependency_changed = asyncio.Event()
            original_notify = client._transport.notify

            async def observe_dependency_change(method, params):
                if method == "workspace/didChangeWatchedFiles" and any(
                    change["uri"] == dependency.as_uri() for change in params["changes"]
                ):
                    dependency_changed.set()
                await original_notify(method, params)

            client._transport.notify = observe_dependency_change
            dependency.write_text("def value : Nat := 2\n", encoding="utf-8")
            await asyncio.wait_for(dependency_changed.wait(), timeout=5)
            await _wait_until(lambda: initial.stale_imports)

            changed = await client.diagnostics("StaleImport/A.lean")
            assert changed.has_errors
            assert not any(
                "Imports are out of date" in diagnostic.get("message", "")
                for diagnostic in changed.items
            )

            # Let the .ilean writes from the first rebuild pass through the
            # watcher, then establish a fresh barrier for the next edit.
            await asyncio.sleep(0.5)
            await client.diagnostics("StaleImport/A.lean")
            assert initial.barrier_version is not None
            dependency_changed.clear()
            dependency.write_text("def value : Nat := 1\n", encoding="utf-8")
            await asyncio.wait_for(dependency_changed.wait(), timeout=5)
            await _wait_until(lambda: initial.stale_imports)
            repaired = await client.diagnostics("StaleImport/A.lean")
            assert not repaired.has_errors, repaired.items
        finally:
            await client.close()

    asyncio.run(run())
