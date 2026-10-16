"""HA-independent V4 opening and conservative RX ownership, without routing.

OpenClient is the opening request. The observed V4 OpenedClient response has a
decodable 48-byte prefix, not a proven complete-message boundary. This skeleton
retains opening bytes privately in ordinary mode. Only an explicit Session300
budget opts into the owner's local experimental handoff hypothesis.
"""

import asyncio
import math
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from enum import Enum, StrEnum
from typing import Protocol

from .client import (
    DEFAULT_BUILD,
    DEFAULT_DEVICE_INFO,
    _validate_delay,
    _validate_device_guid,
)
from .exceptions import (
    HobenAmbiguousSessionError,
    HobenAuthorizationRequiredError,
    HobenClientClosedError,
    HobenClosedError,
    HobenError,
    HobenInvalidCredentialsError,
    HobenInvalidInputError,
    HobenModbusError,
    HobenProtocolError,
    HobenTimeoutError,
    HobenTransportError,
    HobenUnsupportedProfileError,
)
from .modbus import (
    HOBEN_UNIT_ID,
    READ_INPUT_REGISTERS,
    ModbusExceptionResponse,
    ModbusReadResponse,
    build_read_input_registers,
    decode_read_response,
)
from .myhoben import (
    INITIAL_DEVICE_GUID,
    CloseClientReason,
    decode_data_response_client,
    encode_data_request_client,
    encode_open_client,
)
from .profiles import StoveProfile
from .session import (
    _PING,
    _PONG,
    AuthorizationRequiredResult,
    ClosedSessionResult,
    OpenSessionResult,
    SessionTimeout,
    _open_session,
)
from .transport import AsyncTlsTransport, TransportEOF, TransportError, TransportTimeout
from .v4_eof_quarantine import (
    MAX_TIME_MS,
    EofQuarantinePolicy,
    Event,
    Reason,
    Rejection,
    Scenario,
    State,
)
from .v4_experiment import (
    BudgetTransport,
    ExperimentalV4Framer,
    Session300,
    SessionReconnect,
    _RejectedCloseClient,
)
from .v4_no_pong import NoPongAfter120


