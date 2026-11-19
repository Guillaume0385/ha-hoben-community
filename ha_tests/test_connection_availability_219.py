"""#219-006: availability follows real connection loss, never notification age."""

import asyncio
from unittest.mock import Mock

import pytest
from conftest import DEVICE_GUID, assert_private_values_absent
from homeassistant.const import EVENT_HOMEASSISTANT_STOP

from custom_components.hoben import coordinator as module
from custom_components.hoben.modbus import encode_mbap
from custom_components.hoben.transport import (
    TransportCertificateError,
    TransportEOF,
    TransportError,
    TransportTlsError,
)
from ha_tests.test_data_updated_push_219 import push_peers as push_peers  # noqa: F401
from ha_tests.test_data_updated_push_219 import updated
from ha_tests.test_persistent_client import RESPONSE, assert_stopped, load, sensor
from ha_tests.test_persistent_client import peers as peers  # noqa: F401
from tests.test_data_updated_drop_219 import INVALID
from tests.test_data_updated_silence import BAD, Clock, pump
from tests.tls_script import script_transport


@pytest.fixture
async def timeline(hass, monkeypatch):
    clock = Clock(monkeypatch)
    monkeypatch.setattr(module, "monotonic", lambda: clock.now)
    timers = []
    schedule = module.async_call_later

    def observe_timer(hass, delay, action):
        timers.append((clock.now + delay, action))
        return schedule(hass, delay, action)

    monkeypatch.setattr(module, "async_call_later", observe_timer)
    clock.timers = timers
    return clock


@pytest.mark.parametrize("silence", [301, 600, 1800, 3600])
async def test_silent_connected_session_keeps_values_without_fake_freshness_or_tx(
    hass, entry, push_peers, timeline, caplog, silence
):
    wire = push_peers.wire(DEVICE_GUID, [[RESPONSE]])
    coordinator = await load(hass, entry)
    previous = coordinator.data
    stamp = coordinator.last_successful_read_at
    tick = coordinator.client.sample_received_monotonic
    state = sensor(hass, entry)
    listener = Mock()
    unsub = coordinator.async_add_listener(listener)
    try:
        await timeline.advance(silence)
        assert coordinator.client.data_updated_transport_alive
        assert coordinator.snapshot_available, "silence is not a connection loss"
        assert sensor(hass, entry) is state
        assert coordinator.data is previous
        assert coordinator.last_successful_read_at == stamp
        assert coordinator.client.sample_received_monotonic == tick
        listener.assert_not_called()
        assert timeline.timers == []
        assert coordinator.update_interval is None
        for packet in INVALID:
            wire.queue.put_nowait(packet)
        wire.queue.put_nowait(b"\x0a")
        await pump()
        assert coordinator.snapshot_available and coordinator.data is previous
        assert coordinator.last_successful_read_at == stamp
        assert [c.args[0][0] for c in wire.write.await_args_list] == [3, 13, 11]
        assert push_peers.factory.call_count == 1
        wire.close.assert_not_awaited()
        wire.queue.put_nowait(updated((234,) * 20))
        await pump()
        assert coordinator.data.raw.registers == (234,) * 20
        assert coordinator.snapshot_available and sensor(hass, entry).state == "23.4"
        listener.assert_called_once()
        assert timeline.timers == []
        assert_private_values_absent(caplog.text)
    finally:
        unsub()
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert_stopped(push_peers)


@pytest.mark.parametrize("fault", [TransportEOF(), TransportTlsError(), b"\x05\x03"])
async def test_outage_grace_starts_at_loss_and_expires_strictly_after_300_seconds(
    hass, entry, push_peers, timeline, fault
):
    wire = push_peers.wire(DEVICE_GUID, [[RESPONSE]])
    coordinator = await load(hass, entry)
    previous, stamp = coordinator.data, coordinator.last_successful_read_at
    try:
        await timeline.advance(1800)
        wire.queue.put_nowait(fault)
        await push_peers.backoff.entered.get()
        assert coordinator._connection_hold_until == 2100
        assert coordinator.snapshot_available and coordinator.last_snapshot_held
        assert sensor(hass, entry).state != "unavailable"
        await timeline.advance(299)
        assert coordinator.snapshot_available
        await timeline.advance(1)
        assert coordinator.snapshot_available, "five minutes exactly is still grace"
        await timeline.advance(0.001)
        assert not coordinator.snapshot_available
        assert sensor(hass, entry).state == "unavailable"
        assert (
            coordinator.data is previous
            and coordinator.last_successful_read_at == stamp
        )
        assert push_peers.factory.call_count == 1
        assert [c.args[0][0] for c in wire.write.await_args_list] == [3, 13]
    finally:
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert_stopped(push_peers)


