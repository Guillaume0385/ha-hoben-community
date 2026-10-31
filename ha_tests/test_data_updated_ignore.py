"""Actual HA acquisition ignores synthetic notifications without publishing them."""

import asyncio
from unittest.mock import Mock

import pytest
from conftest import DEVICE_GUID, assert_private_values_absent

from custom_components.hoben.transport import TransportEOF
from ha_tests.test_persistent_client import RESPONSE, assert_stopped, load, sensor
from ha_tests.test_persistent_client import peers as peers  # noqa: F401
from tests.test_data_updated_silence import BAD, Clock, pump


def notification():
    # Deliberately different register bytes: they must never reach the HA model.
    return b"\x1b\xff\x05\x0a\x0e" + RESPONSE[1:10] + b"\xfe\xdc" * 20


async def test_idle_notifications_do_not_publish_snapshot_or_trigger_coordinator(
    hass, entry, peers, caplog
):
    wire = peers.wire(DEVICE_GUID, [[RESPONSE]])
    coordinator = await load(hass, entry)
    previous, previous_sensor = coordinator.data, sensor(hass, entry)
    listener = Mock()
    unsubscribe = coordinator.async_add_listener(listener)
    try:
        wire.queue.put_nowait(notification() * 5)
        for _ in range(40):
            await asyncio.sleep(0)
        await hass.async_block_till_done()
        assert coordinator.data is previous and coordinator.last_update_success
        assert sensor(hass, entry) is previous_sensor
        listener.assert_not_called()
        assert peers.lifecycles[0].witness.verified_read_sequence == 1
        assert peers.factory.call_count == 1 and not peers.backoff.delays
        wire.close.assert_not_awaited()
        assert [c.args[0][0] for c in wire.write.await_args_list] == [3, 13]
        assert_private_values_absent(caplog.text)
    finally:
        unsubscribe()
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert_stopped(peers)


async def test_notification_never_completes_a_pending_ha_refresh(hass, entry, peers):
    wire = peers.wire(DEVICE_GUID, [[RESPONSE], [notification() * 3]])
    coordinator = await load(hass, entry)
    previous = coordinator.data
    try:
        pending = asyncio.create_task(coordinator.async_refresh())
        for _ in range(40):
            await asyncio.sleep(0)
        assert not pending.done() and coordinator.data is previous
        assert peers.lifecycles[0].witness.verified_read_sequence == 1
        wire.queue.put_nowait(RESPONSE)
        await pending
        assert coordinator.last_update_success
        assert peers.lifecycles[0].witness.verified_read_sequence == 2
        assert peers.factory.call_count == 1 and not peers.backoff.delays
        wire.close.assert_not_awaited()
    finally:
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert_stopped(peers)


async def enter_hold(hass, entry, peers, monkeypatch):
    fresh = RESPONSE[:10] + b"\x00\x12" * 20
    wire = peers.wire(DEVICE_GUID, [[RESPONSE], [fresh]])
    coordinator = await load(hass, entry)
    previous = coordinator.data
    previous_sensor = sensor(hass, entry)
    previous_read_at = coordinator.last_successful_read_at
    clock = Clock(monkeypatch)
    wire.queue.put_nowait(BAD)
    await pump()
    deferred = asyncio.create_task(coordinator.async_refresh())
    await pump()
    await clock.advance(20)
    wire.queue.put_nowait(b"\xff" * 4096)
    await pump()
    await clock.advance(10)
    await deferred
    assert coordinator.data is previous and not coordinator.last_update_success
    assert coordinator.last_successful_read_at == previous_read_at
    assert sensor(hass, entry) is previous_sensor
    assert coordinator.data_updated_hold and sensor(hass, entry).state != "unavailable"
    assert [c.args[0][0] for c in wire.write.await_args_list] == [3, 13]
    wire.close.assert_not_awaited()
    return wire, coordinator, previous, clock


