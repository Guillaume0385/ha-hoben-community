"""Real session diagnostics on in-memory TLS; no Hoben network access."""

import asyncio
from datetime import timedelta
from unittest.mock import Mock, patch

import pytest
from conftest import DEVICE_GUID, assert_private_values_absent
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.hoben import HobenRuntimeData
from custom_components.hoben.client import HobenClient
from custom_components.hoben.coordinator import HobenDataUpdateCoordinator
from custom_components.hoben.session_monitor import SessionEvent
from custom_components.hoben.session_sensor import HobenSessionSensor
from custom_components.hoben.transport import TransportCertificateError, TransportEOF
from custom_components.hoben.v4_state import V4DecodeError
from ha_tests.test_persistent_client import RESPONSE, assert_stopped, load
from ha_tests.test_persistent_client import peers as peers  # noqa: F401
from tests.test_data_updated_silence import BAD, Clock, pump


def session_state(hass, entry):
    registered = [
        e
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        if e.unique_id == f"{entry.unique_id}_session"
    ]
    assert len(registered) == 1
    return hass.states.get(registered[0].entity_id)


def measures(hass, entry):
    return {
        e.entity_id: hass.states.get(e.entity_id)
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        if e.unique_id != f"{entry.unique_id}_session" and hass.states.get(e.entity_id)
    }


async def test_one_native_diagnostic_entity_reports_the_actual_session(
    hass, entry, peers
):
    wire = peers.wire(DEVICE_GUID, [[RESPONSE]])
    coordinator = await load(hass, entry)
    try:
        state = session_state(hass, entry)
        assert state.entity_id == "sensor.hoben_stove_session"
        assert state.state == "connected"
        registered = er.async_get(hass).async_get(state.entity_id)
        assert registered.entity_category.value == "diagnostic"
        assert state.attributes["options"] == [
            "connected",
            "recovering",
            "reconnecting",
            "disconnected",
        ]
        assert set(state.attributes) == {
            "last_error_category",
            "last_error_phase",
            "last_error_at",
            "last_successful_read_at",
            "last_successful_read_age",
            "reconnect_count",
            "recovery_count",
            "options",
            "device_class",
            "friendly_name",
        }
        assert state.attributes["last_error_category"] is None
        assert (
            state.attributes["last_successful_read_at"]
            == coordinator.last_successful_read_at.isoformat()
        )
        assert state.attributes["reconnect_count"] == 0
        assert state.attributes["recovery_count"] == 0
        assert wire.write.await_count == 2
    finally:
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert_stopped(peers)


async def test_eof_and_reopening_update_session_without_refreshing_measurements(
    hass, entry, peers, caplog
):
    first = peers.wire(DEVICE_GUID, [[RESPONSE]])
    peers.wire(DEVICE_GUID, [[RESPONSE[:10] + b"\x00\x13" * 20]])
    coordinator = await load(hass, entry)
    previous, stamp, before = (
        coordinator.data,
        coordinator.last_successful_read_at,
        measures(hass, entry),
    )
    listener = Mock()
    unsubscribe = coordinator.async_add_listener(listener)
    try:
        first.queue.put_nowait(TransportEOF("PRIVATE_PAYLOAD"))
        assert await peers.backoff.entered.get() == 60
        await pump()
        state = session_state(hass, entry)
        assert state.state == "reconnecting"
        assert state.attributes["last_error_category"] == "transport_unavailable"
        assert state.attributes["last_error_phase"] is None
        assert state.attributes["last_error_at"] is not None
        assert state.attributes["reconnect_count"] == 0
        assert state.attributes["recovery_count"] == 0
        assert all(measures(hass, entry)[k] is v for k, v in before.items())
        listener.assert_not_called()
        peers.backoff.release.put_nowait(None)
        await peers.lifecycles[0].wait_connected()
        await pump()
        state = session_state(hass, entry)
        assert state.state == "connected" and state.attributes["reconnect_count"] == 1
        assert (
            coordinator.data is previous
            and coordinator.last_successful_read_at == stamp
        )
        listener.assert_not_called()
        await coordinator.async_refresh()
        assert coordinator.data.raw.registers == (19,) * 20
        assert_private_values_absent(str(state.attributes) + caplog.text)
    finally:
        unsubscribe()
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert_stopped(peers)


