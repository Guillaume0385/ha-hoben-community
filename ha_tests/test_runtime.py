"""Real config entries, coordinator timers, device registry and unload/reload."""

import asyncio
import traceback
from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest
from conftest import (
    DEVICE_GUID,
    NORMALIZED_USER_GUID,
    PRIVATE_TEXT,
    ROTATED_DEVICE_GUID,
    assert_private_values_absent,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.hoben import HobenRuntimeData
from custom_components.hoben.client import HobenClient, RawStoveSnapshot
from custom_components.hoben.const import CONF_DEVICE_GUID, CONF_USER_GUID, DOMAIN
from custom_components.hoben.coordinator import HobenDataUpdateCoordinator
from custom_components.hoben.exceptions import (
    HobenAmbiguousSessionError,
    HobenAuthorizationRequiredError,
    HobenInvalidCredentialsError,
    HobenInvalidInputError,
    HobenModbusError,
    HobenProtocolError,
    HobenRefreshExhaustedError,
    HobenTimeoutError,
    HobenTransportError,
    HobenUnsupportedProfileError,
)
from custom_components.hoben.helpers import user_guid_fingerprint
from custom_components.hoben.myhoben import INITIAL_DEVICE_GUID, CloseClientReason
from custom_components.hoben.profiles import StoveProfile


async def load_entry(hass, entry):
    """Go through HA's complete config-entry setup instead of calling it directly."""
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry.runtime_data.coordinator


async def advance_poll(hass):
    """Fire monotonic coordinator timers deterministically, without wall-clock sleep."""
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()


async def test_setup_runtime_and_safe_device(
    hass, entry, client_factory, client, snapshot, caplog
):
    with caplog.at_level("DEBUG"):
        coordinator = await load_entry(hass, entry)
    client_factory.assert_called_once_with(
        user_guid=NORMALIZED_USER_GUID, device_guid=DEVICE_GUID
    )
    client.async_refresh.assert_awaited_once_with()
    assert isinstance(entry.runtime_data, HobenRuntimeData)
    assert entry.runtime_data.client is client
    assert entry.runtime_data.coordinator is coordinator
    assert isinstance(coordinator, HobenDataUpdateCoordinator)
    assert coordinator.data is snapshot
    assert isinstance(coordinator.data, RawStoveSnapshot)
    assert coordinator.update_interval == timedelta(seconds=60)

    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert len(devices) == 1
    device = devices[0]
    assert device.identifiers == {(DOMAIN, user_guid_fingerprint(NORMALIZED_USER_GUID))}
    assert device.config_entry_id == entry.entry_id
    assert device.manufacturer == "Hoben"
    assert device.name == "Hoben stove"
    assert device.model == "Protocol V4"
    assert device.sw_version == "8.2"
    assert "Osmose" not in device.model
    assert not er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    assert_private_values_absent(
        caplog.text + repr(device) + repr(coordinator) + repr(entry.runtime_data)
    )


async def test_polling_without_entities_and_unload_stops_timers(
    hass, entry, client_factory, client
):
    coordinator = await load_entry(hass, entry)
    await advance_poll(hass)
    assert client.async_refresh.await_count == 2
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert not hasattr(entry, "runtime_data")
    client.async_close.assert_awaited_once_with()
    await advance_poll(hass)
    assert client.async_refresh.await_count == 2
    assert not coordinator._listeners


async def test_unchanged_identity_does_not_update_entry(
    hass, entry, client_factory, client
):
    with patch.object(
        hass.config_entries,
        "async_update_entry",
        wraps=hass.config_entries.async_update_entry,
    ) as update:
        coordinator = await load_entry(hass, entry)
        await coordinator.async_refresh()
    update.assert_not_called()
    assert client.async_refresh.await_count == 2


async def test_rotation_changes_only_device_field(
    hass, entry, client_factory, client, caplog
):
    coordinator = await load_entry(hass, entry)
    old_data = dict(entry.data)
    old_options = dict(entry.options)
    old_unique_id = entry.unique_id
    client.device_guid_for_persistence = ROTATED_DEVICE_GUID
    with (
        caplog.at_level("DEBUG"),
        patch.object(
            hass.config_entries,
            "async_update_entry",
            wraps=hass.config_entries.async_update_entry,
        ) as update,
    ):
        await coordinator.async_refresh()
        await coordinator.async_refresh()
    update.assert_called_once_with(
        entry, data={**old_data, CONF_DEVICE_GUID: ROTATED_DEVICE_GUID}
    )
    assert entry.data == {**old_data, CONF_DEVICE_GUID: ROTATED_DEVICE_GUID}
    assert entry.options == old_options
    assert entry.unique_id == old_unique_id
    assert entry.title == "Hoben"
    assert_private_values_absent(caplog.text)


async def test_first_refresh_can_persist_rotation(hass, entry, client_factory, client):
    client.device_guid_for_persistence = ROTATED_DEVICE_GUID
    await load_entry(hass, entry)
    assert entry.data[CONF_DEVICE_GUID] == ROTATED_DEVICE_GUID


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (HobenTransportError(), UpdateFailed),
        (HobenTimeoutError(), UpdateFailed),
        (HobenRefreshExhaustedError(2, HobenTimeoutError()), UpdateFailed),
        (
            HobenInvalidCredentialsError(CloseClientReason.INVALID_IDENTIFIER),
            ConfigEntryAuthFailed,
        ),
        (HobenAuthorizationRequiredError(), ConfigEntryAuthFailed),
        (HobenUnsupportedProfileError(StoveProfile.V6), ConfigEntryError),
        (HobenProtocolError(), ConfigEntryError),
        (HobenAmbiguousSessionError(), ConfigEntryError),
        (HobenModbusError(2), ConfigEntryError),
        (RuntimeError(PRIVATE_TEXT), ConfigEntryError),
    ],
)
async def test_runtime_error_mapping_is_sanitized_without_extra_retry_or_persistence(
    hass, entry, client_factory, client, snapshot, caplog, error, expected
):
    coordinator = await load_entry(hass, entry)
    error.__cause__ = ValueError(PRIVATE_TEXT)
    client.async_refresh.side_effect = error
    # Even a client that adopted an identity before a failed read is not persisted.
    client.device_guid_for_persistence = ROTATED_DEVICE_GUID
    with caplog.at_level("DEBUG"):
        await coordinator.async_refresh()
    assert not coordinator.last_update_success
    assert isinstance(coordinator.last_exception, expected)
    assert coordinator.data is snapshot
    assert client.async_refresh.await_count == 2
    assert entry.data[CONF_DEVICE_GUID] == DEVICE_GUID
    assert_private_values_absent(
        caplog.text + "".join(traceback.format_exception(coordinator.last_exception))
    )