class SessionState(StrEnum):
    """Local lifecycle; CONNECTED will require an accepted, safe V4 opening."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    QUARANTINED = "quarantined"
    RECONNECTING = "reconnecting"
    CLOSED = "closed"


class HandoffState(StrEnum):
    """No current evidence promotes UNPROVEN to a routable message boundary."""

    UNPROVEN = "unproven"
    AMBIGUOUS = "ambiguous"
    EXPERIMENTAL = "experimental_hypothesis"


class DelimitedV4Message(Enum):
    """Semantic input from an explicit framing contract, never raw RX input.

    This token does not prove a boundary. Ordinary RX never creates it. The
    session-300 framer may create it under the explicit local hypothesis, with
    boundary_proven remaining false and no generalization to ordinary sessions.
    """

    PING = _PING


class DelimitedV4DataResponse:
    """Private bytes of one complete response, bound to its originating exchange.

    This contract is not a framer or proof of wire freshness. Every framer must
    preserve the originating exchange, never relabel old bytes with a new waiter.
    Only session-300 currently routes RX under its named experimental hypothesis.
    """

    __slots__ = ("_frame", "_exchange")

    def __init__(self, frame: bytes, *, exchange: object) -> None:
        if not isinstance(frame, bytes):
            raise HobenProtocolError()
        self._frame = frame
        self._exchange = exchange

    def __repr__(self) -> str:
        return "DelimitedV4DataResponse()"


@dataclass(frozen=True, slots=True)
class OpeningMetadata:
    """Allowlisted V4 prefix metadata; no identity or claim of complete framing."""

    product_type: int
    product_revision: int
    software_major: int
    software_minor: int
    application_version: int


@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    """Immutable lifecycle view, without identity, RX or household data."""

    state: SessionState
    opening: OpeningMetadata | None = None
    unclassified_bytes: int = 0
    boundary_proven: bool = False
    handoff: HandoffState = HandoffState.UNPROVEN
    rx_error: str | None = None


class SessionTransport(Protocol):
    """Injectable async byte transport; ownership belongs to the future session.

    The factory must eventually provide a fresh verified TLS transport to the
    fixed production destination. Tests inject a wholly offline implementation.
    """

    async def connect(self) -> None: ...

    async def read(self, max_bytes: int = 4096, *, bounded: bool = True) -> bytes: ...

    async def write(self, data: bytes) -> None: ...

    async def close(self) -> None: ...


TransportFactory = Callable[[], SessionTransport]


class SessionStateError(RuntimeError):
    """An invalid lifecycle operation, with fixed payload-free text."""

    def __init__(self) -> None:
        super().__init__("invalid_session_state")


class SessionNotImplementedError(NotImplementedError):
    """The operation has no implementation yet; never report fake success."""

    def __init__(self) -> None:
        super().__init__("session_operation_not_implemented")


class _QuarantinedRead(HobenProtocolError):
    """Private waiter completion; neither a retryable loss nor a close request."""

    code = "session_quarantined"


class _QuarantineOrigin(StrEnum):
    NONE = "none"
    TRANSPORT_READ = "transport_read"


@dataclass(frozen=True, slots=True)
class _QuarantineObservation:
    """Private, provisional scalar observation; never a recovery result."""

    generation: int | None
    at_ms: int | None
    origin: _QuarantineOrigin
    state: State
    reason: Reason


class _QuarantineCapability:
    """One-use internal binding, supplied by offline tests only in L4.

    No environment/input factory exists. Bind exact owners before any opening;
    V4Session rechecks their identity. Deadlines use the budget clock's monotonic
    domain in integer milliseconds. They may shorten, never extend T0+240 s.
    """

    __slots__ = ("_budget", "_no_pong", "_deadlines", "_claimed")

    def __init__(
        self,
        budget,
        no_pong,
        *,
        observation_deadline_ms,
        process_deadline_ms,
        suite_deadline_ms,
    ):
        deadlines = (observation_deadline_ms, process_deadline_ms, suite_deadline_ms)
        if (
            type(budget) is not SessionReconnect
            or type(no_pong) is not NoPongAfter120
            or budget.opens != 0
            or no_pong.first_generation is not None
            or budget.clock is not no_pong._clock
            or not all(type(t) is int and 0 <= t <= MAX_TIME_MS for t in deadlines)
        ):
            raise HobenInvalidInputError()
        self._budget, self._no_pong = budget, no_pong
        self._deadlines = deadlines
        self._claimed = False

    def __repr__(self):
        return "_QuarantineCapability()"


_TRANSITIONS = {
    SessionState.DISCONNECTED: frozenset(
        {SessionState.CONNECTING, SessionState.CLOSED}
    ),
    SessionState.CONNECTING: frozenset(
        {SessionState.CONNECTED, SessionState.DISCONNECTED, SessionState.CLOSED}
    ),
    SessionState.CONNECTED: frozenset(
        {
            SessionState.RECONNECTING,
            SessionState.DISCONNECTED,
            SessionState.CLOSED,
            SessionState.QUARANTINED,
        }
    ),
    SessionState.QUARANTINED: frozenset(
        {SessionState.DISCONNECTED, SessionState.CLOSED}
    ),
    SessionState.RECONNECTING: frozenset(
        {SessionState.CONNECTED, SessionState.DISCONNECTED, SessionState.CLOSED}
    ),
    SessionState.CLOSED: frozenset(),
}


class V4Session:
    """Reusable contract for probes and clients, independent of their runners.

    CONNECTED means an accepted V4 prefix with no already-received suffix. It
    does not prove a complete boundary or authorize routing. One RX owner waits
    after opening; any further bytes are ambiguous and cause safe closure. The
    default factory creates verified TLS to myhoben.fr:465 only.
    """

    __slots__ = (
        "_snapshot",
        "_transport_factory",
        "_transport",
        "_opening_task",
        "_opening_buffer",
        "_user_guid",
        "_device_guid",
        "_rx_task",
        "_rx_error",
        "_tx_lock",
        "_pending_read",
        "_read_sent",
        "_loss_event",
        "_retryable_loss",
        "_operations",
        "_tx_operations",
        "_experiment",
        "_experiment_generation",
        "_framer",
        "_no_pong",
        "_quarantine_capability",
        "_quarantine_policy",
        "_quarantine_latched",
        "_quarantine_observation",
        "_tx_in_flight",
        "_read_timeout",
    )

    def __init__(
        self,
        *,
        user_guid: str | None = None,
        device_guid: str = INITIAL_DEVICE_GUID,
        transport_factory: TransportFactory = AsyncTlsTransport,
        session_300: Session300 | None = None,
        no_pong_after_120: NoPongAfter120 | None = None,
        _quarantine: _QuarantineCapability | None = None,
    ) -> None:
        if not callable(transport_factory):
            raise TypeError("transport_factory_must_be_callable")
        if session_300 is not None and type(session_300) not in (
            Session300,
            SessionReconnect,
        ):
            raise HobenInvalidInputError()
        if no_pong_after_120 is not None and (
            type(no_pong_after_120) is not NoPongAfter120 or session_300 is None
        ):
            raise HobenInvalidInputError()
        if _quarantine is not None:
            if (
                type(_quarantine) is not _QuarantineCapability
                or _quarantine._budget is not session_300
                or _quarantine._no_pong is not no_pong_after_120
                or _quarantine._claimed
                or type(session_300) is not SessionReconnect
                or type(no_pong_after_120) is not NoPongAfter120
                or session_300.opens != 0
                or no_pong_after_120.first_generation is not None
            ):
                raise HobenInvalidInputError()
            _quarantine._claimed = True
        self._quarantine_capability = _quarantine
        self._quarantine_policy = None
        self._quarantine_latched = False
        self._quarantine_observation = None
        self._tx_in_flight = False
        self._read_timeout = None
        self._no_pong = no_pong_after_120
        self._experiment = session_300
        self._experiment_generation = None
        self._framer = (
            ExperimentalV4Framer(diagnostic=session_300)
            if session_300 is not None
            else None
        )
        self._transport_factory = transport_factory
        self._snapshot = SessionSnapshot(SessionState.DISCONNECTED)
        self._transport: SessionTransport | None = None
        self._opening_task: asyncio.Task | None = None
        self._opening_buffer = bytearray()
        self._user_guid = user_guid
        self._device_guid = device_guid
        self._rx_task: asyncio.Task[HobenError | None] | None = None
        self._rx_error: HobenError | None = None
        self._tx_lock = asyncio.Lock()
        self._pending_read: asyncio.Future[ModbusReadResponse] | None = None
        self._read_sent = False
        self._loss_event = asyncio.Event()
        self._retryable_loss = False
        self._operations: dict[asyncio.Task, asyncio.Future[None]] = {}
        self._tx_operations: set[asyncio.Task] = set()

    @asynccontextmanager
    async def _transmitting(self):
        """Record queued/active senders so abort never cancels read-error delivery."""
        task = asyncio.current_task()
        self._tx_operations.add(task)
        try:
            async with self._tx_lock:
                yield
        finally:
            self._tx_operations.discard(task)

    @property
    def loss_is_retryable(self) -> bool:
        """True only for an observed transport loss, never caller cancellation."""
        return self._retryable_loss

    async def wait_lost(self) -> None:
        """Notify lifecycle ownership before RX cleanup waits for an active TX.

        This is a terminal notification, never an idle/read deadline. The owner
        can abort active operations before waiting for the old transport to close.
        """
        await self._loss_event.wait()
        raise self._rx_error or HobenClientClosedError()

    async def abort(self) -> None:
        """Stop owned TX/read operations, then finish the existing close path.

        Lifecycle teardown uses this stronger stop; ordinary close retains its
        existing orderly-TX semantics. Never cancel the calling teardown task.
        """
        self._quarantine_stop(Event.CANCEL)
        if self.state is not SessionState.CLOSED:
            self._transition(SessionState.CLOSED)
        if self._experiment is not None:
            self._experiment.lost(self._experiment_generation)
        self._loss_event.set()
        self._fail_pending_read(self._rx_error or HobenClientClosedError())
        operations = [
            (task, done)
            for task, done in self._operations.items()
            if task is not asyncio.current_task()
        ]
        for task, _ in operations:
            if (
                task in self._tx_operations
                and not task.done()
                and not task.cancelling()
            ):
                task.cancel()
        # Wait for each operation's completion, never for its caller's whole
        # lifetime: the caller may immediately wait for this same recovery.
        await asyncio.gather(*(asyncio.shield(done) for _, done in operations))
        await self.close()

    def _fail_pending_read(self, error: HobenError) -> None:
        """Complete the sole waiter at most once, without exposing its payload."""
        pending = self._pending_read
        if pending is not None and not pending.done():
            pending.set_exception(error)

    def __repr__(self) -> str:
        return f"V4Session(state={self.state.value})"

    @property
    def state(self) -> SessionState:
        """Return the current lifecycle state."""
        return self._snapshot.state

    @property
    def snapshot(self) -> SessionSnapshot:
        """Return a detached immutable view, never a transport or identity."""
        return self._snapshot

    def _transition(self, target: SessionState) -> None:
        """Apply an internal lifecycle edge; CLOSED is terminal."""
        if (
            not isinstance(target, SessionState)
            or target not in _TRANSITIONS[self.state]
        ):
            raise SessionStateError()
        self._snapshot = replace(self._snapshot, state=target)

    @property
    def device_guid_for_persistence(self) -> str:
        """Explicit private identity access; never include this value in reports."""
        return self._device_guid

    async def _release_transport(self) -> None:
        """Wait for any current TX, then detach and close exactly once."""
        async with self._tx_lock:
            transport, self._transport = self._transport, None
            if transport is not None:
                try:
                    await transport.close()
                except Exception:
                    raise HobenTransportError() from None

    async def _handle_delimited_ping(self, message: DelimitedV4Message) -> bool:
        """Track the sender so lifecycle shutdown can abort an in-flight write."""
        task = asyncio.current_task()
        done = asyncio.get_running_loop().create_future()
        self._operations[task] = done
        try:
            return await self._send_delimited_ping(message)
        finally:
            self._operations.pop(task, None)
            done.set_result(None)

    async def _send_delimited_ping(self, message: DelimitedV4Message) -> bool:
        """Respond once to an already-delimited Ping (protocol.md §3).

        This primitive accepts semantic tokens, never raw bytes. Ordinary RX
        does not call it. Only session-300 routes framed events under the local
        experimental handoff hypothesis; a boundary is still not proven.
        A failed/cancelled write closes without replay, since emission is uncertain.
        """
        if message is not DelimitedV4Message.PING:
            raise HobenProtocolError()
        transport = self._transport
        error: HobenError | None = None
        cancelled = False
        async with self._transmitting():
            self._require_tx_allowed()
            # Recheck under the lock: a queued Pong must not outlive RX failure
            # or close(), nor be sent on a replacement/absent transport.
            if self._rx_error is not None:
                raise self._rx_error from None
            if (
                self.state is not SessionState.CONNECTED
                or transport is None
                or self._transport is not transport
            ):
                raise SessionStateError()
            if self._no_pong is not None and self._no_pong.suppress(
                self._experiment_generation
            ):
                return False
            try:
                self._tx_in_flight = True
                try:
                    await transport.write(_PONG)
                finally:
                    self._tx_in_flight = False
            except asyncio.CancelledError:
                cancelled = True
                error = HobenTransportError()
            except TransportError as failure:
                if self._rx_error is None:
                    self._retryable_loss = not isinstance(failure, TransportTimeout)
                error = HobenTransportError()
            except Exception:
                error = HobenProtocolError()
            if error is not None:
                # Stop queued TX before releasing the lock for shutdown.
                self._rx_error = self._rx_error or error
                self._loss_event.set()
                self._fail_pending_read(self._rx_error)
                self._snapshot = replace(self._snapshot, rx_error=self._rx_error.code)
                if self.state is not SessionState.CLOSED:
                    self._transition(SessionState.CLOSED)
        if error is not None:
            try:
                await self.close()
            except HobenTransportError:
                pass  # Retain the primary, sanitized transmission failure.
            if cancelled:
                raise asyncio.CancelledError()
            raise error from None
        return True

    async def connect(self) -> None:
        """Accept only the existing V4 opening, without post-open processing.

        Reject concurrent/repeated calls rather than opening twice. Unknown
        suffixes remain private until explicit close or a fresh opening attempt.
        Their absence now says nothing about bytes that may arrive later.
        """
        if self.state is not SessionState.DISCONNECTED or self._quarantine_latched:
            raise SessionStateError()
        try:
            _validate_device_guid(self._device_guid)
            encode_open_client(
                self._user_guid, DEFAULT_BUILD, self._device_guid, DEFAULT_DEVICE_INFO
            )
        except (TypeError, ValueError):
            raise HobenInvalidInputError() from None
        self._snapshot = SessionSnapshot(SessionState.DISCONNECTED)
        self._opening_buffer.clear()
        self._rx_error = None
        self._loss_event.clear()
        self._retryable_loss = False
        self._rx_task = None
        self._transition(SessionState.CONNECTING)
        self._opening_task = asyncio.current_task()
        succeeded = False
        try:
            try:
                if self._experiment is not None:
                    self._experiment.opening()
                    self._experiment_generation = self._experiment.opens
                self._transport = self._transport_factory()
                if isinstance(self._transport, AsyncTlsTransport) and (
                    self._transport.host != "myhoben.fr" or self._transport.port != 465
                ):
                    raise HobenInvalidInputError()
                if self._experiment is not None:
                    self._transport = BudgetTransport(self._transport, self._experiment)
                result = await _open_session(
                    self._transport,
                    user_guid=self._user_guid,
                    device_guid=self._device_guid,
                    build=DEFAULT_BUILD,
                    device_info=DEFAULT_DEVICE_INFO,
                    response_buffer=self._opening_buffer,
                    answer_ping=False,
                )
                if isinstance(result, AuthorizationRequiredResult):
                    raise HobenAuthorizationRequiredError()
                if isinstance(result, ClosedSessionResult):
                    if result.reason is CloseClientReason.INVALID_IDENTIFIER:
                        raise HobenInvalidCredentialsError(result.reason)
                    raise HobenClosedError(result.reason)
                assert isinstance(result, OpenSessionResult)
                self._snapshot = replace(
                    self._snapshot, unclassified_bytes=result.unclassified_bytes
                )
                if result.unclassified_bytes and self._experiment is None:
                    self._snapshot = replace(
                        self._snapshot, handoff=HandoffState.AMBIGUOUS
                    )
                    raise HobenAmbiguousSessionError()
                if result.profile is not StoveProfile.V4:
                    raise HobenUnsupportedProfileError(result.profile)
                opened = result.opened_client
                assigned = _validate_device_guid(opened.device_guid)
                # No await between acceptance and state/identity adoption.
                self._snapshot = replace(
                    self._snapshot,
                    opening=OpeningMetadata(
                        opened.product_type,
                        opened.product_revision,
                        opened.software_major,
                        opened.software_minor,
                        opened.application_version,
                    ),
                )
                if self._experiment is not None:
                    self._snapshot = replace(
                        self._snapshot, handoff=HandoffState.EXPERIMENTAL
                    )
                self._device_guid = assigned
                if self._experiment is not None:
                    self._experiment.accepted(self._experiment_generation)
                if self._no_pong is not None:
                    self._no_pong.accepted(self._experiment_generation)
                if self._quarantine_capability is not None:
                    observation, process, suite = self._quarantine_capability._deadlines
                    self._quarantine_policy = EofQuarantinePolicy(
                        accepted_generation=self._experiment_generation,
                        accepted_at_ms=self._quarantine_time(
                            self._experiment.accepted_at
                        ),
                        observation_deadline_ms=observation,
                        process_deadline_ms=process,
                        suite_deadline_ms=suite,
                    )
                self._transition(SessionState.CONNECTED)
                # Handshake reads have finished before this sole RX task starts.
                self._rx_task = asyncio.create_task(
                    self._receive_unproven_handoff(self._transport), name="hoben-v4-rx"
                )
                succeeded = True
            except (TransportTimeout, SessionTimeout):
                raise HobenTimeoutError() from None
            except TransportError:
                raise HobenTransportError() from None
            except (
                HobenProtocolError,
                HobenAuthorizationRequiredError,
                HobenClosedError,
                HobenAmbiguousSessionError,
                HobenUnsupportedProfileError,
            ):
                raise
            except Exception:
                raise HobenProtocolError() from None
        finally:
            try:
                if not succeeded:
                    try:
                        await self._release_transport()
                    except HobenTransportError:
                        pass  # A secondary close failure must not mask the cause.
                    finally:
                        if self.state is not SessionState.CLOSED:
                            self._transition(SessionState.DISCONNECTED)
            finally:
                self._opening_task = None

    async def _receive_unproven_handoff(
        self, transport: SessionTransport
    ) -> HobenError | None:
        """Keep all delivered bytes; never guess a boundary or drain past failure.

        With current evidence the first nonempty post-prefix read must stop us,
        regardless of fragmentation, its leading byte or time spent silent.
        No future/read-request method may read this transport independently.
        """
        try:
            if self._experiment is not None:
                await self._receive_experimental(transport)
            else:
                data = await transport.read(4096, bounded=False)
                if not isinstance(data, bytes):
                    raise HobenProtocolError()
                if not data:
                    raise TransportEOF("eof")
                self._opening_buffer.extend(data)
                self._snapshot = replace(
                    self._snapshot,
                    handoff=HandoffState.AMBIGUOUS,
                    unclassified_bytes=len(data),
                )
                self._rx_error = HobenAmbiguousSessionError()
        except asyncio.CancelledError:
            if self.state is not SessionState.CLOSED:
                self._rx_error = HobenTransportError()
        except TransportError as failure:
            self._retryable_loss = not isinstance(failure, TransportTimeout)
            self._rx_error = HobenTransportError()
        except HobenError as failure:
            self._rx_error = failure
        except Exception:
            self._rx_error = HobenProtocolError()
        finally:
            if self._rx_error is not None:
                if self._experiment is not None:
                    self._experiment.lost(self._experiment_generation)
                self._loss_event.set()
                self._fail_pending_read(self._rx_error)
            try:
                await self._release_transport()
            except HobenTransportError:
                if self._rx_error is None and self.state is not SessionState.CLOSED:
                    self._rx_error = HobenTransportError()
            finally:
                self._snapshot = replace(
                    self._snapshot,
                    rx_error=self._rx_error.code if self._rx_error else None,
                )
                if self.state is not SessionState.CLOSED:
                    self._transition(SessionState.DISCONNECTED)
        # Bind an observer's outcome to this transport, even if a caller later
        # makes a fresh explicit connection and resets the current session error.
        return self._rx_error

    async def _receive_experimental(self, transport: SessionTransport) -> None:
        """Sole RX owner under the session-300 hypothesis; never proves a boundary."""
        data = bytes(self._opening_buffer[48:])
        self._opening_buffer.clear()
        first = True
        while True:
            exchange = (
                None if first else (self._pending_read if self._read_sent else None)
            )
            first = False
            events = []
            rejected_close = False
            try:
                events = self._framer.feed(data, exchange)
            except _RejectedCloseClient:
                rejected_close = True
            if rejected_close:
                if self._quarantine_policy is None:
                    raise HobenProtocolError()
                # Discard all unreturned events/suffixes before awaiting, outside
                # the exception handler so no traceback retains rejected bytes.
                data = b""
                self._framer.clear()
                if self._begin_quarantine():
                    await self._receive_quarantine(transport)
                # L4 never lets the lifecycle consume EOF or retry this refusal.
                raise HobenProtocolError()
            self._experiment.partial = self._framer.partial
            for event in events:
                if event.payload == b"\x0a":
                    self._experiment.pings += 1
                    try:
                        sent = await self._handle_delimited_ping(
                            DelimitedV4Message.PING
                        )
                    except HobenError as failure:
                        category = (
                            "transport"
                            if isinstance(failure, HobenTransportError)
                            else "protocol"
                        )
                        self._experiment.note_failure("pong_tx", category, "ping")
                        raise
                    self._experiment.pongs += sent
                else:
                    await self._handle_delimited_data_response(
                        DelimitedV4DataResponse(event.payload, exchange=event.exchange)
                    )
                    self._experiment.responses += 1
            try:
                data = await transport.read(4096, bounded=False)
            except TransportEOF:
                if self._no_pong is not None:
                    self._no_pong.peer_closed(self._experiment_generation)
                raise
            if not data:
                if self._no_pong is not None:
                    self._no_pong.peer_closed(self._experiment_generation)
                if self._framer.partial:
                    self._experiment.note_failure(
                        "frame_boundary", "protocol", "ambiguous"
                    )
                    raise HobenProtocolError()
                self._experiment.note_failure("tls_read", "transport")
                raise TransportEOF("eof")

    @staticmethod
    def _quarantine_time(seconds):
        """Conservatively quantize the existing injected monotonic clock.

        Equal millisecond timestamps remain ambiguous under the pure policy.
        Never retain or echo an invalid clock value in a private observation.
        """
        if (
            type(seconds) not in (int, float)
            or not 0 <= seconds <= MAX_TIME_MS / 1000
            or not math.isfinite(seconds)
        ):
            return None
        value = int(seconds * 1000)
        return value if 0 <= value <= MAX_TIME_MS else None

    def _require_tx_allowed(self):
        if self._quarantine_latched:
            raise _QuarantinedRead()

    def _quarantine_now(self):
        try:
            return self._quarantine_time(self._experiment.clock())
        except Exception:
            return None  # A failing injected clock must never prevent cleanup.

    def _record_quarantine(self, snapshot, now_ms):
        self._quarantine_observation = _QuarantineObservation(
            snapshot.generation,
            now_ms,
            _QuarantineOrigin.TRANSPORT_READ
            if snapshot.state is State.EOF_CANDIDATE
            else _QuarantineOrigin.NONE,
            snapshot.state,
            snapshot.reason,
        )

    def _quarantine_stop(self, event):
        """Record explicit stops before their first await; cleanup is not EOF."""
        if self._quarantine_policy is not None:
            now = self._quarantine_now()
            snapshot = self._quarantine_policy.advance(
                event, now_ms=now, generation=self._experiment_generation
            )
            self._record_quarantine(snapshot, now)

    def _begin_quarantine(self):
        """Synchronous cutoff at the typed rejection, never after acquiring TX.

        Queued writers observe the latch under TX lock. Already-engaged writes
        cannot be recalled, so they poison eligibility rather than claim a freeze.
        The waiter signal leaves its slot consumed but does not close/cancel RX.
        """
        self._quarantine_latched = True
        self._experiment.partial = True
        now = self._quarantine_now()
        stopped = (
            self.state is not SessionState.CONNECTED
            or self._loss_event.is_set()
            or any(task.cancelling() for task in self._operations)
            or self._read_timeout is not None
            and self._read_timeout.expired()
            or self._pending_read is not None
            and self._pending_read.cancelled()
        )
        owners_match = (
            type(self._experiment) is SessionReconnect
            and type(self._no_pong) is NoPongAfter120
            and self._no_pong.first_generation == self._experiment_generation == 1
        )
        snapshot = self._quarantine_policy.request(
            now_ms=now,
            generation=self._experiment_generation,
            scenario=Scenario.RECONNECT if owners_match else Scenario.SESSION_300,
            rejection=Rejection.CLOSE_CLIENT,
            suppressed_pongs=self._no_pong.suppressed,
            tx_in_flight=self._tx_in_flight,
            local_stop=stopped,
        )
        self._record_quarantine(snapshot, now)
        self._retryable_loss = False
        if snapshot.state is not State.WAITING:
            return False
        self._transition(SessionState.QUARANTINED)
        self._fail_pending_read(_QuarantinedRead())
        return True

    async def _receive_quarantine(self, transport):
        """Continue within the SAME RX task, dropping already-budgeted data.

        The rejected read (including coalesced suffix) was counted by
        BudgetTransport exactly once. No suffix is fed again or copied here.
        All subsequent deliveries use that same wrapper and remaining budgets.
        Only actual read EOF can produce a provisional private candidate. No
        terminal loss is announced until the decision; L4 never grants retry.
        """
        policy = self._quarantine_policy
        try:
            now = self._quarantine_now()
            if now is None or now >= policy.snapshot.deadline_ms:
                self._quarantine_stop(Event.TICK)
                return
            remaining = (policy.snapshot.deadline_ms - now) / 1000
            async with asyncio.timeout(remaining):
                while policy.snapshot.state is State.WAITING:
                    try:
                        data = await transport.read(4096, bounded=False)
                    except TransportEOF:
                        data = b""
                    eof = not data
                    data = b""  # No private capture or accumulation in this mode.
                    now = self._quarantine_now()
                    snapshot = policy.advance(
                        Event.EOF if eof else Event.TICK,
                        now_ms=now,
                        generation=self._experiment_generation,
                    )
                    self._record_quarantine(snapshot, now)
                    if snapshot.state is State.EOF_CANDIDATE:
                        self._no_pong.peer_closed(self._experiment_generation)
                        return
        except asyncio.CancelledError:
            self._quarantine_stop(Event.CANCEL)
        except TimeoutError:
            # A real asyncio deadline may win before the quantized clock has
            # advanced. Never turn that timing race into an EOF candidate.
            self._quarantine_stop(Event.TLS_FAILURE)
        except (TransportError, HobenError):
            self._quarantine_stop(Event.TLS_FAILURE)
        except Exception:
            self._quarantine_stop(Event.TLS_FAILURE)

    async def wait_rx_stopped(self) -> None:
        """Await the RX owner and report its fixed typed error, without reading.

        Cancelling an observer cannot cancel the owner. close() owns shutdown.
        The RX task records its failure instead of leaking unhandled exceptions.
        """
        task = self._rx_task
        if task is None:
            raise SessionStateError()
        error = await asyncio.shield(task)
        if error is not None:
            raise error from None

    async def _handle_delimited_data_response(
        self, event: DelimitedV4DataResponse
    ) -> None:
        """Deliver one complete, exchange-bound response; never read the socket."""
        self._require_tx_allowed()
        pending = self._pending_read
        error: HobenError | None = None
        failure_phase = "request_correlation"
        try:
            if (
                type(event) is not DelimitedV4DataResponse
                or pending is None
                or pending.done()
                or event._exchange is not pending
                or not self._read_sent
            ):
                raise HobenProtocolError()
            failure_phase = "response_validation"
            response = decode_read_response(decode_data_response_client(event._frame))
            if (
                response.transaction_id != 0xFFFF
                or response.unit_id != HOBEN_UNIT_ID
                or response.function_code != READ_INPUT_REGISTERS
                or isinstance(response, ModbusReadResponse)
                and len(response.registers) != 20
            ):
                raise HobenProtocolError()
            if isinstance(response, ModbusExceptionResponse):
                pending.set_exception(HobenModbusError(response.exception_code))
            else:
                pending.set_result(response)
            return
        except Exception:
            if self._experiment is not None:
                self._experiment.note_failure(
                    failure_phase, "protocol", "data_response"
                )
            error = HobenProtocolError()
        self._rx_error = self._rx_error or error
        self._loss_event.set()
        self._snapshot = replace(self._snapshot, rx_error=self._rx_error.code)
        if self.state is not SessionState.CLOSED:
            self._transition(SessionState.CLOSED)
        self._fail_pending_read(self._rx_error)
        # An active request owns its TX/cleanup. Do not deadlock waiting for TX
        # when a response arrives while write()/drain() is still in progress.
        if pending is None:
            try:
                await self.close()
            except HobenTransportError:
                pass
        raise error from None

    async def request_v4_data(self, *, timeout: float = 30.0) -> ModbusReadResponse:
        """Track a single caller through deterministic lifecycle teardown."""
        task = asyncio.current_task()
        done = asyncio.get_running_loop().create_future()
        self._operations[task] = done
        try:
            return await self._request_v4_data(timeout=timeout)
        finally:
            self._operations.pop(task, None)
            done.set_result(None)

    async def _request_v4_data(self, *, timeout: float) -> ModbusReadResponse:
        """Send the sole fixed V4 read and await a delimited contract response.

        Ordinary RX has no dispatch; session-300 alone opts in. The total
        deadline covers TX queueing,
        write and response. Abandoned requests close the session: fixed FFFF
        cannot distinguish a late wire response on a reused transport.
        """
        _validate_delay(timeout)
        self._require_tx_allowed()
        if self._rx_error is not None:
            raise self._rx_error from None
        if (
            self.state is not SessionState.CONNECTED
            or self._transport is None
            or self._pending_read is not None
        ):
            raise SessionStateError()
        transport = self._transport
        pending = asyncio.get_running_loop().create_future()
        self._pending_read = pending
        self._read_sent = False
        error: HobenError | None = None
        cancelled = False
        try:
            self._read_timeout = asyncio.timeout(timeout)
            async with self._read_timeout:
                async with self._transmitting():
                    self._require_tx_allowed()
                    if pending.done():
                        pending.result()
                    if self._rx_error is not None:
                        raise self._rx_error from None
                    if (
                        self.state is not SessionState.CONNECTED
                        or self._transport is not transport
                    ):
                        raise HobenClientClosedError()
                    if self._experiment is not None:
                        self._experiment.request()
                    request = encode_data_request_client(
                        build_read_input_registers(
                            0xFFFF, 1024, 20, unit_id=HOBEN_UNIT_ID
                        )
                    )
                    self._read_sent = True
                    self._tx_in_flight = True
                    try:
                        await transport.write(request)
                    finally:
                        self._tx_in_flight = False
                response = await asyncio.shield(pending)
                self._require_tx_allowed()
                if self._rx_error is not None:
                    raise self._rx_error from None
                return response
        except _QuarantinedRead:
            raise  # Dispose the waiter/timeout below without closing RX.
        except asyncio.CancelledError:
            self._quarantine_stop(Event.CANCEL)
            cancelled = True
            error = HobenTransportError()
        except (TransportTimeout, TimeoutError):
            self._quarantine_stop(Event.LOCAL_CLOSE)
            error = HobenTimeoutError()
        except TransportError:
            if self._rx_error is None:
                self._retryable_loss = True
            error = HobenTransportError()
        except HobenModbusError:
            # A correlated exception is a consumed terminal response, not an
            # abandoned read. Preserve the typed error without inventing meaning.
            if self._rx_error is None:
                raise
            error = self._rx_error
        except HobenError as failure:
            error = failure
        except Exception:
            error = HobenProtocolError()
        finally:
            self._read_timeout = None
            if not pending.done():
                pending.cancel()
            elif not pending.cancelled():
                pending.exception()  # Also consume failures arriving during TX.
            if self._pending_read is pending:
                self._pending_read = None
                self._read_sent = False
        self._rx_error = self._rx_error or error
        self._loss_event.set()
        self._snapshot = replace(self._snapshot, rx_error=self._rx_error.code)
        if self.state is not SessionState.CLOSED:
            self._transition(SessionState.CLOSED)
        try:
            await self.close()
        except HobenTransportError:
            pass
        if cancelled:
            raise asyncio.CancelledError()
        raise error from None

    async def close(self) -> None:
        """Stop opening, await its cleanup, then close once; CLOSED is terminal."""
        self._quarantine_stop(Event.LOCAL_CLOSE)
        if self._experiment is not None:
            self._experiment.lost(self._experiment_generation)
        self._loss_event.set()
        self._fail_pending_read(HobenClientClosedError())
        if self.state is not SessionState.CLOSED:
            self._transition(SessionState.CLOSED)
        task = self._opening_task
        if task is not None and task is not asyncio.current_task():
            if not task.cancelling():
                task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass  # The opening caller receives its sanitized failure.
        reader = self._rx_task
        cancelled = False
        if reader is not None and reader is not asyncio.current_task():
            if not reader.done() and not reader.cancelling():
                reader.cancel()
            try:
                await reader
            except asyncio.CancelledError:
                # A task cancelled before its first instruction has no finally.
                # close still owns transport cleanup; preserve caller cancellation.
                cancelled = bool(asyncio.current_task().cancelling())
        try:
            await self._release_transport()
        finally:
            self._opening_buffer.clear()
            if self._framer is not None:
                self._framer.clear()
            self._user_guid = None
            self._device_guid = INITIAL_DEVICE_GUID
        if cancelled:
            raise asyncio.CancelledError()
