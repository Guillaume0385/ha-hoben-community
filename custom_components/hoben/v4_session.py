"""HA-independent V4 opening; post-open reception remains unimplemented.

OpenClient is the opening request. The observed V4 OpenedClient response has a
decodable 48-byte prefix, not a proven complete-message boundary. This skeleton
retains opening bytes privately and never routes post-open traffic.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol

from .client import DEFAULT_BUILD, DEFAULT_DEVICE_INFO, _validate_device_guid
from .exceptions import (
    HobenAmbiguousSessionError,
    HobenAuthorizationRequiredError,
    HobenClosedError,
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


class SessionTransport(Protocol):
    """Injectable async byte transport; ownership belongs to the future session.

    The factory must eventually provide a fresh verified TLS transport to the
    fixed production destination. Tests inject a wholly offline implementation.
    """

    async def connect(self) -> None: ...

    async def read(self, max_bytes: int = 4096) -> bytes: ...

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
    does not prove a complete boundary or authorize reads/routing. No worker is
    started. The default factory creates verified TLS to myhoben.fr:465 only.
    """

    __slots__ = (
        "_snapshot",
        "_transport_factory",
        "_transport",
        "_opening_task",
        "_opening_buffer",
        "_user_guid",
        "_device_guid",
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
        """Detach before awaiting shutdown, preventing duplicate closes."""
        transport, self._transport = self._transport, None
        if transport is not None:
            try:
                await transport.close()
            except Exception:
                raise HobenTransportError() from None

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

    async def request_v4_data(self) -> ModbusReadResponse:
        """Future solicited read only; no request is emitted by this contract."""
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
        try:
            await self._release_transport()
        finally:
            self._opening_buffer.clear()
            self._user_guid = None
            self._device_guid = INITIAL_DEVICE_GUID
