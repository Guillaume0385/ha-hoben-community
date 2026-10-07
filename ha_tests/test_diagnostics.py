"""Real HA diagnostics downloads and adversarial synthetic privacy regressions."""

import asyncio
import json
from dataclasses import replace
from http import HTTPStatus
from unittest.mock import AsyncMock, Mock, call, patch

import pytest
from conftest import DEVICE_GUID, NORMALIZED_USER_GUID, USER_GUID
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.setup import async_setup_component
from test_entities import states
from test_runtime import advance_poll

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
from custom_components.hoben.transport import AsyncTlsTransport

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
@pytest.mark.parametrize("failed", [False, True])
async def test_real_ha_download_wraps_only_safe_hoben_data(
    hass, hass_client, private_entry, client, loaded, unloaded, failed
):
    """Exercise the public HTTP endpoint and the entire downloaded JSON."""
    assert await async_setup_component(hass, "diagnostics", {})
    await hass.async_block_till_done()
    if failed:
        client.async_refresh.side_effect = HobenModbusError(7)
        await loaded.coordinator.async_refresh()
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
    if not unloaded:
        assert full["data"]["coordinator"]["last_error"] == (
            {"error": "modbus_exception", "exception_code": 7} if failed else None
        )
    assert_private_absent(full, private_entry)
    assert private_entry.data == old_data and private_entry.options == old_options
    assert list(dr.async_get(hass).devices) == devices
    assert list(er.async_get(hass).entities) == entities
    assert client.async_refresh.await_count == (2 if failed else 1)
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
    before_tasks = asyncio.all_tasks()
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
    ):
        report = await async_get_config_entry_diagnostics(hass, private_entry)
    assert report["coordinator"]["last_error"] == {"error": "transport_unavailable"}
    assert not report["coordinator"]["last_update_success"]
    assert client.async_refresh.await_count == before_count
    assert private_entry.data == before_data
    assert asyncio.all_tasks() == before_tasks
    assert_private_absent(report, private_entry)


@pytest.mark.parametrize(
    "error, expected",
    [case for case in ERRORS if isinstance(case[0], (HobenError, RuntimeError))],
)
async def test_actual_polling_failure_keeps_typed_metadata_and_private_logs(
    hass, private_entry, client, loaded, caplog, error, expected
):
    """Exercise the Hoben → HA wrapper → diagnostics path, not injected HA state."""
    error.args = (SECRET, USER_GUID, RAW_PACKET, CODE, WORDS)
    error.__cause__ = RuntimeError(SECRET + DEVICE_GUID)
    error.__context__ = ValueError(SECRET + str(CODE))
    error.add_note(SECRET)
    client.async_refresh.side_effect = error
    old_snapshot = loaded.coordinator.data
    old_data, old_options = dict(private_entry.data), dict(private_entry.options)
    with caplog.at_level("DEBUG", logger="custom_components.hoben.coordinator"):
        await loaded.coordinator.async_refresh()
    report = await async_get_config_entry_diagnostics(hass, private_entry)
    assert report["coordinator"]["last_error"] == expected
    assert not report["coordinator"]["last_update_success"]
    if isinstance(
        error, (HobenInvalidCredentialsError, HobenAuthorizationRequiredError)
    ):
        wrapper = ConfigEntryAuthFailed
    elif isinstance(error, HobenTransportError):
        wrapper = UpdateFailed
    else:
        wrapper = ConfigEntryError
    assert type(loaded.coordinator.last_exception) is wrapper
    assert loaded.coordinator.data is old_snapshot
    assert private_entry.data == old_data and private_entry.options == old_options
    assert client.async_refresh.await_count == 2  # setup plus one failed refresh
    client.async_associate.assert_not_awaited()
    assert_private_absent(report, private_entry)
    assert_private_absent({"public": caplog.text}, private_entry)
    for key, value in expected.items():
        assert f"{key}={value}" in str(loaded.coordinator.last_exception)
        assert f"{key}={value}" in caplog.text


