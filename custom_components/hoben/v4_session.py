"""HA-independent V4 opening and conservative RX ownership, without routing.

OpenClient is the opening request. The observed V4 OpenedClient response has a
decodable 48-byte prefix, not a proven complete-message boundary. This skeleton
retains opening bytes privately and never routes post-open traffic.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import Enum, StrEnum
from typing import Protocol

from .client import DEFAULT_BUILD, DEFAULT_DEVICE_INFO, _validate_device_guid
from .exceptions import (
    HobenAmbiguousSessionError,
    HobenAuthorizationRequiredError,
    HobenClosedError,
    HobenError,
    HobenInvalidCredentialsError,
    HobenInvalidInputError,
    HobenProtocolError,
    HobenTimeoutError,
    HobenTransportError,
    HobenUnsupportedProfileError,
)
from .modbus import ModbusReadResponse
from .myhoben import INITIAL_DEVICE_GUID, CloseClientReason, encode_open_client
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
from .transport import AsyncTlsTransport, TransportError, TransportTimeout


class SessionState(StrEnum):
    """Local lifecycle; CONNECTED will require an accepted, safe V4 opening."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    CLOSED = "closed"


class HandoffState(StrEnum):
    """No current evidence promotes UNPROVEN to a routable message boundary."""

    UNPROVEN = "unproven"
    AMBIGUOUS = "ambiguous"


class DelimitedV4Message(Enum):
    """Semantic input from proven framing, never an interpretation of raw RX.

    This token does not prove a boundary. Only an independently established
    message boundary may produce it. The current conservative RX owner never
    creates this token and never invokes the delimited-message handler.
    """

    PING = _PING


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


_TRANSITIONS = {
    SessionState.DISCONNECTED: frozenset(
        {SessionState.CONNECTING, SessionState.CLOSED}
    ),
    SessionState.CONNECTING: frozenset(
        {SessionState.CONNECTED, SessionState.DISCONNECTED, SessionState.CLOSED}
    ),
    SessionState.CONNECTED: frozenset(
        {SessionState.RECONNECTING, SessionState.DISCONNECTED, SessionState.CLOSED}
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
    )

    def __init__(
        self,
        *,
        user_guid: str | None = None,
        device_guid: str = INITIAL_DEVICE_GUID,
        transport_factory: TransportFactory = AsyncTlsTransport,
    ) -> None:
        if not callable(transport_factory):
            raise TypeError("transport_factory_must_be_callable")
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

    async def _handle_delimited_ping(self, message: DelimitedV4Message) -> None:
        """Respond once to an already-delimited Ping (protocol.md §3).

        This is an offline-testable primitive for a future proven framer, not a
        stream parser. Raw bytes, including a lone 0x0A, cannot enter this API.
        No current RX path calls it: post-OpenedClient framing is still unproven.
        A failed/cancelled write closes without replay, since emission is uncertain.
        """
        if message is not DelimitedV4Message.PING:
            raise HobenProtocolError()
        transport = self._transport
        error: HobenError | None = None
        cancelled = False
        async with self._tx_lock:
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
            try:
                await transport.write(_PONG)
            except asyncio.CancelledError:
                cancelled = True
                error = HobenTransportError()
            except TransportError:
                error = HobenTransportError()
            except Exception:
                error = HobenProtocolError()
            if error is not None:
                # Stop queued TX before releasing the lock for shutdown.
                self._rx_error = self._rx_error or error
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

    async def connect(self) -> None:
        """Accept only the existing V4 opening, without post-open processing.

        Reject concurrent/repeated calls rather than opening twice. Unknown
        suffixes remain private until explicit close or a fresh opening attempt.
        Their absence now says nothing about bytes that may arrive later.
        """
        if self.state is not SessionState.DISCONNECTED:
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
        self._rx_task = None
        self._transition(SessionState.CONNECTING)
        self._opening_task = asyncio.current_task()
        succeeded = False
        try:
            try:
                self._transport = self._transport_factory()
                if isinstance(self._transport, AsyncTlsTransport) and (
                    self._transport.host != "myhoben.fr" or self._transport.port != 465
                ):
                    raise HobenInvalidInputError()
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
                if result.unclassified_bytes:
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
                self._device_guid = assigned
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
            data = await transport.read(4096, bounded=False)
            if not isinstance(data, bytes):
                raise HobenProtocolError()
            if not data:
                raise HobenTransportError()
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
        except TransportError:
            self._rx_error = HobenTransportError()
        except Exception:
            self._rx_error = HobenProtocolError()
        finally:
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

    async def request_v4_data(self) -> ModbusReadResponse:
        """Future solicited read only; no request is emitted by this contract."""
        if self._rx_error is not None:
            raise self._rx_error from None
        if self.state is not SessionState.CONNECTED:
            raise SessionStateError()
        raise SessionNotImplementedError()

    async def close(self) -> None:
        """Stop opening, await its cleanup, then close once; CLOSED is terminal."""
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
            self._user_guid = None
            self._device_guid = INITIAL_DEVICE_GUID
        if cancelled:
            raise asyncio.CancelledError()
