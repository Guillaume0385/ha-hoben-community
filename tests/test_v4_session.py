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
    HobenClientClosedError,
    HobenInvalidCredentialsError,
    HobenInvalidInputError,
    HobenModbusError,
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
    DelimitedV4DataResponse,
    DelimitedV4Message,
    HandoffState,
    SessionSnapshot,
    SessionState,
    SessionStateError,
    V4Session,
    V4SessionMode,
)


def session_in(state):
    """Reach internal test states through legal lifecycle edges, without I/O."""
    factory = Mock(side_effect=AssertionError("factory must stay unused"))
    session = V4Session(transport_factory=factory)
    if state in (
        SessionState.CONNECTING,
        SessionState.CONNECTED,
        SessionState.RECONNECTING,
        SessionState.QUARANTINED,
    ):
        session._transition(SessionState.CONNECTING)
    if state in (
        SessionState.CONNECTED,
        SessionState.RECONNECTING,
        SessionState.QUARANTINED,
    ):
        session._transition(SessionState.CONNECTED)
    if state is SessionState.QUARANTINED:
        session._transition(SessionState.QUARANTINED)
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
        and target
        in (
            SessionState.RECONNECTING,
            SessionState.DISCONNECTED,
            SessionState.QUARANTINED,
        )
        or source is SessionState.QUARANTINED
        and target is SessionState.DISCONNECTED
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
def test_operations_without_transport_never_succeed_or_change_state(state):
    session, factory = session_in(state)
    previous = session.snapshot

    async def operations():
        connect_error = (
            HobenInvalidInputError
            if state is SessionState.DISCONNECTED
            else SessionStateError
        )
        with pytest.raises(connect_error):
            await session.connect()
        with pytest.raises(SessionStateError):
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
        assert session._pending_read is None
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


def test_byte_at_a_time_retains_prefix_and_refuses_delayed_suffix():
    prefix = opened_prefix()
    session, transport, _ = opening_session([bytes([b]) for b in prefix] + [b"\x0a"])

    async def scenario():
        await session.connect()
        with pytest.raises(HobenAmbiguousSessionError):
            await session.wait_rx_stopped()
        assert transport.read.await_count == 49
        assert session._opening_buffer == prefix + b"\x0a"
        assert session.snapshot.handoff is HandoffState.AMBIGUOUS
        assert not session.snapshot.boundary_proven
        await session.close()

    asyncio.run(scenario())


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


@pytest.mark.parametrize("mode", list(V4SessionMode))
@pytest.mark.parametrize(
    "host, port",
    [("invalid.example", 465), ("myhoben.fr", 1234), ("invalid.example", 1234)],
)
def test_real_transport_with_another_destination_is_permanent_before_network(
    streams, caplog, mode, host, port
):
    transport = AsyncTlsTransport(host=host, port=port)
    factory = Mock(return_value=transport)
    session = V4Session(
        user_guid="b" * 32,
        transport_factory=factory,
        mode=mode,
    )
    with pytest.raises(HobenInvalidInputError) as caught:
        asyncio.run(session.connect())
    assert type(caught.value) is HobenInvalidInputError
    assert caught.value.safe_report() == {
        "state": "error",
        "error": "invalid_client_inputs",
    }
    factory.assert_called_once_with()
    streams.connect.assert_not_called()
    streams.writer.write.assert_not_called()
    assert session._transport is None and session._opening_task is None
    assert session.cleanup_succeeded
    assert session.state is SessionState.DISCONNECTED
    assert "invalid.example" not in str(caught.value) + caplog.text
    assert "b" * 32 not in str(caught.value) + caplog.text


@pytest.mark.parametrize(
    "tail", [b"\x0a", b"\x0eopaque", b"\x1bopaque", b"\xffunknown"]
)
@pytest.mark.parametrize("split", range(1, 49))
def test_every_prefix_split_and_coalesced_tail_preserves_order_without_routing(
    split, tail
):
    prefix = opened_prefix()
    session, transport, _ = opening_session([prefix[:split], prefix[split:] + tail])

    async def scenario():
        if split < 48:
            with pytest.raises(HobenAmbiguousSessionError):
                await session.connect()
            assert session._rx_task is None
        else:
            await session.connect()
            with pytest.raises(HobenAmbiguousSessionError):
                await session.wait_rx_stopped()
            assert session._rx_task.done()
        assert session._opening_buffer == prefix + tail
        assert session.state is SessionState.DISCONNECTED
        assert session.snapshot.unclassified_bytes == len(tail)
        assert session.snapshot.handoff is HandoffState.AMBIGUOUS
        assert not session.snapshot.boundary_proven
        transport.write.assert_awaited_once()
        transport.close.assert_awaited_once()
        await session.close()
        transport.close.assert_awaited_once()

    asyncio.run(scenario())


