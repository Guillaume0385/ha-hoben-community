"""Explicit household-value export for manual, private V4 research only.

Never use this report in public logs, GitHub artifacts or an automated workflow.
The caller enforces the manual-mode/GitHub Actions guard before client creation.
No Home Assistant dependency, identifiers, session object or generic asdict export.
"""

from custom_components.hoben.client import RawStoveSnapshot
from custom_components.hoben.v4_state import decode_v4_snapshot


def build_private_v4_report(
    snapshot: RawStoveSnapshot, *, timestamp_utc: str
) -> dict[str, object]:
    """Report the twenty words and exactly sixteen candidate HA value properties.

    raw_value is the UInt16 for scalar fields, the extracted byte/code for packed
    mode/OnOff/power/state, or the selected bit (0/1) for derogation flags. Full
    words remain indexed by their register address. ha_value follows the same
    inactive-derogation policy as sensor.py; disabled-by-default ambient sensors
    are included for comparison with the property they would expose if enabled.
    """
    state = decode_v4_snapshot(snapshot)
    registers = snapshot.registers
    rows = (
        ("ambient_temperature", 1031, registers[7], state.ambient_temperature),
        ("target_temperature", 1032, registers[8], state.target_temperature),
        ("power_level", 1030, state.power_level_raw, state.power_level),
        ("operation_state", 1030, state.operation_state_raw, state.operation_state),
        ("operation_mode", 1024, state.operation_mode_raw, state.operation_mode),
        ("ventilation_mode", 1028, state.ventilation_mode_raw, state.ventilation_mode),
        ("smoke_temperature", 1041, registers[17], state.smoke_temperature),
        (
            "combustion_air_temperature",
            1040,
            registers[16],
            state.combustion_air_temperature,
        ),
        (
            "wired_ambient_temperature",
            1039,
            registers[15],
            state.wired_ambient_temperature,
        ),
        ("rf_ambient_temperature", 1043, registers[19], state.rf_ambient_temperature),
        ("derogation_temperature", 1025, registers[1], state.derogation_temperature),
        ("derogation_start_delay", 1026, registers[2], state.derogation_start_delay),
        ("derogation_duration", 1027, registers[3], state.derogation_duration),
        (
            "derogation_active",
            1035,
            (state.information_raw >> 5) & 1,
            state.derogation_active,
        ),
        (
            "derogation_scheduled",
            1035,
            (state.information_raw >> 6) & 1,
            state.derogation_scheduled,
        ),
        ("controller_on_off", 1024, state.on_off_raw, state.on_off),
    )
    derogation_keys = {
        "derogation_temperature",
        "derogation_start_delay",
        "derogation_duration",
    }
    derogation_enabled = state.derogation_active or state.derogation_scheduled
    entities = {
        key: {
            "register_address": address,
            "raw_value": raw,
            "decoded_value": decoded,
            "ha_value": (
                None if key in derogation_keys and not derogation_enabled else decoded
            ),
        }
        for key, address, raw, decoded in rows
    }
    entities["derogation_active"]["bit_mask"] = 0x0020
    entities["derogation_scheduled"]["bit_mask"] = 0x0040
    return {
        "state": "v4_validation_values_captured",
        "timestamp_utc": timestamp_utc,
        "profile": snapshot.profile.value,
        "registers": {
            str(1024 + index): value for index, value in enumerate(registers)
        },
        "entities": entities,
    }
