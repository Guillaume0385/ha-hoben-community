"""Allowlisted support metadata from memory; never export storage or stove data.

The protocol models own their safe_report() contracts. Select only established
scalar fields from those reports, so future additions cannot silently enlarge
the public HA export. Do not inspect exception chains or serialize whole objects.
"""

from collections.abc import Mapping
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryError
from homeassistant.helpers.update_coordinator import UpdateFailed

from . import HobenConfigEntry, HobenRuntimeData
from .client import HobenClient, RawStoveSnapshot
from .const import DOMAIN, UPDATE_INTERVAL
from .coordinator import HobenCoordinatorData
from .exceptions import (
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
from .myhoben import CloseClientReason
from .profiles import StoveProfile

_PROFILES = frozenset(profile.value for profile in StoveProfile)
_ERROR_CODES = frozenset(
    error_type.code
    for error_type in (
        HobenError,
        HobenInvalidInputError,
        HobenAuthorizationRequiredError,
        HobenAuthorizationCodeError,
        HobenClosedError,
        HobenInvalidCredentialsError,
        HobenUnsupportedProfileError,
        HobenProtocolError,
        HobenAmbiguousSessionError,
        HobenModbusError,
        HobenTransportError,
        HobenTimeoutError,
        HobenRefreshExhaustedError,
        HobenClientClosedError,
    )
)
# These are public OpenedClient metadata widths/counts, not register values.
_SNAPSHOT_NUMBERS = {
    "product_type": 255,
    "product_revision": 255,
    "software_major": 255,
    "software_minor": 255,
    "application_version": 65535,
    "register_count": 125,
}


def _select_report(
    model: HobenClient | RawStoveSnapshot | HobenError,
    text_fields: Mapping[str, frozenset[str]],
    number_fields: Mapping[str, int] | None = None,
    boolean_fields: tuple[str, ...] = (),
) -> dict[str, str | int | bool]:
    """Copy only approved primitive fields, with bounded values and no coercion.

    A broken safe-report contract fails closed. Never include arbitrary return
    values, nested objects, unknown keys or the exception raised by the report.
    """
    try:
        report = model.safe_report()
    except Exception:
        return {}
    if type(report) is not dict:
        return {}

    result: dict[str, str | int | bool] = {}
    for field, allowed in text_fields.items():
        value = report.get(field)
        if type(value) is str and value in allowed:
            result[field] = value
    for field, maximum in (number_fields or {}).items():
        value = report.get(field)
        if type(value) is int and 0 <= value <= maximum:
            result[field] = value
    for field in boolean_fields:
        value = report.get(field)
        if type(value) is bool:
            result[field] = value
    return result


def _safe_error(error: Exception | None) -> dict[str, str | int | bool] | None:
    """Prefer typed public codes; HA wrappers get fixed categories, no chains."""
    if error is None:
        return None
    if isinstance(error, HobenError):
        report = _select_report(
            error,
            {
                "error": _ERROR_CODES,
                "reason": frozenset(reason.value for reason in CloseClientReason),
                "profile": _PROFILES,
                "failure": _ERROR_CODES,
            },
            {"exception_code": 255, "attempts": 2},
        )
        if "error" in report:
            return report
    elif isinstance(error, ConfigEntryAuthFailed):
        return {"error": "authentication_failed"}
    elif isinstance(error, UpdateFailed):
        return {"error": "update_failed"}
    elif isinstance(error, ConfigEntryError):
        return {"error": "config_entry_error"}
    return {"error": "unexpected_error"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: HobenConfigEntry
) -> dict[str, Any]:
    """Return bounded, deterministic Hoben metadata without I/O or mutations.

    No entry ID, title, unique ID/fingerprint, data/options, entity state or
    decoded household value is read. HA adds its standard system/manifest
    metadata around this integration-owned payload when downloading diagnostics.
    """
    runtime = getattr(entry, "runtime_data", None)
    result: dict[str, Any] = {
        "domain": DOMAIN,
        "entry": {
            "state": entry.state.value,
            "version": entry.version,
            "minor_version": entry.minor_version,
        },
        "runtime_available": isinstance(runtime, HobenRuntimeData),
    }
    if not isinstance(runtime, HobenRuntimeData):
        return result

    coordinator = runtime.coordinator
    data = coordinator.data
    snapshot = data.raw if isinstance(data, HobenCoordinatorData) else None
    snapshot_available = isinstance(snapshot, RawStoveSnapshot)
    result["client"] = _select_report(
        runtime.client,
        {"state": frozenset({"ready", "closed"}), "profile": _PROFILES},
        boolean_fields=("has_assigned_device_guid",),
    )
    result["coordinator"] = {
        "last_update_success": coordinator.last_update_success is True,
        "update_interval_seconds": int(UPDATE_INTERVAL.total_seconds()),
        "snapshot_available": snapshot_available,
        "last_error": _safe_error(coordinator.last_exception),
    }
    result["snapshot"] = (
        _select_report(
            snapshot,
            {"state": frozenset({"read"}), "profile": _PROFILES},
            _SNAPSHOT_NUMBERS,
        )
        if snapshot_available
        else None
    )
    return result
