"""#219-A: actual RX owners over synthetic read deliveries, never the network."""

import asyncio
import logging

import pytest

from custom_components.hoben.v4_session import SessionState
from tests.test_data_updated_ignore import notification
from tests.test_data_updated_silence import make_owner, pump
from tests.test_v4_persistent import Factory


def reports(caplog):
    return [
        r.hoben_data_updated for r in caplog.records if hasattr(r, "hoben_data_updated")
    ]


def test_each_whole_delivery_is_diagnosed_without_an_acquisition(caplog):
    caplog.set_level(logging.DEBUG)

    async def scenario():
        factory = Factory()
        life = make_owner(factory)
        try:
            await life.connect()
            session, stream = factory.sessions[0], factory.streams[0]
            for _ in range(3):
                stream.queue.put_nowait(notification())
                await pump()
            observed = reports(caplog)
            assert len(observed) == 3, (
                "every real read delivery needs its own safe event"
            )
            assert [r["index"] for r in observed] == [1, 2, 3]
            assert all(r["delivery_bytes"] == 54 for r in observed)
            assert all(r["status"] == "parsed" for r in observed)
            assert all(
                r["length_scope"] == "read_delivery" and r["boundary_proven"] is False
                for r in observed
            )
            assert session.verified_read_sequence == 0
            assert session.state is SessionState.CONNECTED and stream.close_count == 0
            assert [w[0] for w in stream.writes] == [3]
        finally:
            await life.close()
            factory.assert_clean()

    asyncio.run(scenario())


@pytest.mark.parametrize("split", [1, 5, 10, 14, 53])
def test_fragment_is_not_reassembled_or_left_in_the_mbap_framer(split, caplog):
    caplog.set_level(logging.DEBUG)

    async def scenario():
        factory = Factory()
        life = make_owner(factory)
        try:
            await life.connect()
            session, stream = factory.sessions[0], factory.streams[0]
            stream.queue.put_nowait(notification()[:split])
            await pump()
            assert not session._framer.partial, (
                "a notification cannot span read deliveries"
            )
            assert not life.data_updated_recovering
            (event,) = reports(caplog)
            assert event["delivery_bytes"] == split and event["status"] == "incomplete"
            stream.queue.put_nowait(notification()[split:])
            await pump()
            assert not session._framer.partial and session.verified_read_sequence == 0
            stream.queue.put_nowait(notification())
            await pump()
            assert reports(caplog)[-1]["status"] == "parsed"
            assert not life.data_updated_recovering
            assert [w[0] for w in stream.writes] == [3]
        finally:
            await life.close()
            factory.assert_clean()

    asyncio.run(scenario())


@pytest.mark.parametrize("tail", [b"\x0a", b"\x0e", notification()])
def test_adjacent_suffix_is_never_scanned_or_credited_to_pending_v4(tail, caplog):
    caplog.set_level(logging.DEBUG)

    async def scenario():
        factory = Factory()
        life = make_owner(factory)
        pending = None
        try:
            await life.connect()
            session, stream = factory.sessions[0], factory.streams[0]
            stream.chunks = [notification() + tail]
            pending = asyncio.create_task(life.request_v4_data())
            await pump()
            assert not pending.done()
            (event,) = reports(caplog)
            assert (
                event["status"] == "ambiguous" and event["reason"] == "delivery_suffix"
            )
            assert event["delivery_bytes"] == 54 + len(tail)
            assert (
                session.verified_read_sequence == 0 and not life.data_updated_recovering
            )
            assert not session._framer.partial and stream.close_count == 0
            assert [w[0] for w in stream.writes] == [3, 13]
        finally:
            if pending is not None:
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
            await life.close()
            factory.assert_clean()

    asyncio.run(scenario())


def test_payload_byte_1b_continuing_a_real_partial_0e_is_not_a_notification(caplog):
    from tests.test_session_300_runtime import response

    caplog.set_level(logging.DEBUG)

    async def scenario():
        factory = Factory()
        life = make_owner(factory)
        try:
            await life.connect()
            frame = response()[:10] + b"\x1b\x1b" * 20
            factory.streams[0].chunks = [frame[:10], frame[10:]]
            assert (await life.request_v4_data()).registers == (0x1B1B,) * 20
            assert reports(caplog) == [] and not life.data_updated_recovering
            assert life.witness.verified_read_sequence == 1
        finally:
            await life.close()
            factory.assert_clean()

    asyncio.run(scenario())


@pytest.mark.parametrize("prefix", ["ping", "response"])
def test_delimited_message_before_1b_survives_but_the_suffix_is_not_a_new_read(
    prefix, caplog
):
    from tests.test_session_300_runtime import response

    caplog.set_level(logging.DEBUG)

    async def scenario():
        factory = Factory()
        life = make_owner(factory)
        try:
            await life.connect()
            stream = factory.streams[0]
            if prefix == "response":
                stream.chunks = [response() + notification()]
                assert (await life.request_v4_data()).registers == (17,) * 20
                assert life.witness.verified_read_sequence == 1
            else:
                stream.queue.put_nowait(b"\x0a" + notification())
                await pump()
                assert stream.writes[-1] == b"\x0b"
            (event,) = reports(caplog)
            assert event["reason"] == "not_read_start"
            assert event["value_count"] is None and life.data_updated_recovering
            assert stream.close_count == 0 and len(factory.streams) == 1
        finally:
            await life.close()
            factory.assert_clean()

    asyncio.run(scenario())