async def test_transient_failure_recovers(
    hass, entry, client_factory, client, snapshot
):
    coordinator = await load_entry(hass, entry)
    client.async_refresh.side_effect = [HobenTransportError(), snapshot]
    await advance_poll(hass)
    assert not coordinator.last_update_success
    assert client.async_refresh.await_count == 2
    await advance_poll(hass)
    assert coordinator.last_update_success
    assert coordinator.data is snapshot
    assert client.async_refresh.await_count == 3


async def test_authentication_failure_stops_polling(
    hass, entry, client_factory, client
):
    coordinator = await load_entry(hass, entry)
    client.async_refresh.side_effect = HobenAuthorizationRequiredError()
    await coordinator.async_refresh()
    assert isinstance(coordinator.last_exception, ConfigEntryAuthFailed)
    await advance_poll(hass)
    assert client.async_refresh.await_count == 2


@pytest.mark.parametrize(
    ("error", "expected_state"),
    [
        (HobenTransportError(), ConfigEntryState.SETUP_RETRY),
        (HobenTimeoutError(), ConfigEntryState.SETUP_RETRY),
        (HobenAuthorizationRequiredError(), ConfigEntryState.SETUP_ERROR),
        (
            HobenInvalidCredentialsError(CloseClientReason.INVALID_IDENTIFIER),
            ConfigEntryState.SETUP_ERROR,
        ),
        (
            HobenUnsupportedProfileError(StoveProfile.UNKNOWN),
            ConfigEntryState.SETUP_ERROR,
        ),
        (HobenProtocolError(), ConfigEntryState.SETUP_ERROR),
        (HobenModbusError(2), ConfigEntryState.SETUP_ERROR),
        (RuntimeError(PRIVATE_TEXT), ConfigEntryState.SETUP_ERROR),
    ],
)
async def test_first_refresh_failure_cleans_up_and_uses_correct_setup_state(
    hass, entry, client_factory, client, caplog, error, expected_state
):
    client.async_refresh.side_effect = error
    with caplog.at_level("DEBUG"):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is expected_state
    assert not hasattr(entry, "runtime_data")
    client.async_refresh.assert_awaited_once_with()
    client.async_close.assert_awaited_once_with()
    assert not dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert_private_values_absent(caplog.text)
    entry.async_cancel_retry_setup()


@pytest.mark.parametrize("profile", [StoveProfile.V6, StoveProfile.UNKNOWN])
async def test_unsupported_snapshot_is_fatal_and_sanitized(
    hass, entry, client_factory, client, snapshot, profile
):
    client.async_refresh.return_value = replace(snapshot, profile=profile)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    client.async_close.assert_awaited_once_with()


