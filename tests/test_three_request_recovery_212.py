"""#212: three actual transmissions, one TLS generation and one supervisor."""

import asyncio

import pytest

from custom_components.hoben.exceptions import HobenError, HobenTimeoutError
from custom_components.hoben.transport import TransportEOF, TransportTlsError
from tests.test_data_updated_silence import Clock, pump
from tests.test_session_300_runtime import response
from tests.test_session_ignored_rx import ignored_frame
from tests.test_v4_lifecycle import Backoff
from tests.test_v4_persistent import Factory


def requests(wire):
    return [packet for packet in wire.writes if packet[0] == 13]


async def first_timeout(clock, life):
    task = asyncio.create_task(life.request_v4_data(timeout=10))
    await pump()
    await clock.advance(10)
    with pytest.raises(HobenTimeoutError):
        await task


def assert_no_retry_owners():
    assert not any(
        task.get_name() in {"hoben-ha-loss", "hoben-ha-read-retry"} and not task.done()
        for task in asyncio.all_tasks()
    )


@pytest.mark.parametrize("late_reply", [False, True])
def test_three_timeouts_then_cleanup_before_new_tls(monkeypatch, late_reply):
    async def run():
        clock, backoff = Clock(monkeypatch), Backoff()
        factory = Factory(
            lambda wire, index: setattr(
                wire, "chunks", [] if not index else [response()]
            )
        )
        life = factory.lifecycle(
            ha_reconnect=True, recover_acquisition=True, sleep=backoff
        )
        await life.connect()
        old, session = factory.streams[0], factory.sessions[0]
        reader = session._rx_task
        try:
            await first_timeout(clock, life)
            assert len(requests(old)) == 1 and not old.close_count
            for attempt in (2, 3):
                await clock.advance(59.999)
                assert len(requests(old)) == attempt - 1
                await clock.advance(0.001)
                assert len(requests(old)) == attempt
                assert session._rx_task is reader and not reader.done()
                assert not old.close_count and len(factory.streams) == 1
                for _ in range(4):
                    # HA polls and cancelled observers cannot own another TX
                    # or reset the lifecycle's retry deadline/count.
                    with pytest.raises(HobenTimeoutError):
                        await life.request_v4_data(timeout=10)
                observer = asyncio.create_task(life.wait_acquisition_ready())
                await pump()
                observer.cancel()
                await asyncio.gather(observer, return_exceptions=True)
                assert len(requests(old)) == attempt
                if late_reply:
                    # Valid FFFF bytes during a retry are still ambiguous.
                    old.queue.put_nowait(response()[:7])
                    await pump()
                    old.queue.put_nowait(response()[7:] + response())
                old.queue.put_nowait(b"\x0c")
                old.queue.put_nowait(ignored_frame(27, 2))
                old.queue.put_nowait(b"\x0a")
                await pump()
                assert old.writes[-1] == b"\x0b"
                assert session.verified_read_sequence == 0
                assert life.witness.verified_read_generation is None
                await clock.advance(9.999)
                assert not old.close_count
                await clock.advance(0.001)
            assert await backoff.entered.get() == 60
            assert old.close_count == 1 and session.cleanup_succeeded
            assert reader.done() and len(requests(old)) == 3
            assert len(factory.streams) == 1
            backoff.release.put_nowait(None)
            await life.wait_connected()
            assert len(factory.streams) == 2
            await life.request_v4_data()
            assert life.witness.verified_read_generation == 2
            assert factory.sessions[1]._failed_reads == 0
            await clock.advance(120)
            assert len(requests(factory.streams[1])) == 1
        finally:
            await life.close()
            factory.assert_clean()
            assert_no_retry_owners()

    asyncio.run(run())


