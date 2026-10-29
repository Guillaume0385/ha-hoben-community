"""Separate HA policy, real shared sessions, virtual monotonic clock and no I/O."""

import asyncio

import pytest

from custom_components.hoben.exceptions import HobenInvalidInputError
from custom_components.hoben.transport import TransportTlsError
from custom_components.hoben.v4_lifecycle import V4Lifecycle
from custom_components.hoben.v4_session import V4SessionMode
from tests.test_v4_lifecycle import Factory, assert_clean


class Clock:
    """Timers fire only after the full requested virtual interval."""

    def __init__(self):
        self.now = 0.0
        self.waiting = asyncio.Queue()
        self.timer = None

    async def sleep(self, delay):
        timer = asyncio.get_running_loop().create_future()
        self.timer = (self.now + delay, timer)
        self.waiting.put_nowait(delay)
        await timer

    async def advance(self, seconds):
        self.now += seconds
        deadline, timer = self.timer
        if self.now >= deadline and not timer.done():
            timer.set_result(None)
        for _ in range(10):
            await asyncio.sleep(0)


def test_more_than_two_opening_failures_use_every_full_60s_and_log_each(caplog):
    async def scenario():
        clock = Clock()
        started = []
        factory = Factory(
            failures=[TransportTlsError("PRIVATE") for _ in range(4)],
            setup=lambda transport: started.append(clock.now),
        )
        lifecycle = V4Lifecycle(
            user_guid="b" * 32,
            mode=V4SessionMode.PERSISTENT,
            recover_acquisition=True,
            ha_reconnect=True,
            session_factory=factory,
            sleep=clock.sleep,
            clock=lambda: clock.now,
        )
        connect = asyncio.create_task(lifecycle.connect())
        for attempt in range(1, 5):
            assert await clock.waiting.get() == 60.0
            assert len(factory.sessions) == attempt
            assert factory.sessions[-1].cleanup_succeeded
            await clock.advance(59.999)
            assert len(factory.sessions) == attempt and not connect.done()
            await clock.advance(0.0011)
        await connect
        assert started == pytest.approx([0, 60.0001, 120.0002, 180.0003, 240.0004])
        assert lifecycle.snapshot.attempts == 5
        assert lifecycle.snapshot.max_attempts is None
        records = [
            r.getMessage() for r in caplog.records if r.name.endswith("v4_lifecycle")
        ]
        for attempt in range(1, 6):
            assert (
                sum(
                    f"attempt={attempt} " in r and "result=started" in r
                    for r in records
                )
                == 1
            )
            result = "connected" if attempt == 5 else "failed"
            assert (
                sum(
                    f"attempt={attempt} " in r and f"result={result}" in r
                    for r in records
                )
                == 1
            )
        assert not any("PRIVATE" in r or "b" * 32 in r for r in records)
        await lifecycle.close()
        assert_clean(factory)

    with caplog.at_level("INFO", logger="custom_components.hoben.v4_lifecycle"):
        asyncio.run(scenario())


def test_stop_during_59th_second_prevents_any_late_opening():
    async def scenario():
        clock, factory = Clock(), Factory(failures=[TransportTlsError("PRIVATE")])
        lifecycle = V4Lifecycle(
            user_guid="b" * 32,
            mode=V4SessionMode.PERSISTENT,
            recover_acquisition=True,
            ha_reconnect=True,
            session_factory=factory,
            sleep=clock.sleep,
        )
        connect = asyncio.create_task(lifecycle.connect())
        assert await clock.waiting.get() == 60
        await clock.advance(59)
        connect.cancel()
        with pytest.raises(asyncio.CancelledError):
            await connect
        await clock.advance(600)
        assert len(factory.sessions) == 1
        assert_clean(factory)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "kwargs",
    [
        {"ha_reconnect": 1},
        {"ha_reconnect": "PRIVATE"},
        {"ha_reconnect": True},
        {"ha_reconnect": True, "recover_acquisition": True},
    ],
)
def test_policy_cannot_be_enabled_for_campaign_or_without_explicit_opt_in(kwargs):
    with pytest.raises(HobenInvalidInputError):
        V4Lifecycle(user_guid="b" * 32, **kwargs)


def test_rx_loss_before_owner_publication_cannot_return_a_stale_connection(monkeypatch):
    from custom_components.hoben.transport import TransportEOF
    from custom_components.hoben.v4_session import SessionState, V4Session

    async def scenario():
        clock, factory, owner_gate = Clock(), Factory(), asyncio.Event()
        original = V4Session.wait_lost

        async def delayed_owner(session):
            if session is factory.sessions[0]:
                await owner_gate.wait()
            return await original(session)

        monkeypatch.setattr(V4Session, "wait_lost", delayed_owner)
        lifecycle = V4Lifecycle(
            user_guid="b" * 32,
            mode=V4SessionMode.PERSISTENT,
            recover_acquisition=True,
            ha_reconnect=True,
            session_factory=factory,
            sleep=clock.sleep,
        )
        await lifecycle.connect()
        first = factory.sessions[0]
        factory.transports[0].rx.set_exception(TransportEOF("PRIVATE"))
        while first.state is SessionState.CONNECTED:
            await asyncio.sleep(0)
        assert lifecycle.state is SessionState.CONNECTED  # Owner has not resumed.
        observer = asyncio.create_task(lifecycle.wait_connected())
        await asyncio.sleep(0)
        assert not observer.done()
        owner_gate.set()
        assert await clock.waiting.get() == 60
        await clock.advance(59.999)
        assert not observer.done() and len(factory.sessions) == 1
        await clock.advance(0.0011)
        await observer
        assert lifecycle.witness.established_generation == 2
        await lifecycle.close()
        assert_clean(factory)

    asyncio.run(scenario())
