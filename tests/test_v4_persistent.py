"""Slice A: the actual shared persistent runtime, synthetic streams only."""

import asyncio
from dataclasses import FrozenInstanceError, asdict
from unittest.mock import AsyncMock

import pytest

from custom_components.hoben.exceptions import (
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
from custom_components.hoben.transport import TransportEOF, TransportTlsError
from custom_components.hoben.v4_experiment import (
    ExperimentalCloseClientError,
    ExperimentalV4Framer,
    Session300,
    SessionReconnect,
)
from custom_components.hoben.v4_lifecycle import LifecycleExhaustedError, V4Lifecycle
from custom_components.hoben.v4_session import (
    HandoffState,
    SessionState,
    SessionStateError,
    V4OpeningOptions,
    V4Session,
    V4SessionMode,
)
from tests.test_session_300_runtime import Stream, response
from tests.test_session_ignored_rx import ignored_frame
from tests.test_v4_lifecycle import Backoff
from tests.test_v4_session import opened_prefix


class Factory:
    """Fresh real sessions; vary only the wholly offline transport per attempt."""

    def __init__(self, setup=lambda stream, index: None):
        self.sessions, self.streams, self.inputs = [], [], []
        self.setup = setup

    def __call__(self, **kwargs):
        stream = Stream([response()])
        stream.connect = AsyncMock()
        stream.prefix = opened_prefix(identity=b"acde"[len(self.streams) :][:1] * 32)
        self.setup(stream, len(self.streams))
        session = V4Session(**kwargs, transport_factory=lambda: stream)
        self.inputs.append(kwargs)
        self.streams.append(stream)
        self.sessions.append(session)
        return session

    def lifecycle(self, **kwargs):
        return V4Lifecycle(
            user_guid="b" * 32,
            mode=V4SessionMode.PERSISTENT,
            session_factory=self,
            **kwargs,
        )

    def assert_clean(self):
        for session, stream in zip(self.sessions, self.streams, strict=True):
            assert stream.close_count == 1
            assert stream.active_reads == stream.active_tx == 0
            assert session.state is SessionState.CLOSED
            assert session._pending_read is None and session._read_timeout is None
            assert not session._operations and not session._tx_operations
            assert session._opening_task is None
            assert session._rx_task is None or session._rx_task.done()


def test_many_reads_and_over_one_mib_reuse_one_session_without_campaign_reset():
    async def scenario():
        factory = Factory()
        lifecycle = factory.lifecycle()
        await lifecycle.connect()
        session, stream = factory.sessions[0], factory.streams[0]
        framer = session._framer
        assert type(framer) is ExperimentalV4Framer and session._experiment is None
        # No time/cadence manipulation. Opaque notifications exceed the entire
        # experimental lifetime RX quota, without increasing retained memory.
        chunk = ignored_frame(27, 254) * 15
        assert len(chunk) <= 4096
        for _ in range(265):
            stream.queue.put_nowait(chunk)
        for index in range(12):
            result = await lifecycle.request_v4_data()
            assert result.registers == (17,) * 20
            assert session.verified_read_sequence == index + 1
            assert lifecycle.witness.verified_read_sequence == index + 1
            assert lifecycle.witness.established_generation == 1
            assert lifecycle.snapshot.attempts == 1
            assert session._framer is framer
        assert len(factory.sessions) == 1 and stream.close_count == 0
        stream.connect.assert_awaited_once()
        assert [p[0] for p in stream.writes] == [3] + [13] * 12
        assert lifecycle.opening_metadata.product_type == 5
        assert lifecycle.accepted_device_guid_for_persistence == "a" * 32
        assert session.snapshot.handoff is HandoffState.EXPERIMENTAL
        assert not session.snapshot.boundary_proven
        await lifecycle.close()
        assert lifecycle.accepted_device_guid_for_persistence is None
        factory.assert_clean()

    asyncio.run(scenario())


@pytest.mark.parametrize("split", range(1, 50))
def test_persistent_rx_shares_fragmented_mbap_ignored_types_and_ping(split):
    async def scenario():
        factory = Factory()
        lifecycle = factory.lifecycle()
        await lifecycle.connect()
        stream = factory.streams[0]
        stream.chunks = [
            ignored_frame(7) + ignored_frame(27) + b"\x0a" + response()[:split],
            response()[split:] + b"\x0a",
        ]
        await lifecycle.request_v4_data()
        assert [p[0] for p in stream.writes] == [3, 13, 11, 11]
        assert factory.sessions[0].verified_read_sequence == 1
        await lifecycle.close()
        factory.assert_clean()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "chunks", [[b"\x05", b"\x03\x0a" + response()], [b"\x05\x03\xff"]]
)
def test_complete_close_then_correlated_read_on_new_generation(chunks, caplog):
    async def scenario():
        factory, backoff = Factory(), Backoff()
        lifecycle = factory.lifecycle(sleep=backoff, retry_delays=(1,))
        await lifecycle.connect()
        stream, session = factory.streams[0], factory.sessions[0]
        stream.chunks = chunks
        with pytest.raises(ExperimentalCloseClientError) as caught:
            await lifecycle.request_v4_data()
        await backoff.entered.get()
        assert caught.value.safe_report()["subcode"] == 3
        assert lifecycle.snapshot.close_client_subcode == 3
        assert session.snapshot.close_client_subcode == 3
        assert lifecycle.witness.lost_generation is None  # Never fabricate EOF.
        assert [p[0] for p in stream.writes] == [3, 13]  # No suffix processing.
        assert session.cleanup_succeeded
        assert lifecycle.accepted_device_guid_for_persistence == "a" * 32
        backoff.release.put_nowait(None)
        await lifecycle.wait_connected()
        assert lifecycle.witness.established_generation == 2
        assert lifecycle.witness.verified_read_generation is None
        assert factory.inputs[1]["device_guid"] == "a" * 32
        await lifecycle.request_v4_data()
        assert lifecycle.witness.verified_read_generation == 2
        assert lifecycle.accepted_device_guid_for_persistence == "c" * 32
        public = (
            repr(lifecycle)
            + repr(lifecycle.snapshot)
            + repr(lifecycle.opening_metadata)
        )
        assert all(
            secret not in public + caplog.text
            for secret in ("a" * 32, "b" * 32, "c" * 32)
        )
        await lifecycle.close()
        factory.assert_clean()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "loss", [b"", TransportEOF("private"), TransportTlsError("private")]
)
def test_idle_loss_and_repeated_losses_consume_nonresetting_lifetime_attempts(loss):
    async def scenario():
        factory, backoff = Factory(), Backoff()
        lifecycle = factory.lifecycle(sleep=backoff, retry_delays=(1,))
        await lifecycle.connect()
        factory.streams[0].queue.put_nowait(loss)
        await backoff.entered.get()
        backoff.release.put_nowait(None)
        await lifecycle.wait_connected()
        for _ in range(12):
            await lifecycle.request_v4_data()
        factory.streams[1].queue.put_nowait(loss)
        with pytest.raises(LifecycleExhaustedError):
            await lifecycle.wait_stopped()
        assert lifecycle.snapshot.attempts == 2 and backoff.delays == [1]
        assert lifecycle.accepted_device_guid_for_persistence == "c" * 32
        assert lifecycle.opening_metadata.product_type == 5
        await lifecycle.close()
        factory.assert_clean()

    asyncio.run(scenario())