def test_one_rx_owner_with_concurrent_observers_requests_and_close():
    session, transport, factory = opening_session([])

    async def scenario():
        active_reads = 0
        owners = []
        rx_started = asyncio.Event()
        release = asyncio.Event()

        async def read(*args, bounded=True):
            nonlocal active_reads
            assert active_reads == 0, "overlapping transport readers"
            active_reads += 1
            try:
                owners.append(asyncio.current_task())
                if bounded:
                    return opened_prefix()
                rx_started.set()
                await release.wait()
                return b"\x0a\x0eopaque\x1bopaque\xff"
            finally:
                active_reads -= 1

        transport.read.side_effect = read
        await session.connect()
        await rx_started.wait()
        reader = session._rx_task
        assert owners == [asyncio.current_task(), reader]
        assert session.snapshot.handoff is HandoffState.UNPROVEN
        with pytest.raises(SessionStateError):
            await session.connect()
        assert session._pending_read is None
        observer = asyncio.create_task(session.wait_rx_stopped())
        await asyncio.sleep(0)  # Enter the shielded observer before cancelling it.
        observer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await observer
        assert not reader.done() and not reader.cancelling()
        release.set()
        results = await asyncio.gather(
            session.wait_rx_stopped(), session.wait_rx_stopped(), return_exceptions=True
        )
        assert all(isinstance(r, HobenAmbiguousSessionError) for r in results)
        assert (
            session._opening_buffer == opened_prefix() + b"\x0a\x0eopaque\x1bopaque\xff"
        )
        with pytest.raises(HobenAmbiguousSessionError):
            await session.request_v4_data()
        assert owners == [asyncio.current_task(), reader]
        assert active_reads == 0
        await asyncio.gather(session.close(), session.close())
        assert reader.done()
        assert session.state is SessionState.CLOSED

    asyncio.run(scenario())
    factory.assert_called_once()
    transport.write.assert_awaited_once()
    transport.close.assert_awaited_once()


@pytest.mark.parametrize(
    "failure",
    [
        TransportEOF("synthetic"),
        TransportTlsError("synthetic"),
        RuntimeError("synthetic-private-failure"),
    ],
)
def test_rx_error_is_sanitized_and_owner_is_awaited(failure, caplog):
    session, transport, _ = opening_session([opened_prefix(), failure])

    async def scenario():
        await session.connect()
        error = (
            HobenProtocolError
            if isinstance(failure, RuntimeError)
            else HobenTransportError
        )
        with pytest.raises(error):
            await session.wait_rx_stopped()
        assert session._rx_task.done()
        assert session.state is SessionState.DISCONNECTED
        assert session.snapshot.handoff is HandoffState.UNPROVEN
        assert session._opening_buffer == opened_prefix()
        assert "synthetic-private-failure" not in repr(session.snapshot) + repr(session)
        assert not caplog.records
        await session.close()

    asyncio.run(scenario())
    transport.close.assert_awaited_once()
    transport.write.assert_awaited_once()


@pytest.mark.parametrize("cancel_owner", [True, False])
def test_rx_cancellation_and_close_wait_for_transport_cleanup(cancel_owner):
    session, transport, _ = opening_session([])

    async def scenario():
        started = asyncio.Event()

        async def read(*args, bounded=True):
            if bounded:
                return opened_prefix()
            started.set()
            await asyncio.Future()

        transport.read.side_effect = read
        await session.connect()
        await started.wait()
        reader = session._rx_task
        if cancel_owner:
            reader.cancel()
            with pytest.raises(HobenTransportError):
                await session.wait_rx_stopped()
            assert session.state is SessionState.DISCONNECTED
        await asyncio.gather(session.close(), session.close())
        assert reader.done()
        assert session._transport is None
        assert not session._opening_buffer
        assert session.state is SessionState.CLOSED

    asyncio.run(scenario())
    transport.close.assert_awaited_once()


