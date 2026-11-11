"""Home Assistant scheduling over the HA-independent read-only client API."""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from time import monotonic
from typing import TYPE_CHECKING

from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryError
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .client import HobenClient, RawStoveSnapshot
from .const import CONF_DEVICE_GUID, DOMAIN, UPDATE_INTERVAL
from .error_phases import error_boundary
from .exceptions import (
    HobenAuthorizationRequiredError,
    HobenClosedError,
    HobenDataUpdatedRecoveryError,
    HobenError,
    HobenFrameBoundaryError,
    HobenInvalidCredentialsError,
    HobenProtocolError,
    HobenTransportError,
    HobenUnsupportedProfileError,
)
from .helpers import log_unexpected_error
from .myhoben import INITIAL_DEVICE_GUID, CloseClientReason
from .profiles import StoveProfile
from .safe_reports import safe_error_report, wrap_error
from .session_monitor import SessionEvent, report_event
from .v4_experiment import ExperimentalCloseClientError
from .v4_state import V4StoveState, decode_v4_snapshot

if TYPE_CHECKING:
    from . import HobenConfigEntry

_LOGGER = logging.getLogger(__name__)
_CONNECTION_HOLD_SECONDS = 300
_HOLD_CATEGORIES = frozenset(
    {
        "timeout",
        "transport_unavailable",
        "experimental_close_client",
        "server_closed",
        "malformed_response",
        "data_updated_recovery",
        "invalid_v4_snapshot",
    }
)


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
        self._updating = False
        self._recovery_read_handle = self._recovery_read_task = None
        self._recovery_read_generation = None
        # A UI deadline only: neither a read nor permission to reopen transport.
        # It survives accepted openings and failed polls until a decoded read.
        self._connection_hold_until: float | None = None
        self._connection_loss_generation: int | None = None
        self._connection_hold_revoked = False
        self._unsub_hold_expiry = None
        self._hold_timer_token = None
        self._unsub_session_hold = (
            client.session_monitor.subscribe(self._session_changed)
            if type(client) is HobenClient and client.ha_reconnect_enabled
            else None
        )

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
        if self._recovery_read_handle is not None:
            self._recovery_read_handle.cancel()
            self._recovery_read_handle = None
        if self._recovery_read_task is not None:
            self._recovery_read_task.cancel()
            await asyncio.gather(self._recovery_read_task, return_exceptions=True)
            self._recovery_read_task = None
        self._cancel_hold_expiry()
        if self._unsub_session_hold is not None:
            self._unsub_session_hold()
            self._unsub_session_hold = None
        self._snapshot_hold = self.data_updated_hold = False
        self.async_update_listeners()
        self._session_event()
        if self._unsub_client_stop is not None:
            self._unsub_client_stop()
            self._unsub_client_stop = None

    def _session_event(self, event=SessionEvent()) -> None:
        """Diagnostic channel, independent from measure listeners and their hold."""
        if type(self.client) is HobenClient:
            self.client.session_monitor.emit(event)

    def _cancel_hold_expiry(self) -> None:
        self._hold_timer_token = None
        if self._unsub_hold_expiry is not None:
            self._unsub_hold_expiry()
            self._unsub_hold_expiry = None

    def _schedule_hold_expiry(self, seconds: float) -> None:
        token = self._hold_timer_token = object()

        @callback
        def expire(now) -> None:
            # An already queued callback from an old sample/unload cannot
            # expire or duplicate the timer belonging to a later acquisition.
            if self._hold_timer_token is token:
                self._expire_connection_hold(now)

        self._unsub_hold_expiry = async_call_later(self.hass, seconds, expire)

    @property
    def _connection_owner_active(self) -> bool:
        """A task finishing a permanent refusal is not a recovery supervisor."""
        life = self.client._lifecycle
        return (
            self.client.ha_recovery_pending is True
            and life is not None
            and life.state in ("connected", "reconnecting")
        )

    @property
    def _connection_hold_safe(self) -> bool:
        """Observe the existing owner; a UI cache cannot override its refusal."""
        observation = self.client.session_observation
        category = self.client.session_monitor.last_error_category
        return (
            not self._shutdown_requested
            and observation.stopped is not True
            and observation.cleanup_failed is False
            and self._connection_owner_active
            and category in _HOLD_CATEGORIES
            and not (
                category == "experimental_close_client"
                and observation.close_client_subcode in (None, 2, 4, 5)
            )
        )

    @callback
    def _session_changed(self) -> None:
        """Latch the first actual loss, including idle loss between HA polls."""
        self._schedule_recovery_read()
        if (
            self._shutdown_requested
            or self.data is None
            or self.last_successful_read_at is None
        ):
            return
        if (
            self.client.data_updated_transport_alive is not True
            or self.client.acquisition_uncertain is True
        ):
            if self._connection_hold_until is None:
                # Loss is degradation, never a successful HA update. Retained
                # values use their separate availability rule; this also lets
                # HA publish an identical *new* decoded read after expiration.
                if not self._updating:
                    # During a refresh HA records/logs its real exception.
                    # An idle loss must also degrade without inventing a poll.
                    self.last_update_success = False
                self._connection_loss_generation = (
                    self.client.session_observation.generation
                )
                self._connection_hold_until = monotonic() + _CONNECTION_HOLD_SECONDS
                self._schedule_hold_expiry(_CONNECTION_HOLD_SECONDS)
            # During normal cleanup the final proof can still be pending. Do
            # not publish old data again; terminal/failed cleanup revokes now.
            observation = self.client.session_observation
            category = self.client.session_monitor.last_error_category
            if (
                observation.stopped is True
                or observation.cleanup_failed is True
                or not self._connection_owner_active
                or category is not None
                and category not in _HOLD_CATEGORIES
                or category == "experimental_close_client"
                and observation.close_client_subcode in (2, 4, 5)
            ):
                self._connection_hold_revoked = True
                self._cancel_hold_expiry()
                self.async_update_listeners()

    @callback
    def _schedule_recovery_read(self) -> None:
        """One event-driven acquisition, coalesced with a poll already in flight."""
        generation = self.client.ha_acquisition_generation
        if self._shutdown_requested or generation is None:
            if self._recovery_read_handle is not None:
                self._recovery_read_handle.cancel()
                self._recovery_read_handle = None
            return
        if generation == self._recovery_read_generation:
            return
        self._recovery_read_generation = generation

        async def refresh():
            if (
                not self._shutdown_requested
                and not self._updating
                and self.client.ha_acquisition_generation == generation
            ):
                await self.async_request_refresh()

        @callback
        def begin():
            self._recovery_read_handle = None
            if not self._shutdown_requested:
                self._recovery_read_task = self.hass.async_create_background_task(
                    refresh(), "hoben-recovery-acquisition"
                )

        self._recovery_read_handle = self.hass.loop.call_soon(begin)

    @callback
    def _expire_connection_hold(self, _now) -> None:
        """Notify HA at the monotone deadline even if no refresh completes."""
        self._unsub_hold_expiry = None
        if self._shutdown_requested or self._connection_hold_until is None:
            return
        remaining = self._connection_hold_until - monotonic()
        if remaining > 0:
            self._schedule_hold_expiry(remaining)
            return
        self.async_update_listeners()

    @property
    def last_snapshot_held(self) -> bool:
        """Availability of old validated values is never connection/freshness."""
        observation = self.client.session_observation
        if self._connection_hold_until is not None:
            # Cleanup must be attested for the disconnected accepted owner.
            # A new opening without a decoded sample never renews the window.
            cleanup_generation = (
                observation.generation
                if not observation.active
                else self._connection_loss_generation
            )
            return (
                self.data is not None
                and self.last_successful_read_at is not None
                and not self._connection_hold_revoked
                and monotonic() < self._connection_hold_until
                and self._connection_hold_safe
                and (
                    self.client.acquisition_uncertain is True
                    and observation.active is True
                    and observation.generation == self._connection_loss_generation
                    and self.client.data_updated_transport_alive is True
                    or self._cleanup_proven(cleanup_generation)
                )
            )
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

    def _cleanup_proven(self, generation: int | None) -> bool:
        """Read the original proof; never close, await or substitute an owner.

        A failed refresh can return after the real session has finished closing
        but just before the lifecycle copies that proof into cleaned_generation.
        Bridge only this publication race for the exact accepted owner. No
        detached transport, missing session or pending close attests cleanup.
        """
        if type(generation) is not int:
            return False
        cleaned = self.client.session_observation.cleaned_generation
        if type(cleaned) is int and cleaned >= generation:
            return True
        life = self.client._lifecycle
        return (
            life is not None
            and type(life._active_generation) is int
            and life._active_generation == generation
            and life._session is not None
            and life._session.cleanup_succeeded is True
        )

    @property
    def snapshot_available(self) -> bool:
        """A shutdown or terminal failure cannot be covered by retained data."""
        return (
            not self._shutdown_requested
            and self.client.session_observation.stopped is not True
            and self.data is not None
            and (
                self.last_snapshot_held
                if self._connection_hold_until is not None
                else self.last_update_success or self.last_snapshot_held
            )
        )

    async def _async_update_data(self) -> HobenCoordinatorData:
        """Retain values during recovery without reporting a successful read."""
        was_holding = self._snapshot_hold
        pending_owner = False
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
                pending_owner = True
                raise wrap_error(UpdateFailed, "Hoben session recovery pending", source)
            self._updating = True
            try:
                data = await self._async_update_once()
            finally:
                self._updating = False
        except HobenDataUpdatedRecoveryError as error:
            self.data_updated_deferred = True
            self._snapshot_hold = self.data_updated_hold = self.data is not None
            self._hold_loss_generation = self.client.session_observation.loss_generation
            raise wrap_error(
                UpdateFailed, "Hoben DataUpdated recovery pending", error
            ) from None
        except Exception as error:
            self.data_updated_deferred = self.data_updated_hold = False
            report = safe_error_report(error) or {}
            category = report.get("error")
            self._snapshot_hold = (
                category
                in {
                    "malformed_response",
                    "timeout",
                    "invalid_v4_snapshot",
                }
                and report.get("frame_boundary_provenance") != "partial_eof"
            )
            self._hold_loss_generation = self.client.session_observation.loss_generation
            self._snapshot_hold = self.last_snapshot_held
            self._notify_held_failure = was_holding and not self._snapshot_hold
            if not pending_owner and self.client.acquisition_uncertain is not True:
                # A model rejection is degraded even before A1 has a cache.
                self._session_event(
                    report_event(
                        safe_error_report(error),
                        recovering=self._snapshot_hold
                        or (
                            category == "invalid_v4_snapshot"
                            and self.client.data_updated_transport_alive is True
                        ),
                    )
                )
            raise
        except BaseException:
            self.data_updated_deferred = False
            self._snapshot_hold = self.data_updated_hold = False
            # Cancellation closes the real client's owner; notify even though
            # HA re-raises before its usual refresh-finished listener callback.
            self.async_update_listeners()
            self._session_event(SessionEvent("ended"))
            raise
        self._snapshot_hold = self.data_updated_hold = False
        self.data_updated_deferred = False
        return data

    def async_update_listeners(self) -> None:
        """Do not report old sensor values as freshly acquired during a hold."""
        if not self.last_snapshot_held:
            if self._connection_hold_until is not None:
                self._connection_hold_revoked = True
            super().async_update_listeners()

    def _async_refresh_finished(self) -> None:
        """A genuine failure ends the value hold even after repeated deferrals."""
        super()._async_refresh_finished()
        self._session_event()
        if self._notify_held_failure and not self.last_update_success:
            self._notify_held_failure = False
            self.async_update_listeners()

    async def _async_update_once(self) -> HobenCoordinatorData:
        """Decode successful reads; also persist identities accepted before loss."""
        try:
            if self.data is None and self.client.acquisition_uncertain is True:
                # Do not spin the first-refresh retry loop or close solely for
                # silence. This waiter wakes on real loss/stop, never a timer.
                await self.client.async_wait_acquisition_ready()
            try:
                snapshot = await self.client.async_refresh()
            except (HobenError, asyncio.CancelledError):
                # The shared owner can accept/rotate an identity before its
                # following read fails. Persist that accepted identity without
                # replacing the original error if storage itself fails.
                if self.client.profile is StoveProfile.V4:
                    try:
                        with error_boundary("identity_storage"):
                            self._persist_identity()
                    except Exception as storage_error:
                        log_unexpected_error(_LOGGER, storage_error)
                raise
            if snapshot.profile is not StoveProfile.V4:
                raise HobenUnsupportedProfileError(snapshot.profile)
            with error_boundary("model_decode"):
                state = decode_v4_snapshot(snapshot)
            with error_boundary("identity_storage"):
                self._persist_identity()
            self.last_successful_read_at = dt_util.utcnow()
            self._connection_hold_until = None
            self._connection_loss_generation = None
            self._connection_hold_revoked = False
            self._cancel_hold_expiry()
            self._session_event(SessionEvent("read_succeeded"))
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
            # ambiguous frame. Only the live HA owner can recover its classified
            # boundary subtype; internal/ambiguous-opening/decoding failures
            # retain permanent error semantics.
            raise wrap_error(
                UpdateFailed
                if type(error) is HobenProtocolError
                or (
                    type(error) is HobenFrameBoundaryError
                    and self.client.ha_recovery_pending
                )
                else ConfigEntryError,
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