async def test_zero_assignment_never_persisted(hass, entry, client_factory, client):
    client.device_guid_for_persistence = INITIAL_DEVICE_GUID
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert entry.data[CONF_DEVICE_GUID] == DEVICE_GUID
    client.async_close.assert_awaited_once_with()


async def test_invalid_stored_identity_is_fatal(hass, entry, client_factory, caplog):
    client_factory.side_effect = HobenInvalidInputError()
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert_private_values_absent(caplog.text)


async def test_unknown_constructor_error_is_sanitized(
    hass, entry, client_factory, caplog
):
    client_factory.side_effect = RuntimeError(PRIVATE_TEXT)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert_private_values_absent(caplog.text)


async def test_device_registration_failure_closes_and_is_sanitized(
    hass, entry, client_factory, client, monkeypatch, caplog
):
    monkeypatch.setattr(
        dr.async_get(hass),
        "async_get_or_create",
        Mock(side_effect=RuntimeError(PRIVATE_TEXT)),
    )
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert not hasattr(entry, "runtime_data")
    client.async_close.assert_awaited_once_with()
    assert_private_values_absent(caplog.text)


async def test_storage_failure_does_not_disclose_identity(
    hass, entry, client_factory, client, monkeypatch, caplog
):
    coordinator = await load_entry(hass, entry)
    client.device_guid_for_persistence = ROTATED_DEVICE_GUID
    monkeypatch.setattr(
        hass.config_entries,
        "async_update_entry",
        Mock(side_effect=RuntimeError(PRIVATE_TEXT)),
    )
    await coordinator.async_refresh()
    assert not coordinator.last_update_success
    assert isinstance(coordinator.last_exception, ConfigEntryError)
    assert entry.data[CONF_DEVICE_GUID] == DEVICE_GUID
    assert_private_values_absent(caplog.text)


async def test_missing_stored_identity_is_fatal(hass, entry, client_factory):
    hass.config_entries.async_update_entry(
        entry, data={CONF_USER_GUID: NORMALIZED_USER_GUID}
    )
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    client_factory.assert_not_called()


async def test_reload_rebuilds_with_persisted_identity(
    hass, entry, client_factory, client, snapshot
):
    coordinator = await load_entry(hass, entry)
    client.device_guid_for_persistence = ROTATED_DEVICE_GUID
    await coordinator.async_refresh()
    old_runtime = entry.runtime_data
    devices_before = dr.async_entries_for_config_entry(
        dr.async_get(hass), entry.entry_id
    )
    second = Mock(spec=HobenClient)
    second.async_refresh = AsyncMock(return_value=snapshot)
    second.async_close = AsyncMock()
    second.device_guid_for_persistence = ROTATED_DEVICE_GUID
    client_factory.return_value = second
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data is not old_runtime
    assert entry.runtime_data.client is second
    client_factory.assert_called_with(
        user_guid=NORMALIZED_USER_GUID, device_guid=ROTATED_DEVICE_GUID
    )
    client.async_close.assert_awaited_once_with()
    second.async_refresh.assert_awaited_once_with()
    devices_after = dr.async_entries_for_config_entry(
        dr.async_get(hass), entry.entry_id
    )
    assert len(devices_after) == 1
    assert devices_after[0].id == devices_before[0].id


async def test_setup_cancellation_closes_client(hass, entry, client_factory, client):
    waiting = asyncio.Event()

    async def slow_refresh():
        waiting.set()
        await asyncio.Future()

    client.async_refresh.side_effect = slow_refresh
    setup = hass.async_create_task(hass.config_entries.async_setup(entry.entry_id))
    await waiting.wait()
    setup.cancel()
    with pytest.raises(asyncio.CancelledError):
        await setup
    client.async_close.assert_awaited_once_with()
    assert not hasattr(entry, "runtime_data")


async def test_slow_refresh_keeps_event_loop_responsive(
    hass, entry, client_factory, client
):
    coordinator = await load_entry(hass, entry)
    waiting = asyncio.Event()

    async def slow_refresh():
        waiting.set()
        await asyncio.Future()

    client.async_refresh.side_effect = slow_refresh
    refresh = hass.async_create_task(coordinator.async_refresh())
    await waiting.wait()
    responsive = asyncio.Event()
    hass.loop.call_soon(responsive.set)
    await asyncio.wait_for(responsive.wait(), timeout=1)

    async def close_active():
        # Emulate HobenClient's tested cancellation/cleanup contract on unload.
        assert coordinator._shutdown_requested
        refresh.cancel()
        with pytest.raises(asyncio.CancelledError):
            await refresh

    client.async_close.side_effect = close_active
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert refresh.done()
    await advance_poll(hass)
    assert client.async_refresh.await_count == 2
