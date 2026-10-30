"""DataUpdated reception through the real persistent owner, synthetic TLS only."""

import asyncio
import logging

import pytest

from custom_components.hoben.exceptions import HobenProtocolError
from custom_components.hoben.transport import TransportEOF
from custom_components.hoben.v4_session import SessionState
from tests.test_session_300_runtime import response
from tests.test_v4_lifecycle import Backoff
from tests.test_v4_persistent import Factory


def notification():
    # The four bytes are opaque, never a length, identity or sequence number.
    return b"\x1b\xff\x05\x0a\x0e" + response()[1:]


@pytest.mark.parametrize("split", range(1, 54))
def test_persistent_dataupdated_every_split_preserves_correlated_suffix(
    split, monkeypatch
):
    from custom_components.hoben import v4_session

    decoded = []
    original = v4_session.decode_read_response

    def decode(frame):
        decoded.append(frame)
        return original(frame)

    monkeypatch.setattr(v4_session, "decode_read_response", decode)

    async def scenario():
        factory = Factory()
        life = factory.lifecycle(retry_delays=())
        try:
            await life.connect()
            frame = notification()
            factory.streams[0].chunks = [frame[:split], frame[split:] + response()]
            result = await life.request_v4_data()
            assert result.registers == (17,) * 20
            assert decoded == [response()[1:]]
            assert life.snapshot.attempts == 1
            assert life.witness.verified_read_sequence == 1
            assert factory.streams[0].close_count == 0
        finally:
            await life.close()
            factory.assert_clean()

    asyncio.run(scenario())


def test_repeated_notifications_never_release_waiter_or_replace_its_partial_suffix():
    async def scenario():
        factory = Factory()
        life = factory.lifecycle(retry_delays=())
        try:
            await life.connect()
            stream = factory.streams[0]
            stream.chunks = [notification() * 3 + response()[:17]]
            pending = asyncio.create_task(life.request_v4_data())
            for _ in range(40):
                await asyncio.sleep(0)
            assert not pending.done()
            assert life.witness.verified_read_sequence is None
            assert factory.sessions[0].state is SessionState.CONNECTED
            assert stream.close_count == 0
            stream.queue.put_nowait(response()[17:])
            assert (await pending).registers == (17,) * 20
            assert life.witness.verified_read_sequence == 1
        finally:
            await life.close()
            factory.assert_clean()

    asyncio.run(scenario())


def test_unknown_leading_message_never_scans_for_notification_or_response():
    async def scenario():
        factory = Factory()
        life = factory.lifecycle(retry_delays=())
        try:
            await life.connect()
            factory.streams[0].chunks = [b"\xff" + notification() + response()]
            with pytest.raises(HobenProtocolError):
                await life.request_v4_data()
            assert life.witness.verified_read_sequence is None
        finally:
            await life.close()
            factory.assert_clean()

    asyncio.run(scenario())


def test_notifications_on_closed_generation_cannot_satisfy_a_fresh_read():
    async def scenario():
        factory, backoff = Factory(), Backoff()
        life = factory.lifecycle(retry_delays=(1,), sleep=backoff)
        try:
            await life.connect()
            old = factory.streams[0]
            old.queue.put_nowait(TransportEOF("synthetic transport loss"))
            await backoff.entered.get()
            old.queue.put_nowait(notification() + response())
            backoff.release.put_nowait(None)
            await life.wait_connected()
            assert life.witness.established_generation == 2
            assert life.witness.verified_read_sequence is None
            assert (await life.request_v4_data()).registers == (17,) * 20
            assert old.queue.qsize() == 1 and old.close_count == 1
            assert life.witness.verified_read_generation == 2
        finally:
            await life.close()
            factory.assert_clean()

    asyncio.run(scenario())


@pytest.mark.parametrize("protocol, length", [(0, 0), (0, 1), (0, 255), (0, 65535)])
def test_invalid_dataupdated_length_warns_without_immediate_close_or_reconnect(
    protocol, length, caplog
):
    async def scenario():
        factory = Factory()
        life = factory.lifecycle(
            recover_acquisition=True, ha_reconnect=True, retry_delays=()
        )
        try:
            await life.connect()
            stream = factory.streams[0]
            stream.queue.put_nowait(
                b"\x1bPRIVATE"[:5]
                + b"\xff\xff"
                + protocol.to_bytes(2)
                + length.to_bytes(2)
                + b"PRIVATE_PAYLOAD\x0a"
                + response()
            )
            for _ in range(40):
                await asyncio.sleep(0)
            assert factory.sessions[0].state is SessionState.CONNECTED
            assert stream.close_count == 0 and len(factory.streams) == 1
            assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1
            assert "PRIVATE" not in caplog.text
        finally:
            await life.close()
            factory.assert_clean()

    asyncio.run(scenario())
