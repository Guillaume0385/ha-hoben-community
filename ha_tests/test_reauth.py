"""Recover the existing HA entry through confirmation, without changing account."""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, Mock, call

import pytest
from conftest import (
    DEVICE_GUID,
    NORMALIZED_USER_GUID,
    PRIVATE_TEXT,
    ROTATED_DEVICE_GUID,
    assert_private_values_absent,
)
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.hoben.client import HobenClient
from custom_components.hoben.const import (
    CONF_AUTHORIZATION_CODE,
    CONF_DEVICE_GUID,
    CONF_USER_GUID,
    DOMAIN,
)
from custom_components.hoben.exceptions import (
    HobenAuthorizationRequiredError,
    HobenInvalidCredentialsError,
    HobenInvalidInputError,
    HobenProtocolError,
    HobenTransportError,
    HobenUnsupportedProfileError,
)
from custom_components.hoben.myhoben import CloseClientReason
from custom_components.hoben.profiles import StoveProfile
from custom_components.hoben.transport import AsyncTlsTransport


async def start_reauth(hass, entry, data=None):
    """Use HA's entry-owned flow and inspect its public confirmation result."""
    entry.async_start_reauth(hass, data=data)
    await hass.async_block_till_done()
    [flow] = hass.config_entries.flow.async_progress()
    assert flow["context"]["source"] == SOURCE_REAUTH
    assert flow["context"]["entry_id"] == entry.entry_id
    return await hass.config_entries.flow.async_configure(flow["flow_id"])


def successful_client(snapshot, device_guid):
    """Separate temporary validation from the fresh client owned by reload."""
    return Mock(
        spec=HobenClient,
        async_refresh=AsyncMock(return_value=snapshot),
        async_close=AsyncMock(),
        device_guid_for_persistence=device_guid,
    )


@pytest.mark.parametrize(
    "error",
    [
        HobenAuthorizationRequiredError(),
        HobenInvalidCredentialsError(CloseClientReason.INVALID_IDENTIFIER),
    ],
)
@pytest.mark.parametrize("assigned_guid", [DEVICE_GUID, ROTATED_DEVICE_GUID])
async def test_auth_failure_starts_reauth_then_reloads_and_resumes_polling(
    hass, entry, client_factory, client, snapshot, caplog, error, assigned_guid
):
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    old_runtime = entry.runtime_data
    old_data = dict(entry.data)
    old_options = dict(entry.options)
    old_unique_id = entry.unique_id
    client.async_refresh.side_effect = error
    await old_runtime.coordinator.async_refresh()
    await hass.async_block_till_done()
    assert isinstance(old_runtime.coordinator.last_exception, ConfigEntryAuthFailed)
    [flow] = hass.config_entries.flow.async_progress()
    assert flow["context"]["source"] == SOURCE_REAUTH
    assert flow["context"]["entry_id"] == entry.entry_id
    form = await hass.config_entries.flow.async_configure(flow["flow_id"])
    assert form["type"] is FlowResultType.FORM
    assert form["step_id"] == "reauth_confirm"
    assert form["data_schema"].schema == {}
    assert form["errors"] == {}
    assert_private_values_absent(repr(form) + caplog.text)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()
    assert client.async_refresh.await_count == 2

    validation = successful_client(snapshot, assigned_guid)
    resumed = successful_client(snapshot, assigned_guid)
    client_factory.side_effect = [validation, resumed]
    result = await hass.config_entries.flow.async_configure(flow["flow_id"], {})
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data is not old_runtime
    assert entry.runtime_data.client is resumed
    assert entry.data == {**old_data, CONF_DEVICE_GUID: assigned_guid}
    assert entry.options == old_options
    assert entry.unique_id == old_unique_id
    assert entry.title == "Hoben"
    assert hass.config_entries.async_entries(DOMAIN) == [entry]
    assert not hass.config_entries.flow.async_progress()
    assert client_factory.call_args_list == [
        call(user_guid=NORMALIZED_USER_GUID, device_guid=DEVICE_GUID),
        call(user_guid=NORMALIZED_USER_GUID, device_guid=DEVICE_GUID),
        call(user_guid=NORMALIZED_USER_GUID, device_guid=assigned_guid),
    ]
    client.async_close.assert_awaited_once_with()
    validation.async_refresh.assert_awaited_once_with()
    validation.async_close.assert_awaited_once_with()
    resumed.async_refresh.assert_awaited_once_with()
    resumed.async_close.assert_not_awaited()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()
    assert resumed.async_refresh.await_count == 2
    assert client.async_refresh.await_count == 2
    assert_private_values_absent(repr(result) + caplog.text)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (HobenInvalidInputError(), "invalid_identifier"),
        (
            HobenInvalidCredentialsError(CloseClientReason.INVALID_IDENTIFIER),
            "invalid_identifier",
        ),
        (HobenTransportError(), "cannot_connect"),
        (HobenUnsupportedProfileError(StoveProfile.V6), "unsupported_stove"),
        (HobenProtocolError(), "protocol_error"),
        (RuntimeError(PRIVATE_TEXT), "unknown"),
    ],
)
async def test_failed_reauth_keeps_form_and_storage_without_creating_entry(
    hass, entry, client_factory, client, caplog, error, expected
):
    old_data = dict(entry.data)
    old_options = dict(entry.options)
    error.__cause__ = ValueError(PRIVATE_TEXT)
    client.async_refresh.side_effect = error
    # An identity adopted before a failed read must not be written to storage.
    client.device_guid_for_persistence = ROTATED_DEVICE_GUID
    form = await start_reauth(hass, entry)
    client_factory.assert_not_called()
    with caplog.at_level("DEBUG"):
        result = await hass.config_entries.flow.async_configure(form["flow_id"], {})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": expected}
    assert result["data_schema"].schema == {}
    assert entry.data == old_data
    assert entry.options == old_options
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert hass.config_entries.async_entries(DOMAIN) == [entry]
    client_factory.assert_called_once_with(
        user_guid=NORMALIZED_USER_GUID, device_guid=DEVICE_GUID
    )
    client.async_refresh.assert_awaited_once_with()
    client.async_close.assert_awaited_once_with()
    assert_private_values_absent(repr(form) + repr(result) + caplog.text)


