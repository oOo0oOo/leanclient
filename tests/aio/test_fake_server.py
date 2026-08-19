"""Byzantine-server tests: LspTransport / AsyncLeanLSPClient vs a scripted peer.

These cover exactly the failure modes a real ``lake serve`` makes untestable:
malformed output, out-of-order responses, server-request id collisions,
crashes mid-request, huge messages, and cancellation. No Lean toolchain
needed — the peer is ``fake_server.py``.

Plain ``asyncio.run`` wrappers (no pytest-asyncio dependency in this repo).
"""

from __future__ import annotations

import asyncio
import os
import platform
import signal
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from leanclient.aio import (  # noqa: E402
    AsyncLeanLSPClient,
    LeanRequestCancelled,
    LeanRequestTimeout,
    LeanTransportError,
)
from leanclient.aio.transport import LspTransport  # noqa: E402

FAKE = str(Path(__file__).parent / "fake_server.py")


def _transport(scenario: str, notifications=None) -> LspTransport:
    return LspTransport(
        [sys.executable, FAKE, scenario],
        cwd=str(Path(__file__).parent),
        on_notification=notifications
        if notifications is not None
        else (lambda m, p: None),
        default_timeout=10.0,
    )


async def _started(scenario: str, notifications=None) -> LspTransport:
    t = _transport(scenario, notifications)
    await t.start()
    await t.request("initialize", {})
    return t


class _FakeProcess:
    pid = 4321

    def __init__(self):
        self.killed = False

    def kill(self):
        self.killed = True


def _transport_with_process() -> tuple[LspTransport, _FakeProcess]:
    transport = _transport("happy")
    process = _FakeProcess()
    transport._proc = process
    return transport, process


def test_kill_group_uses_process_kill_on_windows(monkeypatch):
    transport, process = _transport_with_process()
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        os,
        "killpg",
        lambda *_args: pytest.fail("Windows must not call os.killpg"),
        raising=False,
    )

    transport._kill_group()

    assert process.killed


def test_kill_group_uses_process_group_on_posix(monkeypatch):
    transport, process = _transport_with_process()
    killed = []
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(os, "getpgid", lambda pid: pid, raising=False)
    monkeypatch.setattr(os, "killpg", lambda *args: killed.append(args), raising=False)

    transport._kill_group()

    assert killed == [(_FakeProcess.pid, signal.SIGKILL)]
    assert not process.killed


def test_kill_group_falls_back_when_posix_group_kill_fails(monkeypatch):
    transport, process = _transport_with_process()
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(os, "getpgid", lambda pid: pid, raising=False)

    def fail_group_kill(*_args):
        raise PermissionError

    monkeypatch.setattr(os, "killpg", fail_group_kill, raising=False)

    transport._kill_group()

    assert process.killed


def test_happy_roundtrip():
    async def run():
        t = await _started("happy")
        result = await t.request("textDocument/hover", {})
        assert result == {"echo": "textDocument/hover", "n": 1}
        await t.close()

    asyncio.run(run())


def test_malformed_header_fails_pending_and_future_requests():
    """A garbage header must fail the in-flight request typed — never hang —
    and subsequent requests must fail instantly."""

    async def run():
        t = await _started("malformed_header")
        with pytest.raises(LeanTransportError):
            await asyncio.wait_for(t.request("anything", {}), timeout=5)
        assert not t.alive
        # Later requests fail immediately (no queue, no hang).
        with pytest.raises(LeanTransportError):
            await asyncio.wait_for(t.request("more", {}), timeout=1)
        await t.close()

    asyncio.run(run())


def test_bad_json_fails_typed():
    async def run():
        t = await _started("bad_json")
        with pytest.raises(LeanTransportError, match="Malformed JSON"):
            await asyncio.wait_for(t.request("anything", {}), timeout=5)
        await t.close()

    asyncio.run(run())


def test_out_of_order_responses_resolve_correct_futures():
    async def run():
        t = await _started("out_of_order")
        first, second = await asyncio.gather(
            t.request("req/one", {}), t.request("req/two", {})
        )
        assert first == {"which": "first"}
        assert second == {"which": "second"}
        await t.close()

    asyncio.run(run())


