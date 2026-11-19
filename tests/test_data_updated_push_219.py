"""#219 owner empirical mapping, single initial read and original #212 owners."""

import asyncio
from unittest.mock import Mock

import pytest

from custom_components.hoben.client import HobenClient
from custom_components.hoben.exceptions import HobenTimeoutError
from custom_components.hoben.modbus import encode_mbap
from custom_components.hoben.transport import TransportEOF
from custom_components.hoben.v4_state import decode_v4_snapshot
from tests.test_data_updated_silence import Clock, pump
from tests.test_session_300_runtime import response
from tests.test_v4_lifecycle import Backoff
from tests.test_v4_persistent import Factory


def notification(words, *, tx=65535, unit=1, function=4):
    return b"\x1bTEST" + encode_mbap(
        tx,
        unit,
        bytes((function, len(words) * 2))
        + b"".join(word.to_bytes(2, "big") for word in words),
    )


async def connect_client(factory, **options):
    client = HobenClient("b" * 32, ha_reconnect=True, push_updates=True)
    client._lifecycle = factory.lifecycle(
        ha_reconnect=True,
        recover_acquisition=True,
        _data_callback=client._receive_data_updated,
        **options,
    )
    await client._lifecycle.connect()
    return client


@pytest.mark.parametrize("before_request", [False, True])
def test_notification_before_or_during_initial_response_wins_without_extra_tx(
    before_request,
):
    async def run():
        factory = Factory()
        client = await connect_client(factory)
        try:
            stream = factory.streams[0]
            packet = notification((234,) * 20)
            if before_request:
                stream.queue.put_nowait(packet)
                await pump()
            else:
                stream.chunks.insert(0, packet)
            first = await client.async_refresh()
            assert first.registers == (234,) * 20
            assert await client.async_refresh() is first
            assert [p[0] for p in stream.writes] == [3, 13]
        finally:
            await client.async_close()
            factory.assert_clean()

    asyncio.run(run())


@pytest.mark.parametrize(
    "tx,unit,function,count",
    [
        (65534, 1, 4, 20),
        (65520, 1, 4, 20),
        (65535, 0, 4, 20),
        (65535, 1, 3, 20),
        (65535, 1, 4, 19),
        (65535, 1, 4, 21),
    ],
)
def test_only_exact_admitted_applicative_shape_can_publish(tx, unit, function, count):
    async def run():
        factory = Factory()
        client = await connect_client(factory)
        listener = Mock()
        unsubscribe = client.subscribe_data(listener)
        try:
            original = await client.async_refresh()
            factory.streams[0].queue.put_nowait(
                notification((100,) * count, tx=tx, unit=unit, function=function)
            )
            await pump()
            assert client.last_snapshot is original
            listener.assert_not_called()
            factory.streams[0].queue.put_nowait(notification((456,) * 20))
            await pump()
            assert client.last_snapshot.registers == (456,) * 20
            listener.assert_called_once()
            raw, state = listener.call_args.args
            assert state == decode_v4_snapshot(raw)
            assert factory.streams[0].close_count == 0
        finally:
            unsubscribe()
            await client.async_close()
            factory.assert_clean()

    asyncio.run(run())


def test_old_generation_callback_cannot_publish_or_replace_new_initial_sample():
    async def run():
        factory, backoff = Factory(), Backoff()
        client = await connect_client(factory, sleep=backoff)
        try:
            await client.async_refresh()
            old = factory.sessions[0]
            factory.streams[0].queue.put_nowait(notification((123,) * 20))
            await pump()
            callback, item = old._data_callback, old._latest_data_updated
            factory.streams[0].queue.put_nowait(TransportEOF())
            await backoff.entered.get()
            assert old.cleanup_succeeded
            backoff.release.put_nowait(None)
            await client._lifecycle.wait_connected()
            fresh = await client.async_refresh()
            assert fresh.registers == (17,) * 20
            callback(item)
            assert client.last_snapshot is fresh
            assert [p[0] for p in factory.streams[1].writes] == [3, 13]
        finally:
            await client.async_close()
            factory.assert_clean()

    asyncio.run(run())


def test_initial_timeout_keeps_three_request_212_and_never_credits_late_du(monkeypatch):
    async def run():
        clock, factory, backoff = Clock(monkeypatch), Factory(), Backoff()
        client = await connect_client(factory, sleep=backoff)
        pending = None
        try:
            stream = factory.streams[0]
            stream.chunks = []
            pending = asyncio.create_task(client.async_refresh())
            await pump()
            await clock.advance(30)
            with pytest.raises(HobenTimeoutError):
                await pending
            with pytest.raises(HobenTimeoutError):
                await client.async_refresh()
            stream.queue.put_nowait(notification((789,) * 20))
            await pump()
            assert client.last_snapshot is None
            for _ in range(2):
                await clock.advance(60)
                await clock.advance(30)
            await backoff.entered.get()
            assert [p[0] for p in stream.writes] == [3, 13, 13, 13]
            assert factory.sessions[0].cleanup_succeeded
            backoff.release.put_nowait(None)
            await client._lifecycle.wait_connected()
            assert (await client.async_refresh()).registers == (17,) * 20
        finally:
            if pending is not None:
                await asyncio.gather(pending, return_exceptions=True)
            await client.async_close()
            factory.assert_clean()

    asyncio.run(run())


def test_retained_notification_keeps_its_original_reception_time(monkeypatch):
    async def run():
        clock, factory = Clock(monkeypatch), Factory()
        client = await connect_client(factory)
        pending = None
        try:
            stream = factory.streams[0]
            stream.chunks = [notification((234,) * 20)]
            pending = asyncio.create_task(client.async_refresh())
            await pump()
            received = factory.sessions[0]._latest_data_updated[3]
            await clock.advance(10)
            stream.queue.put_nowait(response())
            assert (await pending).registers == (234,) * 20
            assert client.sample_received_monotonic == received
            assert asyncio.get_running_loop().time() - received == 10
        finally:
            if pending is not None:
                await asyncio.gather(pending, return_exceptions=True)
            await client.async_close()
            factory.assert_clean()

    asyncio.run(run())


def test_concurrent_refreshes_share_the_single_initial_request():
    async def run():
        factory = Factory()
        client = await connect_client(factory)
        try:
            first, second = await asyncio.gather(
                client.async_refresh(), client.async_refresh()
            )
            assert first is second
            assert [p[0] for p in factory.streams[0].writes] == [3, 13]
        finally:
            await client.async_close()
            factory.assert_clean()

    asyncio.run(run())
