"""Deterministic lifecycle acceptance tests, without sockets or wall-clock waits."""

import asyncio
from dataclasses import FrozenInstanceError
from unittest.mock import AsyncMock

import pytest

from custom_components.hoben.client import DEFAULT_BUILD, DEFAULT_DEVICE_INFO
from custom_components.hoben.exceptions import (
    HobenAmbiguousSessionError,
    HobenAuthorizationRequiredError,
    HobenClientClosedError,
    HobenInvalidInputError,
    HobenModbusError,
    HobenProtocolError,
    HobenTimeoutError,
    HobenTransportError,
)
from custom_components.hoben.myhoben import INITIAL_DEVICE_GUID, encode_open_client
from custom_components.hoben.transport import TransportEOF, TransportTlsError
from custom_components.hoben.v4_lifecycle import (
    LifecycleExhaustedError,
    LifecycleStoppedError,
    V4Lifecycle,
)
from custom_components.hoben.v4_session import (
    DelimitedV4DataResponse,
    DelimitedV4Message,
    SessionState,
    V4Session,
)


class OfflineTransport:
    """One synthetic opening followed by a controllable quiet RX owner."""

    def __init__(self, *, failure=None, identity="a" * 32):
        self.failure = failure
        self.identity = identity
        self.rx = asyncio.get_running_loop().create_future()
        self.rx_started = asyncio.Event()
        self.data_sent = asyncio.Event()
        self.tx_started = asyncio.Event()
        self.close_started = asyncio.Event()
        self.open_gate = None
        self.tx_gate = None
        self.close_gate = None
        self.writes = []
        self.connect_count = 0
        self.close_count = 0
        self.active_tx = 0

    async def connect(self):
        self.connect_count += 1
        if self.open_gate is not None:
            await self.open_gate.wait()
        if self.failure:
            raise self.failure

    async def read(self, max_bytes=4096, *, bounded=True):
        if bounded:
            return (
                bytes([4, 0, 0, 0, 0, 0, 0, 1, 5, 2, 8, 0, 0, 0])
                + self.identity.encode("ascii")
                + b"\x00\x02"
            )
        self.rx_started.set()
        return await self.rx

    async def write(self, payload):
        assert self.active_tx == 0, "overlapping TX"
        self.active_tx += 1
        try:
            self.writes.append(payload)
            if payload[0] == 13:
                self.data_sent.set()
            if payload[0] in (11, 13):
                self.tx_started.set()
                if self.tx_gate is not None:
                    await self.tx_gate.wait()
        finally:
            self.active_tx -= 1

    async def close(self):
        self.close_count += 1
        self.close_started.set()
        if self.close_gate is not None:
            await self.close_gate.wait()


class Factory:
    """Fresh real V4Session objects over wholly offline transports."""

    def __init__(self, *, failures=(), setup=None):
        self.sessions = []
        self.transports = []
        self.inputs = []
        self.failures = failures
        self.setup = setup

    def __call__(self, **kwargs):
        index = len(self.sessions)
        failure = self.failures[index] if index < len(self.failures) else None
        transport = OfflineTransport(failure=failure, identity="acde"[index % 4] * 32)
        if self.setup:
            self.setup(transport)
        session = V4Session(**kwargs, transport_factory=lambda: transport)
        self.inputs.append(kwargs)
        self.transports.append(transport)
        self.sessions.append(session)
        return session


class Backoff:
    """Advance recovery explicitly, without using elapsed wall time."""

    def __init__(self):
        self.delays = []
        self.entered = asyncio.Queue()
        self.release = asyncio.Queue()

    async def __call__(self, delay):
        self.delays.append(delay)
        self.entered.put_nowait(delay)
        await self.release.get()


def assert_clean(factory):
    for session, transport in zip(factory.sessions, factory.transports, strict=True):
        assert session.state is SessionState.CLOSED
        assert session._pending_read is None
        assert not session._tx_operations
        assert not session._operations
        assert session._opening_task is None
        assert session._rx_task is None or session._rx_task.done()
        assert session._transport is None
        assert session._user_guid is None
        assert session.device_guid_for_persistence == INITIAL_DEVICE_GUID
        assert transport.close_count == 1
        assert transport.active_tx == 0