def test_server_request_with_colliding_id_does_not_poison_future():
    """A server->client request whose id equals a pending client-request id
    must not be mistaken for the response (the legacy client resolved the
    future with the raw request object here)."""

    async def run():
        t = await _started("id_collision")
        result = await asyncio.wait_for(t.request("query", {}), timeout=5)
        assert result == {"real": True}
        await t.close()

    asyncio.run(run())


def test_crash_mid_request_fails_typed_with_stderr_tail():
    async def run():
        t = await _started("crash_mid_request")
        with pytest.raises(LeanTransportError) as exc_info:
            await asyncio.wait_for(t.request("boom", {}), timeout=5)
        assert "simulated server crash" in exc_info.value.stderr_tail
        await t.close()

    asyncio.run(run())


def test_silent_eof_fails_typed():
    async def run():
        t = await _started("silent_eof")
        with pytest.raises(LeanTransportError, match="closed the connection"):
            await asyncio.wait_for(t.request("bye", {}), timeout=5)
        await t.close()

    asyncio.run(run())


def test_huge_message_survives():
    async def run():
        t = await _started("huge")
        result = await asyncio.wait_for(t.request("big", {}), timeout=15)
        assert len(result["blob"]) == 5 * 1024 * 1024
        await t.close()

    asyncio.run(run())


def test_timeout_sends_cancel_and_raises():
    """A timed-out request raises LeanRequestTimeout and a $/cancelRequest is
    sent; the server's -32800 acknowledgement is a *response to an abandoned
    id* and must be dropped silently."""

    async def run():
        t = await _started("cancel_ack")
        with pytest.raises(LeanRequestTimeout):
            await t.request("never/answered", {}, timeout=0.5)
        # Transport is still healthy for other traffic afterwards.
        assert t.alive
        await t.close()

    asyncio.run(run())