async def test_data_updated_recovery_is_visible_before_any_measurement_poll(
    hass, entry, peers, monkeypatch
):
    wire = peers.wire(DEVICE_GUID, [[RESPONSE], [RESPONSE[:10] + b"\x00\x13" * 20]])
    coordinator = await load(hass, entry)
    previous, stamp, before = (
        coordinator.data,
        coordinator.last_successful_read_at,
        measures(hass, entry),
    )
    clock = Clock(monkeypatch)
    wire.queue.put_nowait(BAD)
    await pump()
    state = session_state(hass, entry)
    assert state.state == "recovering"
    assert state.attributes["recovery_count"] == 1
    assert state.attributes["last_error_category"] == "malformed_response"
    assert state.attributes["last_error_phase"] == "mbap_header"
    assert wire.write.await_count == 2
    assert all(measures(hass, entry)[k] is v for k, v in before.items())
    await clock.advance(29)
    assert wire.write.await_count == 2
    await clock.advance(1)
    state = session_state(hass, entry)
    assert state.state == "connected" and state.attributes["recovery_count"] == 1
    assert coordinator.data is previous and coordinator.last_successful_read_at == stamp
    assert wire.write.await_count == 3
    await coordinator.async_refresh()
    assert coordinator.data.raw.registers == (19,) * 20
    assert wire.write.await_count == 3  # A2 never adds a read.
    wire.queue.put_nowait(BAD)
    await pump()
    assert session_state(hass, entry).attributes["recovery_count"] == 2
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)


async def test_pending_polls_do_not_increment_episode_count_or_error_date(
    hass, entry, peers
):
    peers.wire(DEVICE_GUID, [[RESPONSE], [b"\xff"]])
    coordinator = await load(hass, entry)
    before = measures(hass, entry)
    await coordinator.async_refresh()
    assert await peers.backoff.entered.get() == 60
    await pump()
    state = session_state(hass, entry)
    assert state.state == "reconnecting" and state.attributes["recovery_count"] == 1
    error_at = state.attributes["last_error_at"]
    for _ in range(3):
        await coordinator.async_refresh()
        await pump()
    state = session_state(hass, entry)
    assert state.attributes["recovery_count"] == 1
    assert state.attributes["reconnect_count"] == 0
    assert state.attributes["last_error_at"] == error_at
    assert all(measures(hass, entry)[k] is v for k, v in before.items())
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)


async def test_rejected_data_updated_probe_updates_error_without_a_new_episode(
    hass, entry, peers, monkeypatch
):
    wire = peers.wire(
        DEVICE_GUID,
        [[RESPONSE], [bytes.fromhex("0effff00000003018402")], [RESPONSE]],
    )
    coordinator = await load(hass, entry)
    stamp, before = coordinator.last_successful_read_at, measures(hass, entry)
    clock = Clock(monkeypatch)
    wire.queue.put_nowait(BAD)
    await pump()
    await clock.advance(30)
    state = session_state(hass, entry)
    assert state.state == "recovering"
    assert state.attributes["last_error_category"] == "modbus_exception"
    assert state.attributes["last_error_phase"] is None
    assert state.attributes["recovery_count"] == 1
    assert state.attributes["reconnect_count"] == 0
    assert coordinator.last_successful_read_at == stamp
    assert all(measures(hass, entry)[k] is v for k, v in before.items())
    await clock.advance(30)
    assert session_state(hass, entry).state == "connected"
    assert session_state(hass, entry).attributes["recovery_count"] == 1
    assert peers.factory.call_count == 1 and wire.write.await_count == 4
    assert coordinator.last_successful_read_at == stamp
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)


@pytest.mark.parametrize("initial", [False, True])
async def test_model_rejection_is_one_recovery_episode_even_without_a_snapshot(
    hass, entry, peers, initial, caplog
):
    wire = peers.wire(DEVICE_GUID, [[RESPONSE]] * (3 if initial else 4))
    if initial:
        client = HobenClient(entry.data["user_guid"], DEVICE_GUID, ha_reconnect=True)
        coordinator = HobenDataUpdateCoordinator(hass, entry, client)
        entry.runtime_data = HobenRuntimeData(client, coordinator)
    else:
        coordinator = await load(hass, entry)
    entity = HobenSessionSensor(entry)
    before, stamp, previous = (
        measures(hass, entry),
        coordinator.last_successful_read_at,
        coordinator.data,
    )
    with patch(
        "custom_components.hoben.coordinator.decode_v4_snapshot",
        side_effect=V4DecodeError(),
    ):
        for _ in range(2):
            await coordinator.async_refresh()
            await pump()
            assert entity.native_value == "recovering"
            assert entity.extra_state_attributes["recovery_count"] == 1
            assert (
                entity.extra_state_attributes["last_error_category"]
                == "invalid_v4_snapshot"
            )
            assert coordinator.last_successful_read_at == stamp
            assert coordinator.data is previous and not coordinator.last_update_success
            assert all(measures(hass, entry)[k] is v for k, v in before.items())
            if not initial:
                assert session_state(hass, entry).state == "recovering"
    await coordinator.async_refresh()
    await pump()
    assert entity.native_value == "connected"
    assert entity.extra_state_attributes["recovery_count"] == 1
    assert coordinator.last_update_success and coordinator.data is not previous
    assert peers.factory.call_count == 1 and wire.write.await_count == (
        4 if initial else 5
    )
    assert_private_values_absent(str(entity.extra_state_attributes) + caplog.text)
    if initial:
        await coordinator.async_shutdown()
        await coordinator.client.async_close()
    else:
        assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)


