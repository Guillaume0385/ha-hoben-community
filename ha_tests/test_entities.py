"""Read-only entities in real HA: metadata, shared updates, errors and lifecycle."""

import asyncio
import traceback
from dataclasses import replace
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
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import EntityCategory

from custom_components.hoben.binary_sensor import BINARY_SENSORS, HobenBinarySensor
from custom_components.hoben.client import HobenClient
from custom_components.hoben.const import CONF_DEVICE_GUID
from custom_components.hoben.coordinator import HobenDataUpdateCoordinator
from custom_components.hoben.exceptions import HobenTransportError
from custom_components.hoben.sensor import SENSORS, HobenSensor
from custom_components.hoben.transport import AsyncTlsTransport
from custom_components.hoben.v4_state import decode_v4_snapshot

# Independent synthetic examples, not actual reference-stove values.
WORDS = (
    0x0201,
    211,
    37,
    181,
    2,
    360,
    0x4305,
    213,
    201,
    0x1234,
    0x8000,
    0x0060,
    0x260A,
    0x010C,
    0x2238,
    219,
    278,
    1103,
    17,
    224,
)
SENSOR_EXPECTATIONS = {
    "ambient_temperature": ("21.3", "temperature", "°C", "measurement", None),
    "target_temperature": ("20.1", "temperature", "°C", None, None),
    "power_level": ("67", None, "%", "measurement", None),
    "operation_state": ("combustion_management", "enum", None, None, None),
    "operation_mode": ("manual", "enum", None, None, None),
    "ventilation_mode": ("boost", "enum", None, None, None),
    "smoke_temperature": ("110.3", "temperature", "°C", "measurement", "diagnostic"),
    "combustion_air_temperature": (
        "27.8",
        "temperature",
        "°C",
        "measurement",
        "diagnostic",
    ),
    "wired_ambient_temperature": (
        "21.9",
        "temperature",
        "°C",
        "measurement",
        "diagnostic",
    ),
    "rf_ambient_temperature": (
        "22.4",
        "temperature",
        "°C",
        "measurement",
        "diagnostic",
    ),
    "derogation_temperature": ("21.1", "temperature", "°C", None, None),
    "derogation_start_delay": ("37", "duration", "min", None, None),
    "derogation_duration": ("181", "duration", "min", None, None),
}
BINARY_EXPECTATIONS = {
    "derogation_active": "on",
    "derogation_scheduled": "on",
    "controller_on_off": "on",
}
DISABLED = {"wired_ambient_temperature", "rf_ambient_temperature"}


def registry_entities(hass, entry):
    """Find entity IDs by stable unique-ID suffix, independent of display language."""
    return {
        entity.unique_id.removeprefix(f"{entry.unique_id}_"): entity
        for entity in er.async_entries_for_config_entry(
            er.async_get(hass), entry.entry_id
        )
    }


def states(hass, entry):
    """Return loaded states, excluding entities disabled in the entity registry."""
    return {
        key: hass.states.get(entity.entity_id)
        for key, entity in registry_entities(hass, entry).items()
        if entity.disabled_by is None
    }


async def setup_entities(hass, entry, client, snapshot):
    """Setup a real entry around one synthetic client result."""
    client.async_refresh.return_value = replace(snapshot, registers=WORDS)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data.coordinator


async def refresh_words(hass, coordinator, client, snapshot, changes):
    """Change synthetic registers by address, then make one shared update."""
    words = list(WORDS)
    for address, value in changes.items():
        words[address - 1024] = value
    client.async_refresh.return_value = replace(snapshot, registers=tuple(words))
    await coordinator.async_refresh()
    await hass.async_block_till_done()


async def test_setup_forwards_only_read_platforms_and_uses_one_refresh(
    hass, entry, client_factory, client, snapshot
):
    with patch.object(
        hass.config_entries,
        "async_forward_entry_setups",
        wraps=hass.config_entries.async_forward_entry_setups,
    ) as forward:
        coordinator = await setup_entities(hass, entry, client, snapshot)
    forward.assert_awaited_once_with(entry, ("sensor", "binary_sensor"))
    client.async_refresh.assert_awaited_once_with()
    entities = registry_entities(hass, entry)
    assert set(entities) == set(SENSOR_EXPECTATIONS) | set(BINARY_EXPECTATIONS)
    assert {entity.domain for entity in entities.values()} == {
        "sensor",
        "binary_sensor",
    }
    assert len(coordinator._listeners) == 14  # Two registered sensors are disabled.


