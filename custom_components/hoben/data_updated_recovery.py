"""Bounded private state for #160's explicitly authorized silence hypothesis.

Silence is not wire-boundary evidence. No bytes, metadata or register decoding
live here; the original session remains the sole transport reader and writer.
"""

import asyncio
from dataclasses import dataclass


@dataclass(repr=False)
class DataUpdatedRecovery:
    """One episode; error outcomes are values so abandoned shields cannot log them."""

    active: bool = False
    probing: bool = False
    quiet_since: float = 0.0
    probe_started: float = 0.0
    read_deadline: asyncio.Timeout | None = None
    task: asyncio.Task | None = None
    result: asyncio.Future | None = None
    observer: bool = False
    consumed: bool = True
    warned: bool = False
    failure_logged: bool = False

    def __repr__(self):
        return "DataUpdatedRecovery()"

    def begin(self):
        loop = asyncio.get_running_loop()
        if not self.active:
            self.result = loop.create_future()
            self.consumed = False
        self.active = True
        self.probing = False
        self.quiet_since = loop.time()
