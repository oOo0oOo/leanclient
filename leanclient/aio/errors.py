"""Typed exception hierarchy for the async client.

One contract: every failure raises a subclass of :class:`LeanClientError`.
No error dicts, no ``None``-for-error returns.
"""

from __future__ import annotations


class LeanClientError(Exception):
    """Base class for all async-client errors."""


class LeanTransportError(LeanClientError):
    """The connection to ``lake serve`` failed (EOF, garbage, broken pipe).

    All pending requests are failed with this error when the transport dies.
    """

    def __init__(self, message: str, stderr_tail: str = ""):
        super().__init__(message)
        self.stderr_tail = stderr_tail


class LeanWorkerCrashed(LeanClientError):
    """A per-file worker process crashed (watchdog reported workerCrashed/workerExited)."""

    def __init__(self, message: str, uri: str = ""):
        super().__init__(message)
        self.uri = uri


class LeanRequestTimeout(LeanClientError):
    """A request exceeded its deadline. A ``$/cancelRequest`` has been sent."""


class LeanRequestCancelled(LeanClientError):
    """The server answered with RequestCancelled (-32800)."""


class LeanRpcError(LeanClientError):
    """The server answered a request with a JSON-RPC error object."""

    def __init__(self, code: int, message: str, data=None):
        super().__init__(f"LSP error {code}: {message}")
        self.code = code
        self.data = data
        self.rpc_message = message


class LeanFileNotOpen(LeanClientError):
    """Operation on a file that is not open in this client."""


class LeanUnsupportedVersion(LeanClientError):
    """Project toolchain is below the supported floor (Lean >= 4.24)."""
