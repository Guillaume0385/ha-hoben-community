"""Pure Python, offline acceptance tests for the V4 session skeleton."""

import asyncio
from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.hoben.client import DEFAULT_BUILD, DEFAULT_DEVICE_INFO
from custom_components.hoben.exceptions import (
    HobenAmbiguousSessionError,
    HobenAuthorizationRequiredError,
    HobenInvalidCredentialsError,
    HobenInvalidInputError,
    HobenProtocolError,
    HobenTimeoutError,
    HobenTransportError,
    HobenUnsupportedProfileError,
)
from custom_components.hoben.myhoben import INITIAL_DEVICE_GUID, encode_open_client
from custom_components.hoben.transport import (
    AsyncTlsTransport,
    TransportEOF,
    TransportTlsError,
)
from custom_components.hoben.v4_session import (
    SessionNotImplementedError,
    SessionSnapshot,
    SessionState,
    SessionStateError,
    V4Session,
)


def session_in(state):
    """Reach internal test states through legal lifecycle edges, without I/O."""
    factory = Mock(side_effect=AssertionError("factory must stay unused"))
    session = V4Session(transport_factory=factory)
    if state in (
        SessionState.CONNECTING,
        SessionState.CONNECTED,
        SessionState.RECONNECTING,
    ):
        session._transition(SessionState.CONNECTING)
    if state in (SessionState.CONNECTED, SessionState.RECONNECTING):
        session._transition(SessionState.CONNECTED)
    if state is SessionState.RECONNECTING:
        session._transition(SessionState.RECONNECTING)
    if state is SessionState.CLOSED:
        asyncio.run(session.close())
    return session, factory


@pytest.mark.parametrize("state", list(SessionState))
def test_close_is_terminal_idempotent_and_does_not_acquire_transport(state):
    session, factory = session_in(state)
    previous = session.snapshot

    async def close_twice():
        await session.close()
        closed = session.snapshot
        await session.close()
        assert session.snapshot is closed

    asyncio.run(close_twice())
    assert session.state is SessionState.CLOSED
    assert previous.state is state
    factory.assert_not_called()


@pytest.mark.parametrize("source", list(SessionState))
@pytest.mark.parametrize("target", list(SessionState))
def test_transition_guard(source, target):
    session, factory = session_in(source)
    previous = session.snapshot
    allowed = (
        source is SessionState.DISCONNECTED
        and target is SessionState.CONNECTING
        or source in (SessionState.CONNECTING, SessionState.RECONNECTING)
        and target in (SessionState.CONNECTED, SessionState.DISCONNECTED)
        or source is SessionState.CONNECTED
        and target in (SessionState.RECONNECTING, SessionState.DISCONNECTED)
        or source is not SessionState.CLOSED
        and target is SessionState.CLOSED
    )
    if allowed:
        session._transition(target)
        assert session.state is target
        assert previous.state is source
    else:
        with pytest.raises(SessionStateError, match="^invalid_session_state$"):
            session._transition(target)
        assert session.snapshot is previous
    factory.assert_not_called()


@pytest.mark.parametrize("state", list(SessionState))
def test_unimplemented_operations_never_succeed_or_change_state(state):
    session, factory = session_in(state)
    previous = session.snapshot

    async def operations():
        connect_error = (
            HobenInvalidInputError
            if state is SessionState.DISCONNECTED
            else SessionStateError
        )
        read_error = (
            SessionNotImplementedError
            if state is SessionState.CONNECTED
            else SessionStateError
        )
        with pytest.raises(connect_error):
            await session.connect()
        with pytest.raises(read_error):
            await session.request_v4_data()

    asyncio.run(operations())
    assert session.snapshot is previous
    factory.assert_not_called()


def test_snapshot_and_public_state_cannot_be_mutated():
    session, _ = session_in(SessionState.DISCONNECTED)
    assert session.snapshot == SessionSnapshot(SessionState.DISCONNECTED)
    with pytest.raises(FrozenInstanceError):
        session.snapshot.state = SessionState.CONNECTED
    with pytest.raises(AttributeError):
        session.state = SessionState.CONNECTED
    with pytest.raises(AttributeError):
        session.snapshot = SessionSnapshot(SessionState.CONNECTED)
    with pytest.raises(SessionStateError):
        session._transition("connecting")


def test_private_dependency_never_appears_in_repr_errors_or_logs(caplog):
    sentinel = "synthetic-private-dependency-marker"
    factory = Mock(name=sentinel)
    session = V4Session(transport_factory=factory)
    assert session._transport_factory is factory
    assert repr(session) == "V4Session(state=disconnected)"
    with pytest.raises(HobenInvalidInputError) as error:
        asyncio.run(session.connect())
    assert sentinel not in repr(session.snapshot) + repr(error.value) + caplog.text
    assert not caplog.records
    factory.assert_not_called()


