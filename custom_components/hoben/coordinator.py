"""Home Assistant scheduling over the HA-independent read-only client API."""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import HobenClient, RawStoveSnapshot
from .const import CONF_DEVICE_GUID, DOMAIN, UPDATE_INTERVAL
from .exceptions import (
    HobenAuthorizationRequiredError,
    HobenError,
    HobenInvalidCredentialsError,
    HobenTransportError,
    HobenUnsupportedProfileError,
)
from .helpers import log_unexpected_error
from .myhoben import INITIAL_DEVICE_GUID
from .profiles import StoveProfile
from .safe_reports import wrap_error
from .v4_state import V4StoveState, decode_v4_snapshot

if TYPE_CHECKING:
    from . import HobenConfigEntry

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class HobenCoordinatorData:
    """Keep raw metadata and decoded state from the same single client refresh."""

    raw: RawStoveSnapshot
    state: V4StoveState


class HobenDataUpdateCoordinator(DataUpdateCoordinator[HobenCoordinatorData]):
    """Poll and decode every 60 seconds; the client alone owns bounded retries."""

    def __init__(
        self, hass: HomeAssistant, entry: "HobenConfigEntry", client: HobenClient
    ) -> None:
        """Associate scheduling/shutdown with the entry without exposing its data."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=UPDATE_INTERVAL,
            always_update=False,
        )
        self.client = client

    async def _async_update_data(self) -> HobenCoordinatorData:
        """Decode before persisting a successful nonzero identity change."""
        try:
            snapshot = await self.client.async_refresh()
            if snapshot.profile is not StoveProfile.V4:
                raise HobenUnsupportedProfileError(snapshot.profile)
            state = decode_v4_snapshot(snapshot)
            device_guid = self.client.device_guid_for_persistence
            if device_guid == INITIAL_DEVICE_GUID:
                raise ConfigEntryError("Hoben client identity was not assigned")
            # Copy through HA's update API; retain other data fields and options.
            # The entry is always supplied explicitly to DataUpdateCoordinator.
            assert self.config_entry is not None
            if device_guid != self.config_entry.data[CONF_DEVICE_GUID]:
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data={**self.config_entry.data, CONF_DEVICE_GUID: device_guid},
                )
            return HobenCoordinatorData(raw=snapshot, state=state)
        except HobenInvalidCredentialsError as error:
            raise wrap_error(
                ConfigEntryAuthFailed, "Hoben identifier was rejected", error
            ) from None
        except HobenAuthorizationRequiredError as error:
            raise wrap_error(
                ConfigEntryAuthFailed,
                "Hoben authorization is required; pairing is not supported yet",
                error,
            ) from None
        except HobenTransportError as error:
            raise wrap_error(
                UpdateFailed, "Cannot connect to the Hoben service", error
            ) from None
        except HobenUnsupportedProfileError as error:
            raise wrap_error(
                ConfigEntryError, "Hoben stove profile is not supported", error
            ) from None
        except HobenError as error:
            raise wrap_error(
                ConfigEntryError,
                "Hoben protocol response could not be accepted",
                error,
            ) from None
        except ConfigEntryError as error:
            raise wrap_error(
                ConfigEntryError, "Hoben client setup failed", error
            ) from None
        except Exception as error:
            log_unexpected_error(_LOGGER, error)
            raise wrap_error(
                ConfigEntryError, "Unexpected Hoben client failure", error
            ) from None
