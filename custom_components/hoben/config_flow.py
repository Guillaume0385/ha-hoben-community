"""UI-only connection validation; no pairing, register parsing or controls."""

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers import selector

from .client import HobenClient
from .const import CONF_DEVICE_GUID, CONF_USER_GUID, DOMAIN
from .exceptions import (
    HobenAuthorizationRequiredError,
    HobenError,
    HobenInvalidCredentialsError,
    HobenInvalidInputError,
    HobenProtocolError,
    HobenTransportError,
    HobenUnsupportedProfileError,
)
from .helpers import log_unexpected_error, user_guid_fingerprint
from .myhoben import INITIAL_DEVICE_GUID, normalize_user_guid
from .profiles import StoveProfile

_LOGGER = logging.getLogger(__name__)
_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USER_GUID): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        )
    }
)


def _connection_error(error: Exception) -> str:
    """Map validation failures to fixed text without exposing client payloads."""
    if isinstance(error, (HobenInvalidInputError, HobenInvalidCredentialsError)):
        return "invalid_identifier"
    if isinstance(error, HobenAuthorizationRequiredError):
        return "authorization_required"
    if isinstance(error, HobenTransportError):
        return "cannot_connect"
    if isinstance(error, HobenUnsupportedProfileError):
        return "unsupported_stove"
    if isinstance(error, HobenError):
        return "protocol_error"
    log_unexpected_error(_LOGGER, error)
    return "unknown"


class HobenConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configure one stove with a private HOBEN identifier and a neutral title."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Normalize, prevent duplicates, then perform exactly one API refresh."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                user_guid = normalize_user_guid(user_input[CONF_USER_GUID])
            except (KeyError, TypeError, ValueError):
                errors[CONF_USER_GUID] = "invalid_identifier"
            else:
                await self.async_set_unique_id(user_guid_fingerprint(user_guid))
                self._abort_if_unique_id_configured()
                try:
                    device_guid = await self._async_validate_connection(user_guid)
                except Exception as error:
                    errors["base"] = _connection_error(error)
                else:
                    return self.async_create_entry(
                        title="Hoben",
                        data={CONF_USER_GUID: user_guid, CONF_DEVICE_GUID: device_guid},
                    )
        # Never prefill an identifier or put it into placeholders/error text.
        return self.async_show_form(
            step_id="user", data_schema=_USER_SCHEMA, errors=errors
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Offer recovery for the entry referenced by HA, without identity input."""
        # Read the authoritative entry on confirmation, not the flow's data copy.
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Retry the stored identity; only a successful V4 read resumes polling."""
        errors: dict[str, str] = {}
        if user_input is not None:
            entry = self._get_reauth_entry()
            try:
                user_guid = normalize_user_guid(entry.data[CONF_USER_GUID])
                device_guid = entry.data[CONF_DEVICE_GUID]
            except (KeyError, TypeError, ValueError):
                errors["base"] = "invalid_identifier"
            else:
                await self.async_set_unique_id(user_guid_fingerprint(user_guid))
                self._abort_if_unique_id_mismatch()
                try:
                    assigned_device_guid = await self._async_validate_connection(
                        user_guid, device_guid
                    )
                except Exception as error:
                    errors["base"] = _connection_error(error)
                else:
                    # Reload even without a rotation: the coordinator stopped on
                    # ConfigEntryAuthFailed and needs a fresh successful setup.
                    return self.async_update_reload_and_abort(
                        entry, data_updates={CONF_DEVICE_GUID: assigned_device_guid}
                    )
        return self.async_show_form(
            step_id="reauth_confirm", data_schema=vol.Schema({}), errors=errors
        )

    async def _async_validate_connection(
        self, user_guid: str, device_guid: str | None = None
    ) -> str:
        """Only persist a nonzero server assignment after a complete V4 refresh."""
        client = HobenClient(user_guid=user_guid, device_guid=device_guid)
        try:
            snapshot = await client.async_refresh()
            if snapshot.profile is not StoveProfile.V4:
                raise HobenUnsupportedProfileError(snapshot.profile)
            device_guid = client.device_guid_for_persistence
            if device_guid == INITIAL_DEVICE_GUID:
                raise HobenProtocolError()
            return device_guid
        finally:
            await client.async_close()
