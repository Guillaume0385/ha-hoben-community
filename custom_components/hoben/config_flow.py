"""Private HA pairing orchestration through the typed client, without framing."""

import asyncio
import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import SOURCE_REAUTH, ConfigFlow, ConfigFlowResult
from homeassistant.core import callback
from homeassistant.helpers import selector

from .client import HobenClient
from .const import CONF_AUTHORIZATION_CODE, CONF_DEVICE_GUID, CONF_USER_GUID, DOMAIN
from .exceptions import (
    HobenAuthorizationCodeError,
    HobenAuthorizationRequiredError,
    HobenClosedError,
    HobenError,
    HobenInvalidCredentialsError,
    HobenInvalidInputError,
    HobenProtocolError,
    HobenTransportError,
    HobenUnsupportedProfileError,
)
from .helpers import log_unexpected_error, user_guid_fingerprint
from .myhoben import INITIAL_DEVICE_GUID, CloseClientReason, normalize_user_guid
from .profiles import StoveProfile

_LOGGER = logging.getLogger(__name__)
_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USER_GUID): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        )
    }
)
_AUTHORIZATION_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_AUTHORIZATION_CODE): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        )
    }
)


def _authorization_code(value: Any) -> int:
    """Convert masked decimal text to UInt16, without guessing server code rules.

    Leading zeroes are allowed, with no prescribed digit count. Bound conversion
    by representability so an arbitrarily long input never reaches int()'s text
    limit or exposes its value in a conversion exception.
    """
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
        raise HobenAuthorizationCodeError()
    significant = value.lstrip("0") or "0"
    if len(significant) > 5:
        raise HobenAuthorizationCodeError()
    code = int(significant)
    if code > 65535:
        raise HobenAuthorizationCodeError()
    return code


