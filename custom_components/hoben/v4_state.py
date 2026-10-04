"""Pure V4 register semantics recovered statically from MyHOBEN (protocol.md §8).

Live raw/UI comparison is still required on the reference Osmose before merge.
Unknown codes stay unknown rather than reproducing MyHOBEN's UI fallbacks.
"""

from dataclasses import dataclass
from enum import StrEnum

from .client import RawStoveSnapshot
from .exceptions import HobenProtocolError, HobenUnsupportedProfileError
from .profiles import StoveProfile


class V4OperationMode(StrEnum):
    """V4 mode byte from 1024; these are read-back values, never controls."""

    AUTOMATIC = "automatic"
    MAGASIN = "magasin"
    MANUAL = "manual"


class V4OperationState(StrEnum):
    """V4-specific state byte from 1030, distinct from generic EOperationState."""

    OFF = "off"
    END_OF_COMBUSTION = "end_of_combustion"
    STANDARD_START = "standard_start"
    BLACKOUT_START = "blackout_start"
    STABILIZATION = "stabilization"
    COMBUSTION_MANAGEMENT = "combustion_management"


class V4VentilationMode(StrEnum):
    """The three established V4 ventilation codes from register 1028."""

    NORMAL = "normal"
    SILENCE = "silence"
    BOOST = "boost"


class V4DecodeError(HobenProtocolError):
    """Invalid local snapshot shape/range; fixed text never includes raw values."""

    code = "invalid_v4_snapshot"


@dataclass(frozen=True, slots=True)
class V4StoveState:
    """Immutable semantic values plus explicit undecoded/unknown raw fields.

    Temperatures are °C, timings are minutes and power is a percentage. Inactive
    derogation read-back is retained here; HA hides its three numeric values
    unless active or scheduled. No incomplete bitmap/date/fault/PVI is guessed.
    This object contains household values: do not publish its repr/asdict live.
    """

    operation_mode: V4OperationMode | None
    operation_mode_raw: int
    on_off: bool | None
    on_off_raw: int
    derogation_temperature: float | None
    derogation_start_delay: int
    derogation_duration: int
    ventilation_mode: V4VentilationMode | None
    ventilation_mode_raw: int
    combustion_fault_raw: int
    power_level: int | None
    power_level_raw: int
    operation_state: V4OperationState | None
    operation_state_raw: int
    ambient_temperature: float | None
    target_temperature: float | None
    combined_ventilation_power_raw: int
    warnings_raw: int
    information_raw: int
    derogation_active: bool
    derogation_scheduled: bool
    date_year_month_raw: int
    date_day_hour_raw: int
    time_minute_second_raw: int
    wired_ambient_temperature: float | None
    combustion_air_temperature: float | None
    smoke_temperature: float | None
    pvi_raw: int
    rf_ambient_temperature: float | None


_OPERATION_MODES = {
    0: V4OperationMode.AUTOMATIC,
    1: V4OperationMode.MAGASIN,
    2: V4OperationMode.MANUAL,
}
_OPERATION_STATES = {
    0: V4OperationState.OFF,
    1: V4OperationState.END_OF_COMBUSTION,
    2: V4OperationState.STANDARD_START,
    3: V4OperationState.BLACKOUT_START,
    4: V4OperationState.STABILIZATION,
    5: V4OperationState.COMBUSTION_MANAGEMENT,
}
_VENTILATION_MODES = {
    0: V4VentilationMode.NORMAL,
    1: V4VentilationMode.SILENCE,
    2: V4VentilationMode.BOOST,
}


def _require_uint16(value: int) -> None:
    """Reject coercion, bools and out-of-range inputs without echoing them."""
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 65535:
        raise V4DecodeError()


def decode_v4_temperature(raw: int) -> float | None:
    """Reinterpret UInt16 as Int16, then divide by ten; 0x0FFF is unavailable.

    Divide the signed integer directly instead of multiplying by an approximate
    binary 0.1; no other sentinel, physical clamp or UI editing range applies.
    """
    _require_uint16(raw)
    if raw == 0x0FFF:
        return None
    signed = raw - 65536 if raw & 0x8000 else raw
    return signed / 10


def decode_v4_snapshot(snapshot: RawStoveSnapshot) -> V4StoveState:
    """Decode exactly 1024..1043 without I/O or changing the client's raw API."""
    if not isinstance(snapshot, RawStoveSnapshot):
        raise V4DecodeError()
    if snapshot.profile is not StoveProfile.V4:
        raise HobenUnsupportedProfileError(snapshot.profile)
    registers = snapshot.registers
    if not isinstance(registers, tuple) or len(registers) != 20:
        raise V4DecodeError()
    for raw in registers:
        _require_uint16(raw)

    mode_raw, on_off_raw = registers[0] >> 8, registers[0] & 0xFF
    power_raw, state_raw = registers[6] >> 8, registers[6] & 0xFF
    target = decode_v4_temperature(registers[8])
    # The main setpoint UI additionally hides signed values below raw 50 (5 °C).
    if target is not None and target < 5:
        target = None
    information = registers[11]

    return V4StoveState(
        operation_mode=_OPERATION_MODES.get(mode_raw),
        operation_mode_raw=mode_raw,
        on_off={0: False, 1: True}.get(on_off_raw),
        on_off_raw=on_off_raw,
        derogation_temperature=decode_v4_temperature(registers[1]),
        derogation_start_delay=registers[2],
        derogation_duration=registers[3],
        ventilation_mode=_VENTILATION_MODES.get(registers[4]),
        ventilation_mode_raw=registers[4],
        combustion_fault_raw=registers[5],
        power_level=power_raw if power_raw <= 100 else None,
        power_level_raw=power_raw,
        operation_state=_OPERATION_STATES.get(state_raw),
        operation_state_raw=state_raw,
        ambient_temperature=decode_v4_temperature(registers[7]),
        target_temperature=target,
        combined_ventilation_power_raw=registers[9],
        warnings_raw=registers[10],
        information_raw=information,
        derogation_active=bool(information & 0x0020),
        derogation_scheduled=bool(information & 0x0040),
        date_year_month_raw=registers[12],
        date_day_hour_raw=registers[13],
        time_minute_second_raw=registers[14],
        wired_ambient_temperature=decode_v4_temperature(registers[15]),
        combustion_air_temperature=decode_v4_temperature(registers[16]),
        smoke_temperature=decode_v4_temperature(registers[17]),
        pvi_raw=registers[18],
        rf_ambient_temperature=decode_v4_temperature(registers[19]),
    )
