"""Issue #152: synthetic peers only; concurrent-app causality is not asserted."""

import asyncio
from datetime import timedelta

import pytest
from conftest import DEVICE_GUID, ROTATED_DEVICE_GUID, assert_private_values_absent
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import CoreState
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryError
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.hoben.const import CONF_DEVICE_GUID
from custom_components.hoben.diagnostics import async_get_config_entry_diagnostics
from custom_components.hoben.exceptions import HobenClosedError, HobenProtocolError
from custom_components.hoben.myhoben import CloseClientReason
from custom_components.hoben.transport import (
    TransportCertificateError,
    TransportError,
    TransportTimeout,
)
from custom_components.hoben.v4_lifecycle import LifecycleExhaustedError
from ha_tests.test_persistent_client import RESPONSE, assert_stopped, load, sensor
from ha_tests.test_persistent_client import peers as peers  # noqa: F401
from ha_tests.test_runtime import advance_poll
from tests.tls_script import script_transport


@pytest.mark.parametrize("fragmented", [False, True])
async def test_setup_maintenance_uses_native_ha_retry_and_fresh_client(
    hass, entry, peers, freezer, caplog, fragmented
):
    hass.set_state(CoreState.running)
    first = peers.wire(DEVICE_GUID, [])
    script_transport(
        first, openings=[[b"\x05", b"\x06"] if fragmented else [b"\x05\x06"]]
    )
    peers.wire(ROTATED_DEVICE_GUID, [[RESPONSE]])
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert not hasattr(entry, "runtime_data")
    assert peers.factory.call_count == 1 and not peers.backoff.delays
    assert_stopped(peers)
    # HA, not a new client retry loop, schedules another setup after >=5 s.
    freezer.tick(timedelta(seconds=2))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert peers.factory.call_count == 1
    freezer.tick(timedelta(seconds=10))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.state is ConfigEntryState.LOADED
    assert peers.factory.call_count == 2 and len(peers.lifecycles) == 2
    assert entry.runtime_data.coordinator.last_update_success
    assert sensor(hass, entry).state != "unavailable"
    assert entry.data[CONF_DEVICE_GUID] == ROTATED_DEVICE_GUID
    assert_private_values_absent(caplog.text)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)


async def test_maintenance_refresh_mapping_keeps_normal_poll_cadence(
    hass, entry, client_factory, client, snapshot, caplog
):
    assert await hass.config_entries.async_setup(entry.entry_id)
    coordinator = entry.runtime_data.coordinator
    client.async_refresh.side_effect = [
        HobenClosedError(CloseClientReason.SERVER_MAINTENANCE),
        snapshot,
    ]
    await advance_poll(hass)
    assert isinstance(coordinator.last_exception, UpdateFailed)
    assert not coordinator.last_update_success
    assert sensor(hass, entry).state == "unavailable"
    assert client.async_refresh.await_count == 2  # no immediate replay
    await advance_poll(hass)
    assert coordinator.last_update_success
    assert sensor(hass, entry).state != "unavailable"
    assert client.async_refresh.await_count == 3
    assert_private_values_absent(caplog.text)


async def test_unload_cancels_pending_native_maintenance_setup_retry(
    hass, entry, peers, freezer
):
    hass.set_state(CoreState.running)
    first = peers.wire(DEVICE_GUID, [])
    script_transport(first, openings=[[b"\x05\x06"]])
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert await hass.config_entries.async_unload(entry.entry_id)
    freezer.tick(timedelta(seconds=60))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done(wait_background_tasks=True)
    assert peers.factory.call_count == 1
    assert not hasattr(entry, "runtime_data")
    assert_stopped(peers)