def _connection_error(error: Exception) -> str:
    """Map validation failures to fixed text without exposing client payloads."""
    if isinstance(error, (HobenInvalidInputError, HobenInvalidCredentialsError)):
        return "invalid_identifier"
    if isinstance(error, HobenAuthorizationRequiredError):
        return "authorization_required"
    if isinstance(error, HobenAuthorizationCodeError):
        return "invalid_authorization_code"
    if isinstance(error, HobenClosedError):
        return {
            CloseClientReason.INVALID_IDENTIFIER: "invalid_identifier",
            CloseClientReason.STOVE_CONNECTION_REQUIRED: "stove_connection_required",
            CloseClientReason.AUTHORIZATION_REJECTED: "authorization_rejected",
            CloseClientReason.AUTHORIZATION_TIMEOUT: "authorization_timeout",
            CloseClientReason.SERVER_MAINTENANCE: "server_maintenance",
        }.get(error.reason, "protocol_error")
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

    def __init__(self) -> None:
        super().__init__()
        # Only the initial flow needs a private identity between forms. Reauth
        # always reads ConfigEntry.data. No code, provider or client is retained.
        self._authorization_user_guid: str | None = None
        self._authorization_requested = False
        self._validation_task: asyncio.Task | None = None
        self._removed = False

    @callback
    def async_remove(self) -> None:
        """Discard pending identity and cancel inline I/O if HA aborts the flow."""
        self._removed = True
        self._authorization_user_guid = None
        self._authorization_requested = False
        if self._validation_task is not None:
            self._validation_task.cancel()
        super().async_remove()

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
                except HobenAuthorizationRequiredError:
                    # Validation has already closed before this form appears.
                    self._authorization_user_guid = user_guid
                    self._authorization_requested = True
                    return await self.async_step_authorization()
                except Exception as error:
                    errors["base"] = _connection_error(error)
                else:
                    return await self._async_finish_validation(user_guid, device_guid)
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
        """Retry the stored identity, with explicit pairing if authorization is due."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                user_guid, device_guid = await self._async_reauth_identity()
            except (KeyError, TypeError, ValueError):
                errors["base"] = "invalid_identifier"
            else:
                try:
                    assigned_device_guid = await self._async_validate_connection(
                        user_guid, device_guid
                    )
                except HobenAuthorizationRequiredError:
                    self._authorization_requested = True
                    return await self.async_step_authorization()
                except Exception as error:
                    errors["base"] = _connection_error(error)
                else:
                    return await self._async_finish_validation(
                        user_guid, assigned_device_guid
                    )
        return self.async_show_form(
            step_id="reauth_confirm", data_schema=vol.Schema({}), errors=errors
        )

    async def async_step_authorization(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Submit one code on a fresh client; retain no I/O or code between forms."""
        if not self._authorization_requested:
            # A code step cannot initiate pairing without a typed request first.
            if self.source == SOURCE_REAUTH:
                return await self.async_step_reauth_confirm()
            return await self.async_step_user()

        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                # HA validates a copy of the submitted mapping. Remove the code
                # immediately; never store it on this flow or prefill a schema.
                code = _authorization_code(
                    user_input.pop(CONF_AUTHORIZATION_CODE, None)
                )
            except HobenAuthorizationCodeError:
                errors[CONF_AUTHORIZATION_CODE] = "invalid_authorization_code"
            else:
                try:
                    if self.source == SOURCE_REAUTH:
                        try:
                            user_guid, device_guid = await self._async_reauth_identity()
                        except (KeyError, TypeError, ValueError):
                            errors["base"] = "invalid_identifier"
                    else:
                        user_guid = self._authorization_user_guid
                        device_guid = None
                        self._abort_if_unique_id_configured()
                    if not errors:
                        try:
                            assigned_device_guid = (
                                await self._async_validate_connection(
                                    user_guid, device_guid, authorization_code=code
                                )
                            )
                        except Exception as error:
                            errors["base"] = _connection_error(error)
                        else:
                            return await self._async_finish_validation(
                                user_guid, assigned_device_guid
                            )
                finally:
                    del code

        return self.async_show_form(
            step_id="authorization", data_schema=_AUTHORIZATION_SCHEMA, errors=errors
        )

    async def _async_reauth_identity(self) -> tuple[str, str]:
        """Use the current entry and preserve the entry-bound account check."""
        entry = self._get_reauth_entry()
        user_guid = normalize_user_guid(entry.data[CONF_USER_GUID])
        device_guid = entry.data[CONF_DEVICE_GUID]
        await self.async_set_unique_id(user_guid_fingerprint(user_guid))
        self._abort_if_unique_id_mismatch()
        return user_guid, device_guid

    async def _async_finish_validation(
        self, user_guid: str, device_guid: str
    ) -> ConfigFlowResult:
        """Commit only after successful validation and temporary-client cleanup."""
        if self._removed:
            raise asyncio.CancelledError()
        if self.source == SOURCE_REAUTH:
            # Protect against an account change while the network call yielded.
            try:
                current_user_guid, _ = await self._async_reauth_identity()
            except (KeyError, TypeError, ValueError):
                return self.async_show_form(
                    step_id=(
                        "authorization"
                        if self._authorization_requested
                        else "reauth_confirm"
                    ),
                    data_schema=(
                        _AUTHORIZATION_SCHEMA
                        if self._authorization_requested
                        else vol.Schema({})
                    ),
                    errors={"base": "invalid_identifier"},
                )
            if current_user_guid != user_guid:
                return self.async_abort(reason="unique_id_mismatch")
            # Reload even without a rotation: authentication stopped polling.
            return self.async_update_reload_and_abort(
                self._get_reauth_entry(), data_updates={CONF_DEVICE_GUID: device_guid}
            )
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title="Hoben",
            data={CONF_USER_GUID: user_guid, CONF_DEVICE_GUID: device_guid},
        )

    async def _async_validate_connection(
        self,
        user_guid: str,
        device_guid: str | None = None,
        *,
        authorization_code: int | None = None,
    ) -> str:
        """Refresh or explicitly associate through the client, then close.

        The provider exists only during a submission; the client decides whether
        to call it after DeviceAuthReq. Association does no Modbus I/O. No socket
        or coroutine awaits user input while the authorization form is visible.
        """
        client: HobenClient | None = None
        self._validation_task = asyncio.current_task()
        try:
            client = HobenClient(user_guid=user_guid, device_guid=device_guid)
            if authorization_code is None:
                result = await client.async_refresh()
            else:

                async def provide_code() -> int:
                    if authorization_code is None:
                        raise HobenAuthorizationCodeError()
                    return authorization_code

                result = await client.async_associate(
                    authorization_code_provider=provide_code
                )
            if result.profile is not StoveProfile.V4:
                raise HobenUnsupportedProfileError(result.profile)
            device_guid = client.device_guid_for_persistence
            if device_guid == INITIAL_DEVICE_GUID:
                raise HobenProtocolError()
            return device_guid
        finally:
            try:
                if client is not None:
                    await client.async_close()
            finally:
                authorization_code = None
                self._validation_task = None