def test_idle_rx_has_no_application_deadline_or_boundary_proof(streams, deadlines):
    session = V4Session(user_guid="b" * 32)

    async def scenario():
        started = asyncio.Event()
        reads = 0

        async def read(*args):
            nonlocal reads
            reads += 1
            if reads == 1:
                return opened_prefix()
            started.set()
            await asyncio.Future()

        streams.reader.read.side_effect = read
        await session.connect()
        await started.wait()
        assert deadlines.contexts[-1][0] is None
        assert deadlines.contexts[-1][1].when() is None
        assert session.state is SessionState.CONNECTED
        assert not session.snapshot.boundary_proven
        assert session.snapshot.handoff is HandoffState.UNPROVEN
        await session.close()
        assert session._rx_task.done()

    asyncio.run(scenario())
    streams.writer.close.assert_called_once()
    streams.writer.write.assert_called_once()


async def connected_ping_session():
    """Inject a known synthetic prefix; park RX without manufacturing a boundary."""
    session, transport, _ = opening_session([opened_prefix()])
    await session.connect()

    async def parked_read(*args, **kwargs):
        await asyncio.Future()

    transport.read.side_effect = parked_read
    transport.write.reset_mock()
    return session, transport


def test_already_delimited_ping_produces_exactly_one_pong():
    async def scenario():
        session, transport = await connected_ping_session()
        before = session.snapshot
        await session._handle_delimited_ping(DelimitedV4Message.PING)
        transport.write.assert_awaited_once_with(b"\x0b")
        assert session.snapshot is before
        assert not session.snapshot.boundary_proven
        await session.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "raw",
    [
        None,
        10,
        "ping",
        b"",
        b"\x0a",
        b"\x0a\x0a",
        b"\x0eopaque",
        b"\x1bopaque",
        bytearray(b"\x0a"),
    ],
)
def test_raw_bytes_cannot_claim_to_be_a_delimited_ping(raw, caplog):
    async def scenario():
        session, transport = await connected_ping_session()
        before = bytes(session._opening_buffer)
        with pytest.raises(HobenProtocolError, match="^malformed_response$"):
            await session._handle_delimited_ping(raw)
        assert session._opening_buffer == before
        assert not session.snapshot.boundary_proven
        transport.write.assert_not_awaited()
        assert not caplog.records
        await session.close()

    asyncio.run(scenario())


def test_pongs_are_serialized_across_awaits_without_another_reader():
    async def scenario():
        session, transport = await connected_ping_session()
        entered = asyncio.Event()
        release = asyncio.Event()
        active = 0

        async def write(payload):
            nonlocal active
            assert payload == b"\x0b"
            assert active == 0, "overlapping TX"
            active += 1
            try:
                entered.set()
                await release.wait()
                await asyncio.sleep(0)
            finally:
                active -= 1

        transport.write.side_effect = write
        tasks = [
            asyncio.create_task(session._handle_delimited_ping(DelimitedV4Message.PING))
            for _ in range(3)
        ]
        await entered.wait()
        await asyncio.sleep(0)
        assert transport.write.await_count == 1
        assert not session._rx_task.done()
        release.set()
        await asyncio.gather(*tasks)
        assert transport.write.await_count == 3
        assert transport.read.await_count == 2  # Handshake + sole parked RX owner.
        assert active == 0
        await session.close()
        transport.close.assert_awaited_once()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "failure",
    [TransportTlsError("synthetic-private-tx"), RuntimeError("synthetic-private-tx")],
)
def test_pong_failure_is_sanitized_closed_and_never_replayed(failure, caplog):
    async def scenario():
        session, transport = await connected_ping_session()
        transport.write.side_effect = failure
        error = (
            HobenTransportError
            if isinstance(failure, TransportTlsError)
            else HobenProtocolError
        )
        with pytest.raises(error) as raised:
            await session._handle_delimited_ping(DelimitedV4Message.PING)
        assert "synthetic-private-tx" not in str(raised.value) + repr(session.snapshot)
        assert session.state is SessionState.CLOSED
        assert session._rx_task.done()
        assert not caplog.records
        transport.write.assert_awaited_once_with(b"\x0b")
        transport.close.assert_awaited_once()
        with pytest.raises((HobenProtocolError, HobenTransportError)):
            await session._handle_delimited_ping(DelimitedV4Message.PING)
        transport.write.assert_awaited_once()

    asyncio.run(scenario())


def test_cancel_during_pong_closes_without_replay_or_orphan():
    async def scenario():
        session, transport = await connected_ping_session()
        entered = asyncio.Event()

        async def write(payload):
            entered.set()
            await asyncio.Future()

        transport.write.side_effect = write
        sending = asyncio.create_task(
            session._handle_delimited_ping(DelimitedV4Message.PING)
        )
        await entered.wait()
        sending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await sending
        assert session.state is SessionState.CLOSED
        assert session._rx_task.done()
        transport.write.assert_awaited_once_with(b"\x0b")
        transport.close.assert_awaited_once()

    asyncio.run(scenario())


