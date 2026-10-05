"""Read-only Home Assistant lifecycle for the unofficial Hoben integration.

Keep HA imports inside lifecycle functions (or TYPE_CHECKING). Importing the
protocol package must still work in the lightweight, HA-free test environment.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .client import HobenClient
from .const import CONF_DEVICE_GUID, CONF_USER_GUID, DOMAIN
from .exceptions import HobenInvalidInputError
from .helpers import log_unexpected_error, user_guid_fingerprint

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .coordinator import HobenDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ("sensor", "binary_sensor")


@dataclass(slots=True, repr=False)
class HobenRuntimeData:
    """Entry-owned client/coordinator; never generically repr sensitive storage."""

    client: HobenClient
    coordinator: HobenDataUpdateCoordinator


type HobenConfigEntry = ConfigEntry[HobenRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: HobenConfigEntry) -> bool:
    """Require a decoded refresh before registering a device and its platforms."""
    from homeassistant.exceptions import (
        ConfigEntryAuthFailed,
        ConfigEntryError,
        ConfigEntryNotReady,
    )
    from homeassistant.helpers import device_registry as dr

    from .coordinator import HobenDataUpdateCoordinator

    try:
        client = HobenClient(
            user_guid=entry.data[CONF_USER_GUID],
            device_guid=entry.data[CONF_DEVICE_GUID],
        )
    except (KeyError, HobenInvalidInputError):
        raise ConfigEntryError("Stored Hoben connection data is invalid") from None
    except Exception as error:
        log_unexpected_error(_LOGGER, error)
        raise ConfigEntryError("Unexpected Hoben client failure") from None

    coordinator = HobenDataUpdateCoordinator(hass, entry, client)
    platforms_started = False
    try:
        await coordinator.async_config_entry_first_refresh()
        snapshot = coordinator.data.raw
        dr.async_get(hass).async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, user_guid_fingerprint(entry.data[CONF_USER_GUID]))},
            manufacturer="Hoben",
            name="Hoben stove",
            # V4 is a confirmed protocol profile, not a commercial model name.
            model=f"Protocol {snapshot.profile.value.upper()}",
            sw_version=f"{snapshot.software_major}.{snapshot.software_minor}",
        )
        entry.runtime_data = HobenRuntimeData(client, coordinator)
        platforms_started = True
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException as error:
        # Includes cancellation; a failed setup must not retain a client or timer.
        if platforms_started:
            try:
                await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
            except Exception as unload_error:
                log_unexpected_error(_LOGGER, unload_error)
        await coordinator.async_shutdown()
        await client.async_close()
        # HA clears runtime_data on successful unload, but retains it after a
        # failed setup. Do not leave a closed client/partial platform runtime.
        if hasattr(entry, "runtime_data"):
            del entry.runtime_data
        if isinstance(error, Exception) and not isinstance(
            error, (ConfigEntryAuthFailed, ConfigEntryError, ConfigEntryNotReady)
        ):
            log_unexpected_error(_LOGGER, error)
            raise ConfigEntryError("Unexpected Hoben setup failure") from None
        raise
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HobenConfigEntry) -> bool:
    """Remove entity listeners, then stop scheduling and any active refresh."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.coordinator.async_shutdown()
        await entry.runtime_data.client.async_close()
    return unload_ok