@pytest.mark.parametrize("outage", [60, 301])
async def test_reconnection_requires_real_initial_read_and_revokes_old_timer(
    hass, entry, push_peers, timeline, outage
):
    first = push_peers.wire(DEVICE_GUID, [[RESPONSE]])
    fresh = push_peers.wire(DEVICE_GUID, [[]])
    coordinator = await load(hass, entry)
    previous, stamp = coordinator.data, coordinator.last_successful_read_at
    unavailable = []

    def changed(event):
        value = event.data.get("new_state")
        if value and value.entity_id == sensor(hass, entry).entity_id:
            unavailable.append(value.state == "unavailable")

    unsubscribe = hass.bus.async_listen("state_changed", changed)
    try:
        await timeline.advance(600)
        first.queue.put_nowait(TransportEOF())
        await push_peers.backoff.entered.get()
        old_expiry = timeline.timers[-1][1]
        await timeline.advance(outage)
        push_peers.backoff.release.put_nowait(None)
        life = push_peers.lifecycles[0]
        await life.wait_connected()
        await pump()
        assert life.witness.established_generation == 2
        assert life.witness.verified_read_generation is None
        assert coordinator.data is previous
        assert coordinator.last_successful_read_at == stamp
        assert coordinator.snapshot_available is (outage < 300)
        fresh.queue.put_nowait(updated((234,) * 20))
        fresh.queue.put_nowait(b"\x0a")
        await pump()
        assert coordinator.data is previous
        assert coordinator.snapshot_available is (outage < 300)
        fresh.queue.put_nowait(RESPONSE)
        await pump()
        assert life.witness.verified_read_generation == 2
        assert coordinator.snapshot_available and sensor(hass, entry).state == "23.4"
        accepted = coordinator.data
        new_stamp = coordinator.last_successful_read_at
        old_expiry(None)
        await timeline.advance(3600)
        assert coordinator.snapshot_available and coordinator.data is accepted
        assert coordinator.last_successful_read_at == new_stamp
        assert [c.args[0][0] for c in fresh.write.await_args_list] == [3, 13, 11]
        if outage < 300:
            assert not any(unavailable)
        else:
            assert any(unavailable)
    finally:
        unsubscribe()
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert_stopped(push_peers)


async def test_losses_without_valid_acquisition_share_original_deadline(
    hass, entry, push_peers, timeline
):
    first = push_peers.wire(DEVICE_GUID, [[RESPONSE]])
    second = push_peers.wire(DEVICE_GUID, [[]])
    third = push_peers.wire(DEVICE_GUID, [[]])
    coordinator = await load(hass, entry)
    try:
        first.queue.put_nowait(TransportEOF())
        await push_peers.backoff.entered.get()
        deadline = coordinator._connection_hold_until
        expired = timeline.timers[-1][1]
        await timeline.advance(60)
        push_peers.backoff.release.put_nowait(None)
        life = push_peers.lifecycles[0]
        await life.wait_connected()
        await pump()
        await timeline.advance(10)
        second.queue.put_nowait(TransportEOF())
        await push_peers.backoff.entered.get()
        assert coordinator._connection_hold_until == deadline == 300
        await timeline.advance(60)
        push_peers.backoff.release.put_nowait(None)
        await life.wait_connected()
        await pump()
        assert life.witness.established_generation == 3
        assert coordinator._connection_hold_until == deadline
        third.queue.put_nowait(RESPONSE)
        await pump()
        assert coordinator.snapshot_available
        assert life.witness.verified_read_generation == 3
        third.queue.put_nowait(TransportEOF())
        await push_peers.backoff.entered.get()
        assert coordinator._connection_hold_until == 430
        token = coordinator._hold_timer_token
        expired(None)
        assert coordinator._hold_timer_token is token
        assert coordinator._connection_hold_until == 430
    finally:
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert_stopped(push_peers)


@pytest.mark.parametrize(
    "refusal",
    [b"\x05\x02", b"\x05\x04", b"\x05\x05", b"\x2f", "certificate", "cleanup"],
)
async def test_terminal_refusal_or_unverified_cleanup_revokes_grace_immediately(
    hass, entry, push_peers, timeline, refusal
):
    first = push_peers.wire(DEVICE_GUID, [[RESPONSE]])
    fresh = push_peers.wire(DEVICE_GUID, [[]])
    coordinator = await load(hass, entry)
    try:
        if refusal == "cleanup":
            first.close.side_effect = TransportError("PRIVATE_PAYLOAD")
        elif refusal == "certificate":
            fresh.connect.side_effect = TransportCertificateError("PRIVATE_PAYLOAD")
        else:
            script_transport(fresh, openings=[[refusal]])
        first.queue.put_nowait(TransportEOF())
        if refusal != "cleanup":
            await push_peers.backoff.entered.get()
            await timeline.advance(60)
            push_peers.backoff.release.put_nowait(None)
        await pump()
        assert not coordinator.snapshot_available
        assert sensor(hass, entry).state == "unavailable"
        assert coordinator._unsub_hold_expiry is None
    finally:
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert_stopped(push_peers)