async def test_setup_authorization_request_can_pair_and_resume_polling(
    hass, entry, client_factory, client, snapshot, caplog
):
    client.async_refresh.side_effect = HobenAuthorizationRequiredError()
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    client.async_close.assert_awaited_once_with()
    [flow] = hass.config_entries.flow.async_progress()
    denied = successful_client(snapshot, ROTATED_DEVICE_GUID)
    denied.async_refresh.side_effect = HobenAuthorizationRequiredError()
    validation = successful_client(snapshot, ROTATED_DEVICE_GUID)
    resumed = successful_client(snapshot, ROTATED_DEVICE_GUID)
    client_factory.side_effect = [denied, validation, resumed]
    failed = await hass.config_entries.flow.async_configure(flow["flow_id"], {})
    assert failed["type"] is FlowResultType.FORM
    assert failed["step_id"] == "authorization"
    assert failed["errors"] == {}
    assert entry.data[CONF_DEVICE_GUID] == DEVICE_GUID
    denied.async_close.assert_awaited_once_with()

    validation.async_associate = AsyncMock(
        return_value=client.async_associate.return_value
    )
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {CONF_AUTHORIZATION_CODE: "12345"}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.client is resumed
    assert entry.data[CONF_DEVICE_GUID] == ROTATED_DEVICE_GUID
    assert hass.config_entries.async_entries(DOMAIN) == [entry]
    validation.async_associate.assert_awaited_once()
    validation.async_refresh.assert_not_awaited()
    validation.async_close.assert_awaited_once_with()
    assert client_factory.call_args_list == [
        call(user_guid=NORMALIZED_USER_GUID, device_guid=DEVICE_GUID),
        call(user_guid=NORMALIZED_USER_GUID, device_guid=DEVICE_GUID),
        call(user_guid=NORMALIZED_USER_GUID, device_guid=DEVICE_GUID),
        call(user_guid=NORMALIZED_USER_GUID, device_guid=ROTATED_DEVICE_GUID),
    ]
    assert_private_values_absent(repr(failed) + repr(result) + caplog.text)


