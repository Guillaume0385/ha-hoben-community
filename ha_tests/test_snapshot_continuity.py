"""Actual HA entities/coordinator/lifecycle; byte peers and clocks stay offline."""

import asyncio
from datetime import timedelta
from unittest.mock import Mock, patch

import pytest
from conftest import DEVICE_GUID, assert_private_values_absent
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from custom_components.hoben.client import HobenClient
from custom_components.hoben.coordinator import HobenDataUpdateCoordinator
from custom_components.hoben.diagnostics import async_get_config_entry_diagnostics
from custom_components.hoben.transport import (
    TransportCertificateError,
    TransportEOF,
    TransportTimeout,
    TransportTlsError,
)
from custom_components.hoben.v4_state import V4DecodeError
from ha_tests.test_persistent_client import RESPONSE, assert_stopped, load
from ha_tests.test_persistent_client import peers as peers  # noqa: F401
from tests.test_data_updated_silence import pump


def states(hass, entry):
    return {
        e.entity_id: hass.states.get(e.entity_id)
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        if hass.states.get(e.entity_id) is not None
        and e.unique_id != f"{entry.unique_id}_session"
    }


@pytest.mark.parametrize("failure", ["malformed_response", "timeout", "decode"])
async def test_validated_snapshot_survives_acquisition_error_without_fake_refresh(
    hass, entry, peers, freezer, caplog, failure
):
    fresh = RESPONSE[:10] + b"\x00\x13" * 20
    if failure == "decode":
        peers.wire(DEVICE_GUID, [[RESPONSE], [RESPONSE], [fresh]])
    else:
        bad = (
            RESPONSE[:1] + b"\x00\x00" + RESPONSE[3:]
            if failure == "malformed_response"
            else TransportTimeout("PRIVATE_PAYLOAD")
        )
        peers.wire(DEVICE_GUID, [[RESPONSE], [bad]])
        peers.wire(DEVICE_GUID, [[fresh]])
    coordinator = await load(hass, entry)
    previous = coordinator.data
    before = states(hass, entry)
    assert before and all(s.state != "unavailable" for s in before.values())
    listener = Mock()
    unsubscribe = coordinator.async_add_listener(listener)
    try:
        freezer.tick(timedelta(seconds=20))
        if failure == "decode":
            with patch(
                "custom_components.hoben.coordinator.decode_v4_snapshot",
                side_effect=V4DecodeError(),
            ):
                await coordinator.async_refresh()
        else:
            await coordinator.async_refresh()
            assert await peers.backoff.entered.get() == 60
        assert not coordinator.last_update_success
        assert coordinator.data is previous
        after = states(hass, entry)
        assert all(after[key] is state for key, state in before.items())
        listener.assert_not_called()
        report = await async_get_config_entry_diagnostics(hass, entry)
        assert report["coordinator"]["last_error"]["error"] == (
            "invalid_v4_snapshot" if failure == "decode" else failure
        )
        assert report["coordinator"]["last_successful_read_age"] == 20
        stamp = coordinator.last_successful_read_at
        freezer.tick(timedelta(seconds=40))
        assert coordinator.last_successful_read_at == stamp
        report = await async_get_config_entry_diagnostics(hass, entry)
        assert report["coordinator"]["last_successful_read_age"] == 60
        if failure != "decode":
            peers.backoff.release.put_nowait(None)
            await peers.lifecycles[0].wait_connected()
        await coordinator.async_refresh()
        assert coordinator.last_update_success and coordinator.data is not previous
        assert coordinator.data.raw.registers == (19,) * 20
        assert coordinator.last_successful_read_at == dt_util.utcnow()
        listener.assert_called_once_with()
        assert all(s.state != "unavailable" for s in states(hass, entry).values())
        assert_private_values_absent(str(report) + caplog.text)
    finally:
        unsubscribe()
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert_stopped(peers)


async def start_protocol_hold(hass, entry, peers):
    bad = RESPONSE[:1] + b"\x00\x00" + RESPONSE[3:]
    peers.wire(DEVICE_GUID, [[RESPONSE], [bad]])
    coordinator = await load(hass, entry)
    await coordinator.async_refresh()
    assert await peers.backoff.entered.get() == 60
    assert coordinator.last_snapshot_held and not coordinator.last_update_success
    return coordinator


