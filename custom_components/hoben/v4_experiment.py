"""Opt-in session-300 limits and framing under the owner's V4 hypothesis.

This is not a proof of the OpenedClient boundary. Only the dedicated reference
Osmose experiment may opt in; ordinary sessions retain their conservative RX.
No register interpretation, Home Assistant or research capture lives here.
"""

import time
from dataclasses import dataclass, field

from .exceptions import HobenProtocolError
from .modbus import modbus_tcp_frame_size
from .transport import TransportError

DIAGNOSTIC_MESSAGES = {
    "none": {"unclassified"},
    "opening": {"unclassified"},
    "scheduled_read": {"unclassified"},
    "lifecycle_transition": {"unclassified"},
    "teardown": {"unclassified"},
    "tls_read": {"unclassified"},
    "frame_boundary": {"unclassified", "ambiguous"},
    "message_classification": {"unknown"},
    "request_correlation": {"data_response"},
    "response_validation": {"data_response"},
    "pong_tx": {"ping"},
}
RECONNECT_DIAGNOSTIC_MESSAGES = DIAGNOSTIC_MESSAGES | {
    "message_classification": {
        "close_client",
        "data_updated",
        "other_known",
        "unknown",
        "unclassified",
    }
}
# Only the discriminator names listed in protocol.md §3, never message lengths.
KNOWN_TYPE_DISCRIMINANTS = frozenset((*range(25), *range(26, 49), *range(80, 89), 96))


class Session300BudgetError(HobenProtocolError):
    """A fixed experimental limit was reached; never retry or echo input."""

    code = "session_300_budget"


class _RejectedCloseClient(HobenProtocolError):
    """Private classification of the rejected head only, never a full frame."""


class Session300:
    """One shared lifetime budget, explicitly named for the fixed experiment."""

    MAX_READS = 6
    diagnostic_messages = DIAGNOSTIC_MESSAGES

    def rejected_type_category(self, discriminator):
        """Keep the historical session-300 diagnostic contract unchanged."""
        return "unknown"

    def __init__(self, *, clock=time.monotonic):
        self.clock = clock
        self.opens = self.rx_bytes = self.rx_chunks = self.pings = self.pongs = 0
        self.requests = self.responses = 0
        self.partial = False
        self.connected_generation = None
        self._last_read = None
        self.failure = None

    def __repr__(self):
        return "Session300()"

    def opening(self):
        if self.opens >= 3:
            raise Session300BudgetError()
        self.opens += 1
        self.failure = None  # A recovered transport cannot describe a later loss.

    def note_failure(self, phase, category, message="unclassified"):
        """Retain the first fixed diagnostic; teardown must not overwrite it.

        These tokens describe the code path, never payload, a transaction ID or
        a proven wire boundary. Only existing parser decisions call this hook.
        """
        if (
            phase not in self.diagnostic_messages
            or category not in {"protocol", "transport", "budget"}
            or message not in self.diagnostic_messages[phase]
        ):
            raise ValueError("invalid_session_300_diagnostic")
        if self.failure is None:
            self.failure = (phase, category, message)

    @property
    def usable(self):
        return self.connected_generation == self.opens and not self.partial

    def accepted(self, generation):
        self.connected_generation = generation

    def lost(self, generation):
        if self.connected_generation == generation:
            self.connected_generation = None

    def receive(self, data):
        if not isinstance(data, bytes) or len(data) > 4096:
            raise Session300BudgetError()
        self.rx_chunks += bool(data)  # EOF is not a received data chunk.
        self.rx_bytes += len(data)
        if self.rx_bytes > 1048576:
            raise Session300BudgetError()

    @property
    def next_read_at(self):
        return 0 if self._last_read is None else self._last_read + 60

    def request(self):
        now = self.clock()
        if self.requests >= self.MAX_READS or (
            self._last_read is not None and now - self._last_read < 60
        ):
            raise Session300BudgetError()
        self.requests += 1
        self._last_read = now


