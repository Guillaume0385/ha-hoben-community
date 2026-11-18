"""#219-005: discard one admitted delivery, without inventing a V4 mapping."""

import asyncio
import logging

import pytest

from custom_components.hoben import v4_session
from custom_components.hoben.exceptions import HobenTimeoutError
from custom_components.hoben.transport import TransportEOF
from custom_components.hoben.v4_session import SessionState
from tests.test_data_updated_delivery_219 import reports
from tests.test_data_updated_ignore import notification
from tests.test_data_updated_parser_219 import candidate
from tests.test_data_updated_silence import Clock, make_owner, pump
from tests.test_session_300_runtime import response
from tests.test_v4_lifecycle import Backoff
from tests.test_v4_persistent import Factory

INVALID = [
    *[notification()[:split] for split in (1, 5, 10, 14, 53)],
    candidate()[:7] + b"\xff\xff" + candidate()[9:],
    candidate()[:9] + b"\xff\xff" + candidate()[11:],
    candidate(b"\x04\x00"),
    candidate(b"\x04\x03\x00\x01\x02"),
    candidate(b"\x04\x04\x00\x01"),
    candidate(b"\x06\x12\x34\xbe\xef"),
    notification() + b"\x0a" + response(),
    notification() + notification(),
]


@pytest.mark.parametrize("delivery", INVALID)
def test_invalid_candidate_never_enters_silence_guard_or_creates_a_probe(
    monkeypatch, caplog, delivery
):
    caplog.set_level(logging.DEBUG, logger="custom_components.hoben.frame_diagnostic")

    async def run():
        clock, factory = Clock(monkeypatch), Factory()
        life = make_owner(factory)
        try:
            await life.connect()
            await life.request_v4_data()
            session, stream = factory.sessions[0], factory.streams[0]
            rx = session._rx_task
            stream.queue.put_nowait(delivery)
            await pump()
            assert not life.data_updated_recovering
            assert session._data_updated.task is None and not session._framer.partial
            assert session._failed_reads == 0 and not session.acquisition_uncertain
            assert session.verified_read_sequence == 1
            await clock.advance(301)
            assert [w[0] for w in stream.writes] == [3, 13]
            stream.queue.put_nowait(b"\x0a")
            stream.queue.put_nowait(notification())
            await pump()
            assert [w[0] for w in stream.writes] == [3, 13, 11]
            assert session._rx_task is rx and not rx.done()
            assert session.state is SessionState.CONNECTED and stream.close_count == 0
            assert session.verified_read_sequence == 1  # No claimed mapping.
            assert len(reports(caplog)) == 2
            assert reports(caplog)[-1]["status"] == "parsed"
            assert len(factory.streams) == 1
            assert not any(
                t.get_name() == "hoben-dataupdated-probe" and not t.done()
                for t in asyncio.all_tasks()
            )
        finally:
            await life.close()
            factory.assert_clean()

    asyncio.run(run())


@pytest.mark.parametrize("fault", ["raises", "wrong_result"])
def test_parser_failure_is_closed_diagnostic_without_private_exception_or_recovery(
    monkeypatch, caplog, fault
):
    caplog.set_level(logging.DEBUG, logger="custom_components.hoben.frame_diagnostic")

    def broken(data):
        if fault == "raises":
            raise RuntimeError("SYNTHETIC_PRIVATE_PARSER_PAYLOAD")
        return object()

    async def run():
        factory, original = Factory(), v4_session.parse_data_updated
        life = make_owner(factory)
        try:
            await life.connect()
            session, stream = factory.sessions[0], factory.streams[0]
            monkeypatch.setattr(v4_session, "parse_data_updated", broken)
            stream.queue.put_nowait(notification())
            await pump()
            assert not life.data_updated_recovering and not session._rx_task.done()
            assert reports(caplog)[0]["reason"] == "parser_failure"
            assert reports(caplog)[0]["value_count"] is None
            assert "SYNTHETIC_PRIVATE_PARSER_PAYLOAD" not in caplog.text
            monkeypatch.setattr(v4_session, "parse_data_updated", original)
            stream.queue.put_nowait(notification())
            stream.queue.put_nowait(b"\x0a")
            await pump()
            assert [w[0] for w in stream.writes] == [3, 11]
            assert session.state is SessionState.CONNECTED and stream.close_count == 0
        finally:
            await life.close()
            factory.assert_clean()

    asyncio.run(run())


@pytest.mark.parametrize("delivery", [INVALID[0], INVALID[6], INVALID[-2]])
def test_drop_does_not_complete_or_abandon_an_inflight_v4_request(delivery):
    async def run():
        factory = Factory()
        life = make_owner(factory)
        try:
            await life.connect()
            session, stream = factory.sessions[0], factory.streams[0]
            stream.chunks = [delivery, notification(), b"\x0a", response()]
            result = await life.request_v4_data()
            assert result.registers == (17,) * 20
            assert session._failed_reads == 0 and not life.data_updated_recovering
            assert session.verified_read_sequence == 1
            assert [w[0] for w in stream.writes] == [3, 13, 11]
            assert stream.close_count == 0 and len(factory.streams) == 1
        finally:
            await life.close()
            factory.assert_clean()

    asyncio.run(run())


def test_real_eof_after_drops_still_requires_cleanup_before_next_generation():
    async def run():
        factory, backoff = Factory(), Backoff()
        life = factory.lifecycle(
            recover_acquisition=True, ha_reconnect=True, sleep=backoff
        )
        try:
            await life.connect()
            old, stream = factory.sessions[0], factory.streams[0]
            for _ in range(20):
                stream.queue.put_nowait(INVALID[6])
            await pump()
            assert not life.data_updated_recovering and stream.close_count == 0
            stream.queue.put_nowait(TransportEOF())
            await backoff.entered.get()
            assert old.cleanup_succeeded and stream.close_count == 1
            assert len(factory.streams) == 1
            stream.queue.put_nowait(notification())  # Never replay old delivery.
            backoff.release.put_nowait(None)
            await life.wait_connected()
            assert life.witness.established_generation == 2
            assert life.witness.verified_read_generation is None
            assert (await life.request_v4_data()).registers == (17,) * 20
            assert life.witness.verified_read_generation == 2
            assert stream.queue.qsize() == 1
        finally:
            await life.close()
            factory.assert_clean()

    asyncio.run(run())


def test_dropping_candidate_neither_resets_v4_deadline_nor_disables_212(monkeypatch):
    async def run():
        clock, factory = Clock(monkeypatch), Factory()
        life = make_owner(factory)
        pending = None
        try:
            await life.connect()
            session, stream = factory.sessions[0], factory.streams[0]
            stream.chunks = []
            pending = asyncio.create_task(life.request_v4_data(timeout=30))
            await pump()
            await clock.advance(29)
            stream.queue.put_nowait(INVALID[6])
            await pump()
            assert not pending.done() and session._failed_reads == 0
            assert not life.data_updated_recovering
            await clock.advance(1)
            with pytest.raises(HobenTimeoutError):
                await pending
            assert session._failed_reads == 1 and session.acquisition_uncertain
            assert stream.close_count == 0 and not session._rx_task.done()
            await clock.advance(59)
            assert [w[0] for w in stream.writes] == [3, 13]
            await clock.advance(1)
            assert [w[0] for w in stream.writes] == [3, 13, 13]
            assert not life.data_updated_recovering and stream.close_count == 0
        finally:
            if pending is not None:
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
            await life.close()
            factory.assert_clean()

    asyncio.run(run())