async def test_reauth_uses_current_entry_instead_of_supplied_identity(
    hass, entry, client_factory, client, caplog
):
    form = await start_reauth(
        hass,
        entry,
        data={CONF_USER_GUID: "a" * 32, CONF_DEVICE_GUID: "S" * 32},
    )
    # A concurrent successful refresh could update the persisted client identity.
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_DEVICE_GUID: ROTATED_DEVICE_GUID}
    )
    client.async_refresh.side_effect = HobenAuthorizationRequiredError()
    result = await hass.config_entries.flow.async_configure(form["flow_id"], {})
    client_factory.assert_called_once_with(
        user_guid=NORMALIZED_USER_GUID, device_guid=ROTATED_DEVICE_GUID
    )
    assert result["step_id"] == "authorization"
    assert result["errors"] == {}
    assert entry.data[CONF_USER_GUID] == NORMALIZED_USER_GUID
    assert hass.config_entries.async_entries(DOMAIN) == [entry]
    assert_private_values_absent(repr(form) + repr(result) + caplog.text)


async def test_reauth_aborts_on_stored_account_mismatch(hass, entry, client_factory):
    form = await start_reauth(hass, entry)
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_USER_GUID: "a" * 32}
    )
    result = await hass.config_entries.flow.async_configure(form["flow_id"], {})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "unique_id_mismatch"
    client_factory.assert_not_called()
    assert hass.config_entries.async_entries(DOMAIN) == [entry]
    assert_private_values_absent(repr(result))


@pytest.mark.parametrize(
    "data",
    [
        {CONF_USER_GUID: "invalid PRIVATE_PAYLOAD", CONF_DEVICE_GUID: DEVICE_GUID},
        {CONF_USER_GUID: NORMALIZED_USER_GUID},
        {CONF_DEVICE_GUID: DEVICE_GUID},
    ],
)
async def test_invalid_stored_data_never_starts_client(
    hass, entry, client_factory, caplog, data
):
    hass.config_entries.async_update_entry(entry, data=data)
    form = await start_reauth(hass, entry)
    result = await hass.config_entries.flow.async_configure(form["flow_id"], {})
    assert result["errors"] == {"base": "invalid_identifier"}
    client_factory.assert_not_called()
    assert entry.data == data
    assert hass.config_entries.async_entries(DOMAIN) == [entry]
    assert_private_values_absent(repr(result) + caplog.text)


async def test_reauth_cancellation_closes_temporary_client(
    hass, entry, client_factory, client
):
    client.async_refresh.side_effect = asyncio.CancelledError()
    form = await start_reauth(hass, entry)
    with pytest.raises(asyncio.CancelledError):
        await hass.config_entries.flow.async_configure(form["flow_id"], {})
    client.async_close.assert_awaited_once_with()
    assert entry.data[CONF_DEVICE_GUID] == DEVICE_GUID
    assert hass.config_entries.async_entries(DOMAIN) == [entry]


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (b"\x2f" + PRIVATE_TEXT.encode(), None),
        (b"\x05\x02", "invalid_identifier"),
    ],
)
async def test_real_client_reauth_rejection_never_sends_pairing(
    hass, entry, monkeypatch, caplog, response, expected
):
    """Exercise real protocol code over a scripted transport with no sockets."""
    transport = Mock(
        spec=AsyncTlsTransport,
        connect=AsyncMock(),
        write=AsyncMock(),
        read=AsyncMock(return_value=response),
        close=AsyncMock(),
    )
    factory = Mock(return_value=transport)
    monkeypatch.setattr("custom_components.hoben.client.AsyncTlsTransport", factory)
    form = await start_reauth(hass, entry)
    with caplog.at_level("DEBUG"):
        result = await hass.config_entries.flow.async_configure(form["flow_id"], {})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == (
        "authorization" if expected is None else "reauth_confirm"
    )
    assert result["errors"] == ({} if expected is None else {"base": expected})
    factory.assert_called_once_with()
    transport.connect.assert_awaited_once_with()
    transport.write.assert_awaited_once()
    [request] = transport.write.await_args.args
    assert request[0] == 0x03  # OpenClient is the only outbound message.
    assert request[1:33] == NORMALIZED_USER_GUID.encode()
    assert request[37:69] == DEVICE_GUID.encode()
    transport.close.assert_awaited_once_with()
    assert entry.data[CONF_DEVICE_GUID] == DEVICE_GUID
    assert hass.config_entries.async_entries(DOMAIN) == [entry]
    assert_private_values_absent(repr(result) + caplog.text)