class SessionReconnect(Session300):
    """Fixed second-scenario budget, never an extension of Session300 defaults.

    Acceptance/loss callbacks come from the sole session owner, so a loss and
    recovery between collector ticks cannot masquerade as continuous stability.
    Ten reads share one cadence across every opening; no budget is replenished.
    """

    MAX_READS = 10
    diagnostic_messages = RECONNECT_DIAGNOSTIC_MESSAGES

    def rejected_type_category(self, discriminator):
        """Name the rejected head byte only; no payload or boundary inference."""
        if discriminator == 5:
            return "close_client"
        if discriminator == 27:
            return "data_updated"
        return "other_known" if discriminator in KNOWN_TYPE_DISCRIMINANTS else "unknown"

    def __init__(self, *, clock=time.monotonic):
        super().__init__(clock=clock)
        self.accepted_at = None
        self.generation_pongs = 0
        self.last_lost_generation = None

    def __repr__(self):
        return "SessionReconnect()"

    def accepted(self, generation):
        super().accepted(generation)
        self.accepted_at = self.clock()
        self.generation_pongs = self.pongs

    def lost(self, generation):
        if self.connected_generation == generation and generation is not None:
            self.last_lost_generation = generation
            self.accepted_at = None
        super().lost(generation)


@dataclass(frozen=True, slots=True)
class ExperimentalFrame:
    """Private payload and the exchange active at its first delivered byte."""

    payload: bytes = field(repr=False)
    exchange: object = field(repr=False)


class ExperimentalV4Framer:
    """Incremental Ping/MBAP framing, never scanning past an unknown byte.

    The first byte of each frame binds its exchange, including across reads.
    All frames from a single delivered read retain that read's exchange even
    if answering Ping yields and lets another caller register a new request.
    """

    def __init__(self, *, diagnostic=None):
        self._buffer = bytearray()
        self._exchange = None
        self._diagnostic = diagnostic

    def _fail(self, phase, message):
        if self._diagnostic is not None:
            self._diagnostic.note_failure(phase, "protocol", message)
        if (
            type(self._diagnostic) is SessionReconnect
            and phase == "message_classification"
            and message == "close_client"
        ):
            raise _RejectedCloseClient()
        raise HobenProtocolError()

    def clear(self):
        self._buffer.clear()
        self._exchange = None

    @property
    def partial(self):
        return bool(self._buffer)

    def feed(self, data: bytes, exchange: object):
        if not isinstance(data, bytes) or len(data) > 4096:
            self._fail("frame_boundary", "unclassified")
        events = []
        for byte in data:
            if not self._buffer:
                self._exchange = exchange
            self._buffer.append(byte)
            if self._buffer[0] == 10:
                events.append(ExperimentalFrame(b"\x0a", self._exchange))
                self._buffer.clear()
            elif self._buffer[0] != 14:
                # Includes DataUpdated: no new interpretation or resync.
                message = (
                    "unknown"
                    if self._diagnostic is None
                    else self._diagnostic.rejected_type_category(self._buffer[0])
                )
                self._fail("message_classification", message)
            elif len(self._buffer) >= 7:
                try:
                    size = 1 + modbus_tcp_frame_size(bytes(self._buffer[1:7]))
                except (TypeError, ValueError):
                    self._fail("frame_boundary", "ambiguous")
                if len(self._buffer) == size:
                    events.append(
                        ExperimentalFrame(bytes(self._buffer), self._exchange)
                    )
                    self._buffer.clear()
        return events


class BudgetTransport:
    """Count delivered bytes, including opening, without introducing a reader."""

    def __init__(self, transport, budget: Session300):
        self._transport = transport
        self._budget = budget

    async def connect(self):
        await self._transport.connect()

    async def read(self, max_bytes=4096, *, bounded=True):
        try:
            data = await self._transport.read(min(max_bytes, 4096), bounded=bounded)
        except TransportError:
            self._budget.note_failure("tls_read", "transport")
            raise
        try:
            self._budget.receive(data)
        except Session300BudgetError:
            self._budget.note_failure("tls_read", "budget")
            raise
        return data

    async def write(self, data):
        await self._transport.write(data)

    async def close(self):
        await self._transport.close()