@pytest.mark.parametrize("phase", ["connect", "read"])
def test_deadlines_preserve_identity_and_stop_without_replay(phase, deadlines):
    async def scenario():
        factory = Factory()
        options = V4OpeningOptions(handshake_timeout=7)
        lifecycle = factory.lifecycle(opening_options=options)
        if phase == "connect":
            factory.setup = lambda stream, index: setattr(
                stream, "read", deadlines.expire
            )
        with pytest.raises(HobenTimeoutError):
            await lifecycle.connect()
            factory.streams[0].chunks = []
            factory.streams[0].write = deadlines.expire
            await lifecycle.request_v4_data(timeout=9)
        with pytest.raises(HobenTimeoutError):
            await lifecycle.wait_stopped()
        assert len(factory.sessions) == 1
        assert lifecycle.accepted_device_guid_for_persistence == (
            None if phase == "connect" else "a" * 32
        )
        assert (7 if phase == "connect" else 9) in [d for d, _ in deadlines.contexts]
        await lifecycle.close()
        factory.assert_clean()

    asyncio.run(scenario())


@pytest.mark.parametrize("stop", ["cancel", "close"])
def test_pending_read_stop_cancels_waiters_and_never_replays(stop):
    async def scenario():
        factory = Factory()
        lifecycle = factory.lifecycle()
        await lifecycle.connect()
        stream = factory.streams[0]
        stream.chunks = []
        pending = asyncio.create_task(lifecycle.request_v4_data())
        while len(stream.writes) < 2:
            await asyncio.sleep(0)
        if stop == "cancel":
            pending.cancel()
        else:
            await lifecycle.close()
        with pytest.raises(
            asyncio.CancelledError
            if stop == "cancel"
            else (asyncio.CancelledError, HobenClientClosedError)
        ):
            await pending
        # Late response belongs to the discarded stream, never a fresh waiter.
        stream.queue.put_nowait(response())
        await lifecycle.close()
        await lifecycle.close()
        assert len(factory.sessions) == 1
        factory.assert_clean()

    asyncio.run(scenario())


