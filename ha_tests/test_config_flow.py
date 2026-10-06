"""Real HA flow-manager coverage of every result, cleanup and privacy path."""

import asyncio
import traceback
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from conftest import (
    DEVICE_GUID,
    NORMALIZED_USER_GUID,
    PRIVATE_TEXT,
    USER_GUID,
    assert_private_values_absent,
)
from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType

from custom_components.hoben.const import CONF_DEVICE_GUID, CONF_USER_GUID, DOMAIN
from custom_components.hoben.exceptions import (
    HobenAmbiguousSessionError,
    HobenClientClosedError,
    HobenClosedError,
    HobenInvalidCredentialsError,
    HobenInvalidInputError,
    HobenModbusError,
    HobenProtocolError,
    HobenRefreshExhaustedError,
    HobenTimeoutError,
    HobenTransportError,
    HobenUnsupportedProfileError,
)
from custom_components.hoben.helpers import user_guid_fingerprint
from custom_components.hoben.myhoben import INITIAL_DEVICE_GUID, CloseClientReason
from custom_components.hoben.profiles import StoveProfile


@pytest.fixture(autouse=True)
def skip_runtime_setup(monkeypatch):
    """Keep the flow's single validation refresh separate from entry setup."""
    monkeypatch.setattr(
        "custom_components.hoben.async_setup_entry", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        "custom_components.hoben.async_unload_entry", AsyncMock(return_value=True)
    )


async def start_flow(hass):
    """Enter the real user flow through HA's public manager API."""
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )


async def test_initial_form(hass, client_factory):
    result = await start_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}
    assert list(result["data_schema"].schema) == [CONF_USER_GUID]
    selector = next(iter(result["data_schema"].schema.values()))
    assert selector.config["type"] == "password"
    client_factory.assert_not_called()


@pytest.mark.parametrize("identifier", [USER_GUID, NORMALIZED_USER_GUID.upper()])
async def test_success_persists_assignment_and_closes(
    hass, client_factory, client, caplog, identifier
):
    flow = await start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {CONF_USER_GUID: identifier}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Hoben"
    assert result["data"] == {
        CONF_USER_GUID: NORMALIZED_USER_GUID,
        CONF_DEVICE_GUID: DEVICE_GUID,
    }
    assert result["result"].options == {}
    fingerprint = result["result"].unique_id
    assert fingerprint == user_guid_fingerprint(USER_GUID)
    assert len(fingerprint) == 64
    client_factory.assert_called_once_with(
        user_guid=NORMALIZED_USER_GUID, device_guid=None
    )
    client.async_refresh.assert_awaited_once_with()
    client.async_close.assert_awaited_once_with()
    # Only the required private storage payload may contain the identifiers.
    assert_private_values_absent(
        caplog.text + result["title"] + fingerprint + repr(client)
    )


@pytest.mark.parametrize("identifier", [USER_GUID, NORMALIZED_USER_GUID.upper()])
async def test_duplicate_rejected_before_network(
    hass, entry, client_factory, identifier
):
    flow = await start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {CONF_USER_GUID: identifier}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    client_factory.assert_not_called()
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1
    assert_private_values_absent(repr(result))


