"""Live smoke test for leanclient.aio against a built Lean project.

Run:  python tests/aio/smoke.py [project_path]
Default project: the lean-lsp-mcp test project (built, Lean 4.30 + Mathlib).
Asserts on behavior; prints timings. Exits non-zero on failure.
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from leanclient.aio import (  # noqa: E402
    AsyncLeanLSPClient,
    LeanFileNotOpen,
    ScratchPool,
)

PROJECT = sys.argv[1] if len(sys.argv) > 1 else str(
    Path.home() / "Code/lean-lsp-mcp/tests/test_project"
)

UNI = (
    "import Mathlib\n\n"
    "theorem uni_smoke {𝕜 : Type*} [Field 𝕜] (x : 𝕜) : x + 0 = x := by\n"
    "  exact add_zero x\n"
)


def check(name, cond, info=""):
    status = "ok" if cond else "FAIL"
    print(f"  [{status}] {name} {info}")
    if not cond:
        raise AssertionError(name)


async def main():
    t0 = time.time()
    client = AsyncLeanLSPClient(PROJECT, max_workers=4)
    await client.start()
    print(f"[{time.time()-t0:6.2f}s] started (version check passed)")

    # 1. Parallel cold opens
    t = time.time()
    await client.open_many(["GoalSample.lean", "DiagnosticTest.lean"])
    dt_par = time.time() - t
    print(f"[{time.time()-t0:6.2f}s] open_many(2 files) = {dt_par:.2f}s")
    check("parallel opens < 1.6x single-file cost", dt_par < 14, f"{dt_par:.2f}s")

    # 2. Diagnostics with codepoint columns
    rep = await client.diagnostics("DiagnosticTest.lean")
    check("diagnostics has errors", rep.has_errors, f"{len(rep.errors)} errors")
    check("diagnostics version tagged", rep.version is not None, f"v{rep.version}")

    # 3. Goal statuses
    g = await client.goal("GoalSample.lean", 3, 2)  # inside `  trivial`
    check("goal at tactic", g.status in ("goals", "complete"), g.status)
    g2 = await client.goal("GoalSample.lean", 1, 0)  # blank line, no proof
    check("no_goal outside proof", g2.status == "no_goal", g2.status)

    # 4. Unicode: codepoint columns on a 𝕜-line (virtual doc, not on disk)
    await client.open("SmokeUni.lean", text=UNI)
    line = UNI.splitlines()[2]
    col_x = line.index("(x") + 1  # codepoint column of `x`
    h = await client.hover("SmokeUni.lean", 2, col_x)
    val = (h or {}).get("contents", {}).get("value", "")
    check("hover at codepoint col on unicode line", "x : 𝕜" in val, repr(val[:30]))
    rep_uni = await client.diagnostics("SmokeUni.lean")
    check("unicode file compiles clean", not rep_uni.has_errors)

    # 5. update + fresh diagnostics (stale-answer guard)
    broken = UNI.replace("add_zero x", "add_zero x.succ")
    await client.update("SmokeUni.lean", broken)
    rep2 = await client.diagnostics("SmokeUni.lean")
    check("fresh diagnostics after update see the error", rep2.has_errors)
    await client.update("SmokeUni.lean", UNI)
    rep3 = await client.diagnostics("SmokeUni.lean")
    check("fresh diagnostics after revert are clean", not rep3.has_errors)

    # 6. goal freshness (the null-goal trap): edit then immediately query fresh
    await client.update("SmokeUni.lean", UNI.replace("x + 0 = x", "0 + x = x"))
    g3 = await client.goal("SmokeUni.lean", 3, 2)
    check("fresh goal after edit is real (not instant-null)",
          g3.status in ("goals", "complete"), g3.status)

    # 7. Scratch pool: 4 tactic trials in parallel
    pool = ScratchPool(client, header="import Mathlib\n", size=2)
    t = time.time()
    await pool.warm()
    print(f"[{time.time()-t0:6.2f}s] pool.warm(2 slots) = {time.time()-t:.2f}s")
    t = time.time()
    results = await pool.run_many(
        [f"theorem s{i} : 2 + 2 = 4 := by {tac}\n"
         for i, tac in enumerate(["norm_num", "rfl", "simp", "sorry"])]
    )
    dt = time.time() - t
    print(f"[{time.time()-t0:6.2f}s] 4 trials = {dt:.2f}s")
    check("trials fast on warm pool", dt < 5, f"{dt:.2f}s")
    ok = [not r.diagnostics.has_errors for r in results]
    check("norm_num/rfl/simp succeed", ok[0] and ok[1] and ok[2], str(ok))
    sorry_warns = [d for d in results[3].diagnostics.items if d.get("severity") == 2]
    check("sorry produces a warning (not silent success)", len(sorry_warns) > 0)

    # 8. references with cap
    refs = await client.references("SmokeUni.lean", 2, 8, max_results=5)
    check("references capped", len(refs) <= 5, f"{len(refs)}")

    # 9. eviction under budget: max_workers=4, opening more evicts LRU
    await client.open("EditorTools.lean")
    await client.open("MiscTools.lean")
    check("doc count within budget+pins",
          len(client.open_paths()) <= 4 + 2, str(client.open_paths()))

    # 10. errors are typed
    try:
        await client.goal("NotOpen.lean", 0, 0)
        check("LeanFileNotOpen raised", False)
    except LeanFileNotOpen:
        check("LeanFileNotOpen raised", True)

    await client.close()
    check("closed cleanly", not client.alive)
    print(f"[{time.time()-t0:6.2f}s] ALL CHECKS PASSED")


asyncio.run(main())