@pytest.mark.parametrize("key", SENSOR_EXPECTATIONS)
async def test_sensor_values_metadata_and_default_enablement(
    hass, entry, client_factory, client, snapshot, key
):
    await setup_entities(hass, entry, client, snapshot)
    registered = registry_entities(hass, entry)[key]
    value, device_class, unit, state_class, category = SENSOR_EXPECTATIONS[key]
    assert registered.entity_category == category
    if key in DISABLED:
        assert registered.disabled_by is er.RegistryEntryDisabler.INTEGRATION
        assert hass.states.get(registered.entity_id) is None
        # The disabled entity still declares valid metadata and a decoded value.
        description = next(item for item in SENSORS if item.key == key)
        entity = HobenSensor(entry, description)
        assert entity.native_value == float(value)
        assert entity.device_class == device_class
        assert entity.native_unit_of_measurement == unit
        assert entity.state_class == state_class
        assert entity.entity_category is EntityCategory.DIAGNOSTIC
        return
    assert registered.disabled_by is None
    state = hass.states.get(registered.entity_id)
    assert state.state == value
    assert state.attributes.get("device_class") == device_class
    assert state.attributes.get("unit_of_measurement") == unit
    assert state.attributes.get("state_class") == state_class


@pytest.mark.parametrize(
    ("key", "options"),
    [
        (
            "operation_state",
            [
                "off",
                "end_of_combustion",
                "standard_start",
                "blackout_start",
                "stabilization",
                "combustion_management",
            ],
        ),
        ("operation_mode", ["automatic", "magasin", "manual"]),
        ("ventilation_mode", ["normal", "silence", "boost"]),
    ],
)
async def test_enum_options(
    hass, entry, client_factory, client, snapshot, key, options
):
    await setup_entities(hass, entry, client, snapshot)
    assert states(hass, entry)[key].attributes["options"] == options


async def test_all_properties_are_in_memory_and_never_invoke_client(
    hass, entry, client_factory, client, snapshot
):
    await setup_entities(hass, entry, client, snapshot)
    client.async_refresh.side_effect = AssertionError("Entities cannot refresh")
    entities = [HobenSensor(entry, item) for item in SENSORS] + [
        HobenBinarySensor(entry, item) for item in BINARY_SENSORS
    ]
    for _ in range(3):
        for entity in entities:
            assert entity.available
            assert not entity.should_poll
            assert entity.has_entity_name
            assert entity.translation_key
            assert entity.device_info
            assert entity.unique_id
            if isinstance(entity, HobenSensor):
                assert entity.native_value is not None
                entity.native_unit_of_measurement
                entity.state_class
                entity.options
            else:
                assert entity.is_on is True
                assert entity.device_class is None
    client.async_refresh.assert_awaited_once_with()
    client.async_close.assert_not_awaited()


async def test_one_update_changes_every_entity_including_enabled_optional_sensors(
    hass, entry, client_factory, client, snapshot
):
    await setup_entities(hass, entry, client, snapshot)
    registry = er.async_get(hass)
    for key in DISABLED:
        registry.async_update_entity(
            registry_entities(hass, entry)[key].entity_id, disabled_by=None
        )
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data.coordinator
    before = states(hass, entry)
    assert len(before) == 16
    count = client.async_refresh.await_count
    await refresh_words(
        hass,
        coordinator,
        client,
        snapshot,
        {
            1024: 0x0100,
            1025: 222,
            1026: 38,
            1027: 182,
            1028: 1,
            1030: 0x4404,
            1031: 214,
            1032: 202,
            1035: 0,
            1039: 220,
            1040: 279,
            1041: 1104,
            1043: 225,
        },
    )
    after = states(hass, entry)
    assert client.async_refresh.await_count == count + 1
    assert all(before[key].state != after[key].state for key in before)
    assert after["wired_ambient_temperature"].state == "22.0"
    assert after["rf_ambient_temperature"].state == "22.5"


@pytest.mark.parametrize("information", [0, 0x20, 0x40, 0x60, 0xFF9F])
async def test_derogation_visibility_and_typed_flags(
    hass, entry, client_factory, client, snapshot, information
):
    coordinator = await setup_entities(hass, entry, client, snapshot)
    await refresh_words(hass, coordinator, client, snapshot, {1035: information})
    current = states(hass, entry)
    assert current["derogation_active"].state == ("on" if information & 0x20 else "off")
    assert current["derogation_scheduled"].state == (
        "on" if information & 0x40 else "off"
    )
    for key, expected in (
        ("derogation_temperature", "21.1"),
        ("derogation_start_delay", "37"),
        ("derogation_duration", "181"),
    ):
        assert current[key].state == (expected if information & 0x60 else STATE_UNKNOWN)


