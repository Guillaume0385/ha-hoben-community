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
                except (HobenInvalidInputError, HobenInvalidCredentialsError):
                    errors["base"] = "invalid_identifier"
                except HobenAuthorizationRequiredError:
                    errors["base"] = "authorization_required"
                except HobenTransportError:
                    errors["base"] = "cannot_connect"
                except HobenUnsupportedProfileError:
                    errors["base"] = "unsupported_stove"
                except HobenError:
                    errors["base"] = "protocol_error"
                except Exception as error:
                    log_unexpected_error(_LOGGER, error)
                    errors["base"] = "unknown"
                else:
                    return self.async_create_entry(
                        title="Hoben",
                        data={CONF_USER_GUID: user_guid, CONF_DEVICE_GUID: device_guid},
                    )
        # Never prefill an identifier or put it into placeholders/error text.
        return self.async_show_form(
            step_id="user", data_schema=_USER_SCHEMA, errors=errors
        )

    async def _async_validate_connection(self, user_guid: str) -> str:
        """Only persist a nonzero server assignment after a complete V4 refresh."""
        client = HobenClient(user_guid=user_guid)
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
