"""ScratchPool — pre-warmed virtual documents for snippet/tactic trials.

The expensive part of checking a Lean snippet is the import header (~8s for
``import Mathlib``, ~5 GB per worker). A ScratchPool pays that once per slot:
each slot is a virtual document (never on disk) opened with the shared header;
a trial is then a full-text didChange + barrier — measured ~0.2s — and slots
run trials **in parallel**.

This replaces every edit-the-user's-file-and-restore pattern: the user's
document is never touched.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Optional

from .client import AsyncLeanLSPClient, DiagnosticsReport, GoalResult


@dataclass
class TrialResult:
    body: str
    diagnostics: DiagnosticsReport
    goal: Optional[GoalResult] = None
    # Diagnostics with lines re-based so line 0 = first line of `body`.
    body_diagnostics: list[dict] = field(default_factory=list)


class ScratchPool:
    def __init__(
        self,
        client: AsyncLeanLSPClient,
        header: str,
        size: int = 2,
        name_prefix: str = "_lc_scratch",
    ):
        self._client = client
        self.header = header.rstrip("\n") + "\n"
        self._header_lines = self.header.count("\n")
        self._size = size
        self._paths = [f"{name_prefix}_{i}.lean" for i in range(size)]
        self._free: asyncio.Queue[str] = asyncio.Queue()
        self._warmed = False
        self._warm_lock = asyncio.Lock()

    async def warm(self) -> None:
        """Open and elaborate all slots (parallel; ~1 header cost wall-clock)."""
        async with self._warm_lock:
            if self._warmed:
                return
            for p in self._paths:
                doc = await self._client.open(p, text=self.header, wait=False)
                doc.pinned = True
            await asyncio.gather(*(self._client.barrier(p) for p in self._paths))
            for p in self._paths:
                self._free.put_nowait(p)
            self._warmed = True

    async def run(
        self,
        body: str,
        want_goal_at: Optional[tuple[int, int]] = None,
        timeout: Optional[float] = None,
    ) -> TrialResult:
        """Check ``header + body``; return diagnostics (and optionally a goal).

        ``want_goal_at`` is (line, col) 0-indexed *within body*.
        Diagnostics in ``body_diagnostics`` are re-based to body coordinates
        (header diagnostics filtered out).
        """
        await self.warm()
        path = await self._free.get()
        try:
            text = self.header + body if body is not None else self.header
            await self._client.update(path, text, wait=False)
            report = await self._client.diagnostics(path, fresh=True, timeout=timeout)
            goal = None
            if want_goal_at is not None:
                goal = await self._client.goal(
                    path,
                    want_goal_at[0] + self._header_lines,
                    want_goal_at[1],
                    fresh=False,  # barrier already passed via diagnostics()
                )
            body_diags = []
            for d in report.items:
                r = d.get("fullRange") or d.get("range")
                if r is None:
                    body_diags.append(d)
                    continue
                if r["start"]["line"] < self._header_lines:
                    continue  # header-region diagnostic
                shifted = _shift_diag(d, -self._header_lines)
                body_diags.append(shifted)
            return TrialResult(
                body=body, diagnostics=report, goal=goal, body_diagnostics=body_diags
            )
        finally:
            self._free.put_nowait(path)

    async def run_text(
        self,
        text: str,
        want_goal_at: Optional[tuple[int, int]] = None,
        timeout: Optional[float] = None,
    ) -> TrialResult:
        """Check a complete document (its own imports included).

        If ``text`` shares its import header with the slot's previous
        content, the server reuses the header snapshot — so repeated trials
        of same-project documents only pay body elaboration.
        ``want_goal_at`` is (line, col) 0-indexed within ``text``.
        Diagnostics in ``body_diagnostics`` are in document coordinates.
        """
        await self.warm()
        path = await self._free.get()
        try:
            await self._client.update(path, text, wait=False)
            report = await self._client.diagnostics(path, fresh=True, timeout=timeout)
            goal = None
            if want_goal_at is not None:
                goal = await self._client.goal(
                    path, want_goal_at[0], want_goal_at[1], fresh=False
                )
            return TrialResult(
                body=text,
                diagnostics=report,
                goal=goal,
                body_diagnostics=list(report.items),
            )
        finally:
            self._free.put_nowait(path)

    async def run_many(
        self,
        bodies: list[str],
        want_goal_at: Optional[tuple[int, int]] = None,
        timeout: Optional[float] = None,
    ) -> list[TrialResult]:
        """Run several trials; parallelism = pool size."""
        return list(
            await asyncio.gather(
                *(self.run(b, want_goal_at=want_goal_at, timeout=timeout) for b in bodies)
            )
        )

    async def run_texts(
        self,
        texts: list[str],
        want_goal_at: Optional[list[Optional[tuple[int, int]]]] = None,
        timeout: Optional[float] = None,
    ) -> list[TrialResult]:
        """Check several complete documents; parallelism = pool size."""
        goals = want_goal_at or [None] * len(texts)
        return list(
            await asyncio.gather(
                *(
                    self.run_text(t, want_goal_at=g, timeout=timeout)
                    for t, g in zip(texts, goals)
                )
            )
        )

    async def close(self) -> None:
        for p in self._paths:
            await self._client.close_file(p)
        self._warmed = False
        while not self._free.empty():
            self._free.get_nowait()


def _shift_diag(diag: dict, delta_lines: int) -> dict:
    out = dict(diag)
    for key in ("range", "fullRange"):
        r = out.get(key)
        if r:
            out[key] = {
                "start": {
                    "line": r["start"]["line"] + delta_lines,
                    "character": r["start"]["character"],
                },
                "end": {
                    "line": r["end"]["line"] + delta_lines,
                    "character": r["end"]["character"],
                },
            }
    return out
