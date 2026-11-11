"""D2: actual HA owner, fake TLS, original timestamps and one UI grace."""

import asyncio

import pytest
from conftest import DEVICE_GUID, assert_private_values_absent

from custom_components.hoben.transport import TransportEOF
from ha_tests.test_persistent_client import RESPONSE, assert_stopped, load, sensor
from ha_tests.test_persistent_client import peers as peers  # noqa: F401
from ha_tests.test_session_sensor import session_state
from ha_tests.test_snapshot_hold_b7 import LocalClock
from tests.test_data_updated_silence import Clock, pump


async def test_timeout_late_and_duplicate_replies_do_not_refresh_or_extend_300s(
    hass, entry, peers, freezer, monkeypatch, caplog
):
    ui = LocalClock(monkeypatch, freezer)
    wire = peers.wire(DEVICE_GUID, [[RESPONSE], []])
    peers.wire(DEVICE_GUID, [[RESPONSE]])
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()
    clock = Clock(monkeypatch)
    life = peers.lifecycles[0]
    session, previous, stamp = (
        life._session,
        coordinator.data,
        coordinator.last_successful_read_at,
    )
    rx, previous_state = session._rx_task, sensor(hass, entry)
    refresh = asyncio.create_task(coordinator.async_refresh())
    try:
        await pump()
        await ui.advance(30.001)
        await clock.advance(30.001)
        await refresh
        assert not coordinator.last_update_success and coordinator.data is previous
        assert (
            session.acquisition_uncertain and session._rx_task is rx and not rx.done()
        )
        assert coordinator.client.session_state == "recovering"
        assert session_state(hass, entry).state == "recovering"
        assert sensor(hass, entry) is previous_state
        until = coordinator._connection_hold_until
        error_at = coordinator.client.session_monitor.last_error_at
        for _ in range(3):
            wire.queue.put_nowait(RESPONSE + b"\x0a" + RESPONSE)
            await pump()
            await coordinator.async_refresh()
            coordinator._async_unsub_refresh()
            assert coordinator.last_successful_read_at == stamp
            assert coordinator._connection_hold_until == until
            assert coordinator.client.session_monitor.last_error_at == error_at
            assert session.verified_read_sequence == 1
        assert [c.args[0][0] for c in wire.write.await_args_list] == [
            3,
            13,
            13,
            11,
            11,
            11,
        ]
        assert peers.factory.call_count == 1 and not peers.backoff.delays
        wire.close.assert_not_awaited()
        await ui.advance(299)
        assert (
            coordinator.last_snapshot_held
            and sensor(hass, entry).state != "unavailable"
        )
        await ui.advance(1)
        assert (
            not coordinator.last_snapshot_held
            and sensor(hass, entry).state == "unavailable"
        )
        assert coordinator.last_successful_read_at == stamp
        wire.queue.put_nowait(TransportEOF())
        assert await peers.backoff.entered.get() == 60
        wire.close.assert_awaited_once_with()
        peers.backoff.release.put_nowait(None)
        await life.wait_connected()
        assert not life.acquisition_uncertain and peers.factory.call_count == 2
        await coordinator.async_refresh()
        coordinator._async_unsub_refresh()
        assert coordinator.last_update_success
        assert coordinator.client.session_observation.read_generation == 2
        assert sensor(hass, entry).state != "unavailable"
        assert_private_values_absent(caplog.text)
    finally:
        refresh.cancel()
        await asyncio.gather(refresh, return_exceptions=True)
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert_stopped(peers)