def test_close_waits_for_active_pong_and_rejects_queued_pong():
    async def scenario():
        session, transport = await connected_ping_session()
        entered = asyncio.Event()
        release = asyncio.Event()

        async def write(payload):
            entered.set()
            await release.wait()

        transport.write.side_effect = write
        first = asyncio.create_task(
            session._handle_delimited_ping(DelimitedV4Message.PING)
        )
        await entered.wait()
        queued = asyncio.create_task(
            session._handle_delimited_ping(DelimitedV4Message.PING)
        )
        closing = asyncio.create_task(session.close())
        await asyncio.sleep(0)
        assert session.state is SessionState.CLOSED
        assert not closing.done()
        transport.close.assert_not_awaited()
        release.set()
        await first
        with pytest.raises(SessionStateError):
            await queued
        await closing
        assert session._rx_task.done()
        transport.write.assert_awaited_once_with(b"\x0b")
        transport.close.assert_awaited_once()

    asyncio.run(scenario())


@pytest.mark.parametrize("state", list(SessionState))
def test_delimited_ping_refused_without_a_connected_transport(state):
    session, factory = session_in(state)
    with pytest.raises(SessionStateError):
        asyncio.run(session._handle_delimited_ping(DelimitedV4Message.PING))
    factory.assert_not_called()


def synthetic_data_response(*, transaction=0xFFFF, unit=1, function=4, count=20):
    """Independent synthetic MBAP fixture, never a captured response."""
    pdu = bytes([function, 2 * count]) + b"".join(
        value.to_bytes(2, "big") for value in range(count)
    )
    return (
        b"\x0e"
        + transaction.to_bytes(2, "big")
        + b"\x00\x00"
        + (len(pdu) + 1).to_bytes(2, "big")
        + bytes([unit])
        + pdu
    )


async def start_synthetic_read(session, transport):
    sent = asyncio.Event()
    transport.write.side_effect = lambda payload: sent.set()
    task = asyncio.create_task(session.request_v4_data(timeout=7.0))
    await sent.wait()
    return task, session._pending_read


def test_fixed_read_exact_tx_typed_result_and_single_waiter(caplog):
    async def scenario():
        session, transport = await connected_ping_session()
        task, exchange = await start_synthetic_read(session, transport)
        with pytest.raises(SessionStateError):
            await session.request_v4_data()
        event = DelimitedV4DataResponse(synthetic_data_response(), exchange=exchange)
        await session._handle_delimited_data_response(event)
        result = await task
        assert session.verified_read_sequence == 1
        assert (result.transaction_id, result.unit_id, result.function_code) == (
            0xFFFF,
            1,
            4,
        )
        assert result.registers == tuple(range(20))
        assert "registers" not in repr(result)
        assert repr(event) == "DelimitedV4DataResponse()"
        assert not session.snapshot.boundary_proven
        assert session._pending_read is None
        assert session.state is SessionState.CONNECTED
        transport.write.assert_awaited_once_with(
            bytes.fromhex("0D FF FF 00 00 00 06 01 04 04 00 00 14")
        )
        assert transport.read.await_count == 2
        assert not caplog.records
        await session.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "frame",
    [
        b"",
        b"\x0e",
        synthetic_data_response()[:-1],
        synthetic_data_response() + b"\x00",
        synthetic_data_response() * 2,
        synthetic_data_response(transaction=1),
        synthetic_data_response(unit=2),
        synthetic_data_response(function=3),
        synthetic_data_response(count=19),
    ],
)
def test_malformed_or_uncorrelated_response_fails_waiter_and_closes(frame):
    async def scenario():
        session, transport = await connected_ping_session()
        task, exchange = await start_synthetic_read(session, transport)
        with pytest.raises(HobenProtocolError):
            await session._handle_delimited_data_response(
                DelimitedV4DataResponse(frame, exchange=exchange)
            )
        with pytest.raises(HobenProtocolError):
            await task
        assert session._pending_read is None
        assert session.state is SessionState.CLOSED
        transport.close.assert_awaited_once()
        transport.write.assert_awaited_once()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "raw", [b"\x0e", synthetic_data_response(), bytearray(b"\x0e")]
)
def test_raw_data_response_cannot_claim_delimitation(raw):
    async def scenario():
        session, transport = await connected_ping_session()
        with pytest.raises(HobenProtocolError):
            await session._handle_delimited_data_response(raw)
        transport.write.assert_not_awaited()
        transport.close.assert_awaited_once()

    asyncio.run(scenario())


