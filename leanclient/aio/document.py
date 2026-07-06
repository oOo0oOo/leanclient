"""Per-file document state.

Tracks exactly what the server contract requires a client to know per file:
the version we last sent, diagnostics tagged with the version they belong to,
fileProgress state, stale-import and crash flags. The freshness primitive
(``barrier``) lives on the client, which owns write ordering; DocState only
records what notifications say.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import Optional


class DocStatus(enum.Enum):
    OPENING = "opening"
    LIVE = "live"
    CRASHED = "crashed"
    CLOSED = "closed"


@dataclass
class DocState:
    path: str  # project-relative path (identity within the client)
    uri: str
    text: str
    version: int = 1
    status: DocStatus = DocStatus.OPENING
    virtual: bool = False  # opened with explicit text; may not exist on disk
    pinned: bool = False
    refcount: int = 0  # in-flight requests referencing this doc
    last_used: float = field(default_factory=time.monotonic)

    # Latest published diagnostics and the doc version they were computed for.
    diagnostics: list = field(default_factory=list)
    diagnostics_version: Optional[int] = None

    # fileProgress: list of currently-processing ranges; fatal flag.
    processing: list = field(default_factory=list)
    fatal_error: bool = False

    # $/lean/staleDependency was received; a reopen would pick up new imports.
    stale_imports: bool = False

    crash_message: str = ""

    def lines(self) -> list[str]:
        return self.text.splitlines()

    def touch(self) -> None:
        self.last_used = time.monotonic()

    # -- notification intake (called from the client's dispatcher) -----------

    def on_publish_diagnostics(self, params: dict) -> None:
        version = params.get("version")
        # Ignore diagnostics for versions older than what we sent; accept
        # untagged ones (shouldn't happen with Lean >= 4.24, but harmless).
        if version is not None and version < self.version:
            return
        self.diagnostics = params.get("diagnostics", [])
        self.diagnostics_version = version

    def on_file_progress(self, params: dict) -> None:
        processing = params.get("processing", [])
        self.processing = processing
        for entry in processing:
            if entry.get("kind") == 2:  # fatalError
                self.fatal_error = True

    def on_stale_dependency(self) -> None:
        self.stale_imports = True

    def mark_crashed(self, message: str) -> None:
        self.status = DocStatus.CRASHED
        self.crash_message = message

    def reset_after_reopen(self, text: str) -> None:
        self.text = text
        self.version += 1  # keep versions monotonic across revivals
        self.status = DocStatus.OPENING
        self.diagnostics = []
        self.diagnostics_version = None
        self.processing = []
        self.fatal_error = False
        self.stale_imports = False
        self.crash_message = ""