@pytest.mark.parametrize("stop", [False, True])
async def test_first_acquisition_silence_keeps_one_setup_owner_without_spin(
    hass, entry, peers, monkeypatch, stop
):
    clock = Clock(monkeypatch)
    wire = peers.wire(DEVICE_GUID, [[]])
    peers.wire(DEVICE_GUID, [[RESPONSE]])
    emitted = asyncio.Event()
    original_write = wire.write.side_effect

    def write(packet):
        original_write(packet)
        if packet[0] == 13:
            emitted.set()

    wire.write.side_effect = write
    setup = asyncio.create_task(hass.config_entries.async_setup(entry.entry_id))
    try:
        # Component import/TLS context executor must finish before advancing
        # the request clock, independently of host load or test order.
        await emitted.wait()
        await pump()
        await clock.advance(30.001)
        await pump()
        assert not setup.done() and peers.lifecycles[0].acquisition_uncertain
        wire.queue.put_nowait(RESPONSE + b"\x0a")
        await pump()
        assert [c.args[0][0] for c in wire.write.await_args_list] == [3, 13, 11]
        assert peers.factory.call_count == 1 and not peers.backoff.delays
        wire.close.assert_not_awaited()
        if stop:
            setup.cancel()
            with pytest.raises(asyncio.CancelledError):
                await setup
            assert peers.factory.call_count == 1
        else:
            wire.queue.put_nowait(TransportEOF())
            assert await peers.backoff.entered.get() == 60
            peers.backoff.release.put_nowait(None)
            assert await setup
            assert entry.runtime_data.coordinator.last_update_success
            assert peers.factory.call_count == 2
            assert await hass.config_entries.async_unload(entry.entry_id)
        assert_stopped(peers)
    finally:
        if not setup.done():
            setup.cancel()
            await asyncio.gather(setup, return_exceptions=True)


async def test_old_cleanup_cannot_cover_next_generation_or_extend_300s(
    hass, entry, peers, freezer, monkeypatch
):
    ui = LocalClock(monkeypatch, freezer)
    first = peers.wire(DEVICE_GUID, [[RESPONSE], []])
    second = peers.wire(DEVICE_GUID, [])
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()
    clock = Clock(monkeypatch)
    life = peers.lifecycles[0]
    stamp = coordinator.last_successful_read_at
    close_started, release = asyncio.Event(), asyncio.Event()

    async def close_second():
        close_started.set()
        await release.wait()

    second.close.side_effect = close_second
    refresh = asyncio.create_task(coordinator.async_refresh())
    try:
        await pump()
        await ui.advance(30.001)
        await clock.advance(30.001)
        await refresh
        until = coordinator._connection_hold_until
        assert coordinator.last_snapshot_held and life.acquisition_uncertain
        first.queue.put_nowait(TransportEOF())
        assert await peers.backoff.entered.get() == 60
        await ui.advance(60)
        peers.backoff.release.put_nowait(None)
        await life.wait_connected()
        assert coordinator.client.session_observation.cleaned_generation == 1
        assert coordinator.client.session_observation.generation == 2
        assert coordinator.last_snapshot_held
        second.queue.put_nowait(TransportEOF())
        await close_started.wait()
        await pump()
        # Generation 1 is clean, but generation 2 still owns an unclosed TLS.
        assert coordinator.client.session_observation.cleaned_generation == 1
        assert not life._session.cleanup_succeeded
        assert not coordinator._cleanup_proven(2)
        assert not coordinator.last_snapshot_held
        assert coordinator._connection_hold_until == until
        release.set()
        assert await peers.backoff.entered.get() == 60
        assert coordinator.client.session_observation.cleaned_generation == 2
        assert coordinator.last_snapshot_held
        assert coordinator.last_successful_read_at == stamp
        assert coordinator.client.session_observation.read_generation is None
        await ui.advance(239.999)
        assert coordinator.last_snapshot_held
        await ui.advance(0.001)
        assert not coordinator.last_snapshot_held
        await ui.advance(1)
        assert not coordinator.snapshot_available
        assert coordinator.last_successful_read_at == stamp
        assert coordinator._connection_hold_until == until
        assert peers.factory.call_count == 2
    finally:
        release.set()
        refresh.cancel()
        await asyncio.gather(refresh, return_exceptions=True)
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert_stopped(peers)
