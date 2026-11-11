"""B8 timing over real shared owners, with synthetic TLS and monotone clock."""

import asyncio

import pytest

from custom_components.hoben.exceptions import (
    HobenClosedError,
    HobenError,
    HobenInternalError,
    HobenTimeoutError,
)
from custom_components.hoben.transport import (
    TransportEOF,
    TransportError,
    TransportTimeout,
    TransportTlsError,
)
from custom_components.hoben.v4_lifecycle import V4Lifecycle
from custom_components.hoben.v4_session import V4Session, V4SessionMode
from tests.test_ha_reconnect_policy import Clock
from tests.test_v4_lifecycle import Factory, assert_clean


@pytest.mark.parametrize("fault", [TransportEOF(), b"", b"\x05\x03", b"\x05\x06"])
def test_frank_loss_waits_10_after_cleanup_then_10_after_acceptance(fault):
    async def scenario():
        clock, factory = Clock(), Factory()
        life = V4Lifecycle(
            user_guid="b" * 32,
            mode=V4SessionMode.PERSISTENT,
            recover_acquisition=True,
            ha_reconnect=True,
            ha_fast_reconnect=True,
            session_factory=factory,
            sleep=clock.sleep,
            clock=lambda: clock.now,
        )
        try:
            await life.connect()
            first = factory.transports[0]
            await first.rx_started.wait()
            if isinstance(fault, Exception):
                first.rx.set_exception(fault)
            else:
                first.rx.set_result(fault)
            assert await clock.waiting.get() == 10
            assert factory.sessions[0].cleanup_succeeded
            await clock.advance(9.999)
            assert len(factory.sessions) == 1
            await clock.advance(0.0011)
            assert await clock.waiting.get() == 10
            assert len(factory.sessions) == 2
            waiter = asyncio.create_task(life.wait_connected())
            with pytest.raises(RuntimeError):
                await life.request_v4_data()
            await clock.advance(9.999)
            assert not waiter.done()
            await clock.advance(0.0011)
            await waiter
            assert life.ha_acquisition_generation == 2
        finally:
            await life.close()
            assert_clean(factory)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "fault",
    [
        TransportError(),
        TransportTlsError(),
        HobenTimeoutError(),
        b"\x05\x09",
        b"\x05\xff",
        b"\x0e\xff\xff\x00\x00\xff\xff",  # malformed known MBAP
    ],
)
def test_ambiguous_or_generic_loss_keeps_60_and_has_no_accelerated_read(fault):
    async def scenario():
        clock, factory = Clock(), Factory()
        life = V4Lifecycle(
            user_guid="b" * 32,
            mode=V4SessionMode.PERSISTENT,
            recover_acquisition=True,
            ha_reconnect=True,
            ha_fast_reconnect=True,
            session_factory=factory,
            sleep=clock.sleep,
            clock=lambda: clock.now,
        )
        try:
            await life.connect()
            wire = factory.transports[0]
            await wire.rx_started.wait()
            if isinstance(fault, Exception):
                wire.rx.set_exception(fault)
            else:
                wire.rx.set_result(fault)
            assert await clock.waiting.get() == 60
            assert factory.sessions[0].cleanup_succeeded
            await clock.advance(59.999)
            assert len(factory.sessions) == 1
            await clock.advance(0.0011)
            await life.wait_connected()
            assert life.ha_acquisition_generation is None
            assert len(factory.sessions) == 2
        finally:
            await life.close()
            assert_clean(factory)

    asyncio.run(scenario())


@pytest.mark.parametrize("later_seconds", [0, 5, 31])
def test_silent_acquisition_timeout_has_no_reconnect_deadline(later_seconds):
    async def scenario():
        clock, factory = Clock(), Factory()
        life = V4Lifecycle(
            user_guid="b" * 32,
            mode=V4SessionMode.PERSISTENT,
            recover_acquisition=True,
            ha_reconnect=True,
            ha_fast_reconnect=True,
            session_factory=factory,
            sleep=clock.sleep,
            clock=lambda: clock.now,
        )
        try:
            await life.connect()
            wire = factory.transports[0]
            request = asyncio.create_task(life.request_v4_data(timeout=30))
            await wire.data_sent.wait()
            wire.rx.set_exception(TransportTimeout("read"))
            with pytest.raises(HobenTimeoutError):
                await request
            clock.now = later_seconds
            assert life.acquisition_uncertain and not wire.close_started.is_set()
            assert clock.waiting.empty() and len(factory.sessions) == 1
            assert life.ha_acquisition_generation is None
            with pytest.raises(HobenTimeoutError):
                await life.request_v4_data()
            assert [packet[0] for packet in wire.writes] == [3, 13]
        finally:
            await life.close()
            assert_clean(factory)

    asyncio.run(scenario())