@pytest.mark.parametrize("loss", [b"\x05\x03", TransportEOF("private")])
def test_failed_close_forbids_production_reopening(loss):
    async def scenario():
        factory = Factory()
        lifecycle = factory.lifecycle()
        await lifecycle.connect()
        stream = factory.streams[0]
        stream.close = AsyncMock(side_effect=TransportTlsError("private-close"))
        stream.queue.put_nowait(loss)
        with pytest.raises((HobenTransportError, ExperimentalCloseClientError)):
            await lifecycle.wait_stopped()
        assert len(factory.sessions) == 1
        assert not factory.sessions[0].cleanup_succeeded
        stream.close.assert_awaited_once()
        await lifecycle.close()
        assert stream.active_reads == stream.active_tx == 0

    asyncio.run(scenario())


def test_opening_options_propagate_once_and_never_appear_in_public_state(caplog):
    async def scenario():
        options = V4OpeningOptions(
            build=35, device_info="synthetic-private-descriptor", handshake_timeout=12
        )
        with pytest.raises(FrozenInstanceError):
            options.build = 36
        factory = Factory()
        lifecycle = factory.lifecycle(opening_options=options, retry_delays=(0,))
        await lifecycle.connect()
        assert factory.streams[0].writes[0] == encode_open_client(
            "b" * 32, 35, INITIAL_DEVICE_GUID, options.device_info
        )
        public = (
            repr(options)
            + repr(lifecycle)
            + repr(asdict(lifecycle.snapshot))
            + repr(lifecycle.opening_metadata)
        )
        assert options.device_info not in public + caplog.text
        assert "b" * 32 not in public + caplog.text
        await lifecycle.close()
        factory.assert_clean()

    asyncio.run(scenario())


@pytest.mark.parametrize("bad", ["persistent", True, None])
def test_mode_must_be_typed_before_any_io(bad):
    with pytest.raises(HobenInvalidInputError):
        V4Session(mode=bad)
    with pytest.raises(HobenInvalidInputError):
        V4Lifecycle(user_guid="b" * 32, mode=bad)


@pytest.mark.parametrize("budget", [Session300, SessionReconnect])
def test_persistent_mode_cannot_bypass_a_campaign_budget(budget):
    with pytest.raises(HobenInvalidInputError):
        V4Session(mode=V4SessionMode.PERSISTENT, session_300=budget())


@pytest.mark.parametrize(
    "field,value",
    [
        ("build", True),
        ("build", 65536),
        ("device_info", 12),
        ("handshake_timeout", 0),
        ("handshake_timeout", float("inf")),
    ],
)
def test_invalid_options_are_rejected_without_echoing_input(field, value):
    with pytest.raises(HobenInvalidInputError, match="^invalid_client_inputs$"):
        V4OpeningOptions(**{field: value})


def test_production_backoff_has_finite_count_and_delay():
    for delays in ((1,) * 9, (31,), (float("inf"),), (-1,)):
        with pytest.raises(HobenInvalidInputError):
            V4Lifecycle(
                user_guid="b" * 32, mode=V4SessionMode.PERSISTENT, retry_delays=delays
            )


@pytest.mark.parametrize(
    "prefix,error",
    [
        (b"\x2f", HobenAuthorizationRequiredError),
        (b"\x05\x02", HobenInvalidCredentialsError),
        (opened_prefix(profile=99), HobenUnsupportedProfileError),
    ],
)
def test_existing_auth_and_profile_failures_do_not_adopt_identity(prefix, error):
    async def scenario():
        factory = Factory(setup=lambda stream, index: setattr(stream, "prefix", prefix))
        lifecycle = factory.lifecycle()
        with pytest.raises(error):
            await lifecycle.connect()
        assert lifecycle.accepted_device_guid_for_persistence is None
        assert lifecycle.opening_metadata is None and len(factory.sessions) == 1
        assert [p[0] for p in factory.streams[0].writes] == [3]
        await lifecycle.close()
        factory.assert_clean()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "data",
    [
        response() * 2,
        response().replace(b"\xff\xff", b"\xff\xfe", 1),
        ignored_frame(7, 1),
        ignored_frame(27, 255),
        b"\x05\xff\xff",
        b"\xff\x0a",
        b"x" * 4097,
    ],
)
def test_bad_rx_never_produces_verified_read_or_unbounded_retry(data):
    async def scenario():
        factory = Factory(setup=lambda stream, index: setattr(stream, "chunks", [data]))
        lifecycle = factory.lifecycle(retry_delays=())
        await lifecycle.connect()
        with pytest.raises((HobenProtocolError, ExperimentalCloseClientError)):
            await lifecycle.request_v4_data()
        assert lifecycle.witness.verified_read_generation is None
        await lifecycle.close()
        factory.assert_clean()

    asyncio.run(scenario())


