"""D2 correlation fences, real owners, deterministic clocks and byte peers."""

import asyncio

import pytest

from custom_components.hoben.exceptions import HobenTimeoutError
from custom_components.hoben.v4_session import SessionState
from tests.test_data_updated_silence import Clock, pump
from tests.test_session_300_runtime import response
from tests.test_v4_lifecycle import Backoff
from tests.test_v4_persistent import Factory


def test_response_deadline_keeps_tls_rx_and_never_credits_late_reply(monkeypatch):
    async def run():
        clock, factory, backoff = Clock(monkeypatch), Factory(), Backoff()
        life = factory.lifecycle(
            ha_reconnect=True, recover_acquisition=True, retry_delays=(), sleep=backoff
        )
        await life.connect()
        session, wire = factory.sessions[0], factory.streams[0]
        await life.request_v4_data()
        wire.chunks = []
        rx, framer = session._rx_task, session._framer
        task = asyncio.create_task(life.request_v4_data(timeout=10))
        try:
            await pump()
            await clock.advance(10.001)
            with pytest.raises(HobenTimeoutError):
                await task
            assert not wire.close_count  # RED: the old request deadline closes TLS.
            assert session.state is SessionState.CONNECTED and session._rx_task is rx
            assert life.acquisition_uncertain and not backoff.delays
            wire.queue.put_nowait(response()[:7])
            await pump()
            assert framer.partial
            wire.queue.put_nowait(response()[7:] + b"\x0a")
            await pump()
            assert (
                session.verified_read_sequence
                == life.witness.verified_read_sequence
                == 1
            )
            for _ in range(3):
                with pytest.raises(HobenTimeoutError):
                    await life.request_v4_data()
                wire.queue.put_nowait(response())
            await pump()
            assert [p[0] for p in wire.writes] == [3, 13, 13, 11]
            assert not wire.close_count and len(factory.sessions) == 1
            assert not session.snapshot.boundary_proven
        finally:
            await life.close()
            await asyncio.gather(task, return_exceptions=True)
            factory.assert_clean()

    asyncio.run(run())


@pytest.mark.parametrize("idle", [False, True])
def test_injected_read_timeout_is_not_eof_and_idle_timeout_needs_no_fence(idle):
    from custom_components.hoben.transport import TransportTimeout

    async def run():
        factory, backoff = Factory(), Backoff()
        life = factory.lifecycle(
            ha_reconnect=True, recover_acquisition=True, sleep=backoff
        )
        await life.connect()
        wire, session = factory.streams[0], factory.sessions[0]
        try:
            if idle:
                wire.queue.put_nowait(TransportTimeout("read"))
                await pump()
                assert not life.acquisition_uncertain
                await life.request_v4_data()
                assert session.verified_read_sequence == 1
            else:
                wire.chunks = [TransportTimeout("read")]
                with pytest.raises(HobenTimeoutError):
                    await life.request_v4_data()
                assert (
                    life.acquisition_uncertain and session.verified_read_sequence == 0
                )
            wire.queue.put_nowait(b"\x0a")
            await pump()
            assert wire.writes[-1] == b"\x0b"
            assert not wire.close_count and not backoff.delays
        finally:
            await life.close()
            factory.assert_clean()

    asyncio.run(run())


@pytest.mark.parametrize(
    "fault", ["eof", "tls", "auth", "certificate", "mbap", "tid", "internal"]
)
def test_real_errors_after_a_deadline_still_close_and_cannot_publish(
    monkeypatch, fault
):
    from custom_components.hoben.exceptions import HobenError
    from custom_components.hoben.transport import (
        TransportCertificateError,
        TransportEOF,
        TransportTlsError,
    )

    async def run():
        clock, factory, backoff = Clock(monkeypatch), Factory(), Backoff()
        life = factory.lifecycle(
            ha_reconnect=True, recover_acquisition=True, sleep=backoff
        )
        await life.connect()
        wire, session = factory.streams[0], factory.sessions[0]
        wire.chunks = []
        task = asyncio.create_task(life.request_v4_data(timeout=10))
        try:
            await pump()
            await clock.advance(10.001)
            with pytest.raises(HobenTimeoutError):
                await task
            assert not wire.close_count
            wire.queue.put_nowait(
                {
                    "eof": TransportEOF(),
                    "tls": TransportTlsError(),
                    "auth": b"\x05\x02",
                    "certificate": TransportCertificateError(),
                    "mbap": b"\x0e\xff\xff\x00\x00\xff\xff",
                    "tid": response()[:1] + b"\x00\x01" + response()[3:],
                    "internal": RuntimeError("PRIVATE_LOCAL"),
                }[fault]
            )
            with pytest.raises(HobenError):
                await session.wait_rx_stopped()
            assert wire.close_count == 1 and session.verified_read_sequence == 0
            await pump()
            assert len(factory.sessions) == 1
        finally:
            await life.close()
            factory.assert_clean()

    asyncio.run(run())