async def test_simulated_concurrent_app_close_during_pending_ha_refresh(
    hass, entry, peers, caplog
):
    first = peers.wire(DEVICE_GUID, [[RESPONSE], []])
    second = peers.wire(ROTATED_DEVICE_GUID, [[RESPONSE[:9], RESPONSE[9:] + b"\x0a"]])
    coordinator = await load(hass, entry)
    previous = coordinator.data
    app_connected = asyncio.Event()

    async def phone_peer():
        # A sideband simulation selects a plausible, documented HA close.
        # No MyHOBEN request or server exclusivity rule is invented here.
        await app_connected.wait()
        first.queue.put_nowait(b"\x05")
        first.queue.put_nowait(b"\x06")

    phone = asyncio.create_task(phone_peer())
    refresh = asyncio.create_task(coordinator.async_refresh())
    while first.write.await_count < 3:
        await asyncio.sleep(0)
    app_connected.set()
    await phone
    await refresh
    assert await peers.backoff.entered.get() == 1.0
    assert not coordinator.last_update_success and coordinator.data is previous
    assert isinstance(coordinator.last_exception, UpdateFailed)
    assert sensor(hass, entry).state == "unavailable"
    assert peers.factory.call_count == 1
    first.close.assert_awaited_once_with()
    peers.backoff.release.put_nowait(None)
    await peers.lifecycles[0].wait_connected()
    assert not coordinator.last_update_success  # opening is not a decoded refresh
    await advance_poll(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert (
        coordinator.last_update_success and sensor(hass, entry).state != "unavailable"
    )
    assert entry.data[CONF_DEVICE_GUID] == ROTATED_DEVICE_GUID
    assert second.write.await_args_list[0].args[0][37:69] == DEVICE_GUID.encode()
    assert all(
        c.args[0][0] in {3, 11, 13}
        for w in peers.wires
        for c in w.write.await_args_list
    )
    assert_private_values_absent(caplog.text)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)


@pytest.mark.parametrize(
    "reply",
    [
        RESPONSE[:1] + b"\x00\x00" + RESPONSE[3:],
        b"\xff",
        RESPONSE + b"\xff",
        bytes.fromhex("0effff0001002b"),  # invalid MBAP protocol id
        TransportTimeout("read"),
    ],
)
async def test_malformed_session_recovers_only_after_cleanup_and_new_read(
    hass, entry, peers, caplog, reply
):
    first = peers.wire(DEVICE_GUID, [[RESPONSE], [reply]])
    second = peers.wire(ROTATED_DEVICE_GUID, [[RESPONSE]])
    coordinator = await load(hass, entry)
    previous = coordinator.data
    await coordinator.async_refresh()
    assert isinstance(coordinator.last_exception, UpdateFailed)
    assert not coordinator.last_update_success and coordinator.data is previous
    assert sensor(hass, entry).state == "unavailable"
    report = await async_get_config_entry_diagnostics(hass, entry)
    assert report["client"]["state"] == "ready"  # object is not explicitly closed
    assert report["coordinator"]["last_error"]["error"] == (
        "timeout" if isinstance(reply, TransportTimeout) else "malformed_response"
    )
    assert await peers.backoff.entered.get() == 1.0
    first.close.assert_awaited_once_with()
    assert peers.factory.call_count == 1
    assert first.write.await_count == 3  # no additional OpenClient/read
    peers.backoff.release.put_nowait(None)
    await peers.lifecycles[0].wait_connected()
    assert not coordinator.last_update_success
    assert second.write.await_count == 1  # opening never replays the failed read
    await advance_poll(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert coordinator.last_update_success
    assert sensor(hass, entry).state != "unavailable"
    assert peers.factory.call_count == 2
    assert entry.data[CONF_DEVICE_GUID] == ROTATED_DEVICE_GUID
    assert_private_values_absent(str(report) + caplog.text)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)


@pytest.mark.parametrize("phase", ["opening", "read"])
async def test_malformed_setup_retries_natively_after_cleanup(
    hass, entry, peers, freezer, phase
):
    hass.set_state(CoreState.running)
    first = peers.wire(DEVICE_GUID, [[b"\xff"]])
    if phase == "opening":
        script_transport(first, openings=[[b"\xff"]])
    peers.wire(ROTATED_DEVICE_GUID, [[RESPONSE]])
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert not hasattr(entry, "runtime_data")
    assert_stopped(peers)
    freezer.tick(timedelta(seconds=2))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert peers.factory.call_count == 1
    freezer.tick(timedelta(seconds=10))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.coordinator.last_update_success
    assert sensor(hass, entry).state != "unavailable"
    assert peers.factory.call_count == 2
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)


