"""Asyncio-native Lean 4 LSP client.

Usage::

    from leanclient.aio import AsyncLeanLSPClient

    client = AsyncLeanLSPClient("path/to/project")
    await client.start()
    await client.open_many(["A.lean", "B.lean"])   # parallel elaboration
    report = await client.diagnostics("A.lean")     # fresh by construction
    goal = await client.goal("A.lean", line=3, col=2)  # codepoint columns
    await client.close()

The legacy synchronous API (``leanclient.LeanLSPClient``) is unchanged.
"""

from .client import AsyncLeanLSPClient, DiagnosticsReport, GoalResult
from .convert import codepoint_to_utf16, utf16_to_codepoint
from .document import DocState, DocStatus
from .errors import (
    LeanClientError,
    LeanFileNotOpen,
    LeanRequestCancelled,
    LeanRequestTimeout,
    LeanRpcError,
    LeanTransportError,
    LeanUnsupportedVersion,
    LeanWorkerCrashed,
)
from .scratch import ScratchPool, TrialResult

__all__ = [
    "AsyncLeanLSPClient",
    "DiagnosticsReport",
    "GoalResult",
    "DocState",
    "DocStatus",
    "ScratchPool",
    "TrialResult",
    "LeanClientError",
    "LeanTransportError",
    "LeanWorkerCrashed",
    "LeanRequestTimeout",
    "LeanRequestCancelled",
    "LeanRpcError",
    "LeanFileNotOpen",
    "LeanUnsupportedVersion",
    "codepoint_to_utf16",
    "utf16_to_codepoint",
]