@pytest.mark.parametrize(
    "loss", [TransportEOF("private-loss"), TransportTlsError("private-loss")]
)
def test_loss_cleans_read_before_backoff_and_new_opening(loss, caplog):
    async def scenario():
        factory, sleep = Factory(), Backoff()
        lifecycle = V4Lifecycle(
            user_guid="b" * 32, session_factory=factory, sleep=sleep
        )
        await lifecycle.connect()
        old = factory.sessions[0]
        transport = factory.transports[0]
        await transport.rx_started.wait()
        read = asyncio.create_task(lifecycle.request_v4_data())
        await transport.data_sent.wait()
        old_exchange = old._pending_read
        transport.rx.set_exception(loss)
        assert await sleep.entered.get() == 1
        with pytest.raises(HobenTransportError) as raised:
            await read
        assert type(raised.value) is HobenTransportError
        assert lifecycle.state is SessionState.RECONNECTING
        assert lifecycle.snapshot.attempts == 1
        assert lifecycle.snapshot.failure == "transport_unavailable"
        assert_clean(factory)
        sleep.release.put_nowait(None)
        await lifecycle.wait_connected()
        new = factory.sessions[1]
        assert new is not old and new._pending_read is None
        assert old_exchange.done()
        assert factory.inputs[1]["device_guid"] == "a" * 32
        assert lifecycle.device_guid_for_persistence == "c" * 32
        assert factory.transports[1].writes == [
            encode_open_client("b" * 32, DEFAULT_BUILD, "a" * 32, DEFAULT_DEVICE_INFO)
        ]
        assert "private-loss" not in repr(lifecycle.snapshot) + str(raised.value)
        assert "b" * 32 not in repr(lifecycle) + repr(lifecycle.snapshot)
        assert not caplog.records
        await lifecycle.close()
        assert_clean(factory)

    asyncio.run(scenario())


def test_ordered_backoff_and_strict_lifetime_budget():
    async def scenario():
        factory = Factory(failures=[TransportTlsError("private")] * 3)
        sleep = AsyncMock()
        lifecycle = V4Lifecycle(
            user_guid="b" * 32,
            retry_delays=(2, 5),
            session_factory=factory,
            sleep=sleep,
        )
        with pytest.raises(LifecycleExhaustedError):
            await lifecycle.connect()
        with pytest.raises(LifecycleExhaustedError):
            await lifecycle.wait_stopped()
        assert [call.args[0] for call in sleep.await_args_list] == [2, 5]
        assert len(factory.sessions) == 3
        assert lifecycle.snapshot.attempts == lifecycle.snapshot.max_attempts == 3
        assert lifecycle.snapshot.failure == "session_lifecycle_exhausted"
        assert lifecycle.state is SessionState.DISCONNECTED
        assert_clean(factory)
        await lifecycle.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "settings",
    [
        {"retry_delays": (0,)},
        {"retry_delays": (-1,)},
        {"retry_delays": (True,)},
        {"retry_delays": (float("nan"),)},
        {"retry_delays": (float("inf"),)},
        {"retry_delays": ("bad",)},
        {"retry_delays": [1]},
        {"retry_delays": (1,) * 9},
        {"session_factory": None},
        {"sleep": None},
        {"user_guid": "private-invalid"},
        {"device_guid": "private-invalid"},
    ],
)
def test_invalid_configuration_rejected_before_factory(settings):
    factory = Factory()
    with pytest.raises(HobenInvalidInputError, match="^invalid_client_inputs$"):
        V4Lifecycle(**({"user_guid": "b" * 32, "session_factory": factory} | settings))
    assert not factory.sessions


