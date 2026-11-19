"""Read-only Home Assistant lifecycle for the unofficial Hoben integration.

Keep HA imports inside lifecycle functions (or TYPE_CHECKING). Importing the
protocol package must still work in the lightweight, HA-free test environment.
"""

from __future__ import annotations

import asyncio
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
# Leave the existing transport's five-second close budget inside the 15 s
# bootstrap target. This deadline stops setup, not the protocol's #212 retries
# once an entry is loaded. HA owns retries between fully cleaned setup attempts.
SETUP_REFRESH_TIMEOUT = 10.0


@dataclass(slots=True, repr=False)
class HobenRuntimeData:
    """Entry-owned client/coordinator; never generically repr sensitive storage."""

    client: HobenClient
    coordinator: HobenDataUpdateCoordinator
    setup_cleanup_failed: bool = False


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

    previous = getattr(entry, "runtime_data", None)
    if isinstance(previous, HobenRuntimeData) and previous.setup_cleanup_failed:
        # HA also permits reload from SETUP_ERROR. Retain the failed owner as
        # a barrier: explicit reload is not evidence its old socket was closed.
        raise ConfigEntryError("Hoben setup cleanup not verified")

    try:
        client = HobenClient(
            user_guid=entry.data[CONF_USER_GUID],
            device_guid=entry.data[CONF_DEVICE_GUID],
            ha_reconnect=True,
            ha_fast_reconnect=True,
            push_updates=True,
        )
    except (KeyError, HobenInvalidInputError):
        raise ConfigEntryError("Stored Hoben connection data is invalid") from None
    except Exception as error:
        log_unexpected_error(_LOGGER, error)
        raise ConfigEntryError("Unexpected Hoben client failure") from None

    coordinator = HobenDataUpdateCoordinator(hass, entry, client)
    platforms_started = False
    try:
        try:
            async with asyncio.timeout(SETUP_REFRESH_TIMEOUT) as deadline:
                while True:
                    try:
                        await coordinator.async_config_entry_first_refresh()
                        break
                    except ConfigEntryNotReady:
                        # A brief recovery may finish within this setup budget.
                        # Never park HA bootstrap through the long-lived owner's
                        # reconnect/backoff or uncertain-acquisition waiters.
                        if (
                            client.ha_recovery_pending is not True
                            and coordinator.data_updated_deferred is not True
                        ):
                            raise
        except TimeoutError:
            if not deadline.expired():
                raise  # An inner error is not proof that our deadline elapsed.
            raise ConfigEntryNotReady(
                "Hoben service unavailable during setup"
            ) from None
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
        if client.ha_reconnect_enabled is True:
            observation = client.session_observation
            if not (
                observation.stopped is True
                and observation.active is False
                and observation.cleanup_failed is False
            ):
                # No platforms/snapshot are registered. Keep only the stopped
                # owners and failure latch so native retry OR reload cannot
                # replace an unverified socket. Cancellation still propagates.
                entry.runtime_data = HobenRuntimeData(client, coordinator, True)
                if isinstance(error, asyncio.CancelledError):
                    raise
                raise ConfigEntryError("Hoben setup cleanup not verified") from None
        if isinstance(error, ConfigEntryNotReady):
            _LOGGER.info("Hoben setup event=unavailable retry=native_ha")
        if isinstance(error, Exception) and not isinstance(
            error, (ConfigEntryAuthFailed, ConfigEntryError, ConfigEntryNotReady)
        ):
            log_unexpected_error(_LOGGER, error)
            raise ConfigEntryError("Unexpected Hoben setup failure") from None
        raise
    _LOGGER.info("Hoben setup event=initial_snapshot_ready")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HobenConfigEntry) -> bool:
    """Remove entity listeners, then stop scheduling and any active refresh."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.coordinator.async_shutdown()
        await entry.runtime_data.client.async_close()
    return unload_ok