def test_task_cancellation_sends_cancel():
    """Cancelling the awaiting task abandons the request server-side too;
    the RequestCancelled reply for a *still-pending* id surfaces typed."""

    async def run():
        t = await _started("cancel_ack")
        task = asyncio.create_task(t.request("never/answered", {}, timeout=30))
        await asyncio.sleep(0.2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert t.alive
        await t.close()

    asyncio.run(run())


def test_request_cancelled_response_surfaces_typed():
    """When the server answers a live request with -32800, the caller gets
    LeanRequestCancelled (not a generic RPC error)."""

    async def run():
        t = await _started("cancel_ack")

        task = asyncio.create_task(t.request("never/answered", {}, timeout=30))
        await asyncio.sleep(0.2)
        # Fire the cancel notification ourselves while the future is pending;
        # the fake replies with -32800 for the ORIGINAL id, which is still
        # registered, so the future must resolve with LeanRequestCancelled.
        pending_id = next(iter(t._futures))
        await t.notify("$/cancelRequest", {"id": pending_id})
        with pytest.raises(LeanRequestCancelled):
            await asyncio.wait_for(task, timeout=5)
        await t.close()

    asyncio.run(run())


# --- client-level: barrier + freshness against the scripted peer ------------


def _project(tmp_path: Path) -> Path:
    (tmp_path / "lean-toolchain").write_text("leanprover/lean4:v4.24.0\n")
    return tmp_path


def test_client_open_update_barrier_against_fake(tmp_path: Path):
    async def run():
        client = AsyncLeanLSPClient(
            str(_project(tmp_path)),
            server_command=[sys.executable, FAKE, "happy"],
        )
        await client.start()
        doc = await client.open("Foo.lean", text="def x := 1\n")
        assert doc.version == 1
        report = await client.diagnostics("Foo.lean")
        assert report.items == [] and report.version == 1

        await client.update("Foo.lean", "def x := 2\n")
        report2 = await client.diagnostics("Foo.lean")
        assert report2.version == 2
        await client.close()

    asyncio.run(run())


def test_client_default_command_disables_report_delay(tmp_path: Path):
    project = str(_project(tmp_path))
    client = AsyncLeanLSPClient(project)
    assert client._transport._command == [
        "lake",
        "serve",
        "--",
        "-Dserver.reportDelayMs=0",
    ]

    debounced = AsyncLeanLSPClient(project, report_delay_ms=200)
    assert debounced._transport._command[-1] == "-Dserver.reportDelayMs=200"

    unmodified = AsyncLeanLSPClient(project, report_delay_ms=None)
    assert unmodified._transport._command == ["lake", "serve", "--"]

    custom = [sys.executable, FAKE, "happy"]
    custom_client = AsyncLeanLSPClient(
        project,
        server_command=custom,
        report_delay_ms=123,
    )
    assert custom_client._transport._command == custom


def test_client_advertises_incremental_diagnostics(tmp_path: Path):
    async def run():
        client = AsyncLeanLSPClient(
            str(_project(tmp_path)),
            server_command=[sys.executable, FAKE, "happy"],
        )
        seen = {}
        original = client._transport.request

        async def spy(method, params, *args, **kwargs):
            if method == "initialize":
                seen.update(params)
            return await original(method, params, *args, **kwargs)

        setattr(client._transport, "request", spy)
        await client.start()
        assert seen["capabilities"]["lean"]["incrementalDiagnosticSupport"] is True
        await client.close()

    asyncio.run(run())


def test_client_reuses_barrier_for_unchanged_version(tmp_path: Path):
    async def run():
        client = AsyncLeanLSPClient(
            str(_project(tmp_path)),
            server_command=[sys.executable, FAKE, "happy"],
        )
        barriers = 0
        original = client._transport.request

        async def spy(method, params, *args, **kwargs):
            nonlocal barriers
            if method == "textDocument/waitForDiagnostics":
                barriers += 1
            return await original(method, params, *args, **kwargs)

        setattr(client._transport, "request", spy)
        await client.start()
        doc = await client.open("Foo.lean", text="def x := 1\n")
        assert barriers == 1
        assert doc.barrier_version == 1

        await client.diagnostics("Foo.lean")
        await client.diagnostics("Foo.lean")
        assert barriers == 1

        await client.update("Foo.lean", "def x := 2\n")
        assert doc.barrier_version is None
        await client.diagnostics("Foo.lean")
        assert barriers == 2
        assert doc.barrier_version == 2
        await client.close()

    asyncio.run(run())


def test_client_barrier_completion_does_not_downgrade_version(tmp_path: Path):
    async def run():
        client = AsyncLeanLSPClient(
            str(_project(tmp_path)),
            server_command=[sys.executable, FAKE, "happy"],
        )
        await client.start()
        doc = await client.open("Foo.lean", text="def x := 1\n", wait=False)

        gates = {1: asyncio.Event(), 2: asyncio.Event()}
        barrier_calls = []
        original = client._transport.request

        async def delayed(method, params, *args, **kwargs):
            if method != "textDocument/waitForDiagnostics":
                return await original(method, params, *args, **kwargs)
            version = params["version"]
            barrier_calls.append(version)
            await gates[version].wait()
            return {}

        setattr(client._transport, "request", delayed)
        first = asyncio.create_task(client.barrier("Foo.lean"))
        await asyncio.sleep(0)
        await client.update("Foo.lean", "def x := 2\n")
        second = asyncio.create_task(client.barrier("Foo.lean"))
        await asyncio.sleep(0)

        gates[2].set()
        await second
        assert doc.barrier_version == 2

        gates[1].set()
        await first
        assert doc.barrier_version == 2

        await client.barrier("Foo.lean")
        assert barrier_calls == [1, 2]
        await client.close()

    asyncio.run(run())


def test_client_workspace_symbol_and_ileans(tmp_path: Path):
    async def run():
        client = AsyncLeanLSPClient(
            str(_project(tmp_path)),
            server_command=[sys.executable, FAKE, "happy"],
        )
        await client.start()
        assert await client.wait_for_ileans(timeout=5)
        assert client.ileans_ready

        symbols, ready = await client.workspace_symbol("foo", max_results=1)
        assert ready
        assert len(symbols) == 1
        assert symbols[0]["name"] == "foo_exact"
        # Location converted: path + codepoint range present.
        assert symbols[0]["location"]["path"].endswith("Dep.lean")
        assert symbols[0]["location"]["range"]["start"]["line"] == 4
        await client.close()

    asyncio.run(run())


def test_client_didopen_sends_dependency_build_mode(tmp_path: Path):
    """All opens (incl. scratch docs) must send dependencyBuildMode so trials
    can never trigger a `lake` build."""

    async def run():
        seen = []
        client = AsyncLeanLSPClient(
            str(_project(tmp_path)),
            server_command=[sys.executable, FAKE, "happy"],
        )
        await client.start()
        original = client._transport.notify

        async def spy(method, params):
            seen.append((method, params))
            await original(method, params)

        client._transport.notify = spy
        await client.open("Foo.lean", text="def x := 1\n")
        opens = [p for m, p in seen if m == "textDocument/didOpen"]
        assert opens and opens[0]["dependencyBuildMode"] == "never"
        await client.close()

    asyncio.run(run())


def test_partial_diagnostics_on_slow_elaboration(tmp_path: Path):
    """A barrier timeout with partial_ok returns an honest partial report
    carrying the still-processing ranges instead of raising."""

    async def run():
        client = AsyncLeanLSPClient(
            str(_project(tmp_path)),
            server_command=[sys.executable, FAKE, "slow_elab"],
        )
        await client.start()
        await client.open("Slow.lean", text="def x := 1\n" * 50, wait=False)

        report = await client.diagnostics(
            "Slow.lean", fresh=True, timeout=1.0, partial_ok=True
        )
        assert report.partial is True
        assert report.processing_ranges
        assert report.processing_ranges[0]["start"]["line"] == 2
        assert report.processing_ranges[0]["end"]["line"] == 40

        # Without partial_ok the timeout is still a typed error.
        with pytest.raises(LeanRequestTimeout):
            await client.diagnostics("Slow.lean", fresh=True, timeout=0.5)
        await client.close()

    asyncio.run(run())


def test_docstate_ignores_stale_version_diagnostics(tmp_path: Path):
    """The D1 race from the audit: diagnostics for version N-1 arriving after
    the didChange to N must not overwrite the store."""
    from leanclient.aio.document import DocState

    doc = DocState(path="Foo.lean", uri="file:///Foo.lean", text="v2")
    doc.version = 2
    doc.on_publish_diagnostics({"version": 1, "diagnostics": [{"message": "stale"}]})
    assert doc.diagnostics == []  # stale publish ignored
    doc.on_publish_diagnostics({"version": 2, "diagnostics": [{"message": "fresh"}]})
    assert doc.diagnostics == [{"message": "fresh"}]
    assert doc.diagnostics_version == 2


def test_docstate_appends_incremental_diagnostics_and_resets():
    from leanclient.aio.document import DocState

    doc = DocState(path="Foo.lean", uri="file:///Foo.lean", text="v1")
    first = {"message": "first"}
    second = {"message": "second"}
    replacement = {"message": "replacement"}

    doc.on_publish_diagnostics({"version": 1, "diagnostics": [first]})
    doc.on_publish_diagnostics(
        {"version": 1, "isIncremental": True, "diagnostics": [second]}
    )
    assert doc.diagnostics == [first, second]

    doc.on_publish_diagnostics(
        {"version": 1, "isIncremental": False, "diagnostics": [replacement]}
    )
    assert doc.diagnostics == [replacement]


def test_docstate_caches_lines_until_text_changes():
    from leanclient.aio.document import DocState

    doc = DocState(path="Foo.lean", uri="file:///Foo.lean", text="one\ntwo\n")
    first = doc.lines()
    assert first == ["one", "two"]
    assert doc.lines() is first

    doc.barrier_version = 1
    doc.replace_text("three\n")
    assert doc.lines() == ["three"]
    assert doc.lines() is not first
    assert doc.barrier_version is None


def test_unsupported_toolchain_rejected(tmp_path: Path):
    from leanclient.aio import LeanUnsupportedVersion

    (tmp_path / "lean-toolchain").write_text("leanprover/lean4:v4.22.0\n")

    async def run():
        client = AsyncLeanLSPClient(
            str(tmp_path), server_command=[sys.executable, FAKE, "happy"]
        )
        with pytest.raises(LeanUnsupportedVersion):
            await client.start()

    asyncio.run(run())


if __name__ == "__main__":
    import inspect

    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            params = inspect.signature(fn).parameters
            if "tmp_path" in params:
                import tempfile

                with tempfile.TemporaryDirectory() as d:
                    fn(Path(d))
            else:
                fn()
            print(f"  [ok] {name}")
    print("fake-server tests passed")