async def test_recovery_holds_values_without_fake_updates_then_uses_one_probe(
    hass, entry, peers, monkeypatch, caplog
):
    wire, coordinator, previous, clock = await enter_hold(
        hass, entry, peers, monkeypatch
    )
    listener = Mock()
    unsubscribe = coordinator.async_add_listener(listener)
    try:
        observer = asyncio.create_task(coordinator.async_refresh())
        await pump()
        await clock.advance(19)
        assert coordinator.data is previous and coordinator.data_updated_hold
        assert [c.args[0][0] for c in wire.write.await_args_list] == [3, 13]
        listener.assert_not_called()
        await clock.advance(1)
        await observer
        assert coordinator.last_update_success and not coordinator.data_updated_hold
        assert coordinator.data.raw.registers == (18,) * 20
        assert [c.args[0][0] for c in wire.write.await_args_list] == [3, 13, 13]
        assert peers.factory.call_count == 1 and not peers.backoff.delays
        assert_private_values_absent(caplog.text)
        assert "PRIVATE" not in caplog.text
    finally:
        unsubscribe()
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert_stopped(peers)


async def test_genuine_transport_loss_ends_value_hold_and_preserves_normal_retry(
    hass, entry, peers, monkeypatch
):
    wire, coordinator, _, _ = await enter_hold(hass, entry, peers, monkeypatch)
    peers.wire(DEVICE_GUID, [[RESPONSE]])
    try:
        wire.queue.put_nowait(TransportEOF("synthetic loss"))
        await peers.backoff.entered.get()
        refresh = asyncio.create_task(coordinator.async_refresh())
        await pump()
        assert sensor(hass, entry).state == "unavailable"
        await refresh
        assert not coordinator.last_update_success
        peers.backoff.release.put_nowait(None)
        await peers.lifecycles[0].wait_connected()
        await coordinator.async_refresh()
        assert (
            coordinator.last_update_success
            and sensor(hass, entry).state != "unavailable"
        )
        assert peers.factory.call_count == 2
    finally:
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert_stopped(peers)


async def test_setup_recovery_can_be_cancelled_without_reconnection_or_orphan_probe(
    hass, entry, peers, monkeypatch
):
    wire = peers.wire(DEVICE_GUID, [[BAD], []])
    received = asyncio.Event()
    original_read = wire.read.side_effect

    async def read(*args, **kwargs):
        data = await original_read(*args, **kwargs)
        if data == BAD:
            received.set()
        return data

    wire.read.side_effect = read
    clock = Clock(monkeypatch)
    setup = asyncio.create_task(hass.config_entries.async_setup(entry.entry_id))
    await received.wait()
    await pump()
    await clock.advance(30)
    assert not setup.done()
    assert [c.args[0][0] for c in wire.write.await_args_list] == [3, 13, 13]
    setup.cancel()
    with pytest.raises(asyncio.CancelledError):
        await setup
    assert peers.factory.call_count == 1
    wire.close.assert_awaited_once_with()
    assert_stopped(peers)
    assert not any(
        t.get_name() == "hoben-dataupdated-probe" for t in asyncio.all_tasks()
    )


async def test_setup_consumes_a_completed_probe_once_without_a_third_read(
    hass, entry, peers, monkeypatch
):
    wire = peers.wire(DEVICE_GUID, [[BAD], [RESPONSE]])
    received = asyncio.Event()
    original_read = wire.read.side_effect

    async def read(*args, **kwargs):
        data = await original_read(*args, **kwargs)
        if data == BAD:
            received.set()
        return data

    wire.read.side_effect = read
    clock = Clock(monkeypatch)
    setup = asyncio.create_task(hass.config_entries.async_setup(entry.entry_id))
    await received.wait()
    await pump()
    await clock.advance(30)
    assert await setup
    try:
        assert entry.runtime_data.coordinator.last_update_success
        assert [c.args[0][0] for c in wire.write.await_args_list] == [3, 13, 13]
        assert peers.factory.call_count == 1
    finally:
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert_stopped(peers)