def test_no_second_request_while_dataupdated_recovery_is_uncorrelated(monkeypatch):
    from tests.test_data_updated_silence import BAD

    async def run():
        clock, factory = Clock(monkeypatch), Factory()
        life = factory.lifecycle(ha_reconnect=True, recover_acquisition=True)
        await life.connect()
        wire, session = factory.streams[0], factory.sessions[0]
        wire.chunks = []
        task = asyncio.create_task(life.request_v4_data(timeout=10))
        try:
            await pump()
            wire.queue.put_nowait(BAD)
            await pump()
            await clock.advance(10.001)
            with pytest.raises(HobenTimeoutError):
                await task
            for _ in range(3):
                await clock.advance(31)
            assert life.acquisition_uncertain and life.data_updated_recovering
            assert [p[0] for p in wire.writes] == [3, 13]
            assert session._data_updated.task is None
            assert not wire.close_count and session.verified_read_sequence == 0
        finally:
            await life.close()
            factory.assert_clean()

    asyncio.run(run())


def test_tx_queue_deadline_has_no_outstanding_reply_and_write_timeout_stays_closed(
    monkeypatch,
):
    from custom_components.hoben.transport import TransportTimeout

    async def run():
        clock, factory = Clock(monkeypatch), Factory()
        life = factory.lifecycle(
            ha_reconnect=True, recover_acquisition=True, sleep=Backoff()
        )
        await life.connect()
        wire, session = factory.streams[0], factory.sessions[0]
        await session._tx_lock.acquire()
        task = asyncio.create_task(life.request_v4_data(timeout=10))
        try:
            await pump()
            await clock.advance(10.001)
            with pytest.raises(HobenTimeoutError):
                await task
            assert not life.acquisition_uncertain and not wire.close_count
            assert [p[0] for p in wire.writes] == [3]
            session._tx_lock.release()
            await life.request_v4_data()
            assert session.verified_read_sequence == 1
            old = wire.write

            async def fail(packet):
                if packet[0] == 13:
                    raise TransportTimeout("write")
                await old(packet)

            wire.write = fail
            with pytest.raises(HobenTimeoutError):
                await life.request_v4_data()
            assert wire.close_count == 1
        finally:
            if session._tx_lock.locked():
                session._tx_lock.release()
            await life.close()
            factory.assert_clean()

    asyncio.run(run())


def test_idle_timeout_after_a_consumed_reply_does_not_poison_the_next_read():
    from custom_components.hoben.transport import TransportTimeout

    async def run():
        factory = Factory()
        life = factory.lifecycle(ha_reconnect=True, recover_acquisition=True)
        await life.connect()
        wire, session = factory.streams[0], factory.sessions[0]
        wire.chunks = [response(), TransportTimeout("read")]
        try:
            # RX can see the next idle timeout before the request waiter resumes.
            for sequence in (1, 2):
                await life.request_v4_data()
                await pump()
                assert not life.acquisition_uncertain
                assert session.verified_read_sequence == sequence
            assert not wire.close_count and len(factory.sessions) == 1
        finally:
            await life.close()
            factory.assert_clean()

    asyncio.run(run())


@pytest.mark.parametrize("cleanup_ok", [True, False])
def test_real_loss_after_silence_requires_cleanup_before_any_new_tls(
    monkeypatch, cleanup_ok
):
    from custom_components.hoben.exceptions import HobenError
    from custom_components.hoben.transport import TransportEOF, TransportTimeout

    async def run():
        clock, factory, backoff = Clock(monkeypatch), Factory(), Backoff()
        life = factory.lifecycle(
            ha_reconnect=True, recover_acquisition=True, sleep=backoff
        )
        await life.connect()
        wire, session = factory.streams[0], factory.sessions[0]
        entered, release = asyncio.Event(), asyncio.Event()
        original_close = wire.close

        async def close():
            entered.set()
            await release.wait()
            await original_close()
            if not cleanup_ok:
                raise TransportTimeout("cleanup")

        wire.close = close
        wire.chunks = []
        task = asyncio.create_task(life.request_v4_data(timeout=10))
        try:
            await pump()
            await clock.advance(10.001)
            with pytest.raises(HobenTimeoutError):
                await task
            wire.queue.put_nowait(TransportEOF())
            await entered.wait()
            await clock.advance(300)
            assert len(factory.sessions) == 1 and not backoff.delays
            assert not session.cleanup_succeeded
            release.set()
            await pump()
            if cleanup_ok:
                assert await backoff.entered.get() == 60
                assert session.cleanup_succeeded and len(factory.sessions) == 1
                backoff.release.put_nowait(None)
                await life.wait_connected()
                await life.request_v4_data()
                assert len(factory.sessions) == 2
                assert not life.acquisition_uncertain
                assert life.witness.verified_read_generation == 2
            else:
                with pytest.raises(HobenError):
                    await life.wait_stopped()
                assert not session.cleanup_succeeded
                assert len(factory.sessions) == 1 and not backoff.delays
        finally:
            release.set()
            await life.close()
            factory.assert_clean()

    asyncio.run(run())