def test_correlated_modbus_exception_is_typed_and_consumed():
    async def scenario():
        session, transport = await connected_ping_session()
        task, exchange = await start_synthetic_read(session, transport)
        await session._handle_delimited_data_response(
            DelimitedV4DataResponse(
                bytes.fromhex("0E FF FF 00 00 00 03 01 84 02"), exchange=exchange
            )
        )
        with pytest.raises(HobenModbusError) as raised:
            await task
        assert raised.value.exception_code == 2
        assert session.state is SessionState.CONNECTED
        assert session._pending_read is None
        await session.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["duplicate", "stale", "unsolicited"])
def test_response_exchange_cannot_be_reassigned(mode):
    async def scenario():
        session, transport = await connected_ping_session()
        old_exchange = object()
        if mode != "unsolicited":
            first, old_exchange = await start_synthetic_read(session, transport)
            event = DelimitedV4DataResponse(
                synthetic_data_response(), exchange=old_exchange
            )
            await session._handle_delimited_data_response(event)
            if mode == "duplicate":
                with pytest.raises(HobenProtocolError):
                    await session._handle_delimited_data_response(event)
                with pytest.raises(HobenProtocolError):
                    await first
            else:
                await first
        if mode != "duplicate":
            pending = None
            if mode == "stale":
                pending, _ = await start_synthetic_read(session, transport)
            with pytest.raises(HobenProtocolError):
                await session._handle_delimited_data_response(
                    DelimitedV4DataResponse(
                        synthetic_data_response(), exchange=old_exchange
                    )
                )
            if pending:
                with pytest.raises(HobenProtocolError):
                    await pending
        assert session._pending_read is None
        assert session.state is SessionState.CLOSED
        transport.close.assert_awaited_once()

    asyncio.run(scenario())


@pytest.mark.parametrize("timeout", [0, -1, True, float("nan"), float("inf"), "bad"])
def test_read_timeout_validation_precedes_tx(timeout):
    async def scenario():
        session, transport = await connected_ping_session()
        with pytest.raises(HobenInvalidInputError):
            await session.request_v4_data(timeout=timeout)
        assert session.state is SessionState.CONNECTED
        transport.write.assert_not_awaited()
        await session.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["timeout", "cancel", "close", "rx", "eof", "tx"])
def test_read_failure_terminates_waiter_without_replay(mode, deadlines):
    async def scenario():
        session, transport = await connected_ping_session()
        rx_release = asyncio.Event()
        if mode in ("rx", "eof"):

            async def read(*args, **kwargs):
                await rx_release.wait()
                if mode == "eof":
                    raise TransportEOF("private-synthetic-eof")
                return synthetic_data_response()

            transport.read.side_effect = read
        if mode == "tx":
            transport.write.side_effect = TransportTlsError("private-synthetic-error")
            task = asyncio.create_task(session.request_v4_data())
        else:
            task, exchange = await start_synthetic_read(session, transport)
        error = HobenTransportError
        if mode == "timeout":
            context = next(
                context for delay, context in deadlines.contexts if delay == 7
            )
            context.reschedule(asyncio.get_running_loop().time())
            error = HobenTimeoutError
        elif mode == "cancel":
            task.cancel()
            error = asyncio.CancelledError
        elif mode == "close":
            await session.close()
            error = HobenClientClosedError
        elif mode in ("rx", "eof"):
            # The sole real RX owner rejects bytes, including apparent responses.
            rx_release.set()
            error = HobenAmbiguousSessionError if mode == "rx" else HobenTransportError
        with pytest.raises(error) as raised:
            await task
        assert type(raised.value) is error
        assert "private-synthetic" not in str(raised.value) + repr(session.snapshot)
        assert session._pending_read is None
        assert session.state is SessionState.CLOSED
        assert session._rx_task.done()
        transport.close.assert_awaited_once()
        transport.write.assert_awaited_once()
        with pytest.raises(
            (
                SessionStateError,
                HobenTransportError,
                HobenProtocolError,
                HobenClientClosedError,
            )
        ):
            await session.request_v4_data()
        if mode == "timeout":
            with pytest.raises(HobenProtocolError):
                await session._handle_delimited_data_response(
                    DelimitedV4DataResponse(
                        synthetic_data_response(), exchange=exchange
                    )
                )
        transport.write.assert_awaited_once()

    asyncio.run(scenario())


