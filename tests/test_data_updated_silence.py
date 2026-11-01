"""Deterministic monotonic-clock tests for the owner's silent-RX hypothesis."""

import asyncio
import logging

import pytest

from custom_components.hoben.exceptions import HobenDataUpdatedRecoveryError
from custom_components.hoben.transport import (
    TransportCertificateError,
    TransportEOF,
    TransportTimeout,
    TransportTlsError,
)
from custom_components.hoben.v4_session import SessionState
from tests.test_session_300_runtime import response
from tests.test_v4_persistent import Factory

BAD = b"\x1bPRIV\xff\xff\x00\x00\xff\xffPRIVATE_PAYLOAD"


async def pump():
    for _ in range(40):
        await asyncio.sleep(0)


class Clock:
    def __init__(self, monkeypatch):
        loop = asyncio.get_running_loop()
        self.start, self.now = loop.time(), 0.0
        monkeypatch.setattr(loop, "time", lambda: self.start + self.now)

    async def advance(self, seconds):
        self.now += seconds
        await pump()


def make_owner(factory):
    return factory.lifecycle(
        retry_delays=(), recover_acquisition=True, ha_reconnect=True
    )


def test_every_rx_rearms_silence_then_one_probe_uses_the_original_transport(
    monkeypatch,
):
    async def scenario():
        clock, factory = Clock(monkeypatch), Factory()
        life = make_owner(factory)
        try:
            await life.connect()
            stream = factory.streams[0]
            stream.queue.put_nowait(BAD)
            await pump()
            assert life.data_updated_recovering
            await clock.advance(29)
            assert [w[0] for w in stream.writes] == [3]
            stream.queue.put_nowait(b"\xff" * 4096)
            await pump()
            await clock.advance(29)
            assert [w[0] for w in stream.writes] == [3]
            await clock.advance(1)
            assert [w[0] for w in stream.writes] == [3, 13]
            assert not life.data_updated_recovering
            assert factory.sessions[0].verified_read_sequence == 1
            assert len(factory.streams) == 1 and stream.close_count == 0
            assert (await life.request_v4_data()).registers == (17,) * 20
            assert [w[0] for w in stream.writes] == [3, 13]
            assert life.witness.verified_read_sequence == 1
            await life.request_v4_data()
            assert [w[0] for w in stream.writes] == [3, 13, 13]
            assert life.witness.verified_read_sequence == 2
        finally:
            await life.close()
            factory.assert_clean()
        assert not any(
            t.get_name() == "hoben-dataupdated-probe" for t in asyncio.all_tasks()
        )

    asyncio.run(scenario())


def test_continuous_rx_is_discarded_without_accumulation_or_new_reads(monkeypatch):
    async def scenario():
        clock, factory = Clock(monkeypatch), Factory()
        life = make_owner(factory)
        try:
            await life.connect()
            stream = factory.streams[0]
            stream.queue.put_nowait(BAD)
            await pump()
            for _ in range(12):
                await clock.advance(29)
                stream.queue.put_nowait(b"\x0e" * 4096)
                await pump()
                session = factory.sessions[0]
                assert not session._framer.partial and not session._framer._buffer
                assert session._data_updated.task is None
            assert [w[0] for w in stream.writes] == [3] and stream.close_count == 0
        finally:
            await life.close()
            factory.assert_clean()

    asyncio.run(scenario())


