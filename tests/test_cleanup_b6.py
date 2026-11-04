"""B6 teardown races: actual session/lifecycle, in-memory I/O and clock only."""

import asyncio

import pytest

from custom_components.hoben.exceptions import HobenTimeoutError
from custom_components.hoben.transport import TransportTimeout
from tests.test_data_updated_silence import BAD, Clock, make_owner, pump
from tests.test_v4_persistent import Factory


@pytest.mark.parametrize("origin", ["read", "probe_write"])
def test_timeout_does_not_cancel_the_rx_owned_tls_shutdown(monkeypatch, origin):
    async def scenario():
        clock, factory = Clock(monkeypatch), Factory()
        life = make_owner(factory)
        close_started, allow_close = asyncio.Event(), asyncio.Event()
        finished, interrupted = [], []
        try:
            await life.connect()
            await life.request_v4_data()
            owner = life._task
            for generation in range(1, 4):
                close_started.clear()
                allow_close.clear()
                session, stream = factory.sessions[-1], factory.streams[-1]
                original_write = stream.write

                async def write(packet):
                    if packet[0] == 13:
                        if origin == "probe_write":
                            raise TransportTimeout("write")
                        return  # Expire the real request deadline below.
                    await original_write(packet)

                async def close():
                    stream.close_count += 1
                    close_started.set()
                    try:
                        await allow_close.wait()
                    except asyncio.CancelledError:
                        interrupted.append(generation)
                        raise
                    finished.append(generation)

                stream.write, stream.close = write, close
                request = None
                if origin == "probe_write":
                    stream.queue.put_nowait(BAD)
                    await pump()
                    await clock.advance(30)
                else:
                    request = asyncio.create_task(life.request_v4_data(timeout=30))
                    await pump()
                    await clock.advance(30)
                await pump()
                assert close_started.is_set()
                assert len(factory.sessions) == generation
                assert not session.cleanup_succeeded
                allow_close.set()
                await pump()
                if request is not None:
                    with pytest.raises(HobenTimeoutError):
                        await request
                assert not interrupted, "internal teardown cancelled TLS shutdown"
                assert finished == list(range(1, generation + 1))
                assert session.cleanup_succeeded
                assert session._rx_error.code == "timeout"
                assert session._rx_task.done() and not session._operations
                assert not session._tx_operations and session._pending_read is None
                assert not life.session_observation.cleanup_failed
                assert life.session_observation.cleaned_generation == generation
                assert life._task is owner and not owner.done()
                assert len(factory.sessions) == generation
                await clock.advance(59)
                assert len(factory.sessions) == generation
                await clock.advance(1)
                assert len(factory.sessions) == generation + 1
                await life.request_v4_data()
                assert life.witness.verified_read_generation == generation + 1
        finally:
            allow_close.set()
            await life.close()
            factory.assert_clean()

    asyncio.run(scenario())
