"""#212: real HA/client/session owners over synthetic TLS and virtual time."""

import asyncio

from conftest import DEVICE_GUID, assert_private_values_absent

from custom_components.hoben import coordinator as coordinator_module
from custom_components.hoben.client import HobenClient
from custom_components.hoben.coordinator import HobenDataUpdateCoordinator
from custom_components.hoben.v4_lifecycle import V4Lifecycle
from custom_components.hoben.v4_session import V4Session
from ha_tests.test_persistent_client import RESPONSE, assert_stopped, load, sensor
from ha_tests.test_persistent_client import peers as peers  # noqa: F401
from tests.test_data_updated_silence import Clock, pump


async def test_first_timeout_retries_on_same_tls_after_sixty_seconds(
    hass, entry, peers, monkeypatch, caplog
):
    """RED: the current owner fences reads forever instead of sending #2.

    Only transport and time are synthetic. A late FFFF reply must not make
    the second request disappear by pretending acquisition already recovered.
    """
    wire = peers.wire(DEVICE_GUID, [[RESPONSE], [], []])
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()
    clock = Clock(monkeypatch)
    life = peers.lifecycles[0]
    session = life._session
    assert isinstance(coordinator, HobenDataUpdateCoordinator)
    assert isinstance(coordinator.client, HobenClient)
    assert isinstance(life, V4Lifecycle)
    assert isinstance(session, V4Session)
    previous = coordinator.data
    stamp = coordinator.last_successful_read_at
    rx = session._rx_task
    refresh = asyncio.create_task(coordinator.async_refresh())

    def requests():
        return sum(c.args[0][0] == 13 for c in wire.write.await_args_list)

    try:
        await pump()
        assert requests() == 2  # Initial successful read + failing request #1.
        await clock.advance(30)
        await refresh
        coordinator._async_unsub_refresh()
        assert session.acquisition_uncertain
        assert not coordinator.last_update_success
        assert coordinator.data is previous
        assert coordinator.last_successful_read_at == stamp
        wire.close.assert_not_awaited()

        # RX and Ping/Pong survive; a complete late reply is never fresh.
        wire.queue.put_nowait(RESPONSE + b"\x0a")
        await pump()
        assert wire.write.await_args_list[-1].args == (b"\x0b",)
        assert session.verified_read_sequence == 1
        await clock.advance(59.999)
        assert requests() == 2
        assert peers.factory.call_count == 1
        wire.close.assert_not_awaited()

        await clock.advance(0.001)
        assert requests() == 3, "request #2 missing at first timeout + 60 seconds"
        assert session._rx_task is rx and not rx.done()
        assert life._session is session and peers.factory.call_count == 1
        wire.close.assert_not_awaited()
        assert coordinator.last_successful_read_at == stamp
        assert_private_values_absent(caplog.text)
    finally:
        refresh.cancel()
        await asyncio.gather(refresh, return_exceptions=True)
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert_stopped(peers)


async def test_three_timeouts_then_new_generation_restores_only_a_fresh_ha_read(
    hass, entry, peers, monkeypatch
):
    """HA's 300-second grace does not become a new acquisition on a probe."""
    wire = peers.wire(DEVICE_GUID, [[RESPONSE], [], [RESPONSE], [RESPONSE]])
    peers.wire(DEVICE_GUID, [[RESPONSE]])
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()
    clock = Clock(monkeypatch)
    monkeypatch.setattr(coordinator_module, "monotonic", lambda: clock.now)
    previous = coordinator.data
    stamp = coordinator.last_successful_read_at
    life = peers.lifecycles[0]
    old = life._session
    refresh = asyncio.create_task(coordinator.async_refresh())
    try:
        await pump()
        await clock.advance(30)
        await refresh
        coordinator._async_unsub_refresh()
        for _ in range(2):
            await clock.advance(60)
            await clock.advance(29.999)
            wire.close.assert_not_awaited()
            assert coordinator.last_successful_read_at == stamp
            assert coordinator.data is previous
            assert old.verified_read_sequence == 1
            await clock.advance(0.001)
        assert await peers.backoff.entered.get() == 60
        wire.close.assert_awaited_once_with()
        assert old.cleanup_succeeded and peers.factory.call_count == 1
        assert sum(c.args[0][0] == 13 for c in wire.write.await_args_list) == 4
        assert coordinator.last_snapshot_held
        await clock.advance(119.999)
        assert coordinator.last_snapshot_held
        await clock.advance(0.001)
        assert not coordinator.last_snapshot_held
        assert sensor(hass, entry).state == "unavailable"
        assert coordinator.last_successful_read_at == stamp
        peers.backoff.release.put_nowait(None)
        await life.wait_connected()
        assert coordinator.last_successful_read_at == stamp
        await coordinator.async_refresh()
        coordinator._async_unsub_refresh()
        assert coordinator.last_update_success
        assert life.witness.verified_read_generation == 2
        assert sensor(hass, entry).state != "unavailable"
    finally:
        refresh.cancel()
        await asyncio.gather(refresh, return_exceptions=True)
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert_stopped(peers)
