"""Real HA diagnostics downloads and adversarial synthetic privacy regressions."""

import asyncio
import json
from dataclasses import replace
from http import HTTPStatus
from unittest.mock import Mock, call, patch

import pytest
from conftest import DEVICE_GUID, NORMALIZED_USER_GUID, USER_GUID
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.setup import async_setup_component

from custom_components.hoben import HobenRuntimeData
from custom_components.hoben.client import HobenClient, RawStoveSnapshot
from custom_components.hoben.const import CONF_AUTHORIZATION_CODE, DOMAIN
from custom_components.hoben.coordinator import HobenDataUpdateCoordinator
from custom_components.hoben.diagnostics import async_get_config_entry_diagnostics
from custom_components.hoben.exceptions import (
    HobenAmbiguousSessionError,
    HobenAuthorizationCodeError,
    HobenAuthorizationRequiredError,
    HobenClientClosedError,
    HobenClosedError,
    HobenError,
    HobenInvalidCredentialsError,
    HobenInvalidInputError,
    HobenModbusError,
    HobenProtocolError,
    HobenRefreshExhaustedError,
    HobenTimeoutError,
    HobenTransportError,
    HobenUnsupportedProfileError,
)
from custom_components.hoben.myhoben import CloseClientReason
from custom_components.hoben.profiles import StoveProfile

# Invented inputs only. Distinctive private values do not overlap public metadata.
CODE = 49261
SECRET = "DIAGNOSTICS_PRIVATE_PAYLOAD"
RAW_PACKET = b"\x03" + NORMALIZED_USER_GUID.encode() + DEVICE_GUID.encode()
WORDS = (
    0x0201,
    267,
    43,
    179,
    2,
    59731,
    0x4305,
    243,
    261,
    59991,
    58911,
    0x0060,
    0x3712,
    0x023F,
    0x2238,
    273,
    318,
    1247,
    55219,
    287,
)


