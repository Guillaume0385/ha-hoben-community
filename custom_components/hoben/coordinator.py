"""Home Assistant scheduling over the HA-independent read-only client API."""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .client import HobenClient, RawStoveSnapshot
from .const import CONF_DEVICE_GUID, DOMAIN, UPDATE_INTERVAL
from .exceptions import (
    HobenAuthorizationRequiredError,
    HobenClosedError,
    HobenDataUpdatedRecoveryError,
    HobenError,
    HobenInvalidCredentialsError,
    HobenProtocolError,
    HobenTransportError,
    HobenUnsupportedProfileError,
)
from .helpers import log_unexpected_error
from .myhoben import INITIAL_DEVICE_GUID, CloseClientReason
from .profiles import StoveProfile
from .safe_reports import safe_error_report, wrap_error
from .v4_experiment import ExperimentalCloseClientError
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
    """Poll/decode every 60 seconds; the shared client alone owns reconnection."""

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
        self.data_updated_hold = False
        self.data_updated_deferred = False
        self.last_successful_read_at: datetime | None = None
        self._snapshot_hold = False
        self._hold_loss_generation = None
        self._notify_held_failure = False

        async def stop_client(_event) -> None:
            # The one-shot bus listener is already removed before invocation.
            self._unsub_client_stop = None
            await self.async_shutdown()
            await self.client.async_close()

        self._unsub_client_stop = (
            hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stop_client)
            if client.ha_reconnect_enabled is True
            else None
        )

    async def async_shutdown(self) -> None:
        """Cancel scheduling and the entry's shutdown hook; unload closes the client."""
        await super().async_shutdown()
        self._snapshot_hold = self.data_updated_hold = False
        self.async_update_listeners()
        if self._unsub_client_stop is not None:
            self._unsub_client_stop()
            self._unsub_client_stop = None

    @property
    def last_snapshot_held(self) -> bool:
        """Availability of old validated values is never connection/freshness."""
        observation = self.client.session_observation
        return (
            self._snapshot_hold
            and not self._shutdown_requested
            and self.data is not None
            and self.last_successful_read_at is not None
            and observation.stopped is not True
            and observation.loss_generation == self._hold_loss_generation
            and (
                self.client.data_updated_transport_alive is True
                or self.client.acquisition_recovery_pending is True
            )
        )

    @property
    def snapshot_available(self) -> bool:
        """A shutdown or terminal failure cannot be covered by retained data."""
        return (
            not self._shutdown_requested
            and self.client.session_observation.stopped is not True
            and self.data is not None
            and (self.last_update_success or self.last_snapshot_held)
        )

    async def _async_update_data(self) -> HobenCoordinatorData:
        """Retain values during recovery without reporting a successful read."""
        was_holding = self._snapshot_hold
        self._notify_held_failure = False
        if was_holding and not self.last_snapshot_held:
            self._snapshot_hold = self.data_updated_hold = False
            self.async_update_listeners()
            was_holding = False  # Already notified before any potentially slow I/O.
        try:
            if (
                self.data is not None
                and self.client.ha_recovery_pending is True
                and self.client.data_updated_transport_alive is not True
            ):
                # A pending owner is not an acquisition. Return to HA's normal
                # poll instead of waiting forever through repeated open failures.
                source = (
                    self.last_exception
                    if self.last_snapshot_held and self.last_exception is not None
                    else HobenTransportError()
                )
                raise wrap_error(UpdateFailed, "Hoben session recovery pending", source)
            data = await self._async_update_once()
        except HobenDataUpdatedRecoveryError as error:
            self.data_updated_deferred = True
            self._snapshot_hold = self.data_updated_hold = self.data is not None
            self._hold_loss_generation = self.client.session_observation.loss_generation
            raise wrap_error(
                UpdateFailed, "Hoben DataUpdated recovery pending", error
            ) from None
        except Exception as error:
            self.data_updated_deferred = self.data_updated_hold = False
            category = (safe_error_report(error) or {}).get("error")
            self._snapshot_hold = category in {
                "malformed_response",
                "timeout",
                "invalid_v4_snapshot",
            }
            self._hold_loss_generation = self.client.session_observation.loss_generation
            self._snapshot_hold = self.last_snapshot_held
            self._notify_held_failure = was_holding and not self._snapshot_hold
            raise
        except BaseException:
            self.data_updated_deferred = False
            self._snapshot_hold = self.data_updated_hold = False
            # Cancellation closes the real client's owner; notify even though
            # HA re-raises before its usual refresh-finished listener callback.
            self.async_update_listeners()
            raise
        self._snapshot_hold = self.data_updated_hold = False
        self.data_updated_deferred = False
        return data

    def async_update_listeners(self) -> None:
        """Do not report old sensor values as freshly acquired during a hold."""
        if not self.last_snapshot_held:
            super().async_update_listeners()

    def _async_refresh_finished(self) -> None:
        """A genuine failure ends the value hold even after repeated deferrals."""
        super()._async_refresh_finished()
        if self._notify_held_failure and not self.last_update_success:
            self._notify_held_failure = False
            self.async_update_listeners()

    async def _async_update_once(self) -> HobenCoordinatorData:
        """Decode successful reads; also persist identities accepted before loss."""
        try:
            try:
                snapshot = await self.client.async_refresh()
            except (HobenError, asyncio.CancelledError):
                # The shared owner can accept/rotate an identity before its
                # following read fails. Persist that accepted identity without
                # replacing the original error if storage itself fails.
                if self.client.profile is StoveProfile.V4:
                    try:
                        self._persist_identity()
                    except Exception as storage_error:
                        log_unexpected_error(_LOGGER, storage_error)
                raise
            if snapshot.profile is not StoveProfile.V4:
                raise HobenUnsupportedProfileError(snapshot.profile)
            state = decode_v4_snapshot(snapshot)
            self._persist_identity()
            self.last_successful_read_at = dt_util.utcnow()
            return HobenCoordinatorData(raw=snapshot, state=state)
        except HobenDataUpdatedRecoveryError:
            raise
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
        except HobenClosedError as error:
            # Known maintenance/session loss can be temporary. Authentication
            # and unknown refusals stay explicit. HA owns setup backoff; this
            # mapping never recreates the client's lifecycle or replays a read.
            if error.reason in (
                CloseClientReason.INVALID_IDENTIFIER,
                CloseClientReason.AUTHORIZATION_REJECTED,
                CloseClientReason.AUTHORIZATION_TIMEOUT,
            ):
                error_type = ConfigEntryAuthFailed
            elif error.reason is CloseClientReason.SERVER_MAINTENANCE or (
                type(error) is ExperimentalCloseClientError
            ):
                error_type = UpdateFailed
            else:
                error_type = ConfigEntryError
            raise wrap_error(
                error_type, "Hoben protocol response could not be accepted", error
            ) from None
        except HobenProtocolError as error:
            # Recovery rejects/closes the old stream; it never validates an
            # ambiguous frame. Subclasses (internal, unsupported, ambiguous
            # opening or decoding failures) retain permanent error semantics.
            raise wrap_error(
                UpdateFailed if type(error) is HobenProtocolError else ConfigEntryError,
                "Hoben protocol response could not be accepted",
                error,
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

    def _persist_identity(self) -> None:
        """Store only the client's accepted nonzero identity, never report it."""
        device_guid = self.client.device_guid_for_persistence
        if device_guid == INITIAL_DEVICE_GUID:
            raise ConfigEntryError("Hoben client identity was not assigned")
        assert self.config_entry is not None
        if device_guid != self.config_entry.data[CONF_DEVICE_GUID]:
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={**self.config_entry.data, CONF_DEVICE_GUID: device_guid},
            )