def test_read_tx_serialized_with_pong_and_deadline_covers_queue(deadlines):
    async def scenario():
        session, transport = await connected_ping_session()
        entered, release = asyncio.Event(), asyncio.Event()

        async def write(payload):
            assert payload == b"\x0b"
            entered.set()
            await release.wait()

        transport.write.side_effect = write
        pong = asyncio.create_task(
            session._handle_delimited_ping(DelimitedV4Message.PING)
        )
        await entered.wait()
        task = asyncio.create_task(session.request_v4_data(timeout=7))
        await asyncio.sleep(0)
        context = next(context for delay, context in deadlines.contexts if delay == 7)
        context.reschedule(asyncio.get_running_loop().time())
        await asyncio.sleep(0)
        release.set()
        await pong
        with pytest.raises(HobenTimeoutError):
            await task
        transport.write.assert_awaited_once_with(b"\x0b")
        transport.close.assert_awaited_once()

    asyncio.run(scenario())


@pytest.mark.parametrize("during_tx", [False, True])
def test_cancel_read_while_queued_or_writing_closes(during_tx):
    async def scenario():
        session, transport = await connected_ping_session()
        entered = asyncio.Event()

        async def write(payload):
            entered.set()
            await asyncio.Future()

        transport.write.side_effect = write
        if not during_tx:
            await session._tx_lock.acquire()
        task = asyncio.create_task(session.request_v4_data())
        if during_tx:
            await entered.wait()
        else:
            await asyncio.sleep(0)
        task.cancel()
        if not during_tx:
            session._tx_lock.release()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert session._pending_read is None
        assert transport.write.await_count == int(during_tx)
        transport.close.assert_awaited_once()
        assert session._rx_task.done()

    asyncio.run(scenario())


def test_response_before_tx_is_rejected_without_sending():
    async def scenario():
        session, transport = await connected_ping_session()
        await session._tx_lock.acquire()
        task = asyncio.create_task(session.request_v4_data())
        await asyncio.sleep(0)
        with pytest.raises(HobenProtocolError):
            await session._handle_delimited_data_response(
                DelimitedV4DataResponse(
                    synthetic_data_response(), exchange=session._pending_read
                )
            )
        session._tx_lock.release()
        with pytest.raises(HobenProtocolError):
            await task
        transport.write.assert_not_awaited()
        transport.close.assert_awaited_once()

    asyncio.run(scenario())


def test_read_and_pong_share_tx_lock_and_response_can_arrive_during_drain():
    async def scenario():
        session, transport = await connected_ping_session()
        entered, release = asyncio.Event(), asyncio.Event()
        active = 0

        async def write(payload):
            nonlocal active
            assert active == 0
            active += 1
            try:
                if payload == b"\x0b":
                    entered.set()
                    await release.wait()
                else:
                    await session._handle_delimited_data_response(
                        DelimitedV4DataResponse(
                            synthetic_data_response(), exchange=session._pending_read
                        )
                    )
                await asyncio.sleep(0)
            finally:
                active -= 1

        transport.write.side_effect = write
        pong = asyncio.create_task(
            session._handle_delimited_ping(DelimitedV4Message.PING)
        )
        await entered.wait()
        read = asyncio.create_task(session.request_v4_data())
        await asyncio.sleep(0)
        assert transport.write.await_count == 1
        release.set()
        await pong
        assert (await read).registers == tuple(range(20))
        assert transport.write.await_count == 2
        assert transport.read.await_count == 2
        assert session._pending_read is None
        await session.close()

    asyncio.run(scenario())


def test_verified_read_witness_rejects_uncorrelated_and_ping_only():
    async def scenario():
        session, transport = await connected_ping_session()
        assert session.verified_read_sequence == 0
        await session._handle_delimited_ping(DelimitedV4Message.PING)
        assert session.verified_read_sequence == 0
        task, exchange = await start_synthetic_read(session, transport)
        assert session.verified_read_sequence == 0
        with pytest.raises(HobenProtocolError):
            await session._handle_delimited_data_response(
                DelimitedV4DataResponse(synthetic_data_response(), exchange=object())
            )
        with pytest.raises(HobenProtocolError):
            await task
        assert session.verified_read_sequence == 0
        await session.close()

    asyncio.run(scenario())