@pytest.mark.parametrize("phase", ["wait2", "read2", "wait3", "read3"])
@pytest.mark.parametrize("end", ["stop", "eof", "tls", "close", "auth", "malformed"])
def test_terminal_events_cancel_old_generation_timers(monkeypatch, phase, end):
    async def run():
        clock, factory, backoff = Clock(monkeypatch), Factory(), Backoff()
        life = factory.lifecycle(
            ha_reconnect=True, recover_acquisition=True, sleep=backoff
        )
        await life.connect()
        wire, session = factory.streams[0], factory.sessions[0]
        wire.chunks = []
        try:
            await first_timeout(clock, life)
            if phase != "wait2":
                await clock.advance(60)
            if phase in {"wait3", "read3"}:
                await clock.advance(10)
            if phase == "read3":
                await clock.advance(60)
            emitted = len(requests(wire))
            if end == "stop":
                await life.close()
            else:
                wire.queue.put_nowait(
                    {
                        "eof": TransportEOF(),
                        "tls": TransportTlsError(),
                        "close": b"\x05\x03",
                        "auth": b"\x05\x02",
                        "malformed": b"\x0e\xff\xff\x00\x00\xff\xff",
                    }[end]
                )
                await pump()
            await clock.advance(500)
            assert len(requests(wire)) == emitted
            assert wire.close_count == 1 and session.cleanup_succeeded
            assert len(factory.streams) == 1
        finally:
            await life.close()
            factory.assert_clean()
            assert_no_retry_owners()

    asyncio.run(run())


def test_failed_cleanup_after_third_timeout_forbids_new_generation(monkeypatch):
    async def run():
        clock, factory, backoff = Clock(monkeypatch), Factory(), Backoff()
        life = factory.lifecycle(
            ha_reconnect=True, recover_acquisition=True, sleep=backoff
        )
        await life.connect()
        wire = factory.streams[0]
        wire.chunks = []

        async def fail_close():
            wire.close_count += 1
            raise TransportTlsError()

        wire.close = fail_close
        try:
            await first_timeout(clock, life)
            for _ in range(2):
                await clock.advance(60)
                await clock.advance(10)
            with pytest.raises(HobenError):
                await life.wait_stopped()
            assert not factory.sessions[0].cleanup_succeeded
            assert len(factory.streams) == 1 and not backoff.delays
            assert len(requests(wire)) == 3
        finally:
            await life.close()
            assert_no_retry_owners()

    asyncio.run(run())


def test_success_before_timeout_cancels_no_session_and_creates_no_retry(monkeypatch):
    async def run():
        clock, factory = Clock(monkeypatch), Factory()
        life = factory.lifecycle(ha_reconnect=True, recover_acquisition=True)
        await life.connect()
        try:
            await life.request_v4_data()
            await clock.advance(500)
            assert life.witness.verified_read_sequence == 1
            assert factory.sessions[0]._failed_reads == 0
            assert len(requests(factory.streams[0])) == 1
            assert not factory.streams[0].close_count
        finally:
            await life.close()
            factory.assert_clean()
            assert_no_retry_owners()

    asyncio.run(run())


def test_tx_queue_expiry_does_not_count_a_request_or_spin(monkeypatch):
    async def run():
        clock, factory, backoff = Clock(monkeypatch), Factory(), Backoff()
        life = factory.lifecycle(
            ha_reconnect=True, recover_acquisition=True, sleep=backoff
        )
        await life.connect()
        wire, session = factory.streams[0], factory.sessions[0]
        wire.chunks = []
        try:
            await first_timeout(clock, life)
            await session._tx_lock.acquire()
            await clock.advance(60)
            await clock.advance(10)
            assert len(requests(wire)) == session._failed_reads == 1
            assert not wire.close_count
            session._tx_lock.release()
            await clock.advance(59.999)
            assert len(requests(wire)) == 1
            await clock.advance(0.001)
            assert len(requests(wire)) == 2
            await clock.advance(10)
            await clock.advance(60)
            assert len(requests(wire)) == 3
            await clock.advance(10)
            assert await backoff.entered.get() == 60
            assert session.cleanup_succeeded and len(requests(wire)) == 3
        finally:
            if session._tx_lock.locked():
                session._tx_lock.release()
            await life.close()
            factory.assert_clean()
            assert_no_retry_owners()

    asyncio.run(run())


def test_write_failure_on_retry_is_a_real_loss_not_a_response_timeout(monkeypatch):
    async def run():
        clock, factory, backoff = Clock(monkeypatch), Factory(), Backoff()
        life = factory.lifecycle(
            ha_reconnect=True, recover_acquisition=True, sleep=backoff
        )
        await life.connect()
        wire, session = factory.streams[0], factory.sessions[0]
        wire.chunks = []
        try:
            await first_timeout(clock, life)

            async def fail_write(packet):
                raise TransportTlsError()

            wire.write = fail_write
            await clock.advance(60)
            assert await backoff.entered.get() == 60
            assert session.cleanup_succeeded and wire.close_count == 1
            assert session._failed_reads == 1
            assert len(factory.streams) == 1
        finally:
            await life.close()
            factory.assert_clean()
            assert_no_retry_owners()

    asyncio.run(run())
