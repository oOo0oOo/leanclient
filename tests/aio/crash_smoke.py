"""Crash-path smoke test: kill lake serve mid-session, verify typed failures.

Run: python tests/aio/crash_smoke.py [project_path]
"""

import asyncio
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from leanclient.aio import (  # noqa: E402
    AsyncLeanLSPClient,
    LeanTransportError,
)

PROJECT = sys.argv[1] if len(sys.argv) > 1 else str(
    Path.home() / "Code/lean-lsp-mcp/tests/test_project"
)


def check(name, cond, info=""):
    status = "ok" if cond else "FAIL"
    print(f"  [{status}] {name} {info}")
    if not cond:
        raise AssertionError(name)


async def main():
    t0 = time.time()
    client = AsyncLeanLSPClient(PROJECT)
    await client.start()
    await client.open("GoalSample.lean")
    print(f"[{time.time()-t0:6.2f}s] warm")

    # Kill lake serve while a request is in flight (cold file: barrier
    # genuinely blocks on ~8s of elaboration).
    pid = client._transport._proc.pid
    await client.open("EditorTools.lean", wait=False)
    pending = asyncio.create_task(client.diagnostics("EditorTools.lean"))
    await asyncio.sleep(0.5)
    import os

    os.killpg(os.getpgid(pid), signal.SIGKILL)  # kill lake + watchdog + workers
    try:
        await pending
        check("pending request fails typed", False, "no exception")
    except LeanTransportError as e:
        check("pending request fails typed", True, type(e).__name__)
    except Exception as e:  # noqa: BLE001
        check("pending request fails typed", False, f"wrong type: {type(e).__name__}")

    # New calls after death also fail typed, immediately.
    t = time.time()
    try:
        await client.goal("GoalSample.lean", 3, 2)
        check("post-death call fails typed", False)
    except LeanTransportError:
        check("post-death call fails typed", True, f"{time.time()-t:.3f}s (no hang)")
    check("alive is False", not client.alive)

    # Fresh client works (restart story is the consumer's policy decision).
    client2 = AsyncLeanLSPClient(PROJECT)
    await client2.start()
    await client2.open("GoalSample.lean")
    g = await client2.goal("GoalSample.lean", 3, 2)
    check("fresh client recovers", g.status in ("goals", "complete"), g.status)
    await client2.close()
    await client.close()
    print(f"[{time.time()-t0:6.2f}s] CRASH CHECKS PASSED")


asyncio.run(main())