@pytest.mark.parametrize("phase", ["opening", "read", "pong", "backoff", "cleanup"])
def test_close_during_each_phase_has_no_late_reconnect_or_orphan(phase):
    async def scenario():
        gate = asyncio.Event()

        def setup(transport):
            if phase == "opening":
                transport.open_gate = gate
            if phase == "cleanup":
                transport.close_gate = gate

        factory, sleep = Factory(setup=setup), Backoff()
        lifecycle = V4Lifecycle(
            user_guid="b" * 32, session_factory=factory, sleep=sleep
        )
        connecting = asyncio.create_task(lifecycle.connect())
        if phase == "opening":
            await asyncio.sleep(0)
            await asyncio.sleep(0)
        else:
            await connecting
        operation = None
        transport = factory.transports[0]
        if phase == "read":
            operation = asyncio.create_task(lifecycle.request_v4_data())
            await transport.data_sent.wait()
        elif phase == "pong":
            transport.tx_gate = gate
            operation = asyncio.create_task(
                factory.sessions[0]._handle_delimited_ping(DelimitedV4Message.PING)
            )
            await transport.tx_started.wait()
        elif phase in ("backoff", "cleanup"):
            await transport.rx_started.wait()
            transport.rx.set_exception(TransportEOF("private"))
            if phase == "backoff":
                await sleep.entered.get()
            else:
                await transport.close_started.wait()
        await lifecycle.close()
        await lifecycle.close()
        if phase == "opening":
            with pytest.raises(LifecycleStoppedError):
                await connecting
        if operation:
            with pytest.raises((asyncio.CancelledError, HobenClientClosedError)):
                await operation
        gate.set()
        sleep.release.put_nowait(None)
        await asyncio.sleep(0)
        assert len(factory.sessions) == 1
        assert lifecycle.state is SessionState.CLOSED
        assert lifecycle._task.done()
        assert_clean(factory)
        with pytest.raises(LifecycleStoppedError):
            await lifecycle.wait_stopped()
        with pytest.raises(LifecycleStoppedError):
            await lifecycle.request_v4_data()

    asyncio.run(scenario())


def test_quiet_session_and_consumed_modbus_exception_never_reconnect(
    deadlines, monkeypatch
):
    async def scenario():
        factory, sleep = Factory(), AsyncMock()
        lifecycle = V4Lifecycle(
            user_guid="b" * 32, session_factory=factory, sleep=sleep
        )
        await lifecycle.connect()
        transport = factory.transports[0]
        await transport.rx_started.wait()
        # Advance the monotonic clock beyond the one-shot and polling intervals.
        loop = asyncio.get_running_loop()
        advanced = loop.time() + 601
        monkeypatch.setattr(loop, "time", lambda: advanced)
        # No live inactivity timer exists to expire, even beyond polling cadence.
        assert all(context.expired() is False for _, context in deadlines.contexts)
        for _ in range(5):
            await asyncio.sleep(0)
        assert not lifecycle._task.done()
        sleep.assert_not_awaited()
        assert len(factory.sessions) == 1
        read = asyncio.create_task(lifecycle.request_v4_data())
        await transport.data_sent.wait()
        session = factory.sessions[0]
        await session._handle_delimited_data_response(
            DelimitedV4DataResponse(
                bytes.fromhex("0E FF FF 00 00 00 03 01 84 02"),
                exchange=session._pending_read,
            )
        )
        with pytest.raises(HobenModbusError):
            await read
        await asyncio.sleep(0)
        assert lifecycle.state is SessionState.CONNECTED
        assert len(factory.sessions) == 1
        sleep.assert_not_awaited()
        await lifecycle.close()
        assert_clean(factory)

    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["ambiguous", "auth", "timeout"])
def test_nonretryable_failures_stop_with_original_typed_error(kind, deadlines):
    async def scenario():
        factory, sleep = Factory(), AsyncMock()
        lifecycle = V4Lifecycle(
            user_guid="b" * 32, session_factory=factory, sleep=sleep
        )
        await lifecycle.connect()
        transport = factory.transports[0]
        await transport.rx_started.wait()
        if kind == "ambiguous":
            transport.rx.set_result(b"\x0a")
            error = HobenAmbiguousSessionError
        elif kind == "auth":
            factory.sessions[0]._rx_error = HobenAuthorizationRequiredError()
            factory.sessions[0]._loss_event.set()
            error = HobenAuthorizationRequiredError
        else:
            read = asyncio.create_task(lifecycle.request_v4_data(timeout=7))
            await transport.data_sent.wait()
            next(
                context for delay, context in deadlines.contexts if delay == 7
            ).reschedule(asyncio.get_running_loop().time())
            with pytest.raises(HobenTimeoutError):
                await read
            error = HobenTimeoutError
        with pytest.raises(error):
            await lifecycle.wait_stopped()
        assert len(factory.sessions) == 1
        sleep.assert_not_awaited()
        assert_clean(factory)
        await lifecycle.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("operation", ["read", "pong"])