async def test_typed_error_recovers_on_normal_timers_without_history_or_extra_io(
    hass, private_entry, client, loaded, caplog
):
    """An accepted snapshot survives failure; success clears the current report."""
    coordinator = loaded.coordinator
    old_snapshot = coordinator.data
    old_data, old_options = dict(private_entry.data), dict(private_entry.options)
    client.async_refresh.side_effect = [
        HobenModbusError(7),
        HobenModbusError(7),
        old_snapshot.raw,
        HobenProtocolError(),
    ]
    caplog.clear()
    with patch.object(
        hass.config_entries,
        "async_update_entry",
        wraps=hass.config_entries.async_update_entry,
    ) as update:
        await advance_poll(hass)
        report = await async_get_config_entry_diagnostics(hass, private_entry)
        assert report["coordinator"]["last_error"] == {
            "error": "modbus_exception",
            "exception_code": 7,
        }
        assert all(
            state.state == STATE_UNAVAILABLE
            for state in states(hass, private_entry).values()
        )
        assert coordinator.data is old_snapshot
        assert client.async_refresh.await_count == 2
        await advance_poll(hass)
        assert client.async_refresh.await_count == 3
        assert (
            len(
                [
                    record
                    for record in caplog.records
                    if record.name == "custom_components.hoben.coordinator"
                    and record.levelname == "ERROR"
                ]
            )
            == 1
        )
        await advance_poll(hass)
        report = await async_get_config_entry_diagnostics(hass, private_entry)
        assert report["coordinator"]["last_update_success"]
        assert report["coordinator"]["last_error"] is None
        assert all(
            state.state != STATE_UNAVAILABLE
            for state in states(hass, private_entry).values()
        )
        assert coordinator.data == old_snapshot
        assert client.async_refresh.await_count == 4
        await advance_poll(hass)
        report = await async_get_config_entry_diagnostics(hass, private_entry)
        assert report["coordinator"]["last_error"] == {"error": "malformed_response"}
        assert client.async_refresh.await_count == 5
        assert (
            len(
                [
                    record
                    for record in caplog.records
                    if record.name == "custom_components.hoben.coordinator"
                    and record.levelname == "ERROR"
                ]
            )
            == 2
        )
    update.assert_not_called()
    assert private_entry.data == old_data and private_entry.options == old_options
    client.async_associate.assert_not_awaited()
    assert_private_absent(report, private_entry)


@pytest.mark.parametrize(
    "failure, expected, request_types",
    [
        ("malformed", {"error": "malformed_response"}, [0x03, 0x0D]),
        ("ambiguous", {"error": "unclassified_opened_client_bytes"}, [0x03]),
        ("modbus", {"error": "modbus_exception", "exception_code": 7}, [0x03, 0x0D]),
        ("closed", {"error": "server_closed", "reason": "server_maintenance"}, [0x03]),
    ],
)
async def test_scripted_wire_failure_reaches_actual_polling_diagnostics(
    hass, private_entry, monkeypatch, caplog, failure, expected, request_types
):
    """Only replace TLS: real client/parsers, HA setup and refresh stay intact."""
    opened = bytearray(48)
    opened[0] = 0x04
    opened[8:11] = bytes([5, 2, 8])
    opened[14:46] = DEVICE_GUID.encode("ascii")
    opened[46:48] = b"\x00\x02"
    opened = bytes(opened)
    registers = b"".join(word.to_bytes(2, "big") for word in WORDS)
    response = b"\x0e\xff\xff\x00\x00\x00\x2b\x01\x04\x28" + registers
    failures = {
        "malformed": [opened, b"\x0e\xff\xfe\x00\x00\x00\x03\x01\x84\x07"],
        "ambiguous": [opened + SECRET.encode()],
        "modbus": [opened, b"\x0e\xff\xff\x00\x00\x00\x03\x01\x84\x07"],
        "closed": [b"\x05\x06"],
    }

    def transport(chunks):
        return Mock(
            spec=AsyncTlsTransport,
            connect=AsyncMock(),
            write=AsyncMock(),
            read=AsyncMock(side_effect=chunks),
            close=AsyncMock(),
        )

    successful = transport([opened, response])
    failed = transport(failures[failure])
    factory = Mock(side_effect=[successful, failed])
    monkeypatch.setattr("custom_components.hoben.client.AsyncTlsTransport", factory)
    assert await hass.config_entries.async_setup(private_entry.entry_id)
    await hass.async_block_till_done()
    coordinator = private_entry.runtime_data.coordinator
    previous = coordinator.data
    old_data = dict(private_entry.data)
    with caplog.at_level("DEBUG", logger="custom_components.hoben.coordinator"):
        await coordinator.async_refresh()
    report = await async_get_config_entry_diagnostics(hass, private_entry)
    assert report["coordinator"]["last_error"] == expected
    assert type(coordinator.last_exception) is ConfigEntryError
    assert coordinator.data is previous
    assert private_entry.data == old_data
    assert factory.call_count == 2  # no protocol retry or diagnostic connection
    for wire, types in ((successful, [0x03, 0x0D]), (failed, request_types)):
        assert [args.args[0][0] for args in wire.write.await_args_list] == types
        wire.close.assert_awaited_once_with()
        wire.connect.assert_awaited_once_with()
    assert_private_absent(report, private_entry)
    assert_private_absent({"public": caplog.text}, private_entry)
    for key, value in expected.items():
        assert f"{key}={value}" in caplog.text


