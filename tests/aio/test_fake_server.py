"""Byzantine-server tests: LspTransport / AsyncLeanLSPClient vs a scripted peer.

These cover exactly the failure modes a real ``lake serve`` makes untestable:
malformed output, out-of-order responses, server-request id collisions,
crashes mid-request, huge messages, and cancellation. No Lean toolchain
needed — the peer is ``fake_server.py``.

Plain ``asyncio.run`` wrappers (no pytest-asyncio dependency in this repo).
"""

from __future__ import annotations

import asyncio
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
        on_notification=notifications if notifications is not None else (lambda m, p: None),
        default_timeout=10.0,
    )


async def _started(scenario: str, notifications=None) -> LspTransport:
    t = _transport(scenario, notifications)
    await t.start()
    await t.request("initialize", {})
    return t


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


def test_docstate_ignores_stale_version_diagnostics(tmp_path: Path):
    """The D1 race from the audit: diagnostics for version N-1 arriving after
    the didChange to N must not overwrite the store."""
    from leanclient.aio.document import DocState

    doc = DocState(path="Foo.lean", uri="file:///Foo.lean", text="v2")
    doc.version = 2
    doc.on_publish_diagnostics(
        {"version": 1, "diagnostics": [{"message": "stale"}]}
    )
    assert doc.diagnostics == []  # stale publish ignored
    doc.on_publish_diagnostics(
        {"version": 2, "diagnostics": [{"message": "fresh"}]}
    )
    assert doc.diagnostics == [{"message": "fresh"}]
    assert doc.diagnostics_version == 2


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
