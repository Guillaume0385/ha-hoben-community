"""Opt-in session-300 limits and framing under the owner's V4 hypothesis.

This is not a proof of the OpenedClient boundary. Only the dedicated reference
Osmose experiment may opt in; ordinary sessions retain their conservative RX.
No register interpretation, Home Assistant or research capture lives here.
"""

import time
from dataclasses import dataclass, field

from .error_phases import error_boundary
from .exceptions import HobenClosedError, HobenProtocolError
from .frame_diagnostic import FrameDiagnostic, FrameEvidence
from .malformed import MalformedDiagnostic, message_name
from .modbus import modbus_tcp_frame_size
from .myhoben import decode_close_client
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
    "close_client": {"close_client"},
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
# Post-open only: opening/authorization codecs and TX Pong remain unchanged.
UNSUPPORTED_MESSAGE_TYPES = KNOWN_TYPE_DISCRIMINANTS - {5, 7, 10, 14, 27}
IGNORED_PREFIXES = {7: 1, 27: 5}


class UnsupportedMessageTypeError(HobenProtocolError):
    """A known post-open type without a framing contract; no payload retained."""

    code = "unsupported_message_type"

    def __init__(self, message_type):
        if (
            type(message_type) is not int
            or message_type not in UNSUPPORTED_MESSAGE_TYPES
        ):
            raise ValueError("invalid_unsupported_message_type")
        self.message_type = message_type
        super().__init__()

    def safe_report(self):
        return super().safe_report() | {"message_type": self.message_type}


class Session300BudgetError(HobenProtocolError):
    """A fixed experimental limit was reached; never retry or echo input."""

    code = "session_300_budget"


class _RejectedCloseClient(HobenProtocolError):
    """Private classification of the rejected head only, never a full frame."""


class ExperimentalCloseClientError(HobenClosedError):
    """Terminal post-open event under #112's experimental two-byte contract.

    Neither a universal protocol length nor a TLS EOF. Keep the UInt8 even when
    its meaning is unknown; never attach remaining RX or an exchange to errors.
    """

    code = "experimental_close_client"

    def __init__(self, subcode):
        if type(subcode) is not int or not 0 <= subcode <= 255:
            raise ValueError("invalid_close_client_subcode")
        self.subcode = subcode
        self._cleanup_failed = False
        super().__init__(decode_close_client(bytes((5, subcode))))

    def safe_report(self):
        return super().safe_report() | {
            "state": "closed",
            "subcode": self.subcode,
            "phase": "post_open",
        }


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
        # Dense histograms bound storage independently of the number of events.
        # Bin i means total length prefix + 6 + 2 + i (MBAP.length 2..254).
        self.ignored_messages = {str(t): [0] * 253 for t in IGNORED_PREFIXES}
        self.close_client_subcodes = []

    def note_close_client(self, subcode):
        if len(self.close_client_subcodes) >= 3:
            raise Session300BudgetError()
        self.close_client_subcodes.append(subcode)
        self.note_failure("close_client", "closed", "close_client")

    def close_client_diagnostic(self, after_threshold_ms=None):
        """At most one numeric code per opening, never bytes or identifiers."""
        if not self.close_client_subcodes:
            return {}
        return {
            "close_client": {
                "phase": "post_open",
                "subcodes": self.close_client_subcodes.copy(),
                "after_threshold_ms": after_threshold_ms,
            }
        }

    def note_ignored(self, message_type, total_length):
        prefix = IGNORED_PREFIXES[message_type]
        self.ignored_messages[str(message_type)][total_length - prefix - 8] += 1

    def ignored_diagnostic(self):
        """Optional closed extension; never backfill a historical observation."""
        if not any(any(bins) for bins in self.ignored_messages.values()):
            return {}
        return {
            "ignored_messages": {
                t: bins.copy() for t, bins in self.ignored_messages.items()
            }
        }

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
            or category not in {"protocol", "transport", "budget", "closed"}
            or message not in self.diagnostic_messages[phase]
            or (category == "closed") != (phase == "close_client")
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
    evidence: FrameEvidence = field(
        default_factory=FrameEvidence, repr=False, compare=False
    )