def test_invalid_factory_is_rejected_without_echoing_input():
    with pytest.raises(TypeError, match="^transport_factory_must_be_callable$"):
        V4Session(transport_factory="synthetic-private-input")


# Generated, wholly synthetic opening bytes, with no real identity/capture.
def opened_prefix(*, profile=5, identity=b"a" * 32):
    return (
        bytes([4, 0, 0, 0, 0, 0, 0, 1, profile, 2, 8, 0, 0, 0]) + identity + b"\x00\x02"
    )


def opening_session(chunks):
    transport = SimpleNamespace(
        connect=AsyncMock(),
        write=AsyncMock(),
        read=AsyncMock(side_effect=[*chunks, TransportEOF("synthetic-eof")]),
        close=AsyncMock(),
    )
    factory = Mock(return_value=transport)
    return V4Session(user_guid="b" * 32, transport_factory=factory), transport, factory


@pytest.mark.parametrize("split", range(1, 48))
def test_fragmented_opening_preserves_bytes_and_accepts_only_prefix(split):
    prefix = opened_prefix()
    session, transport, factory = opening_session([prefix[:split], prefix[split:]])

    async def scenario():
        before = session.snapshot
        await session.connect()
        assert before.state is SessionState.DISCONNECTED
        assert session.state is SessionState.CONNECTED
        assert session.snapshot.opening.product_type == 5
        assert session.snapshot.opening.application_version == 512
        assert not session.snapshot.boundary_proven
        assert session.snapshot.unclassified_bytes == 0
        assert session._opening_buffer == prefix
        assert session.device_guid_for_persistence == "a" * 32
        transport.close.assert_not_awaited()
        with pytest.raises(SessionNotImplementedError):
            await session.request_v4_data()
        with pytest.raises(SessionStateError):
            await session.connect()
        await session.close()
        await session.close()

    asyncio.run(scenario())
    factory.assert_called_once_with()
    transport.connect.assert_awaited_once()
    transport.write.assert_awaited_once_with(
        encode_open_client(
            "b" * 32, DEFAULT_BUILD, INITIAL_DEVICE_GUID, DEFAULT_DEVICE_INFO
        )
    )
    transport.close.assert_awaited_once()
    assert not session._opening_buffer
    assert session.device_guid_for_persistence == INITIAL_DEVICE_GUID


@pytest.mark.parametrize("suffix", [b"\x0a", b"\x0eopaque", b"\x1bunknown"])
def test_ambiguous_suffix_is_retained_not_routed_or_adopted(suffix):
    data = opened_prefix() + suffix
    session, transport, _ = opening_session([data])
    with pytest.raises(HobenAmbiguousSessionError):
        asyncio.run(session.connect())
    assert session.state is SessionState.DISCONNECTED
    assert session.snapshot.unclassified_bytes == len(suffix)
    assert not session.snapshot.boundary_proven
    assert session._opening_buffer == data
    assert session.snapshot.opening is None
    assert session.device_guid_for_persistence == INITIAL_DEVICE_GUID
    transport.write.assert_awaited_once()
    transport.close.assert_awaited_once()


@pytest.mark.parametrize(
    ("chunks", "error"),
    [
        ([], HobenTransportError),
        ([opened_prefix()[:20]], HobenTransportError),
        ([opened_prefix(identity=b"\xff" * 32)], HobenProtocolError),
        ([opened_prefix(profile=99)], HobenUnsupportedProfileError),
        ([b"\x05\x02"], HobenInvalidCredentialsError),
        ([b"\x2f"], HobenAuthorizationRequiredError),
        ([b"\x0a"], HobenProtocolError),
        ([b"\x1bopaque"], HobenProtocolError),
        ([TransportTlsError("synthetic-private-failure")], HobenTransportError),
        ([RuntimeError("synthetic-private-failure")], HobenProtocolError),
    ],
)
def test_opening_failure_cleans_transport_without_extra_emission(chunks, error, caplog):
    session, transport, factory = opening_session(chunks)
    with pytest.raises(error) as raised:
        asyncio.run(session.connect())
    assert session.state is SessionState.DISCONNECTED
    assert session._opening_task is None
    assert session._transport is None
    assert session.device_guid_for_persistence == INITIAL_DEVICE_GUID
    factory.assert_called_once()
    transport.write.assert_awaited_once()
    transport.close.assert_awaited_once()
    public = repr(session) + repr(session.snapshot) + str(raised.value) + caplog.text
    assert "synthetic-private-failure" not in public
    assert "a" * 32 not in public
    assert "b" * 32 not in public
    assert not caplog.records