@pytest.mark.parametrize("code", [2, 4, 5])
def test_complete_auth_close_never_retries_or_schedules_read(code):
    async def scenario():
        clock, factory = Clock(), Factory()
        life = V4Lifecycle(
            user_guid="b" * 32,
            mode=V4SessionMode.PERSISTENT,
            recover_acquisition=True,
            ha_reconnect=True,
            ha_fast_reconnect=True,
            session_factory=factory,
            sleep=clock.sleep,
            clock=lambda: clock.now,
        )
        try:
            await life.connect()
            wire = factory.transports[0]
            await wire.rx_started.wait()
            wire.rx.set_result(bytes([5, code]))
            with pytest.raises(HobenClosedError):
                await life.wait_stopped()
            assert clock.waiting.empty() and len(factory.sessions) == 1
            assert life.ha_acquisition_generation is None
        finally:
            await life.close()
            assert_clean(factory)

    asyncio.run(scenario())


def owner(factory, clock, **options):
    return V4Lifecycle(
        **(
            dict(
                user_guid="b" * 32,
                mode=V4SessionMode.PERSISTENT,
                recover_acquisition=True,
                ha_reconnect=True,
                ha_fast_reconnect=True,
                session_factory=factory,
                sleep=clock.sleep,
                clock=lambda: clock.now,
            )
            | options
        )
    )


@pytest.mark.parametrize("phase", ["backoff", "accepted"])
def test_stop_cancels_the_only_wait_and_prevents_late_read_or_open(phase):
    async def scenario():
        clock, factory = Clock(), Factory()
        life = owner(factory, clock)
        await life.connect()
        wire = factory.transports[0]
        await wire.rx_started.wait()
        wire.rx.set_exception(TransportEOF())
        assert await clock.waiting.get() == 10
        if phase == "accepted":
            await clock.advance(10)
            assert await clock.waiting.get() == 10
        count = len(factory.sessions)
        await life.close()
        await clock.advance(1000)
        assert len(factory.sessions) == count
        assert life.ha_acquisition_generation is None
        assert all(len(w.writes) == 1 for w in factory.transports)
        assert_clean(factory)
        assert not any(
            not t.done() and t is not asyncio.current_task()
            for t in asyncio.all_tasks()
        )

    asyncio.run(scenario())


def test_loss_during_post_open_gate_restarts_cleanup_not_acquisition():
    async def scenario():
        clock, factory = Clock(), Factory()
        life = owner(factory, clock)
        try:
            await life.connect()
            for generation in range(3):
                wire = factory.transports[generation]
                await wire.rx_started.wait()
                wire.rx.set_exception(TransportEOF())
                assert await clock.waiting.get() == 10
                assert factory.sessions[generation].cleanup_succeeded
                assert life.ha_acquisition_generation is None
                await clock.advance(10)
                assert await clock.waiting.get() == 10
                assert all(len(w.writes) == 1 for w in factory.transports)
                # Each next loss occurs before this post-open gate elapses.
            await clock.advance(10)
            await life.wait_connected()
            assert life.ha_acquisition_generation == 4
            assert len(factory.sessions) == 4 and life.snapshot.attempts == 4
        finally:
            await life.close()
            assert_clean(factory)

    asyncio.run(scenario())


@pytest.mark.parametrize("bad", [None, 0, 1, "true"])
def test_bad_fast_policy_is_rejected_before_a_factory_or_transport(bad):
    from custom_components.hoben.client import HobenClient
    from custom_components.hoben.exceptions import HobenInvalidInputError

    with pytest.raises(HobenInvalidInputError):
        V4Lifecycle(user_guid="b" * 32, ha_fast_reconnect=bad)
    with pytest.raises(HobenInvalidInputError):
        HobenClient("b" * 32, ha_fast_reconnect=bad)
    with pytest.raises(HobenInvalidInputError):
        V4Lifecycle(user_guid="b" * 32, ha_fast_reconnect=True)
    with pytest.raises(HobenInvalidInputError):
        HobenClient("b" * 32, ha_fast_reconnect=True)