class ExperimentalV4Framer:
    """Incremental Ping/MBAP framing, never scanning past an unknown byte.

    The first byte of each frame binds its exchange, including across reads.
    All frames from a single delivered read retain that read's exchange even
    if answering Ping yields and lets another caller register a new request.
    """

    def __init__(
        self, *, diagnostic=None, _reject_close_client=False, recover_data_updated=False
    ):
        self._buffer = bytearray()
        self._exchange = None
        self._diagnostic = diagnostic
        self._remaining = 0
        self._ignored_type = self._ignored_size = None
        self._tail = None
        # Preserve the separate, dormant private EOF-quarantine contract.
        self._reject_close_client = _reject_close_client
        self._recover_data_updated = recover_data_updated
        self.invalid_data_updated = None
        self.frame_log = FrameDiagnostic()

    def _fail(self, phase, message):
        self.frame_log.failure_phase = phase
        self.frame_log.header()
        if self._diagnostic is not None:
            self._diagnostic.note_failure(phase, "protocol", message)
        if (
            type(self._diagnostic) is SessionReconnect
            and phase == "message_classification"
            and message == "close_client"
        ):
            raise _RejectedCloseClient()
        if (
            phase == "message_classification"
            and self._buffer[0] in UNSUPPORTED_MESSAGE_TYPES
        ):
            raise UnsupportedMessageTypeError(self._buffer[0])
        raise HobenProtocolError(
            MalformedDiagnostic(
                phase=phase,
                message_type=message_name(self._buffer[0] if self._buffer else None),
                received_length=len(self._buffer),
                length_scope="mbap_header"
                if phase == "frame_boundary"
                else "not_proven",
                missing_fields="none"
                if phase == "frame_boundary" and self._buffer
                else "unknown",
                rejection="unknown_type"
                if phase == "message_classification"
                else "invalid_mbap",
            )
        )

    def incomplete_error(self):
        """Describe an EOF in a partial frame without publishing any buffered byte."""
        head = self._buffer[0] if self._buffer else self._ignored_type
        received = len(self._buffer)
        expected = "not_proven"
        missing = "mbap_header"
        scope = "mbap_header"
        if self._remaining:
            received = self._ignored_size - self._remaining
            expected = self._ignored_size
            missing, scope = "message_body", "frame"
        elif head == 5:
            missing, scope = "close_subcode", "not_proven"
        elif head in {7, 14, 27}:
            prefix = IGNORED_PREFIXES.get(head, 1)
            if received >= prefix + 6:
                expected = prefix + modbus_tcp_frame_size(
                    bytes(self._buffer[prefix : prefix + 6])
                )
                missing, scope = "message_body", "frame"
        else:
            missing, scope = "unknown", "not_proven"
        error = HobenProtocolError(
            MalformedDiagnostic(
                phase="frame_boundary",
                message_type=message_name(head),
                received_length=received,
                expected_length=expected,
                length_scope=scope,
                missing_fields=missing,
                rejection="incomplete_frame",
            )
        )
        self.frame_log.failure(error, status="partial")
        return error

    def clear(self):
        self._buffer.clear()
        self._exchange = None
        self._remaining = 0
        self._ignored_type = self._ignored_size = None
        self._tail = None
        self.invalid_data_updated = None
        self.frame_log.clear()

    @property
    def partial(self):
        return bool(self._buffer) or self._remaining > 0 or self._tail is not None

    def feed(self, data: bytes, exchange: object):
        try:
            return self._feed(data, exchange)
        except Exception as error:
            self.frame_log.failure(
                error,
                status="invalid" if isinstance(error, HobenProtocolError) else None,
            )
            raise

    def _feed(self, data: bytes, exchange: object):
        if not isinstance(data, bytes) or len(data) > 4096:
            self._fail("frame_boundary", "unclassified")
        if self._tail is not None:
            # Drain retained coalesced bytes before accepting another chunk.
            # This bounds retention to one original <=4096-byte delivery.
            if data:
                self._fail("frame_boundary", "ambiguous")
            data, exchange = self._tail
            self._tail = None
        events = []
        for index, byte in enumerate(data):
            if self._remaining:
                # Consume exactly the validated body; never retain or decode it.
                self._remaining -= 1
                self.frame_log.received()
                if not self._remaining and self._diagnostic is not None:
                    self._diagnostic.note_ignored(
                        self._ignored_type, self._ignored_size
                    )
                if not self._remaining:
                    self.frame_log.finish()
                continue
            if not self._buffer:
                self._exchange = exchange
                self.frame_log.start(byte)
            self._buffer.append(byte)
            self.frame_log.received()
            if self._buffer[0] == 10:
                self.frame_log.header(1, provenance="fixed_contract", scope="frame")
                events.append(
                    ExperimentalFrame(b"\x0a", self._exchange, self.frame_log.finish())
                )
                self._buffer.clear()
            elif self._buffer[0] == 5 and not self._reject_close_client:
                self.frame_log.header(
                    2, provenance="fixed_contract", scope="post_open_hypothesis"
                )
                # Owner-authorized hypothesis (#6395141200), not wire proof.
                if len(self._buffer) == 2:
                    events.append(
                        ExperimentalFrame(
                            bytes(self._buffer), self._exchange, self.frame_log.finish()
                        )
                    )
                    self._buffer.clear()
                    if index + 1 < len(data):
                        self._tail = (data[index + 1 :], exchange)
                    return events  # Never scan/process bytes past terminal RX.
            elif self._buffer[0] not in {7, 14, 27}:
                message = (
                    "unknown"
                    if self._diagnostic is None
                    else self._diagnostic.rejected_type_category(self._buffer[0])
                )
                self._fail("message_classification", message)
            else:
                prefix = IGNORED_PREFIXES.get(self._buffer[0], 1)
                if len(self._buffer) < prefix + 6:
                    continue
                try:
                    with error_boundary("mbap_header"):
                        size = prefix + modbus_tcp_frame_size(
                            bytes(self._buffer[prefix : prefix + 6])
                        )
                except (TypeError, ValueError):
                    self.frame_log.header()
                    self.frame_log.failure(
                        HobenProtocolError(), phase="mbap_header", status="invalid"
                    )
                    if self._buffer[0] == 27 and self._recover_data_updated:
                        # Only persistent reception opts into owner-authorized
                        # recovery. No size/boundary is inferred from this header.
                        length = int.from_bytes(self._buffer[9:11], "big")
                        self.clear()
                        self.invalid_data_updated = (
                            length,
                            "invalid_length"
                            if not 2 <= length <= 254
                            else "invalid_protocol",
                        )
                        return []
                    self._fail("frame_boundary", "ambiguous")
                self.frame_log.header(
                    size, provenance="validated_header", scope="frame"
                )
                if self._buffer[0] in IGNORED_PREFIXES:
                    self._ignored_type, self._ignored_size = self._buffer[0], size
                    self._remaining = size - len(self._buffer)
                    self._buffer.clear()
                    self._exchange = None
                    continue
                if len(self._buffer) == size:
                    events.append(
                        ExperimentalFrame(
                            bytes(self._buffer), self._exchange, self.frame_log.finish()
                        )
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