def test_concurrent_read_is_rejected_and_consumed_modbus_exception_keeps_session():
    async def scenario():
        factory = Factory()
        lifecycle = factory.lifecycle()
        await lifecycle.connect()
        stream = factory.streams[0]
        stream.chunks = []
        pending = asyncio.create_task(lifecycle.request_v4_data())
        while len(stream.writes) < 2:
            await asyncio.sleep(0)
        with pytest.raises(SessionStateError):
            await lifecycle.request_v4_data()
        stream.queue.put_nowait(bytes.fromhex("0effff00000003018402"))
        with pytest.raises(HobenModbusError):
            await pending
        stream.chunks = [response()]
        await lifecycle.request_v4_data()
        assert len(factory.sessions) == 1
        await lifecycle.close()
        factory.assert_clean()

    asyncio.run(scenario())


def test_silence_across_poll_intervals_has_no_idle_deadline(deadlines):
    async def scenario():
        now = [0.0]
        factory = Factory()
        lifecycle = factory.lifecycle(clock=lambda: now[0])
        await lifecycle.connect()
        for time in (31, 61, 301, 901):
            now[0] = time
            await asyncio.sleep(0)
            assert lifecycle.state is SessionState.CONNECTED
            assert lifecycle.snapshot.attempts == 1
        assert len(deadlines.contexts) == 1  # Completed handshake only.
        await lifecycle.request_v4_data()
        assert len(factory.sessions) == 1
        await lifecycle.close()
        factory.assert_clean()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "ending", [b"", TransportEOF("private"), TransportTlsError("private")]
)
def test_partial_close_is_not_a_complete_close_or_numeric_diagnostic(ending):
    async def scenario():
        factory = Factory(
            setup=lambda stream, index: setattr(stream, "chunks", [b"\x05", ending])
        )
        lifecycle = factory.lifecycle(retry_delays=())
        await lifecycle.connect()
        with pytest.raises((HobenProtocolError, HobenTransportError)):
            await lifecycle.request_v4_data()
        assert lifecycle.snapshot.close_client_subcode is None
        assert factory.sessions[0].snapshot.close_client_subcode is None
        assert not factory.sessions[0].close_client_received
        await lifecycle.close()
        factory.assert_clean()

    asyncio.run(scenario())


def test_opening_ping_and_coalesced_suffix_share_existing_handshake_and_rx():
    async def scenario():
        factory = Factory(
            setup=lambda stream, index: setattr(
                stream, "prefix", b"\x0a" + opened_prefix() + b"\x0a"
            )
        )
        lifecycle = factory.lifecycle()
        await lifecycle.connect()
        await lifecycle.request_v4_data()
        assert [p[0] for p in factory.streams[0].writes].count(11) == 2
        await lifecycle.close()
        factory.assert_clean()

    asyncio.run(scenario())


def test_response_coalesced_with_opening_cannot_satisfy_a_later_request():
    async def scenario():
        factory = Factory(
            setup=lambda stream, index: setattr(
                stream, "prefix", opened_prefix() + response()
            )
        )
        lifecycle = factory.lifecycle()
        await lifecycle.connect()
        with pytest.raises(HobenProtocolError):
            await lifecycle.wait_stopped()
        assert lifecycle.witness.verified_read_generation is None
        assert [p[0] for p in factory.streams[0].writes] == [3]
        await lifecycle.close()
        factory.assert_clean()

    asyncio.run(scenario())


def test_stop_during_opening_cleans_without_late_acceptance():
    async def scenario():
        entered = asyncio.Event()

        async def wait(*args, **kwargs):
            entered.set()
            await asyncio.Future()

        factory = Factory(setup=lambda stream, index: setattr(stream, "read", wait))
        lifecycle = factory.lifecycle()
        pending = asyncio.create_task(lifecycle.connect())
        await entered.wait()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert lifecycle.accepted_device_guid_for_persistence is None
        await lifecycle.close()
        factory.assert_clean()

    asyncio.run(scenario())