def test_old_waiter_is_invalidated_and_only_fresh_probe_can_complete_observer(
    monkeypatch,
):
    async def scenario():
        clock, factory = Clock(monkeypatch), Factory()
        life = make_owner(factory)
        try:
            await life.connect()
            stream = factory.streams[0]
            stream.chunks = [BAD + response()]
            old = asyncio.create_task(life.request_v4_data(timeout=120))
            await pump()
            observer = asyncio.create_task(life.request_v4_data(timeout=120))
            await pump()
            assert not old.done() and not observer.done()
            stream.chunks = [response()]
            await clock.advance(30)
            with pytest.raises(HobenDataUpdatedRecoveryError):
                await old
            assert (await observer).registers == (17,) * 20
            assert life.witness.verified_read_sequence == 1
            assert [w[0] for w in stream.writes] == [3, 13, 13]
            assert len(factory.streams) == 1 and stream.close_count == 0
        finally:
            await life.close()
            factory.assert_clean()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "reply",
    [
        b"\xffPRIVATE_PAYLOAD",
        response()[:17],
        None,
        BAD,
        response().replace(b"\xff\xff", b"\xff\xfe", 1),
        bytes.fromhex("0effff00000003018402"),
        response().replace(b"\x00\x00\x00\x2b", b"\x00\x01\x00\x2b", 1),
    ],
)
def test_failed_probe_returns_to_bounded_recovery_without_reconnect(
    monkeypatch, caplog, reply
):
    async def scenario():
        clock, factory = Clock(monkeypatch), Factory()
        life = make_owner(factory)
        try:
            await life.connect()
            stream = factory.streams[0]
            stream.chunks = [] if reply is None else [reply]
            stream.queue.put_nowait(BAD)
            await pump()
            await clock.advance(30)
            assert [w[0] for w in stream.writes] == [3, 13]
            await clock.advance(29)
            assert [w[0] for w in stream.writes] == [3, 13]
            stream.chunks = [response()]
            await clock.advance(1)
            await pump()
            assert [w[0] for w in stream.writes] == [3, 13, 13]
            assert not life.data_updated_recovering
            assert factory.sessions[0].verified_read_sequence == 1
            assert len(factory.streams) == 1 and stream.close_count == 0
            # B3 adds separate per-frame diagnostics; the recovery transition
            # itself must still warn only once for this episode.
            assert (
                len(
                    [
                        r
                        for r in caplog.records
                        if r.levelno == logging.WARNING
                        and r.name == "custom_components.hoben.v4_session"
                    ]
                )
                == 1
            )
            assert "PRIVATE" not in caplog.text
        finally:
            await life.close()
            factory.assert_clean()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "failure",
    [
        TransportEOF("synthetic transport loss"),
        TransportTimeout("read"),
        TransportCertificateError("synthetic certificate failure"),
        TransportTlsError("synthetic TLS failure"),
        TimeoutError("synthetic unexpected I/O expiry"),
    ],
)
def test_real_transport_failure_during_recovery_still_stops_the_old_generation(
    monkeypatch, failure
):
    async def scenario():
        Clock(monkeypatch)
        factory = Factory()
        life = make_owner(factory)
        try:
            await life.connect()
            stream = factory.streams[0]
            stream.queue.put_nowait(BAD)
            await pump()
            stream.queue.put_nowait(failure)
            await pump()
            assert factory.sessions[0].state is SessionState.CLOSED
            assert stream.close_count == 1
        finally:
            await life.close()
            factory.assert_clean()

    asyncio.run(scenario())


def test_a_coalesced_second_response_cannot_turn_a_rejected_probe_into_success(
    monkeypatch,
):
    async def scenario():
        clock, factory = Clock(monkeypatch), Factory()
        life = make_owner(factory)
        try:
            await life.connect()
            stream = factory.streams[0]
            stream.chunks = [response() * 2]
            stream.queue.put_nowait(BAD)
            await pump()
            await clock.advance(30)
            assert life.data_updated_recovering
            assert not factory.sessions[0]._data_updated.result.done()
            assert life.witness.verified_read_generation is None
            stream.chunks = [response()]
            observer = asyncio.create_task(life.request_v4_data(timeout=60))
            await pump()
            await clock.advance(30)
            assert (await observer).registers == (17,) * 20
            assert not life.data_updated_recovering and stream.close_count == 0
        finally:
            await life.close()
            factory.assert_clean()

    asyncio.run(scenario())


@pytest.mark.parametrize("probe_started", [False, True])
def test_close_cancels_recovery_and_prevents_stale_timer_transmission(
    monkeypatch, probe_started
):
    async def scenario():
        clock, factory = Clock(monkeypatch), Factory()
        life = make_owner(factory)
        await life.connect()
        stream = factory.streams[0]
        stream.chunks = []
        stream.queue.put_nowait(BAD)
        await pump()
        if probe_started:
            await clock.advance(30)
        await life.close()
        before = list(stream.writes)
        await clock.advance(300)
        assert stream.writes == before
        factory.assert_clean()
        assert not any(
            t.get_name() == "hoben-dataupdated-probe" for t in asyncio.all_tasks()
        )

    asyncio.run(scenario())


def test_deferred_acquisition_has_a_finite_deadline_and_cancellation_closes_cleanly(
    monkeypatch,
):
    async def scenario():
        clock, factory = Clock(monkeypatch), Factory()
        life = make_owner(factory)
        try:
            await life.connect()
            stream = factory.streams[0]
            stream.queue.put_nowait(BAD)
            await pump()
            deferred = asyncio.create_task(life.request_v4_data(timeout=10))
            await pump()
            await clock.advance(10)
            with pytest.raises(HobenDataUpdatedRecoveryError):
                await deferred
            assert stream.close_count == 0 and [w[0] for w in stream.writes] == [3]
            cancelled = asyncio.create_task(life.request_v4_data(timeout=60))
            await pump()
            cancelled.cancel()
            with pytest.raises(asyncio.CancelledError):
                await cancelled
            assert stream.close_count == 1
        finally:
            await life.close()
            factory.assert_clean()

    asyncio.run(scenario())