@pytest.mark.parametrize(
    ("address", "key"),
    [
        (1025, "derogation_temperature"),
        (1031, "ambient_temperature"),
        (1032, "target_temperature"),
        (1040, "combustion_air_temperature"),
        (1041, "smoke_temperature"),
    ],
)
async def test_sentinel_affects_only_its_sensor(
    hass, entry, client_factory, client, snapshot, address, key
):
    coordinator = await setup_entities(hass, entry, client, snapshot)
    before = states(hass, entry)
    await refresh_words(hass, coordinator, client, snapshot, {address: 0x0FFF})
    current = states(hass, entry)
    assert coordinator.last_update_success
    assert current[key].state == STATE_UNKNOWN
    for other in current.keys() - {key}:
        assert current[other].state == before[other].state
        assert current[other].state != STATE_UNAVAILABLE


@pytest.mark.parametrize("target", [0, 49, 0xFFFF])
async def test_target_ui_mask_returns_unknown(
    hass, entry, client_factory, client, snapshot, target
):
    coordinator = await setup_entities(hass, entry, client, snapshot)
    await refresh_words(hass, coordinator, client, snapshot, {1032: target})
    assert states(hass, entry)["target_temperature"].state == STATE_UNKNOWN


async def test_unknown_codes_are_unknown_without_fallback_or_device_failure(
    hass, entry, client_factory, client, snapshot
):
    coordinator = await setup_entities(hass, entry, client, snapshot)
    await refresh_words(
        hass,
        coordinator,
        client,
        snapshot,
        {
            1024: 0xFFFE,
            1028: 0xFFFF,
            1030: 0xFFFE,
        },
    )
    current = states(hass, entry)
    for key in (
        "operation_mode",
        "controller_on_off",
        "ventilation_mode",
        "power_level",
        "operation_state",
    ):
        assert current[key].state == STATE_UNKNOWN
    assert current["ambient_temperature"].state == "21.3"
    assert coordinator.last_update_success


async def test_availability_failure_retains_data_and_recovery_restores_all_entities(
    hass, entry, client_factory, client, snapshot
):
    coordinator = await setup_entities(hass, entry, client, snapshot)
    before = coordinator.data
    client.async_refresh.side_effect = HobenTransportError()
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert coordinator.data is before
    assert all(
        state.state == STATE_UNAVAILABLE for state in states(hass, entry).values()
    )
    client.async_refresh.side_effect = None
    await refresh_words(hass, coordinator, client, snapshot, {1031: 214})
    assert coordinator.last_update_success
    assert states(hass, entry)["ambient_temperature"].state == "21.4"
    assert all(
        state.state != STATE_UNAVAILABLE for state in states(hass, entry).values()
    )


async def test_stable_private_ids_device_attachment_reload_and_unload(
    hass, entry, client_factory, client, snapshot, caplog
):
    coordinator = await setup_entities(hass, entry, client, snapshot)
    before = registry_entities(hass, entry)
    [device] = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    for key, registered in before.items():
        assert registered.unique_id == f"{entry.unique_id}_{key}"
        assert registered.device_id == device.id
        assert_private_values_absent(registered.unique_id)
    client.device_guid_for_persistence = ROTATED_DEVICE_GUID
    await coordinator.async_refresh()
    second = Mock(
        spec=HobenClient,
        async_refresh=AsyncMock(return_value=replace(snapshot, registers=WORDS)),
        async_close=AsyncMock(),
        device_guid_for_persistence=ROTATED_DEVICE_GUID,
    )
    client_factory.return_value = second
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    after = registry_entities(hass, entry)
    assert {
        key: (value.entity_id, value.unique_id, value.device_id)
        for key, value in before.items()
    } == {
        key: (value.entity_id, value.unique_id, value.device_id)
        for key, value in after.items()
    }
    assert not coordinator._listeners
    client.async_close.assert_awaited_once_with()
    restored = entry.runtime_data.coordinator
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert not restored._listeners
    second.async_close.assert_awaited_once_with()
    assert not hasattr(entry, "runtime_data")
    assert_private_values_absent(caplog.text)


@pytest.mark.parametrize("failure", ["shape", "range", "unexpected"])
async def test_decoder_failure_sanitized_keeps_last_data_and_does_not_persist(
    hass, entry, client_factory, client, snapshot, caplog, failure
):
    coordinator = await setup_entities(hass, entry, client, snapshot)
    before = coordinator.data
    client.device_guid_for_persistence = ROTATED_DEVICE_GUID
    if failure == "unexpected":
        decoder = patch(
            "custom_components.hoben.coordinator.decode_v4_snapshot",
            side_effect=RuntimeError(PRIVATE_TEXT),
        )
    else:
        words = (0,) * 19 if failure == "shape" else (65536,) * 20
        client.async_refresh.return_value = replace(snapshot, registers=words)
        decoder = patch(
            "custom_components.hoben.coordinator.decode_v4_snapshot",
            wraps=decode_v4_snapshot,
        )
    with decoder, caplog.at_level("DEBUG"):
        await coordinator.async_refresh()
    assert isinstance(coordinator.last_exception, ConfigEntryError)
    assert coordinator.data is before
    assert entry.data[CONF_DEVICE_GUID] == DEVICE_GUID
    assert_private_values_absent(
        caplog.text + "".join(traceback.format_exception(coordinator.last_exception))
    )