@pytest.mark.parametrize("shutdown", [False, True])
async def test_stop_or_unload_revokes_pending_timer_and_late_notifications(
    hass, entry, push_peers, timeline, shutdown
):
    wire = push_peers.wire(DEVICE_GUID, [[RESPONSE]])
    coordinator = await load(hass, entry)
    wire.queue.put_nowait(TransportEOF())
    await push_peers.backoff.entered.get()
    expired = timeline.timers[-1][1]
    if shutdown:
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
        await pump()
    else:
        assert await hass.config_entries.async_unload(entry.entry_id)
    previous = coordinator.data
    expired(None)
    await timeline.advance(3600)
    assert not coordinator.snapshot_available
    assert coordinator.data is previous
    assert coordinator._hold_timer_token is None
    assert coordinator._unsub_hold_expiry is None
    assert_stopped(push_peers)


async def test_reload_uses_fresh_coordinator_and_old_outage_timer_is_inert(
    hass, entry, push_peers, timeline
):
    wire = push_peers.wire(DEVICE_GUID, [[RESPONSE]])
    push_peers.wire(DEVICE_GUID, [[RESPONSE]])
    previous = await load(hass, entry)
    wire.queue.put_nowait(TransportEOF())
    await push_peers.backoff.entered.get()
    expired = timeline.timers[-1][1]
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(push_peers)
    assert await hass.config_entries.async_setup(entry.entry_id)
    current = entry.runtime_data.coordinator
    try:
        assert current is not previous and current.snapshot_available
        stamp, snapshot = current.last_successful_read_at, current.data
        expired(None)
        await timeline.advance(3600)
        assert not previous.snapshot_available
        assert current.snapshot_available and current.data is snapshot
        assert current.last_successful_read_at == stamp
        assert current._unsub_hold_expiry is None
        assert len(push_peers.lifecycles) == 2
    finally:
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert_stopped(push_peers)


async def test_loss_window_starts_before_slow_cleanup_and_never_moves(
    hass, entry, push_peers, timeline
):
    wire = push_peers.wire(DEVICE_GUID, [[RESPONSE]])
    coordinator = await load(hass, entry)
    closing = asyncio.Event()

    async def close():
        closing.set()
        await asyncio.sleep(5)

    wire.close.side_effect = close
    try:
        await timeline.advance(600)
        wire.queue.put_nowait(TransportEOF())
        await pump()
        assert closing.is_set()
        assert coordinator._connection_hold_until == 900
        # Pending cleanup is not a positive teardown proof. No UI publication
        # is manufactured while the sole supervisor is completing that proof.
        assert not coordinator.snapshot_available
        await timeline.advance(5)
        await push_peers.backoff.entered.get()
        assert coordinator.snapshot_available
        assert coordinator._connection_hold_until == 900
        await timeline.advance(294)
        assert coordinator.snapshot_available
        await timeline.advance(1)
        assert coordinator.snapshot_available
        await timeline.advance(0.001)
        assert not coordinator.snapshot_available
        assert sensor(hass, entry).state == "unavailable"
    finally:
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert_stopped(push_peers)


async def test_rejected_160_probe_keeps_last_values_while_connection_stays_active(
    hass, entry, push_peers, timeline
):
    rejected = b"\x0e" + encode_mbap(65535, 1, b"\x84\x02")
    wire = push_peers.wire(DEVICE_GUID, [[RESPONSE], [rejected]])
    coordinator = await load(hass, entry)
    previous, stamp = coordinator.data, coordinator.last_successful_read_at
    try:
        # This boundary remains under #160; do not turn its failed read-only
        # probe into a fictitious transport outage or a new validated sample.
        wire.queue.put_nowait(BAD)
        await pump()
        assert coordinator.client.data_updated_recovering
        await timeline.advance(30)
        assert coordinator.client.data_updated_transport_alive
        assert coordinator.client.data_updated_recovering
        assert (
            coordinator.client.session_monitor.last_error_category == "modbus_exception"
        )
        assert coordinator.snapshot_available
        assert (
            coordinator.data is previous
            and coordinator.last_successful_read_at == stamp
        )
        assert coordinator._connection_hold_until is None
        assert [c.args[0][0] for c in wire.write.await_args_list] == [3, 13, 13]
        wire.close.assert_not_awaited()
    finally:
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert_stopped(push_peers)
