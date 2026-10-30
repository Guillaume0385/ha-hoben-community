"""Actual HA acquisition ignores synthetic notifications without publishing them."""

import asyncio
from unittest.mock import Mock

from conftest import DEVICE_GUID, assert_private_values_absent

from ha_tests.test_persistent_client import RESPONSE, assert_stopped, load, sensor
from ha_tests.test_persistent_client import peers as peers  # noqa: F401


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