@pytest.mark.parametrize(
    "unsafe_report, expected",
    [
        (None, {"error": "unexpected_error"}),
        ([SECRET, USER_GUID, CODE], {"error": "unexpected_error"}),
        ({SECRET: RAW_PACKET}, {"error": "unexpected_error"}),
        ({"error": SECRET, "reason": USER_GUID}, {"error": "unexpected_error"}),
        ({"error": True}, {"error": "unexpected_error"}),
        (
            {
                "error": "malformed_response",
                "reason": SECRET,
                "profile": USER_GUID,
                "failure": {SECRET: CODE},
                "exception_code": True,
                "attempts": 3,
                SECRET: {"registers": WORDS, "raw_packet": RAW_PACKET},
            },
            {"error": "malformed_response"},
        ),
        (
            {
                "error": "modbus_exception",
                "exception_code": 256,
                "attempts": -1,
            },
            {"error": "modbus_exception"},
        ),
        (
            {
                "error": "refresh_exhausted",
                "attempts": 2,
                "failure": "timeout",
                "private": SECRET * 100_000,
                "authorization_code": CODE,
                "registers": WORDS,
            },
            {"error": "refresh_exhausted", "failure": "timeout", "attempts": 2},
        ),
    ],
)
async def test_real_error_mapping_validates_contract_before_logging_and_export(
    hass, private_entry, client, loaded, caplog, unsafe_report, expected
):
    """Future/malformed reports are filtered before either public surface."""
    error = HobenProtocolError()
    error.safe_report = Mock(return_value=unsafe_report)
    client.async_refresh.side_effect = error
    await loaded.coordinator.async_refresh()
    report = await async_get_config_entry_diagnostics(hass, private_entry)
    assert report["coordinator"]["last_error"] == expected
    assert len(json.dumps(report)) < 2048
    error.safe_report.assert_called_once_with()
    assert_private_absent(report, private_entry)
    assert_private_absent({"public": caplog.text}, private_entry)
    for key, value in expected.items():
        assert f"{key}={value}" in caplog.text


async def test_broken_error_report_during_polling_is_safe_and_not_retried(
    hass, private_entry, client, loaded, caplog
):
    error = HobenProtocolError()
    error.safe_report = Mock(side_effect=RuntimeError(SECRET + USER_GUID + str(CODE)))
    client.async_refresh.side_effect = error
    await loaded.coordinator.async_refresh()
    report = await async_get_config_entry_diagnostics(hass, private_entry)
    assert report["coordinator"]["last_error"] == {"error": "unexpected_error"}
    assert type(loaded.coordinator.last_exception) is ConfigEntryError
    assert client.async_refresh.await_count == 2
    error.safe_report.assert_called_once_with()
    assert_private_absent(report, private_entry)
    assert_private_absent({"public": caplog.text}, private_entry)


