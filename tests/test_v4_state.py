"""Deterministic V4 decoding; no HA import, identifiers or live household data."""

from dataclasses import FrozenInstanceError, asdict, replace

import pytest

from custom_components.hoben.client import RawStoveSnapshot
from custom_components.hoben.exceptions import HobenUnsupportedProfileError
from custom_components.hoben.profiles import StoveProfile
from custom_components.hoben.v4_state import (
    V4DecodeError,
    V4OperationMode,
    V4OperationState,
    V4VentilationMode,
    decode_v4_snapshot,
    decode_v4_temperature,
)


def snapshot(**registers):
    """Build synthetic words by register address, independently of decoder offsets."""
    words = [0] * 20
    for address, value in registers.items():
        words[int(address) - 1024] = value
    return RawStoveSnapshot(StoveProfile.V4, tuple(words), 5, 0, 8, 2, 512)


@pytest.mark.parametrize(
    "profile", [p for p in StoveProfile if p is not StoveProfile.V4]
)
def test_requires_v4(profile):
    with pytest.raises(HobenUnsupportedProfileError):
        decode_v4_snapshot(replace(snapshot(), profile=profile))


@pytest.mark.parametrize("count", [0, 19, 21])
def test_requires_exactly_twenty_registers(count):
    with pytest.raises(V4DecodeError, match="^invalid_v4_snapshot$"):
        decode_v4_snapshot(replace(snapshot(), registers=(0,) * count))


@pytest.mark.parametrize("invalid", [-1, 65536, True, 1.5, "PRIVATE"])
def test_invalid_word_rejected_without_payload(invalid):
    with pytest.raises(V4DecodeError, match="^invalid_v4_snapshot$"):
        decode_v4_snapshot(snapshot(**{"1042": invalid}))
    with pytest.raises(V4DecodeError, match="^invalid_v4_snapshot$"):
        decode_v4_temperature(invalid)


@pytest.mark.parametrize("invalid", [None, object(), "PRIVATE"])
def test_requires_raw_snapshot(invalid):
    with pytest.raises(V4DecodeError):
        decode_v4_snapshot(invalid)


def test_requires_immutable_register_tuple():
    with pytest.raises(V4DecodeError):
        decode_v4_snapshot(replace(snapshot(), registers=[0] * 20))


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (213, 21.3),
        (0, 0.0),
        (1, 0.1),
        (3, 0.3),
        (0xFFFF, -0.1),
        (65536 - 123, -12.3),
        (0x0FFF, None),
        (0x8000, -3276.8),
        (0x7FFF, 3276.7),
        (0x1000, 409.6),
    ],
)
def test_temperature_int16_sentinel_and_precision(raw, expected):
    # Exact equality, not approx: dividing an integer by ten must give the same
    # float as the literal, including 0.3 (multiplication by 0.1 would differ).
    assert decode_v4_temperature(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(0, None), (49, None), (50, 5.0), (51, 5.1), (0xFFFF, None), (0x0FFF, None)],
)
def test_main_target_hides_signed_values_below_fifty(raw, expected):
    assert decode_v4_snapshot(snapshot(**{"1032": raw})).target_temperature == expected