def test_loss_during_blocked_tx_aborts_before_fresh_opening(operation):
    async def scenario():
        factory, sleep = Factory(), Backoff()
        lifecycle = V4Lifecycle(
            user_guid="b" * 32, session_factory=factory, sleep=sleep
        )
        await lifecycle.connect()
        old, transport = factory.sessions[0], factory.transports[0]
        await transport.rx_started.wait()
        transport.tx_gate = asyncio.Event()
        sending = asyncio.create_task(
            lifecycle.request_v4_data()
            if operation == "read"
            else old._handle_delimited_ping(DelimitedV4Message.PING)
        )
        await transport.tx_started.wait()
        transport.rx.set_exception(TransportTlsError("private-loss"))
        await sleep.entered.get()
        with pytest.raises(asyncio.CancelledError):
            await sending
        assert_clean(factory)
        sleep.release.put_nowait(None)
        await lifecycle.wait_connected()
        assert len(factory.transports[1].writes) == 1  # Only a fresh OpenClient.
        await lifecycle.close()
        assert_clean(factory)

    asyncio.run(scenario())


def test_snapshot_immutable_and_close_before_start_is_terminal():
    factory = Factory()
    lifecycle = V4Lifecycle(user_guid="b" * 32, session_factory=factory)
    with pytest.raises(FrozenInstanceError):
        lifecycle.snapshot.attempts = 8
    asyncio.run(lifecycle.close())
    with pytest.raises(LifecycleStoppedError):
        asyncio.run(lifecycle.connect())
    assert not factory.sessions


def test_close_before_worker_first_instruction_wakes_connect_caller():
    async def scenario():
        factory = Factory()
        lifecycle = V4Lifecycle(user_guid="b" * 32, session_factory=factory)
        connecting = asyncio.create_task(lifecycle.connect())
        await asyncio.sleep(0)  # connect has queued its worker, not run it yet.
        await lifecycle.close()
        await asyncio.gather(lifecycle.close(), lifecycle.close())
        with pytest.raises(LifecycleStoppedError):
            await connecting
        with pytest.raises(LifecycleStoppedError):
            await lifecycle.wait_stopped()
        assert not factory.sessions
        assert lifecycle._task.done()
        assert lifecycle._ready.done()

    asyncio.run(scenario())


def test_success_does_not_replenish_budget_and_late_response_stays_old():
    async def scenario():
        factory, sleep = Factory(), Backoff()
        lifecycle = V4Lifecycle(
            user_guid="b" * 32, retry_delays=(3,), session_factory=factory, sleep=sleep
        )
        await lifecycle.connect()
        old, transport = factory.sessions[0], factory.transports[0]
        await transport.rx_started.wait()
        read = asyncio.create_task(lifecycle.request_v4_data())
        await transport.data_sent.wait()
        exchange = old._pending_read
        transport.rx.set_exception(TransportEOF("private"))
        await sleep.entered.get()
        with pytest.raises(HobenTransportError):
            await read
        sleep.release.put_nowait(None)
        await lifecycle.wait_connected()
        session, transport = factory.sessions[1], factory.transports[1]
        read = asyncio.create_task(lifecycle.request_v4_data())
        await transport.data_sent.wait()
        frame = bytes.fromhex("0E FF FF 00 00 00 2B 01 04 28") + b"\x00\x11" * 20
        # An old callback, even synthetically well formed, retains its old owner.
        with pytest.raises(HobenProtocolError):
            await old._handle_delimited_data_response(
                DelimitedV4DataResponse(frame, exchange=exchange)
            )
        assert not read.done()
        assert session._pending_read is not exchange
        await session._handle_delimited_data_response(
            DelimitedV4DataResponse(frame, exchange=session._pending_read)
        )
        assert (await read).registers == (17,) * 20
        assert len(transport.writes) == 2  # Opening + only the new caller's read.
        await transport.rx_started.wait()
        transport.rx.set_exception(TransportEOF("private"))
        with pytest.raises(LifecycleExhaustedError):
            await lifecycle.wait_stopped()
        assert sleep.delays == [3]
        assert len(factory.sessions) == 2
        assert_clean(factory)
        await lifecycle.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("operation", ["read", "pong"])
def test_tx_tls_error_preserves_typed_cause_and_never_replays(operation):
    async def scenario():
        factory, sleep = Factory(), Backoff()
        lifecycle = V4Lifecycle(
            user_guid="b" * 32, session_factory=factory, sleep=sleep
        )
        await lifecycle.connect()
        transport = factory.transports[0]
        transport.write = AsyncMock(side_effect=TransportTlsError("private-tx"))
        with pytest.raises(HobenTransportError) as raised:
            if operation == "read":
                await lifecycle.request_v4_data()
            else:
                await factory.sessions[0]._handle_delimited_ping(
                    DelimitedV4Message.PING
                )
        assert type(raised.value) is HobenTransportError
        await sleep.entered.get()
        assert lifecycle.snapshot.failure == "transport_unavailable"
        transport.write.assert_awaited_once()
        sleep.release.put_nowait(None)
        await lifecycle.wait_connected()
        assert len(factory.transports[1].writes) == 1
        await lifecycle.close()
        assert_clean(factory)

    asyncio.run(scenario())