@pytest.mark.parametrize("identifier", ["invalid PRIVATE_PAYLOAD", "", "abc"])
async def test_local_invalid_identifier(hass, client_factory, caplog, identifier):
    flow = await start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {CONF_USER_GUID: identifier}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_USER_GUID: "invalid_identifier"}
    client_factory.assert_not_called()
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
        (HobenTimeoutError(), "cannot_connect"),
        (HobenRefreshExhaustedError(2, HobenTimeoutError()), "cannot_connect"),
        (HobenUnsupportedProfileError(StoveProfile.V6), "unsupported_stove"),
        (HobenProtocolError(), "protocol_error"),
        (HobenAmbiguousSessionError(), "protocol_error"),
        (HobenModbusError(2), "protocol_error"),
        (HobenClosedError(CloseClientReason.UNKNOWN), "protocol_error"),
        (HobenClientClosedError(), "protocol_error"),
        (RuntimeError(PRIVATE_TEXT), "unknown"),
    ],
)
async def test_client_errors_are_sanitized_and_close(
    hass, client_factory, client, caplog, error, expected
):
    error.__cause__ = ValueError(PRIVATE_TEXT)
    client.async_refresh.side_effect = error
    flow = await start_flow(hass)
    with caplog.at_level("DEBUG"):
        result = await hass.config_entries.flow.async_configure(
            flow["flow_id"], {CONF_USER_GUID: USER_GUID}
        )
    assert result["errors"] == {"base": expected}
    assert result["type"] is FlowResultType.FORM
    assert hass.config_entries.async_entries(DOMAIN) == []
    client.async_refresh.assert_awaited_once_with()
    client.async_close.assert_awaited_once_with()
    assert_private_values_absent(repr(result) + caplog.text)
    if expected == "unknown":
        assert "stack locations" in caplog.text
        assert "_async_validate_connection" in caplog.text


@pytest.mark.parametrize(
    "failure", [HobenInvalidInputError(), RuntimeError(PRIVATE_TEXT)]
)
async def test_constructor_failure_is_sanitized(hass, client_factory, caplog, failure):
    client_factory.side_effect = failure
    flow = await start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {CONF_USER_GUID: USER_GUID}
    )
    expected = (
        "invalid_identifier"
        if isinstance(failure, HobenInvalidInputError)
        else "unknown"
    )
    assert result["errors"] == {"base": expected}
    assert_private_values_absent(repr(result) + caplog.text)


async def test_zero_identity_never_persisted(hass, client_factory, client):
    client.device_guid_for_persistence = INITIAL_DEVICE_GUID
    flow = await start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {CONF_USER_GUID: USER_GUID}
    )
    assert result["errors"] == {"base": "protocol_error"}
    assert not hass.config_entries.async_entries(DOMAIN)
    client.async_close.assert_awaited_once_with()


async def test_unsupported_snapshot_never_creates_entry(
    hass, client_factory, client, snapshot
):
    client.async_refresh.return_value = replace(snapshot, profile=StoveProfile.V6)
    flow = await start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {CONF_USER_GUID: USER_GUID}
    )
    assert result["errors"] == {"base": "unsupported_stove"}
    client.async_close.assert_awaited_once_with()


async def test_error_can_be_retried_later(hass, client_factory, client):
    client.async_refresh.side_effect = HobenTransportError()
    flow = await start_flow(hass)
    failed = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {CONF_USER_GUID: USER_GUID}
    )
    assert failed["errors"] == {"base": "cannot_connect"}
    client.async_refresh.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {CONF_USER_GUID: USER_GUID}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert client.async_refresh.await_count == client.async_close.await_count == 2


async def test_close_failure_prevents_entry_and_is_sanitized(
    hass, client_factory, client, caplog
):
    client.async_close.side_effect = RuntimeError(PRIVATE_TEXT)
    flow = await start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {CONF_USER_GUID: USER_GUID}
    )
    assert result["errors"] == {"base": "unknown"}
    assert not hass.config_entries.async_entries(DOMAIN)
    assert_private_values_absent(repr(result) + caplog.text)


async def test_cancellation_closes_without_translation_or_entry(
    hass, client_factory, client
):
    client.async_refresh.side_effect = asyncio.CancelledError()
    flow = await start_flow(hass)
    with pytest.raises(asyncio.CancelledError) as caught:
        await hass.config_entries.flow.async_configure(
            flow["flow_id"], {CONF_USER_GUID: USER_GUID}
        )
    client.async_close.assert_awaited_once_with()
    assert not hass.config_entries.async_entries(DOMAIN)
    assert_private_values_absent("".join(traceback.format_exception(caught.value)))