@pytest.mark.parametrize(
    ("address", "field"),
    [
        (1025, "derogation_temperature"),
        (1031, "ambient_temperature"),
        (1032, "target_temperature"),
        (1039, "wired_ambient_temperature"),
        (1040, "combustion_air_temperature"),
        (1041, "smoke_temperature"),
        (1043, "rf_ambient_temperature"),
    ],
)
@pytest.mark.parametrize("raw", [0x0FFF, 213, 65536 - 123])
def test_every_documented_temperature(address, field, raw):
    expected = decode_v4_temperature(raw)
    if address == 1032 and raw == 65536 - 123:
        expected = None
    state = decode_v4_snapshot(snapshot(**{str(address): raw}))
    assert getattr(state, field) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (0, V4OperationMode.AUTOMATIC),
        (1, V4OperationMode.MAGASIN),
        (2, V4OperationMode.MANUAL),
        (3, None),
        (255, None),
    ],
)
@pytest.mark.parametrize("on_off", [0, 1, 2, 255])
def test_packed_mode_onoff_without_fallback(raw, expected, on_off):
    state = decode_v4_snapshot(snapshot(**{"1024": raw << 8 | on_off}))
    assert state.operation_mode is expected
    assert state.operation_mode_raw == raw
    assert state.on_off is {0: False, 1: True}.get(on_off)
    assert state.on_off_raw == on_off


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (0, V4OperationState.OFF),
        (1, V4OperationState.END_OF_COMBUSTION),
        (2, V4OperationState.STANDARD_START),
        (3, V4OperationState.BLACKOUT_START),
        (4, V4OperationState.STABILIZATION),
        (5, V4OperationState.COMBUSTION_MANAGEMENT),
        (6, None),
        (255, None),
    ],
)
@pytest.mark.parametrize("power", [0, 1, 99, 100, 101, 255])
def test_packed_v4_power_state_without_fallback(raw, expected, power):
    state = decode_v4_snapshot(snapshot(**{"1030": power << 8 | raw}))
    assert state.operation_state is expected
    assert state.operation_state_raw == raw
    assert state.power_level == (power if power <= 100 else None)
    assert state.power_level_raw == power


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (0, V4VentilationMode.NORMAL),
        (1, V4VentilationMode.SILENCE),
        (2, V4VentilationMode.BOOST),
        (3, None),
        (256, None),
        (65535, None),
    ],
)
def test_ventilation_full_word_not_low_byte(raw, expected):
    state = decode_v4_snapshot(snapshot(**{"1028": raw}))
    assert state.ventilation_mode is expected
    assert state.ventilation_mode_raw == raw


@pytest.mark.parametrize("information", [0, 0x20, 0x40, 0x60, 0xFF9F, 0xFFFF])
def test_only_established_derogation_bits(information):
    state = decode_v4_snapshot(
        snapshot(
            **{
                "1025": 211,
                "1026": 37,
                "1027": 181,
                "1035": information,
            }
        )
    )
    assert state.derogation_active is bool(information & 0x20)
    assert state.derogation_scheduled is bool(information & 0x40)
    # The pure decoder retains read-back even when HA must hide inactive values.
    assert state.derogation_temperature == 21.1
    assert state.derogation_start_delay == 37
    assert state.derogation_duration == 181
    assert state.information_raw == information


def test_all_twenty_address_offsets_and_partial_fields():
    raw = snapshot(**{str(address): address for address in range(1024, 1044)})
    state = decode_v4_snapshot(raw)
    assert asdict(state) == {
        "operation_mode": None,
        "operation_mode_raw": 4,
        "on_off": False,
        "on_off_raw": 0,
        "derogation_temperature": 102.5,
        "derogation_start_delay": 1026,
        "derogation_duration": 1027,
        "ventilation_mode": None,
        "ventilation_mode_raw": 1028,
        "combustion_fault_raw": 1029,
        "power_level": 4,
        "power_level_raw": 4,
        "operation_state": None,
        "operation_state_raw": 6,
        "ambient_temperature": 103.1,
        "target_temperature": 103.2,
        "combined_ventilation_power_raw": 1033,
        "warnings_raw": 1034,
        "information_raw": 1035,
        "derogation_active": False,
        "derogation_scheduled": False,
        "date_year_month_raw": 1036,
        "date_day_hour_raw": 1037,
        "time_minute_second_raw": 1038,
        "wired_ambient_temperature": 103.9,
        "combustion_air_temperature": 104.0,
        "smoke_temperature": 104.1,
        "pvi_raw": 1042,
        "rf_ambient_temperature": 104.3,
    }


def test_immutable_hashable_equal_without_mutating_raw():
    raw = snapshot(**{"1031": 213})
    before = asdict(raw)
    state = decode_v4_snapshot(raw)
    assert state == decode_v4_snapshot(raw)
    assert hash(state) == hash(decode_v4_snapshot(raw))
    assert state != decode_v4_snapshot(snapshot(**{"1031": 214}))
    with pytest.raises(FrozenInstanceError):
        state.ambient_temperature = 0
    assert asdict(raw) == before