def test_opening_timeout_is_bounded_and_cleans_up(deadlines):
    session, transport, _ = opening_session([])
    transport.read.side_effect = deadlines.expire
    with pytest.raises(HobenTimeoutError):
        asyncio.run(session.connect())
    assert session.state is SessionState.DISCONNECTED
    transport.close.assert_awaited_once()


@pytest.mark.parametrize("cancel_directly", [False, True])
@pytest.mark.parametrize("phase", ["connect", "write", "read"])
def test_concurrent_connect_and_close_during_opening_leave_no_orphan(
    cancel_directly, phase
):
    session, transport, factory = opening_session([])

    async def scenario():
        reading = asyncio.Event()

        async def blocked_read(*args):
            reading.set()
            await asyncio.Future()

        getattr(transport, phase).side_effect = blocked_read
        task = asyncio.create_task(session.connect())
        await reading.wait()
        assert session.state is SessionState.CONNECTING
        with pytest.raises(SessionStateError):
            await session.connect()
        if cancel_directly:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert session.state is SessionState.DISCONNECTED
        else:
            await asyncio.gather(session.close(), session.close())
            assert task.done() and task.cancelled()
            assert session.state is SessionState.CLOSED
        await session.close()
        assert session._opening_task is None
        assert session._transport is None
        with pytest.raises(SessionStateError):
            await session.connect()

    asyncio.run(scenario())
    factory.assert_called_once()
    transport.connect.assert_awaited_once()
    transport.close.assert_awaited_once()


def test_default_transport_uses_verified_fixed_tls_and_starts_no_reader(streams):
    streams.reader.read.return_value = opened_prefix()
    session = V4Session(user_guid="b" * 32)

    async def scenario():
        await session.connect()
        kwargs = streams.connect.call_args.kwargs
        context = kwargs["ssl"]
        assert context.check_hostname
        assert context.verify_mode.name == "CERT_REQUIRED"
        assert kwargs["server_hostname"] == "myhoben.fr"
        assert streams.connect.call_args.args == ("myhoben.fr", 465)
        streams.reader.read.assert_awaited_once()
        await session.close()

    asyncio.run(scenario())


def test_shutdown_failure_does_not_mask_opening_failure():
    session, transport, _ = opening_session([b"\x05\x02"])
    transport.close.side_effect = RuntimeError("synthetic-private-close")
    with pytest.raises(HobenInvalidCredentialsError):
        asyncio.run(session.connect())
    assert session.state is SessionState.DISCONNECTED
    assert session._transport is None


def test_byte_at_a_time_retains_prefix_without_reading_delayed_suffix():
    prefix = opened_prefix()
    session, transport, _ = opening_session([bytes([b]) for b in prefix] + [b"\x0a"])
    asyncio.run(session.connect())
    assert transport.read.await_count == 48
    assert session._opening_buffer == prefix
    assert not session.snapshot.boundary_proven
    asyncio.run(session.close())


def test_tls_failure_before_openclient_is_sanitized_and_closed():
    session, transport, _ = opening_session([])
    transport.connect.side_effect = TransportTlsError("synthetic-private-tls")
    with pytest.raises(HobenTransportError, match="^transport_unavailable$"):
        asyncio.run(session.connect())
    transport.write.assert_not_awaited()
    transport.close.assert_awaited_once()
    assert session.state is SessionState.DISCONNECTED


@pytest.mark.parametrize("user", [None, "synthetic-private-input", 123])
def test_invalid_identity_never_acquires_transport(user):
    factory = Mock()
    session = V4Session(user_guid=user, transport_factory=factory)
    with pytest.raises(HobenInvalidInputError):
        asyncio.run(session.connect())
    factory.assert_not_called()
    assert session.state is SessionState.DISCONNECTED


def test_factory_failure_returns_to_disconnected_without_retry():
    factory = Mock(side_effect=RuntimeError("synthetic-private-factory"))
    session = V4Session(user_guid="b" * 32, transport_factory=factory)
    with pytest.raises(HobenProtocolError):
        asyncio.run(session.connect())
    factory.assert_called_once()
    assert session.state is SessionState.DISCONNECTED
    assert session._opening_task is None


def test_real_transport_with_another_destination_is_rejected_before_network(streams):
    session = V4Session(
        user_guid="b" * 32,
        transport_factory=lambda: AsyncTlsTransport(host="invalid.example", port=1234),
    )
    with pytest.raises(HobenProtocolError):
        asyncio.run(session.connect())
    streams.connect.assert_not_called()
    assert session.state is SessionState.DISCONNECTED