@pytest.mark.parametrize("cancelled", [False, True])
async def test_partial_platform_setup_failure_unloads_entities_and_closes_client(
    hass, entry, client_factory, client, snapshot, monkeypatch, caplog, cancelled
):
    coordinators = []

    def make_coordinator(*args):
        coordinator = HobenDataUpdateCoordinator(*args)
        coordinators.append(coordinator)
        return coordinator

    monkeypatch.setattr(
        "custom_components.hoben.coordinator.HobenDataUpdateCoordinator",
        make_coordinator,
    )
    original = hass.config_entries.async_forward_entry_setups
    waiting = asyncio.Event()

    async def partial_setup(config_entry, platforms):
        await original(config_entry, ("sensor",))
        assert coordinators[0]._listeners
        if cancelled:
            waiting.set()
            await asyncio.Future()
        raise RuntimeError(PRIVATE_TEXT)

    with patch.object(
        hass.config_entries, "async_forward_entry_setups", side_effect=partial_setup
    ):
        if cancelled:
            setup = hass.async_create_task(
                hass.config_entries.async_setup(entry.entry_id)
            )
            await waiting.wait()
            setup.cancel()
            with pytest.raises(asyncio.CancelledError):
                await setup
        else:
            assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert not hasattr(entry, "runtime_data")
    assert not coordinators[0]._listeners
    assert coordinators[0]._shutdown_requested
    client.async_close.assert_awaited_once_with()
    assert_private_values_absent(caplog.text)


async def test_refused_platform_unload_keeps_runtime_until_success(
    hass, entry, client_factory, client, snapshot
):
    coordinator = await setup_entities(hass, entry, client, snapshot)
    with patch.object(
        hass.config_entries, "async_unload_platforms", return_value=False
    ):
        assert not await hass.config_entries.async_unload(entry.entry_id)
    assert coordinator._listeners
    assert not coordinator._shutdown_requested
    client.async_close.assert_not_awaited()
    # HA marks FAILED_UNLOAD as unrecoverable. Test the integration's cleanup
    # directly to finish the test without leaving a timer or weakening HA rules.
    from custom_components.hoben import async_unload_entry

    assert entry.state is ConfigEntryState.FAILED_UNLOAD
    assert await async_unload_entry(hass, entry)
    assert not coordinator._listeners
    client.async_close.assert_awaited_once_with()


async def test_real_client_entities_cannot_send_control_or_pairing_frames(
    hass, entry, snapshot, monkeypatch
):
    """Keep protocol/HA code real; replace only the TLS transport with a script."""
    opened = (
        b"\x04\x00\x00\x00\x00\x00\x00\x00\x05\x02\x08\x00\x00\x00"
        + DEVICE_GUID.encode()
        + b"\x00\x02"
    )
    response = bytes.fromhex("0E FF FF 00 00 00 2B 01 04 28") + b"".join(
        value.to_bytes(2, "big") for value in WORDS
    )
    transport = Mock(
        spec=AsyncTlsTransport,
        connect=AsyncMock(),
        write=AsyncMock(),
        read=AsyncMock(side_effect=[opened, response]),
        close=AsyncMock(),
    )
    factory = Mock(return_value=transport)
    monkeypatch.setattr("custom_components.hoben.client.AsyncTlsTransport", factory)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    for _ in range(3):
        for entity in (HobenSensor(entry, item) for item in SENSORS):
            entity.native_value
            entity.available
        for entity in (HobenBinarySensor(entry, item) for item in BINARY_SENSORS):
            entity.is_on
            entity.available
    [opening, read] = transport.write.await_args_list
    assert opening.args[0][0] == 3
    assert opening.args[0][1:33] == NORMALIZED_USER_GUID.encode()
    assert read.args[0] == bytes.fromhex("0D FF FF 00 00 00 06 01 04 04 00 00 14")
    transport.close.assert_awaited_once_with()
    factory.assert_called_once_with()


@pytest.mark.parametrize("language", ["en", "fr"])
async def test_translated_names_are_used_by_real_entities(
    hass, entry, client_factory, client, snapshot, language
):
    hass.config.language = language
    await setup_entities(hass, entry, client, snapshot)
    entities = registry_entities(hass, entry)
    assert entities["ambient_temperature"].original_name == (
        "Ambient temperature" if language == "en" else "Température ambiante"
    )
    assert entities["controller_on_off"].original_name == (
        "Controller on/off request"
        if language == "en"
        else "Consigne marche/arrêt du contrôleur"
    )