def atoms(value):
    """Inspect every key and value, rather than looking only at selected paths."""
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from atoms(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from atoms(child)
    else:
        yield value


def assert_private_absent(payload, entry):
    """JSON serialization and recursive absence protect the complete payload."""
    flat = list(atoms(payload))
    assert all(type(value) in (str, int, float, bool, type(None)) for value in flat)
    encoded = json.dumps(payload, allow_nan=False, sort_keys=True)
    for private in (
        USER_GUID,
        NORMALIZED_USER_GUID,
        DEVICE_GUID,
        str(CODE),
        SECRET,
        entry.unique_id,
        entry.entry_id,
        RAW_PACKET.hex(),
        "combustion_management",
        "manual",
        "boost",
    ):
        assert private not in encoded
    for private in (
        CODE,
        267,
        43,
        179,
        59731,
        243,
        261,
        59991,
        58911,
        273,
        318,
        1247,
        55219,
        287,
        26.7,
        24.3,
        26.1,
        27.3,
        31.8,
        124.7,
        28.7,
    ):
        assert private not in flat
    for private_key in (
        "user_guid",
        "device_guid",
        "authorization_code",
        "registers",
        "ambient_temperature",
        "target_temperature",
        "smoke_temperature",
        "combustion_air_temperature",
        "wired_ambient_temperature",
        "rf_ambient_temperature",
        "derogation_temperature",
        "derogation_start_delay",
        "derogation_duration",
        "raw_packet",
        "raw_modbus",
        "unique_id",
        "traceback",
    ):
        assert private_key not in flat


@pytest.fixture
def private_entry(hass, entry):
    """Seed secrets in nested storage, options, title and unrelated HA state."""
    private = {
        CONF_AUTHORIZATION_CODE: CODE,
        "raw_packet": RAW_PACKET.hex(),
        "raw_modbus": (b"\x0e\xff\xff\x00\x00" + SECRET.encode()).hex(),
        "registers": WORDS,
        SECRET: {entry.unique_id: USER_GUID},
    }
    hass.config_entries.async_update_entry(
        entry,
        title=SECRET + USER_GUID,
        data={**entry.data, **private},
        options={**entry.options, **private},
    )
    hass.states.async_set("sensor.hoben_private_fixture", SECRET, private)
    return entry


@pytest.fixture
async def loaded(hass, private_entry, client_factory, client, snapshot):
    """Use actual setup, entities and coordinator; replace only the network API."""
    client.async_refresh.return_value = replace(snapshot, registers=WORDS)
    client.safe_report.return_value = {
        "state": "ready",
        "profile": "v4",
        "has_assigned_device_guid": True,
    }
    assert await hass.config_entries.async_setup(private_entry.entry_id)
    await hass.async_block_till_done()
    assert private_entry.state is ConfigEntryState.LOADED
    return private_entry.runtime_data


async def test_loaded_diagnostics_schema_is_private_deterministic_and_read_only(
    hass, private_entry, client_factory, client, loaded, caplog
):
    """The adapter may read only metadata and must not even schedule work."""
    coordinator = loaded.coordinator
    old_data, old_options = dict(private_entry.data), dict(private_entry.options)
    old_coordinator_data = coordinator.data
    old_exception = coordinator.last_exception
    old_listeners = dict(coordinator._listeners)
    client_factory.reset_mock()
    old_calls = client.mock_calls.copy()
    old_state = hass.states.get("sensor.hoben_private_fixture")
    old_tasks = asyncio.all_tasks()
    with (
        patch.object(hass, "async_create_task", side_effect=AssertionError("No tasks")),
        patch.object(
            hass, "async_create_background_task", side_effect=AssertionError("No tasks")
        ),
        patch.object(
            hass.config_entries,
            "async_update_entry",
            side_effect=AssertionError("No updates"),
        ),
        caplog.at_level("DEBUG"),
    ):
        report = await async_get_config_entry_diagnostics(hass, private_entry)
        repeated = await async_get_config_entry_diagnostics(hass, private_entry)
    assert (
        report
        == repeated
        == {
            "domain": DOMAIN,
            "entry": {"state": "loaded", "version": 1, "minor_version": 1},
            "runtime_available": True,
            "client": {
                "state": "ready",
                "profile": "v4",
                "has_assigned_device_guid": True,
            },
            "coordinator": {
                "last_update_success": True,
                "update_interval_seconds": 60,
                "snapshot_available": True,
                "last_error": None,
            },
            "snapshot": {
                "state": "read",
                "profile": "v4",
                "product_type": 5,
                "product_revision": 0,
                "software_major": 8,
                "software_minor": 2,
                "application_version": 512,
                "register_count": 20,
            },
        }
    )
    assert type(report["client"]["has_assigned_device_guid"]) is bool
    assert len(json.dumps(report)) < 2048
    assert_private_absent(report, private_entry)
    assert SECRET not in caplog.text and str(CODE) not in caplog.text
    assert private_entry.data == old_data and private_entry.options == old_options
    assert private_entry.runtime_data is loaded
    assert coordinator.data is old_coordinator_data
    assert coordinator.last_exception is old_exception
    assert coordinator.last_update_success
    assert coordinator._listeners == old_listeners
    assert hass.states.get("sensor.hoben_private_fixture") is old_state
    assert asyncio.all_tasks() == old_tasks
    assert client.mock_calls[len(old_calls) :] == [
        call.safe_report(),
        call.safe_report(),
    ]
    client_factory.assert_not_called()


@pytest.mark.parametrize("unloaded", [False, True])
async def test_real_ha_download_wraps_only_safe_hoben_data(
    hass, hass_client, private_entry, client, loaded, unloaded
):
    """Exercise the public HTTP endpoint and the entire downloaded JSON."""
    assert await async_setup_component(hass, "diagnostics", {})
    await hass.async_block_till_done()
    if unloaded:
        assert await hass.config_entries.async_unload(private_entry.entry_id)
        await hass.async_block_till_done()
    before_calls = client.mock_calls.copy()
    devices = list(dr.async_get(hass).devices)
    entities = list(er.async_get(hass).entities)
    old_data, old_options = dict(private_entry.data), dict(private_entry.options)
    http = await hass_client()
    response = await http.get(f"/api/diagnostics/config_entry/{private_entry.entry_id}")
    assert response.status == HTTPStatus.OK
    full = await response.json()
    assert full["integration_manifest"]["domain"] == DOMAIN
    assert full["data"] == await async_get_config_entry_diagnostics(hass, private_entry)
    assert full["data"]["runtime_available"] is not unloaded
    assert_private_absent(full, private_entry)
    assert private_entry.data == old_data and private_entry.options == old_options
    assert list(dr.async_get(hass).devices) == devices
    assert list(er.async_get(hass).entities) == entities
    assert client.async_refresh.await_count == 1
    client.async_associate.assert_not_awaited()
    assert all(
        call[0] == "safe_report" for call in client.mock_calls[len(before_calls) :]
    )


@pytest.mark.parametrize(
    "state",
    [
        ConfigEntryState.NOT_LOADED,
        ConfigEntryState.SETUP_RETRY,
        ConfigEntryState.SETUP_ERROR,
        ConfigEntryState.MIGRATION_ERROR,
        ConfigEntryState.FAILED_UNLOAD,
    ],
)
async def test_missing_runtime_has_only_safe_lifecycle_metadata(
    hass, private_entry, client_factory, client, state
):
    private_entry._async_set_state(hass, state, SECRET)
    report = await async_get_config_entry_diagnostics(hass, private_entry)
    assert report == {
        "domain": DOMAIN,
        "entry": {"state": state.value, "version": 1, "minor_version": 1},
        "runtime_available": False,
    }
    assert_private_absent(report, private_entry)
    client_factory.assert_not_called()
    assert client.mock_calls == []
    private_entry._async_set_state(hass, ConfigEntryState.NOT_LOADED, None)


async def test_runtime_without_snapshot_uses_the_real_client_safe_contract(
    hass, private_entry, client_factory
):
    """An unrefreshed client is entirely local and needs no successful snapshot."""
    client = HobenClient(user_guid=NORMALIZED_USER_GUID)
    coordinator = HobenDataUpdateCoordinator(hass, private_entry, client)
    private_entry.runtime_data = HobenRuntimeData(client, coordinator)
    old_client = vars(client).copy()
    old_coordinator_data = coordinator.data
    report = await async_get_config_entry_diagnostics(hass, private_entry)
    assert report["runtime_available"]
    assert report["client"] == {
        "state": "ready",
        "profile": "unknown",
        "has_assigned_device_guid": False,
    }
    assert report["coordinator"]["snapshot_available"] is False
    assert report["snapshot"] is None
    assert vars(client) == old_client
    assert coordinator.data is old_coordinator_data
    assert_private_absent(report, private_entry)
    client_factory.assert_not_called()


ERRORS = [
    (HobenError(), {"error": "client_failed"}),
    (HobenInvalidInputError(), {"error": "invalid_client_inputs"}),
    (HobenAuthorizationRequiredError(), {"error": "authorization_required"}),
    (HobenAuthorizationCodeError(), {"error": "authorization_code_unavailable"}),
    (
        HobenInvalidCredentialsError(CloseClientReason.INVALID_IDENTIFIER),
        {"error": "invalid_credentials", "reason": "invalid_identifier"},
    ),
    (
        HobenUnsupportedProfileError(StoveProfile.V6),
        {"error": "unsupported_profile", "profile": "v6"},
    ),
    (HobenProtocolError(), {"error": "malformed_response"}),
    (HobenAmbiguousSessionError(), {"error": "unclassified_opened_client_bytes"}),
    (HobenModbusError(7), {"error": "modbus_exception", "exception_code": 7}),
    (HobenTransportError(), {"error": "transport_unavailable"}),
    (HobenTimeoutError(), {"error": "timeout"}),
    (
        HobenRefreshExhaustedError(2, HobenTimeoutError()),
        {"error": "refresh_exhausted", "attempts": 2, "failure": "timeout"},
    ),
    (HobenClientClosedError(), {"error": "client_closed"}),
    (UpdateFailed(SECRET), {"error": "update_failed"}),
    (ConfigEntryAuthFailed(SECRET), {"error": "authentication_failed"}),
    (ConfigEntryError(SECRET), {"error": "config_entry_error"}),
    (RuntimeError(SECRET, RAW_PACKET, CODE, WORDS), {"error": "unexpected_error"}),
] + [
    (HobenClosedError(reason), {"error": "server_closed", "reason": reason.value})
    for reason in CloseClientReason
]


@pytest.mark.parametrize("error, expected", ERRORS)
async def test_failure_exports_only_safe_codes_never_exception_chains_or_args(
    hass, private_entry, client, loaded, caplog, error, expected
):
    error.args = (SECRET, USER_GUID, RAW_PACKET, CODE, WORDS)
    error.__cause__ = RuntimeError(SECRET + DEVICE_GUID)
    loaded.coordinator.last_exception = error
    loaded.coordinator.last_update_success = False
    old_data = loaded.coordinator.data
    before_calls = client.mock_calls.copy()
    report = await async_get_config_entry_diagnostics(hass, private_entry)
    assert not report["coordinator"]["last_update_success"]
    assert report["coordinator"]["last_error"] == expected
    assert report["snapshot"]["register_count"] == 20  # retained metadata only
    assert loaded.coordinator.data is old_data
    assert loaded.coordinator.last_exception is error
    assert all(
        call[0] == "safe_report" for call in client.mock_calls[len(before_calls) :]
    )
    assert_private_absent(report, private_entry)
    assert SECRET not in caplog.text


async def test_actual_failed_update_remains_read_only_during_diagnostics(
    hass, private_entry, client, loaded
):
    client.async_refresh.side_effect = HobenTransportError()
    await loaded.coordinator.async_refresh()
    assert isinstance(loaded.coordinator.last_exception, UpdateFailed)
    before_count = client.async_refresh.await_count
    before_data = dict(private_entry.data)
    report = await async_get_config_entry_diagnostics(hass, private_entry)
    assert report["coordinator"]["last_error"] == {"error": "update_failed"}
    assert not report["coordinator"]["last_update_success"]
    assert client.async_refresh.await_count == before_count
    assert private_entry.data == before_data
    assert_private_absent(report, private_entry)


async def test_future_report_extensions_cannot_enlarge_the_public_allowlist(
    hass, private_entry, client, loaded, monkeypatch
):
    poison = {
        SECRET: {USER_GUID: RAW_PACKET},
        "registers": WORDS,
        "authorization_code": CODE,
        "private": SECRET * 100_000,
    }
    client.safe_report.return_value |= poison
    original = RawStoveSnapshot.safe_report
    monkeypatch.setattr(
        RawStoveSnapshot, "safe_report", lambda self: original(self) | poison
    )
    error = HobenTimeoutError()
    error.safe_report = Mock(return_value={"error": "timeout", **poison})
    loaded.coordinator.last_exception = error
    report = await async_get_config_entry_diagnostics(hass, private_entry)
    assert report["coordinator"]["last_error"] == {"error": "timeout"}
    assert len(json.dumps(report)) < 2048
    assert_private_absent(report, private_entry)


@pytest.mark.parametrize(
    "value", [SECRET, [SECRET], {SECRET: CODE}, True, -1, 65536, 1.5]
)
async def test_invalid_scalar_report_fields_are_omitted_without_coercion(
    hass, private_entry, client, loaded, monkeypatch, value
):
    client.safe_report.return_value = {
        "state": value,
        "profile": value,
        "has_assigned_device_guid": SECRET,
    }
    monkeypatch.setattr(
        RawStoveSnapshot,
        "safe_report",
        lambda self: {
            "profile": SECRET,
            "product_type": value,
            "product_revision": value,
            "software_major": value,
            "software_minor": value,
            "application_version": value,
            "register_count": value,
        },
    )
    error = HobenError()
    error.safe_report = Mock(
        return_value={"error": SECRET, "reason": SECRET, "attempts": value}
    )
    loaded.coordinator.last_exception = error
    report = await async_get_config_entry_diagnostics(hass, private_entry)
    assert report["client"] == {}
    assert report["snapshot"] == {}
    assert report["coordinator"]["last_error"] == {"error": "unexpected_error"}
    assert_private_absent(report, private_entry)


@pytest.mark.parametrize("raises", [False, True])
async def test_broken_safe_report_contract_fails_closed(
    hass, private_entry, client, loaded, monkeypatch, raises
):
    def broken(*args):
        if raises:
            raise RuntimeError(SECRET + USER_GUID + str(CODE))
        return [SECRET, USER_GUID, CODE]

    client.safe_report.side_effect = broken
    monkeypatch.setattr(RawStoveSnapshot, "safe_report", broken)
    error = HobenError()
    error.safe_report = broken
    loaded.coordinator.last_exception = error
    report = await async_get_config_entry_diagnostics(hass, private_entry)
    assert report["client"] == {}
    assert report["snapshot"] == {}
    assert report["coordinator"]["last_error"] == {"error": "unexpected_error"}
    assert_private_absent(report, private_entry)
