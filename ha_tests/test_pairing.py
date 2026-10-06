"""Real HA form lifecycle and typed-client pairing, with synthetic secrets only."""

import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock, Mock

import pytest
import voluptuous as vol
from conftest import (
    DEVICE_GUID,
    NORMALIZED_USER_GUID,
    PRIVATE_TEXT,
    ROTATED_DEVICE_GUID,
    USER_GUID,
    assert_private_values_absent,
)
from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType

from custom_components.hoben.client import HobenClient
from custom_components.hoben.const import (
    CONF_AUTHORIZATION_CODE,
    CONF_DEVICE_GUID,
    CONF_USER_GUID,
    DOMAIN,
)
from custom_components.hoben.exceptions import (
    HobenAmbiguousSessionError,
    HobenAuthorizationCodeError,
    HobenAuthorizationRequiredError,
    HobenClosedError,
    HobenInvalidCredentialsError,
    HobenInvalidInputError,
    HobenProtocolError,
    HobenTimeoutError,
    HobenTransportError,
    HobenUnsupportedProfileError,
)
from custom_components.hoben.helpers import user_guid_fingerprint
from custom_components.hoben.myhoben import INITIAL_DEVICE_GUID, CloseClientReason
from custom_components.hoben.profiles import StoveProfile
from custom_components.hoben.transport import AsyncTlsTransport

CODE_TEXT = "54321"
CODE = 54321


@pytest.fixture(autouse=True)
def skip_runtime_setup(monkeypatch):
    """Separate form submission from the subsequent coordinator-owned refresh."""
    monkeypatch.setattr(
        "custom_components.hoben.async_setup_entry", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        "custom_components.hoben.async_unload_entry", AsyncMock(return_value=True)
    )


@pytest.fixture
def association_client(client):
    """A fresh temporary client, distinct from the authorization-request probe."""
    return Mock(
        spec=HobenClient,
        async_associate=AsyncMock(return_value=client.async_associate.return_value),
        async_refresh=AsyncMock(),
        async_close=AsyncMock(),
        device_guid_for_persistence=ROTATED_DEVICE_GUID,
    )


def assert_public(result, hass, caplog):
    """Inspect public metadata without exporting ConfigEntry's private storage."""
    text = repr(result) + caplog.text + repr(hass.config_entries.flow.async_progress())
    assert_private_values_absent(text)
    assert CODE_TEXT not in text


async def start_pairing(hass, client, entry=None):
    """Make a real first attempt, then prove cleanup precedes the code form."""
    client.async_refresh.side_effect = HobenAuthorizationRequiredError()
    if entry is None:
        form = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            form["flow_id"], {CONF_USER_GUID: USER_GUID}
        )
    else:
        form = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_REAUTH, "entry_id": entry.entry_id},
            data={CONF_USER_GUID: "a" * 32, CONF_DEVICE_GUID: "S" * 32},
        )
        result = await hass.config_entries.flow.async_configure(form["flow_id"], {})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "authorization"
    assert result["errors"] == {}
    client.async_close.assert_awaited_once_with()
    client.async_associate.assert_not_awaited()
    return result


@pytest.mark.parametrize("reauth", [False, True])
async def test_request_shows_private_empty_form_with_no_active_client(
    hass, request, client_factory, client, caplog, reauth
):
    entry = request.getfixturevalue("entry") if reauth else None
    result = await start_pairing(hass, client, entry)
    assert hass.config_entries.async_entries(DOMAIN) == (
        [] if entry is None else [entry]
    )
    assert list(result["data_schema"].schema) == [CONF_AUTHORIZATION_CODE]
    field, input_selector = next(iter(result["data_schema"].schema.items()))
    assert input_selector.config["type"] == "password"
    assert field.default is vol.UNDEFINED
    assert_public(result, hass, caplog)
    flow = hass.config_entries.flow._progress[result["flow_id"]]
    assert flow._validation_task is None
    assert flow._authorization_user_guid == (None if reauth else NORMALIZED_USER_GUID)
    await hass.config_entries.flow.async_configure(result["flow_id"])
    client_factory.assert_called_once()
    hass.config_entries.flow.async_abort(result["flow_id"])
    assert flow._authorization_user_guid is None
    assert flow._validation_task is None
    assert not hass.config_entries.flow.async_progress()
    client.async_close.assert_awaited_once_with()