def test_opening_residue_is_not_relabelled_as_a_complete_read_delivery(caplog):
    caplog.set_level(logging.DEBUG)

    async def scenario():
        factory = Factory(
            lambda stream, index: setattr(
                stream, "prefix", stream.prefix + notification()
            )
        )
        life = make_owner(factory)
        try:
            await life.connect()
            await pump()
            (event,) = reports(caplog)
            assert event["delivery_bytes"] is None
            assert event["reason"] == "not_read_start"
            assert life.data_updated_recovering
            assert [w[0] for w in factory.streams[0].writes] == [3]
        finally:
            await life.close()
            factory.assert_clean()

    asyncio.run(scenario())


def test_counter_saturates_but_every_delivery_still_emits_an_event(caplog):
    caplog.set_level(logging.DEBUG)

    async def scenario():
        factory = Factory()
        life = make_owner(factory)
        try:
            await life.connect()
            session, stream = factory.sessions[0], factory.streams[0]
            session._data_updated_deliveries = 65534
            for _ in range(3):
                stream.queue.put_nowait(notification())
            await pump()
            assert [r["index"] for r in reports(caplog)] == [65535] * 3
            assert all(r["counter_capped"] for r in reports(caplog))
            assert (
                session.verified_read_sequence == 0 and not life.data_updated_recovering
            )
        finally:
            await life.close()
            factory.assert_clean()

    asyncio.run(scenario())


def test_reconnect_keeps_generations_separate_and_never_replays_old_candidates(caplog):
    from custom_components.hoben.transport import TransportEOF
    from tests.test_v4_lifecycle import Backoff

    caplog.set_level(logging.DEBUG)

    async def scenario():
        factory, backoff = Factory(), Backoff()
        life = factory.lifecycle(
            recover_acquisition=True, ha_reconnect=True, sleep=backoff
        )
        try:
            await life.connect()
            old = factory.streams[0]
            old.queue.put_nowait(notification())
            await pump()
            old.queue.put_nowait(TransportEOF())
            await backoff.entered.get()
            old.queue.put_nowait(notification())
            backoff.release.put_nowait(None)
            await life.wait_connected()
            factory.streams[1].queue.put_nowait(notification())
            await pump()
            assert [(r["generation"], r["index"]) for r in reports(caplog)] == [
                (1, 1),
                (2, 1),
            ]
            assert old.queue.qsize() == 1 and old.close_count == 1
            assert life.witness.verified_read_generation is None
            assert (await life.request_v4_data()).registers == (17,) * 20
            assert life.witness.verified_read_generation == 2
        finally:
            await life.close()
            factory.assert_clean()

    asyncio.run(scenario())


def test_failed_logging_handler_cannot_change_rx_or_read_correlation(monkeypatch):
    from unittest.mock import Mock

    from custom_components.hoben import frame_diagnostic

    monkeypatch.setattr(
        frame_diagnostic._DATA_UPDATED_LOGGER,
        "debug",
        Mock(side_effect=RuntimeError("PRIVATE_PAYLOAD")),
    )

    async def scenario():
        factory = Factory()
        life = make_owner(factory)
        try:
            await life.connect()
            factory.streams[0].queue.put_nowait(notification())
            await pump()
            assert factory.sessions[0].state is SessionState.CONNECTED
            assert (await life.request_v4_data()).registers == (17,) * 20
            assert life.witness.verified_read_sequence == 1
        finally:
            await life.close()
            factory.assert_clean()

    asyncio.run(scenario())


def test_ineligible_notification_closes_the_read_gate_before_awaiting_prior_pong():
    async def scenario():
        factory = Factory()
        life = make_owner(factory)
        pong_started, finish_pong = asyncio.Event(), asyncio.Event()
        pending = None
        try:
            await life.connect()
            stream, session = factory.streams[0], factory.sessions[0]
            original = stream.write

            async def write(payload):
                if payload == b"\x0b":
                    pong_started.set()
                    await finish_pong.wait()
                await original(payload)

            stream.write = write
            stream.queue.put_nowait(b"\x0a" + notification())
            await pong_started.wait()
            assert life.data_updated_recovering, (
                "known ambiguity must gate reads before any await"
            )
            pending = asyncio.create_task(life.request_v4_data())
            await pump()
            assert session._pending_read is None and not pending.done()
            assert [w[0] for w in stream.writes] == [3]
            finish_pong.set()
            await pump()
            assert [w[0] for w in stream.writes] == [3, 11]
        finally:
            finish_pong.set()
            if pending is not None:
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
            await life.close()
            factory.assert_clean()

    asyncio.run(scenario())
