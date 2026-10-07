"""Allowlisted support metadata from memory; never export storage or stove data.

The protocol models own their safe_report() contracts. Select only established
scalar fields from those reports, so future additions cannot silently enlarge
the public HA export. Do not inspect exception chains or serialize whole objects.
"""

from typing import Any

from homeassistant.core import HomeAssistant

from . import HobenConfigEntry, HobenRuntimeData
from .client import RawStoveSnapshot
from .const import DOMAIN, UPDATE_INTERVAL
from .coordinator import HobenCoordinatorData
from .safe_reports import PROFILES, safe_error_report, select_report

# These are public OpenedClient metadata widths/counts, not register values.
_SNAPSHOT_NUMBERS = {
    "product_type": 255,
    "product_revision": 255,
    "software_major": 255,
    "software_minor": 255,
    "application_version": 65535,
    "register_count": 125,
}


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
    result["client"] = select_report(
        runtime.client,
        {"state": frozenset({"ready", "closed"}), "profile": PROFILES},
        boolean_fields=("has_assigned_device_guid",),
    )
    result["coordinator"] = {
        "last_update_success": coordinator.last_update_success is True,
        "update_interval_seconds": int(UPDATE_INTERVAL.total_seconds()),
        "snapshot_available": snapshot_available,
        "last_error": (
            safe_error_report(coordinator.last_exception)
            if coordinator.last_update_success is not True
            else None
        ),
    }
    result["snapshot"] = (
        select_report(
            snapshot,
            {"state": frozenset({"read"}), "profile": PROFILES},
            _SNAPSHOT_NUMBERS,
        )
        if snapshot_available
        else None
    )
    return result