@pytest.mark.parametrize(
    "text", ["", "-1", "65536", "1.5", "+1", " 1 ", "١٢", "PRIVATE_PAYLOAD", "9" * 5000]
)
@pytest.mark.parametrize("reauth", [False, True])
async def test_invalid_code_is_private_and_rejected_before_new_client(
    hass, request, client_factory, client, caplog, text, reauth
):
    entry = request.getfixturevalue("entry") if reauth else None
    form = await start_pairing(hass, client, entry)
    client_factory.reset_mock()
    result = await hass.config_entries.flow.async_configure(
        form["flow_id"], {CONF_AUTHORIZATION_CODE: text}
    )
    assert result["step_id"] == "authorization"
    assert result["errors"] == {CONF_AUTHORIZATION_CODE: "invalid_authorization_code"}
    client_factory.assert_not_called()
    assert_public(result, hass, caplog)


@pytest.mark.parametrize("value", [None, True, 12, 1.0, b"12", ["12"]])
async def test_non_text_input_cannot_be_coerced_by_the_step(
    hass, client_factory, client, value
):
    """Also guard direct calls, beyond HA's password selector type check."""
    form = await start_pairing(hass, client)
    flow = hass.config_entries.flow._progress[form["flow_id"]]
    client_factory.reset_mock()
    result = await flow.async_step_authorization({CONF_AUTHORIZATION_CODE: value})
    assert result["errors"] == {CONF_AUTHORIZATION_CODE: "invalid_authorization_code"}
    client_factory.assert_not_called()


@pytest.mark.parametrize("reauth", [False, True])
async def test_code_cannot_start_association_without_a_server_request(
    hass, request, client_factory, client, reauth
):
    entry = request.getfixturevalue("entry") if reauth else None
    if entry is None:
        form = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
    else:
        form = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_REAUTH, "entry_id": entry.entry_id},
            data={},
        )
    flow = hass.config_entries.flow._progress[form["flow_id"]]
    result = await flow.async_step_authorization({CONF_AUTHORIZATION_CODE: CODE_TEXT})
    assert result["step_id"] == ("reauth_confirm" if reauth else "user")
    client_factory.assert_not_called()
    client.async_associate.assert_not_awaited()


