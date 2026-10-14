"""HA-independent V4 session contract; network operations are not implemented.

OpenClient is the opening request. The observed V4 OpenedClient response has a
decodable 48-byte prefix, not a proven complete-message boundary. This skeleton
does not connect, parse RX, adopt an identity or send any protocol message.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from .modbus import ModbusReadResponse


class SessionState(StrEnum):
    """Local lifecycle; CONNECTED will require an accepted, safe V4 opening."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    """Immutable lifecycle view, without identity, RX or household data."""

    state: SessionState


class SessionTransport(Protocol):
    """Injectable async byte transport; ownership belongs to the future session.

    The factory must eventually provide a fresh verified TLS transport to the
    fixed production destination. No factory is called by this skeleton.
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

    Only close is implemented. The private transition guard is intended for
    future lifecycle code; consumers cannot declare a successful connection via
    the public API. No credentials, worker, waiter or socket are acquired yet.
    """

    __slots__ = ("_snapshot", "_transport_factory")

    def __init__(self, *, transport_factory: TransportFactory) -> None:
        if not callable(transport_factory):
            raise TypeError("transport_factory_must_be_callable")
        self._transport_factory = transport_factory
        self._snapshot = SessionSnapshot(SessionState.DISCONNECTED)

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
        self._snapshot = SessionSnapshot(target)

    async def connect(self) -> None:
        """Fail explicitly without creating a transport or claiming connection."""
        if self.state is not SessionState.DISCONNECTED:
            raise SessionStateError()
        raise SessionNotImplementedError()

    async def request_v4_data(self) -> ModbusReadResponse:
        """Future solicited read only; no request is emitted by this contract."""
        if self.state is not SessionState.CONNECTED:
            raise SessionStateError()
        raise SessionNotImplementedError()

    async def close(self) -> None:
        """Close the empty skeleton idempotently; no factory call or reconnect."""
        if self.state is not SessionState.CLOSED:
            self._transition(SessionState.CLOSED)