def test_unproven_or_failed_close_never_allows_fast_tls():
    async def scenario():
        clock, factory = Clock(), Factory()
        life = owner(factory, clock)
        try:
            await life.connect()
            wire = factory.transports[0]

            async def fail_close():
                raise TransportError("PRIVATE_PAYLOAD")

            wire.close = fail_close
            await wire.rx_started.wait()
            wire.rx.set_exception(TransportEOF())
            with pytest.raises(Exception) as caught:
                await life.wait_stopped()
            assert caught.value.code == "cleanup_failed"
            assert not factory.sessions[0].cleanup_succeeded
            assert clock.waiting.empty() and len(factory.sessions) == 1
            assert life.ha_acquisition_generation is None
        finally:
            await life.close()

    asyncio.run(scenario())


def test_early_sleep_cannot_authorize_post_open_tx():
    async def scenario():
        clock, factory = Clock(), Factory()
        life = owner(factory, clock)
        try:
            await life.connect()
            wire = factory.transports[0]
            await wire.rx_started.wait()
            wire.rx.set_exception(TransportEOF())
            assert await clock.waiting.get() == 10
            await clock.advance(10)
            assert await clock.waiting.get() == 10
            clock.timer[1].set_result(None)  # Broken injected timer, clock unchanged.
            with pytest.raises(Exception) as caught:
                await life.wait_stopped()
            assert caught.value.code == "internal_failure"
            assert life.ha_acquisition_generation is None
            assert all(len(w.writes) == 1 for w in factory.transports)
        finally:
            await life.close()
            assert_clean(factory)

    asyncio.run(scenario())


def test_failed_new_openings_revert_to_60_without_replenishing_owner():
    async def scenario():
        clock = Clock()
        factory = Factory(failures=[None, TransportTlsError(), TransportTlsError()])
        life = owner(factory, clock)
        try:
            await life.connect()
            wire = factory.transports[0]
            await wire.rx_started.wait()
            wire.rx.set_exception(TransportEOF())
            assert await clock.waiting.get() == 10
            for delay in (10, 60, 60):
                await clock.advance(delay)
                if len(factory.sessions) < 4:
                    assert await clock.waiting.get() == 60
                    assert factory.sessions[-1].cleanup_succeeded
            await life.wait_connected()
            assert len(factory.sessions) == 4 and life.snapshot.attempts == 4
            assert life.ha_acquisition_generation is None
            assert all(len(w.writes) <= 1 for w in factory.transports)
        finally:
            await life.close()
            assert_clean(factory)

    asyncio.run(scenario())


@pytest.mark.parametrize("elapsed", [3, 9.999])
def test_returning_loss_observer_aborts_gate_without_waiting_or_acquisition(
    monkeypatch, elapsed
):
    """A violated wait_lost contract must fail closed, not wait out the gate."""

    async def scenario():
        clock, factory = Clock(), Factory()
        real_wait_lost = V4Session.wait_lost

        async def contradictory_observer(session):
            try:
                await real_wait_lost(session)
            except HobenError:
                if len(factory.sessions) > 1 and session is factory.sessions[1]:
                    return  # Synthetic contract violation: loss without its error.
                raise

        monkeypatch.setattr(V4Session, "wait_lost", contradictory_observer)
        life = owner(factory, clock)
        try:
            await life.connect()
            first = factory.transports[0]
            await first.rx_started.wait()
            first.rx.set_exception(TransportEOF())
            assert await clock.waiting.get() == 10
            await clock.advance(10)
            assert await clock.waiting.get() == 10
            post_open_timer = clock.timer[1]
            await clock.advance(elapsed)
            factory.transports[1].rx.set_exception(TransportEOF())
            for _ in range(40):
                await asyncio.sleep(0)
            assert life._task.done(), "loss completion must not await the sleeper"
            assert post_open_timer.cancelled()
            with pytest.raises(HobenInternalError):
                await life.wait_stopped()
            assert life.session_observation.cleaned_generation == 2
            assert life.ha_acquisition_generation is None
            assert len(factory.sessions) == 2 and clock.waiting.empty()
            assert all(len(w.writes) == 1 for w in factory.transports)
        finally:
            await life.close()
            assert_clean(factory)

    asyncio.run(scenario())