@pytest.mark.parametrize(
    "text, expected", [("0", 0), ("65535", 65535), ("00054321", CODE)]
)
async def test_code_submission_uses_only_the_typed_api_and_private_storage(
    hass, client_factory, client, association_client, caplog, text, expected
):
    form = await start_pairing(hass, client)
    client_factory.reset_mock()
    client_factory.return_value = association_client

    async def associate(*, authorization_code_provider):
        assert await authorization_code_provider() == expected
        return client.async_associate.return_value

    association_client.async_associate.side_effect = associate
    result = await hass.config_entries.flow.async_configure(
        form["flow_id"], {CONF_AUTHORIZATION_CODE: text}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    assert entry.data == {
        CONF_USER_GUID: NORMALIZED_USER_GUID,
        CONF_DEVICE_GUID: ROTATED_DEVICE_GUID,
    }
    assert entry.options == {}
    assert entry.title == "Hoben"
    assert entry.unique_id == user_guid_fingerprint(USER_GUID)
    client_factory.assert_called_once_with(
        user_guid=NORMALIZED_USER_GUID, device_guid=None
    )
    association_client.async_associate.assert_awaited_once()
    association_client.async_refresh.assert_not_awaited()
    association_client.async_close.assert_awaited_once_with()
    assert CONF_AUTHORIZATION_CODE not in entry.data
    assert CONF_AUTHORIZATION_CODE not in entry.options
    # The only identifiers exported are the explicitly private storage payload.
    assert_public(
        {k: v for k, v in result.items() if k not in {"data", "result"}}, hass, caplog
    )
    assert CODE_TEXT not in repr(entry.data) + repr(entry.options)


async def test_already_authorized_on_code_submission_needs_no_provider_call(
    hass, client_factory, client, association_client
):
    form = await start_pairing(hass, client)
    # The typed client may return a valid opening without needing the code.
    client_factory.return_value = association_client
    result = await hass.config_entries.flow.async_configure(
        form["flow_id"], {CONF_AUTHORIZATION_CODE: CODE_TEXT}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    association_client.async_associate.assert_awaited_once()
    association_client.async_close.assert_awaited_once_with()


ERRORS = [
    (HobenInvalidInputError(), "invalid_identifier"),
    (
        HobenInvalidCredentialsError(CloseClientReason.INVALID_IDENTIFIER),
        "invalid_identifier",
    ),
    (HobenClosedError(CloseClientReason.INVALID_IDENTIFIER), "invalid_identifier"),
    (
        HobenClosedError(CloseClientReason.STOVE_CONNECTION_REQUIRED),
        "stove_connection_required",
    ),
    (
        HobenClosedError(CloseClientReason.AUTHORIZATION_REJECTED),
        "authorization_rejected",
    ),
    (
        HobenClosedError(CloseClientReason.AUTHORIZATION_TIMEOUT),
        "authorization_timeout",
    ),
    (HobenClosedError(CloseClientReason.SERVER_MAINTENANCE), "server_maintenance"),
    (HobenClosedError(CloseClientReason.UNKNOWN), "protocol_error"),
    (HobenAuthorizationCodeError(), "invalid_authorization_code"),
    (HobenAuthorizationRequiredError(), "authorization_required"),
    (HobenTimeoutError(), "cannot_connect"),
    (HobenTransportError(), "cannot_connect"),
    (HobenUnsupportedProfileError(StoveProfile.UNKNOWN), "unsupported_stove"),
    (HobenProtocolError(), "protocol_error"),
    (HobenAmbiguousSessionError(), "protocol_error"),
    (RuntimeError(PRIVATE_TEXT + CODE_TEXT), "unknown"),
]


@pytest.mark.parametrize("error, expected", ERRORS)
@pytest.mark.parametrize("reauth", [False, True])
async def test_failed_association_closes_and_keeps_form_and_storage_private(
    hass,
    request,
    client_factory,
    client,
    association_client,
    caplog,
    error,
    expected,
    reauth,
):
    entry = request.getfixturevalue("entry") if reauth else None
    old_data = dict(entry.data) if entry else None
    form = await start_pairing(hass, client, entry)
    client_factory.reset_mock()
    client_factory.return_value = association_client
    error.__cause__ = ValueError(PRIVATE_TEXT + CODE_TEXT)
    association_client.async_associate.side_effect = error
    with caplog.at_level("DEBUG"):
        result = await hass.config_entries.flow.async_configure(
            form["flow_id"], {CONF_AUTHORIZATION_CODE: CODE_TEXT}
        )
    assert result["step_id"] == "authorization"
    assert result["errors"] == {"base": expected}
    assert hass.config_entries.async_entries(DOMAIN) == (
        [] if entry is None else [entry]
    )
    if entry:
        assert entry.data == old_data
        assert entry.options == {"future_option": "retained"}
    client_factory.assert_called_once()
    association_client.async_associate.assert_awaited_once()
    association_client.async_refresh.assert_not_awaited()
    association_client.async_close.assert_awaited_once_with()
    flow = hass.config_entries.flow._progress[form["flow_id"]]
    assert flow._validation_task is None
    assert CODE_TEXT not in repr(flow) + repr(flow.context)
    assert CONF_AUTHORIZATION_CODE not in vars(flow)
    assert_public(result, hass, caplog)


@pytest.mark.parametrize(
    "reason",
    [CloseClientReason.AUTHORIZATION_REJECTED, CloseClientReason.AUTHORIZATION_TIMEOUT],
)
async def test_retry_requires_an_explicit_submission_and_a_fresh_client(
    hass, client_factory, client, association_client, reason
):
    form = await start_pairing(hass, client)
    association_client.async_associate.side_effect = HobenClosedError(reason)
    retry = Mock(
        spec=HobenClient,
        async_associate=AsyncMock(return_value=client.async_associate.return_value),
        async_close=AsyncMock(),
        device_guid_for_persistence=ROTATED_DEVICE_GUID,
    )
    client_factory.reset_mock()
    client_factory.side_effect = [association_client, retry]
    denied = await hass.config_entries.flow.async_configure(
        form["flow_id"], {CONF_AUTHORIZATION_CODE: CODE_TEXT}
    )
    assert denied["errors"] == {"base": reason.value}
    await hass.async_block_till_done()
    await hass.config_entries.flow.async_configure(form["flow_id"])
    assert client_factory.call_count == 1
    association_client.async_close.assert_awaited_once_with()
    result = await hass.config_entries.flow.async_configure(
        form["flow_id"], {CONF_AUTHORIZATION_CODE: "12345"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert client_factory.call_count == 2
    association_client.async_associate.assert_awaited_once()
    retry.async_associate.assert_awaited_once()
    retry.async_close.assert_awaited_once_with()


@pytest.mark.parametrize("reauth", [False, True])
@pytest.mark.parametrize("invalid_assignment", [True, False])
async def test_zero_identity_and_unsupported_opening_cannot_be_committed(
    hass,
    request,
    client_factory,
    client,
    association_client,
    reauth,
    invalid_assignment,
):
    entry = request.getfixturevalue("entry") if reauth else None
    old_data = dict(entry.data) if entry else None
    form = await start_pairing(hass, client, entry)
    client_factory.return_value = association_client
    if invalid_assignment:
        association_client.device_guid_for_persistence = INITIAL_DEVICE_GUID
        expected = "protocol_error"
    else:
        association_client.async_associate.return_value = replace(
            client.async_associate.return_value, profile=StoveProfile.V6
        )
        expected = "unsupported_stove"
    result = await hass.config_entries.flow.async_configure(
        form["flow_id"], {CONF_AUTHORIZATION_CODE: CODE_TEXT}
    )
    assert result["errors"] == {"base": expected}
    assert hass.config_entries.async_entries(DOMAIN) == (
        [] if entry is None else [entry]
    )
    if entry:
        assert entry.data == old_data
    association_client.async_close.assert_awaited_once_with()


@pytest.mark.parametrize("reauth", [False, True])
async def test_cancellation_and_removing_an_active_flow_clean_up_without_storage(
    hass, request, client_factory, client, association_client, reauth
):
    entry = request.getfixturevalue("entry") if reauth else None
    old_data = dict(entry.data) if entry else None
    form = await start_pairing(hass, client, entry)
    client_factory.return_value = association_client
    waiting = asyncio.Event()

    async def pending(*, authorization_code_provider):
        assert await authorization_code_provider() == CODE
        waiting.set()
        await asyncio.Event().wait()

    association_client.async_associate.side_effect = pending
    task = asyncio.create_task(
        hass.config_entries.flow.async_configure(
            form["flow_id"], {CONF_AUTHORIZATION_CODE: CODE_TEXT}
        )
    )
    await asyncio.wait_for(waiting.wait(), timeout=1)
    flow = hass.config_entries.flow._progress[form["flow_id"]]
    hass.config_entries.flow.async_abort(form["flow_id"])
    with pytest.raises(asyncio.CancelledError):
        await task
    association_client.async_close.assert_awaited_once_with()
    assert flow._authorization_user_guid is None
    assert flow._validation_task is None
    assert hass.config_entries.async_entries(DOMAIN) == (
        [] if entry is None else [entry]
    )
    if entry:
        assert entry.data == old_data
    assert not hass.config_entries.flow.async_progress()


@pytest.mark.parametrize("stage", ["constructor", "close"])
async def test_local_failures_are_sanitized_before_committing(
    hass, client_factory, client, association_client, caplog, stage
):
    form = await start_pairing(hass, client)
    client_factory.return_value = association_client
    if stage == "constructor":
        client_factory.side_effect = RuntimeError(PRIVATE_TEXT + CODE_TEXT)
    else:
        association_client.async_close.side_effect = RuntimeError(
            PRIVATE_TEXT + CODE_TEXT
        )
    result = await hass.config_entries.flow.async_configure(
        form["flow_id"], {CONF_AUTHORIZATION_CODE: CODE_TEXT}
    )
    assert result["errors"] == {"base": "unknown"}
    assert not hass.config_entries.async_entries(DOMAIN)
    assert_public(result, hass, caplog)


@pytest.mark.parametrize("assigned", [DEVICE_GUID, ROTATED_DEVICE_GUID])
async def test_reauth_association_uses_current_entry_and_only_updates_device_guid(
    hass, entry, client_factory, client, association_client, assigned
):
    form = await start_pairing(hass, client, entry)
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_DEVICE_GUID: ROTATED_DEVICE_GUID}
    )
    old_data = dict(entry.data)
    old_unique_id = entry.unique_id
    old_title = entry.title
    client_factory.reset_mock()
    client_factory.return_value = association_client
    association_client.device_guid_for_persistence = assigned
    result = await hass.config_entries.flow.async_configure(
        form["flow_id"], {CONF_AUTHORIZATION_CODE: CODE_TEXT}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    client_factory.assert_called_once_with(
        user_guid=NORMALIZED_USER_GUID, device_guid=ROTATED_DEVICE_GUID
    )
    assert entry.data == {**old_data, CONF_DEVICE_GUID: assigned}
    assert entry.options == {"future_option": "retained"}
    assert entry.unique_id == old_unique_id
    assert entry.title == old_title
    assert hass.config_entries.async_entries(DOMAIN) == [entry]
    association_client.async_close.assert_awaited_once_with()


@pytest.mark.parametrize("change_during_call", [False, True])
async def test_reauth_mismatched_identity_never_accepts_assignment(
    hass, entry, client_factory, client, association_client, change_during_call
):
    form = await start_pairing(hass, client, entry)
    changed_data = {**entry.data, CONF_USER_GUID: "a" * 32}
    client_factory.reset_mock()
    client_factory.return_value = association_client
    if change_during_call:

        async def associate(**kwargs):
            hass.config_entries.async_update_entry(entry, data=changed_data)
            return client.async_associate.return_value

        association_client.async_associate.side_effect = associate
    else:
        hass.config_entries.async_update_entry(entry, data=changed_data)
    result = await hass.config_entries.flow.async_configure(
        form["flow_id"], {CONF_AUTHORIZATION_CODE: CODE_TEXT}
    )
    assert result["reason"] == "unique_id_mismatch"
    assert entry.data == changed_data
    assert hass.config_entries.async_entries(DOMAIN) == [entry]
    if change_during_call:
        association_client.async_close.assert_awaited_once_with()
    else:
        client_factory.assert_not_called()


@pytest.mark.parametrize("change_during_call", [False, True])
async def test_reauth_invalidated_entry_data_is_sanitized_and_not_overwritten(
    hass, entry, client_factory, client, association_client, caplog, change_during_call
):
    form = await start_pairing(hass, client, entry)
    changed_data = {**entry.data, CONF_USER_GUID: PRIVATE_TEXT + CODE_TEXT}
    client_factory.reset_mock()
    client_factory.return_value = association_client
    if change_during_call:

        async def associate(**kwargs):
            hass.config_entries.async_update_entry(entry, data=changed_data)
            return client.async_associate.return_value

        association_client.async_associate.side_effect = associate
    else:
        hass.config_entries.async_update_entry(entry, data=changed_data)
    result = await hass.config_entries.flow.async_configure(
        form["flow_id"], {CONF_AUTHORIZATION_CODE: CODE_TEXT}
    )
    assert result["step_id"] == "authorization"
    assert result["errors"] == {"base": "invalid_identifier"}
    assert entry.data == changed_data
    assert_public(result, hass, caplog)
    if change_during_call:
        association_client.async_close.assert_awaited_once_with()
    else:
        client_factory.assert_not_called()


async def test_duplicate_created_while_waiting_for_code_prevents_new_attempt(
    hass, request, client_factory, client
):
    form = await start_pairing(hass, client)
    entry = request.getfixturevalue("entry")
    client_factory.reset_mock()
    result = await hass.config_entries.flow.async_configure(
        form["flow_id"], {CONF_AUTHORIZATION_CODE: CODE_TEXT}
    )
    assert result["reason"] == "already_configured"
    client_factory.assert_not_called()
    assert hass.config_entries.async_entries(DOMAIN) == [entry]


@pytest.mark.parametrize("reauth", [False, True])
async def test_real_client_pairing_emits_exact_existing_handshake_and_no_modbus(
    hass, request, monkeypatch, caplog, reauth
):
    """No client mock: only the TLS transport is replaced with synthetic bytes."""
    entry = request.getfixturevalue("entry") if reauth else None
    opened = bytearray(48)
    opened[0] = 0x04
    opened[8:11] = bytes([5, 2, 8])
    opened[14:46] = ROTATED_DEVICE_GUID.encode("ascii")
    opened[46:48] = b"\x00\x02"
    probe = Mock(
        spec=AsyncTlsTransport,
        connect=AsyncMock(),
        write=AsyncMock(),
        read=AsyncMock(return_value=b"\x2f"),
        close=AsyncMock(),
    )
    association = Mock(
        spec=AsyncTlsTransport,
        connect=AsyncMock(),
        write=AsyncMock(),
        read=AsyncMock(
            side_effect=[b"\x0a\x2f\x0a" + bytes(opened[:17]), bytes(opened[17:])]
        ),
        close=AsyncMock(),
    )
    factory = Mock(side_effect=[probe, association])
    monkeypatch.setattr("custom_components.hoben.client.AsyncTlsTransport", factory)
    if reauth:
        form = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_REAUTH, "entry_id": entry.entry_id},
            data={},
        )
        form = await hass.config_entries.flow.async_configure(form["flow_id"], {})
    else:
        form = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        form = await hass.config_entries.flow.async_configure(
            form["flow_id"], {CONF_USER_GUID: USER_GUID}
        )
    assert form["step_id"] == "authorization"
    probe.close.assert_awaited_once_with()
    assert factory.call_count == 1
    result = await hass.config_entries.flow.async_configure(
        form["flow_id"], {CONF_AUTHORIZATION_CODE: CODE_TEXT}
    )
    requests = [args.args[0] for args in association.write.await_args_list]
    assert [packet[0] for packet in requests] == [0x03, 0x0B, 0x30, 0x0B]
    assert requests[2] == b"\x30\x31\xd4"
    assert requests[0][1:33] == NORMALIZED_USER_GUID.encode("ascii")
    assert requests[0][37:69] == (
        DEVICE_GUID if reauth else INITIAL_DEVICE_GUID
    ).encode("ascii")
    assert factory.call_count == 2
    association.close.assert_awaited_once_with()
    assert all(packet[0] != 0x0D for packet in requests)
    if reauth:
        assert result["reason"] == "reauth_successful"
        assert entry.data[CONF_DEVICE_GUID] == ROTATED_DEVICE_GUID
        assert hass.config_entries.async_entries(DOMAIN) == [entry]
    else:
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"][CONF_DEVICE_GUID] == ROTATED_DEVICE_GUID
    assert_public(
        {k: v for k, v in result.items() if k not in {"data", "result"}}, hass, caplog
    )