def test_invalid_user_call_and_cancelled_observer_do_not_reconnect():
    async def scenario():
        factory, sleep = Factory(), AsyncMock()
        lifecycle = V4Lifecycle(
            user_guid="b" * 32, session_factory=factory, sleep=sleep
        )
        await lifecycle.connect()
        with pytest.raises(HobenInvalidInputError):
            await lifecycle.request_v4_data(timeout=0)
        observer = asyncio.create_task(lifecycle.wait_stopped())
        await asyncio.sleep(0)
        observer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await observer
        assert not lifecycle._task.cancelling()
        assert lifecycle.state is SessionState.CONNECTED
        sleep.assert_not_awaited()
        assert len(factory.transports[0].writes) == 1
        await lifecycle.close()
        assert_clean(factory)

    asyncio.run(scenario())


def test_cancel_initial_connect_closes_opening_and_does_not_retry():
    async def scenario():
        factory = Factory(
            setup=lambda transport: setattr(transport, "open_gate", asyncio.Event())
        )
        sleep = AsyncMock()
        lifecycle = V4Lifecycle(
            user_guid="b" * 32, session_factory=factory, sleep=sleep
        )
        connecting = asyncio.create_task(lifecycle.connect())
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        connecting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await connecting
        assert lifecycle.state is SessionState.CLOSED
        assert lifecycle._task.done()
        assert_clean(factory)
        sleep.assert_not_awaited()

    asyncio.run(scenario())


@pytest.mark.parametrize("cause", ["factory", "backoff", "close"])
def test_injected_failures_are_sanitized_and_secondary_close_keeps_primary(
    cause, caplog
):
    async def scenario():
        factory = Factory(failures=[TransportTlsError("private-injected")])
        sleep = AsyncMock(side_effect=RuntimeError("private-injected"))

        def session_factory(**kwargs):
            if cause == "factory":
                raise RuntimeError("private-injected")
            session = factory(**kwargs)
            if cause == "close":
                factory.transports[-1].close = AsyncMock(
                    side_effect=RuntimeError("private-injected")
                )
            return session

        lifecycle = V4Lifecycle(
            user_guid="b" * 32,
            retry_delays=() if cause == "close" else (1,),
            session_factory=session_factory,
            sleep=sleep,
        )
        error = LifecycleExhaustedError if cause == "close" else HobenProtocolError
        with pytest.raises(error) as raised:
            await lifecycle.connect()
        assert "private-injected" not in repr(raised.value) + repr(lifecycle.snapshot)
        assert not caplog.records
        assert lifecycle._session is None
        assert lifecycle._task.done()
        await lifecycle.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("operation", ["read", "pong"])
def test_caller_cancellation_is_not_misclassified_as_transport_loss(operation):
    async def scenario():
        factory, sleep = Factory(), AsyncMock()
        lifecycle = V4Lifecycle(
            user_guid="b" * 32, session_factory=factory, sleep=sleep
        )
        await lifecycle.connect()
        transport = factory.transports[0]
        transport.tx_gate = asyncio.Event()
        task = asyncio.create_task(
            lifecycle.request_v4_data()
            if operation == "read"
            else factory.sessions[0]._handle_delimited_ping(DelimitedV4Message.PING)
        )
        await transport.tx_started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(HobenTransportError):
            await lifecycle.wait_stopped()
        sleep.assert_not_awaited()
        assert len(factory.sessions) == 1
        assert_clean(factory)
        await lifecycle.close()

    asyncio.run(scenario())


def test_empty_rx_is_a_transport_loss_and_consumes_budget():
    async def scenario():
        factory = Factory()
        lifecycle = V4Lifecycle(
            user_guid="b" * 32, retry_delays=(), session_factory=factory
        )
        await lifecycle.connect()
        transport = factory.transports[0]
        await transport.rx_started.wait()
        transport.rx.set_result(b"")
        with pytest.raises(LifecycleExhaustedError):
            await lifecycle.wait_stopped()
        assert_clean(factory)
        await lifecycle.close()

    asyncio.run(scenario())