async def test_first_read_failure_then_failed_open_never_invents_a_reconnect(
    hass, entry, peers
):
    peers.wire(DEVICE_GUID, [[b"\xff"]])
    second = peers.wire(DEVICE_GUID, [])
    second.connect.side_effect = TransportCertificateError("PRIVATE_PAYLOAD")
    client = HobenClient(entry.data["user_guid"], DEVICE_GUID, ha_reconnect=True)
    coordinator = HobenDataUpdateCoordinator(hass, entry, client)
    entry.runtime_data = HobenRuntimeData(client, coordinator)
    entity = HobenSessionSensor(entry)
    await coordinator.async_refresh()
    assert await peers.backoff.entered.get() == 60
    assert entity.native_value == "reconnecting"
    assert entity.extra_state_attributes["recovery_count"] == 1
    assert entity.extra_state_attributes["last_successful_read_at"] is None
    assert entity.extra_state_attributes["last_successful_read_age"] is None
    peers.backoff.release.put_nowait(None)
    await pump()
    assert entity.native_value == "disconnected"
    assert entity.extra_state_attributes["reconnect_count"] == 0
    assert (
        entity.extra_state_attributes["last_error_category"]
        == "tls_verification_failed"
    )
    assert peers.backoff.delays == [60] and peers.factory.call_count == 2
    assert coordinator.data is None and not coordinator.last_update_success
    await coordinator.async_shutdown()
    await client.async_close()
    assert_stopped(peers)


@pytest.mark.parametrize(
    "failure,category",
    [
        (b"\x05\x02", "experimental_close_client"),
        (TransportCertificateError("PRIVATE_PAYLOAD"), "tls_verification_failed"),
    ],
)
async def test_permanent_failure_is_visible_as_disconnected_not_unavailable_diagnostic(
    hass, entry, peers, failure, category, caplog
):
    peers.wire(DEVICE_GUID, [[RESPONSE], [failure]])
    coordinator = await load(hass, entry)
    await coordinator.async_refresh()
    await pump()
    state = session_state(hass, entry)
    assert state.state == "disconnected"
    assert state.attributes["last_error_category"] == category
    assert (
        state.attributes["reconnect_count"] == state.attributes["recovery_count"] == 0
    )
    assert all(s.state == "unavailable" for s in measures(hass, entry).values())
    assert_private_values_absent(str(state.attributes) + caplog.text)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)


async def test_age_timer_only_updates_local_diagnostic_metadata(
    hass, entry, peers, freezer
):
    wire = peers.wire(DEVICE_GUID, [[RESPONSE]])
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()  # Isolate the diagnostic's own local timer.
    before, stamp = measures(hass, entry), coordinator.last_successful_read_at
    freezer.tick(timedelta(seconds=61))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert session_state(hass, entry).attributes["last_successful_read_age"] == 61
    assert coordinator.last_successful_read_at == stamp and wire.write.await_count == 2
    assert all(measures(hass, entry)[k] is v for k, v in before.items())
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)


async def test_no_initial_snapshot_and_cancellation_never_invent_freshness(
    hass, entry, peers
):
    wire = peers.wire(DEVICE_GUID, [[]])
    client = HobenClient(entry.data["user_guid"], DEVICE_GUID, ha_reconnect=True)
    coordinator = HobenDataUpdateCoordinator(hass, entry, client)
    entry.runtime_data = HobenRuntimeData(client, coordinator)
    entity = HobenSessionSensor(entry)
    assert entity.native_value == "disconnected"
    assert entity.extra_state_attributes["last_successful_read_age"] is None
    refresh = asyncio.create_task(coordinator.async_refresh())
    await pump()
    assert wire.write.await_count == 2 and not refresh.done()
    assert entity.native_value == "connected"  # Opening alone says nothing about age.
    assert entity.extra_state_attributes["last_successful_read_at"] is None
    refresh.cancel()
    with pytest.raises(asyncio.CancelledError):
        await refresh
    assert entity.native_value == "disconnected"
    assert entity.extra_state_attributes["reconnect_count"] == 0
    await coordinator.async_shutdown()
    await client.async_close()
    assert_stopped(peers)


async def test_unload_cancels_queued_callbacks_timer_and_late_events(
    hass, entry, peers, freezer
):
    peers.wire(DEVICE_GUID, [[RESPONSE]])
    coordinator = await load(hass, entry)
    monitor = coordinator.client.session_monitor
    entity_id = session_state(hass, entry).entity_id
    monitor.emit()  # A callback is queued exactly when unload begins.
    assert await hass.config_entries.async_unload(entry.entry_id)
    before = hass.states.get(entity_id)
    count = monitor.recovery_count
    monitor.emit(SessionEvent("recovery", "malformed_response", "mbap_header"))
    freezer.tick(timedelta(seconds=120))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert hass.states.get(entity_id) is before
    assert not monitor._listeners and monitor.recovery_count == count
    assert_stopped(peers)