@pytest.mark.parametrize("failure", ["transport", "certificate", "authentication"])
async def test_later_open_failure_cannot_hide_behind_previous_acquisition_hold(
    hass, entry, peers, failure, caplog
):
    coordinator = await start_protocol_hold(hass, entry, peers)
    previous, stamp = coordinator.data, coordinator.last_successful_read_at
    wire = peers.wire(DEVICE_GUID, [])
    if failure == "authentication":
        from tests.tls_script import script_transport

        wire.queue = script_transport(wire, openings=[[b"\x05\x02"]])
    else:
        wire.connect.side_effect = (
            TransportTlsError("PRIVATE_PAYLOAD")
            if failure == "transport"
            else TransportCertificateError("PRIVATE_PAYLOAD")
        )
    peers.backoff.release.put_nowait(None)
    if failure == "transport":
        assert await peers.backoff.entered.get() == 60
    else:
        await pump()
    assert not coordinator.last_snapshot_held
    refresh = asyncio.create_task(coordinator.async_refresh())
    await pump()
    assert refresh.done()  # The coordinator never waits forever through an outage.
    await refresh
    assert coordinator.data is previous and not coordinator.last_update_success
    assert coordinator.last_successful_read_at == stamp
    assert all(s.state == "unavailable" for s in states(hass, entry).values())
    assert peers.factory.call_count == 2
    assert peers.backoff.delays == ([60, 60] if failure == "transport" else [60])
    assert_private_values_absent(caplog.text)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)


async def test_cancellation_during_read_ends_hold_and_preserves_last_validated_data(
    hass, entry, peers
):
    coordinator = await start_protocol_hold(hass, entry, peers)
    previous, stamp = coordinator.data, coordinator.last_successful_read_at
    wire = peers.wire(DEVICE_GUID, [[]])
    peers.backoff.release.put_nowait(None)
    await peers.lifecycles[0].wait_connected()
    refresh = asyncio.create_task(coordinator.async_refresh())
    await pump()
    assert wire.write.await_count == 2 and not refresh.done()
    refresh.cancel()
    with pytest.raises(asyncio.CancelledError):
        await refresh
    assert not coordinator.last_snapshot_held and not coordinator.last_update_success
    assert coordinator.data is previous and coordinator.last_successful_read_at == stamp
    assert all(s.state == "unavailable" for s in states(hass, entry).values())
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)


async def test_explicit_shutdown_ends_hold_without_a_new_read(hass, entry, peers):
    coordinator = await start_protocol_hold(hass, entry, peers)
    previous, stamp = coordinator.data, coordinator.last_successful_read_at
    count = peers.factory.call_count
    await coordinator.async_shutdown()
    await coordinator.client.async_close()
    assert not coordinator.snapshot_available
    assert coordinator.data is previous and coordinator.last_successful_read_at == stamp
    assert all(s.state == "unavailable" for s in states(hass, entry).values())
    assert peers.factory.call_count == count
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)


async def test_initial_failure_cannot_create_a_snapshot_or_an_available_entity(
    hass, entry, peers
):
    peers.wire(DEVICE_GUID, [[RESPONSE[:1] + b"\x00\x00" + RESPONSE[3:]]])
    client = HobenClient(entry.data["user_guid"], DEVICE_GUID, ha_reconnect=True)
    coordinator = HobenDataUpdateCoordinator(hass, entry, client)
    try:
        await coordinator.async_refresh()
        assert await peers.backoff.entered.get() == 60
        assert coordinator.data is None and coordinator.last_successful_read_at is None
        assert not coordinator.last_snapshot_held and not coordinator.snapshot_available
        assert states(hass, entry) == {}
    finally:
        await coordinator.async_shutdown()
        await client.async_close()
        assert_stopped(peers)


async def test_real_idle_eof_during_hold_marks_entities_unavailable_at_next_poll(
    hass, entry, peers
):
    coordinator = await start_protocol_hold(hass, entry, peers)
    previous, stamp = coordinator.data, coordinator.last_successful_read_at
    wire = peers.wire(DEVICE_GUID, [])
    peers.backoff.release.put_nowait(None)
    await peers.lifecycles[0].wait_connected()
    wire.queue.put_nowait(TransportEOF("PRIVATE_PAYLOAD"))
    assert await peers.backoff.entered.get() == 60
    await coordinator.async_refresh()
    assert not coordinator.last_snapshot_held and not coordinator.last_update_success
    assert coordinator.data is previous and coordinator.last_successful_read_at == stamp
    assert all(s.state == "unavailable" for s in states(hass, entry).values())
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)


async def test_identical_valid_read_advances_freshness_without_inventing_state_changes(
    hass, entry, peers, freezer
):
    peers.wire(DEVICE_GUID, [[RESPONSE], [RESPONSE]])
    coordinator = await load(hass, entry)
    before = states(hass, entry)
    stamp = coordinator.last_successful_read_at
    freezer.tick(timedelta(seconds=30))
    await coordinator.async_refresh()
    assert coordinator.last_successful_read_at == stamp + timedelta(seconds=30)
    assert coordinator.last_update_success and not coordinator.last_snapshot_held
    after = states(hass, entry)
    assert all(after[key] is state for key, state in before.items())
    report = await async_get_config_entry_diagnostics(hass, entry)
    assert report["coordinator"]["last_successful_read_age"] == 0
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)