@pytest.mark.parametrize("tamper", [False, True])
async def test_wrapped_report_is_copied_and_revalidated_without_source_access(
    hass, private_entry, client, loaded, tamper
):
    original = {"error": "modbus_exception", "exception_code": 7, SECRET: RAW_PACKET}
    error = HobenModbusError(7)
    error.safe_report = Mock(return_value=original)
    client.async_refresh.side_effect = error
    await loaded.coordinator.async_refresh()
    original.clear()
    error.safe_report.side_effect = AssertionError("Do not read the source again")
    if tamper:
        loaded.coordinator.last_exception._hoben_safe_report = {
            "error": SECRET,
            "reason": USER_GUID,
            "private": WORDS,
        }
    report = await async_get_config_entry_diagnostics(hass, private_entry)
    assert report["coordinator"]["last_error"] == (
        {"error": "config_entry_error"}
        if tamper
        else {"error": "modbus_exception", "exception_code": 7}
    )
    error.safe_report.assert_called_once_with()
    assert_private_absent(report, private_entry)


@pytest.mark.parametrize(
    "base, expected",
    [
        (HobenProtocolError, "malformed_response"),
        (ConfigEntryError, "config_entry_error"),
    ],
)
async def test_polling_never_inspects_source_args_text_or_chains(
    hass, private_entry, client, loaded, caplog, base, expected
):
    """Tripwires cover both Hoben codes and a HA fallback without safe metadata."""

    class OpaqueError(base):
        def __str__(self):
            raise AssertionError("Do not inspect source text")

        def __repr__(self):
            raise AssertionError("Do not inspect source repr")

        def __getattribute__(self, name):
            if name in {"args", "__cause__", "__context__", "__traceback__"}:
                raise AssertionError("Do not inspect source exception internals")
            return super().__getattribute__(name)

    error = OpaqueError() if issubclass(base, HobenError) else OpaqueError(SECRET)
    error.__cause__ = RuntimeError(SECRET + USER_GUID)
    client.async_refresh.side_effect = error
    await loaded.coordinator.async_refresh()
    report = await async_get_config_entry_diagnostics(hass, private_entry)
    assert report["coordinator"]["last_error"] == {"error": expected}
    assert type(loaded.coordinator.last_exception) is ConfigEntryError
    assert_private_absent(report, private_entry)
    assert_private_absent({"public": caplog.text}, private_entry)


@pytest.mark.parametrize(
    "wrapper, expected",
    [
        (ConfigEntryAuthFailed, "authentication_failed"),
        (UpdateFailed, "update_failed"),
        (ConfigEntryError, "config_entry_error"),
    ],
)
async def test_inaccessible_wrapper_metadata_uses_fixed_fallback(
    hass, private_entry, loaded, caplog, wrapper, expected
):
    """An invalid metadata accessor cannot fail the download or leak its error."""

    class BrokenMetadata(wrapper):
        @property
        def _hoben_safe_report(self):
            raise RuntimeError(SECRET + USER_GUID + str(CODE))

    loaded.coordinator.last_exception = BrokenMetadata(SECRET)
    loaded.coordinator.last_update_success = False
    report = await async_get_config_entry_diagnostics(hass, private_entry)
    assert report["coordinator"]["last_error"] == {"error": expected}
    assert_private_absent(report, private_entry)
    assert_private_absent({"public": caplog.text}, private_entry)


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
    loaded.coordinator.last_update_success = False
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
    loaded.coordinator.last_update_success = False
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
    loaded.coordinator.last_update_success = False
    report = await async_get_config_entry_diagnostics(hass, private_entry)
    assert report["client"] == {}
    assert report["snapshot"] == {}
    assert report["coordinator"]["last_error"] == {"error": "unexpected_error"}
    assert_private_absent(report, private_entry)