async def test_repeated_malformed_errors_exhaust_the_same_two_openings(
    hass, entry, peers
):
    peers.wire(DEVICE_GUID, [[RESPONSE], [b"\xff"]])
    second = peers.wire(ROTATED_DEVICE_GUID, [[b"\xff"]])
    coordinator = await load(hass, entry)
    await coordinator.async_refresh()
    await peers.backoff.entered.get()
    peers.backoff.release.put_nowait(None)
    lifecycle = peers.lifecycles[0]
    await lifecycle.wait_connected()
    await coordinator.async_refresh()
    with pytest.raises(LifecycleExhaustedError):
        await lifecycle.wait_stopped()
    for _ in range(3):
        await coordinator.async_refresh()
    assert not coordinator.last_update_success
    assert sensor(hass, entry).state == "unavailable"
    assert peers.factory.call_count == 2 and peers.backoff.delays == [1.0]
    assert second.write.await_count == 2  # opening + one new scheduled read
    report = await async_get_config_entry_diagnostics(hass, entry)
    assert report["coordinator"]["last_error"] == {
        "error": "refresh_exhausted",
        "attempts": 2,
        "failure": "malformed_response",
    }
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)


@pytest.mark.parametrize("phase", ["opening", "refresh"])
@pytest.mark.parametrize(
    "failure, wrapper, code",
    [
        (RuntimeError("PRIVATE-PAYLOAD"), ConfigEntryError, "internal_failure"),
        (
            TransportCertificateError("PRIVATE-PAYLOAD"),
            ConfigEntryError,
            "tls_verification_failed",
        ),
        (b"\x05\x02", ConfigEntryAuthFailed, "server_closed"),
        (b"\x05\x04", ConfigEntryAuthFailed, "server_closed"),
        (b"\x05\x05", ConfigEntryAuthFailed, "server_closed"),
    ],
)
async def test_permanent_failures_never_reconnect(
    hass, entry, peers, caplog, phase, failure, wrapper, code
):
    wire = peers.wire(DEVICE_GUID, [[RESPONSE], [failure]])
    if phase == "opening":
        script_transport(wire, openings=[[failure]])
        assert not await hass.config_entries.async_setup(entry.entry_id)
        assert entry.state is ConfigEntryState.SETUP_ERROR
    else:
        coordinator = await load(hass, entry)
        await coordinator.async_refresh()
        assert isinstance(coordinator.last_exception, wrapper)
        report = await async_get_config_entry_diagnostics(hass, entry)
        if code == "server_closed":
            code = "experimental_close_client"
        assert report["coordinator"]["last_error"]["error"] == code
        assert await hass.config_entries.async_unload(entry.entry_id)
    assert peers.backoff.delays == [] and peers.factory.call_count == 1
    assert "PRIVATE-PAYLOAD" not in caplog.text
    assert_stopped(peers)


async def test_unload_cancels_malformed_backoff_and_a_waiting_refresh(
    hass, entry, peers
):
    peers.wire(DEVICE_GUID, [[RESPONSE], [b"\xff"]])
    coordinator = await load(hass, entry)
    await coordinator.async_refresh()
    await peers.backoff.entered.get()
    pending = asyncio.create_task(coordinator.async_refresh())
    # Wait until the actual client owns this second caller, waiting for recovery.
    while entry.runtime_data.client._active_operation is not pending:
        await asyncio.sleep(0)
    assert await hass.config_entries.async_unload(entry.entry_id)
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert peers.factory.call_count == 1
    assert_stopped(peers)


async def test_failed_cleanup_forbids_recovery_after_malformed(hass, entry, peers):
    first = peers.wire(DEVICE_GUID, [[RESPONSE], [b"\xff"]])
    coordinator = await load(hass, entry)
    first.close.side_effect = TransportError("PRIVATE-PAYLOAD")
    await coordinator.async_refresh()
    with pytest.raises(HobenProtocolError):
        await peers.lifecycles[0].wait_stopped()
    await coordinator.async_refresh()
    assert peers.factory.call_count == 1 and peers.backoff.delays == []
    assert not coordinator.last_update_success
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)
