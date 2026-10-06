"""Offline DeviceAuth sequence over the real client/session/verified TLS stack."""

import asyncio
import json
import traceback
from dataclasses import FrozenInstanceError, asdict
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.hoben import client as client_module
from custom_components.hoben.client import AssociationResult, HobenClient
from custom_components.hoben.exceptions import (
    HobenAmbiguousSessionError,
    HobenAuthorizationCodeError,
    HobenAuthorizationRequiredError,
    HobenClientClosedError,
    HobenClosedError,
    HobenInvalidCredentialsError,
    HobenInvalidInputError,
    HobenProtocolError,
    HobenTimeoutError,
    HobenTransportError,
    HobenUnsupportedProfileError,
)
from custom_components.hoben.myhoben import INITIAL_DEVICE_GUID, CloseClientReason
from custom_components.hoben.profiles import StoveProfile
from custom_components.hoben.transport import AsyncTlsTransport

# Independent synthetic wire vectors; no production identity/capture/code.
USER_GUID = "01234567-89AB-CDEF-0123-456789ABCDEF"
NORMALIZED_USER_GUID = "0123456789abcdef0123456789abcdef"
DEVICE_GUID = "ABCDabcdABCDabcdABCDabcdABCDabcd"
CODE = 0xABCD
AUTH_RESPONSE = b"\x30\xcd\xab"
OPEN_REQUEST = (
    b"\x030123456789abcdef0123456789abcdef\x00\x01\x22\x00"
    b"00000000000000000000000000000000Synthetic/Association"
)
# 0A/0B inside the prefix are payload, not standalone keepalives.
OPENED = (
    b"\x04\x00\x0a\x0b\x00\x00\x00\x00\x05\x02\x08\x00\x00\x00"
    + DEVICE_GUID.encode("ascii")
    + b"\x00\x02"
)
READ_REQUEST = bytes.fromhex("0D FF FF 00 00 00 06 01 04 04 00 00 14")
READ_RESPONSE = bytes.fromhex("0E FF FF 00 00 00 2B 01 04 28") + b"\x00\x00" * 20


def make_client(**overrides):
    return HobenClient(
        **({"user_guid": USER_GUID, "device_info": "Synthetic/Association"} | overrides)
    )


def emitted(streams):
    return [call.args[0] for call in streams.writer.write.call_args_list]


@pytest.fixture
def transports(monkeypatch):
    """Track actual transport cleanup and detect any implicit reconnect/resend."""
    created = []

    def construct():
        transport = AsyncTlsTransport()
        transport.close = AsyncMock(wraps=transport.close)
        created.append(transport)
        return transport

    monkeypatch.setattr(client_module, "AsyncTlsTransport", Mock(side_effect=construct))
    return created


def assert_cleanup(streams, transports, *, connected=True, attempts=1):
    assert len(transports) == streams.connect.await_count == attempts
    for transport in transports:
        transport.close.assert_awaited_once_with()
        assert transport._writer is None
    assert streams.writer.close.call_count == (attempts if connected else 0)
    assert streams.writer.wait_closed.await_count == (attempts if connected else 0)


def assert_private_output(client, result, capsys, caplog):
    output = capsys.readouterr()
    public = (
        repr(client)
        + repr(result)
        + json.dumps(result.safe_report())
        + json.dumps(client.safe_report())
        + output.out
        + output.err
        + caplog.text
    )
    if isinstance(result, Exception):
        public += "".join(traceback.format_exception(result))
    else:
        public += repr(asdict(result))
    for sensitive in (
        USER_GUID,
        NORMALIZED_USER_GUID,
        DEVICE_GUID,
        str(CODE),
        "PRIVATE",
        "Synthetic/Association",
    ):
        assert sensitive not in public


def test_associate_submits_only_on_request_and_returns_public_metadata(
    streams, transports, capsys, caplog
):
    client = make_client()
    streams.reader.read.side_effect = [b"\x2f", OPENED]

    async def code():
        assert streams.reader.read.await_count == 1
        assert emitted(streams) == [OPEN_REQUEST]
        assert client.device_guid_for_persistence == INITIAL_DEVICE_GUID
        return CODE

    provider = AsyncMock(side_effect=code)
    with caplog.at_level("DEBUG"):
        result = asyncio.run(
            client.async_associate(authorization_code_provider=provider)
        )
    assert result == AssociationResult(StoveProfile.V4, 5, 0, 8, 2, 512)
    with pytest.raises(FrozenInstanceError):
        result.product_type = 6
    assert set(asdict(result)) == {
        "profile",
        "product_type",
        "product_revision",
        "software_major",
        "software_minor",
        "application_version",
    }
    provider.assert_awaited_once_with()
    # This exhaustively excludes every Modbus read/write/control/FFF0 frame.
    assert emitted(streams) == [OPEN_REQUEST, AUTH_RESPONSE]
    assert client.device_guid_for_persistence == DEVICE_GUID
    assert client.has_assigned_device_guid and client.profile is StoveProfile.V4
    assert client.last_snapshot is None
    assert not any(value is provider for value in vars(client).values())
    assert_private_output(client, result, capsys, caplog)
    assert_cleanup(streams, transports)


@pytest.mark.parametrize("use_provider", [False, True])
def test_already_authorized_association_never_requests_or_sends_code(
    streams, transports, use_provider
):
    streams.reader.read.side_effect = [OPENED]
    provider = AsyncMock(side_effect=AssertionError("PRIVATE"))
    client = make_client()
    result = asyncio.run(
        client.async_associate(
            authorization_code_provider=provider if use_provider else None
        )
    )
    assert result.profile is StoveProfile.V4
    assert client.device_guid_for_persistence == DEVICE_GUID
    provider.assert_not_called()
    assert emitted(streams) == [OPEN_REQUEST]
    assert_cleanup(streams, transports)


@pytest.mark.parametrize("method", ["async_associate", "async_refresh"])
def test_no_provider_preserves_authorization_required_observation(
    streams, transports, method
):
    streams.reader.read.side_effect = [b"\x0a\x2fPRIVATE", OPENED]
    client = make_client()
    with pytest.raises(HobenAuthorizationRequiredError):
        asyncio.run(getattr(client, method)())
    assert client.device_guid_for_persistence == INITIAL_DEVICE_GUID
    assert emitted(streams) == [OPEN_REQUEST, b"\x0b"]
    streams.reader.read.assert_awaited_once()
    assert_cleanup(streams, transports)


# Every split across Ping/Req/Ping/Opened, including one coalesced receive and
# a fully fragmented prefix. TLS read boundaries never determine message types.
SEQUENCE = b"\x0a\x2f\x0a" + OPENED


@pytest.mark.parametrize("split", range(len(SEQUENCE)))
def test_every_association_coalescence_and_fragmentation_boundary(
    streams, transports, split
):
    streams.reader.read.side_effect = (
        [SEQUENCE] if split == 0 else [SEQUENCE[:split], SEQUENCE[split:]]
    )
    provider = AsyncMock(return_value=CODE)
    client = make_client()
    result = asyncio.run(client.async_associate(authorization_code_provider=provider))
    assert result.profile is StoveProfile.V4
    provider.assert_awaited_once_with()
    assert emitted(streams) == [OPEN_REQUEST, b"\x0b", AUTH_RESPONSE, b"\x0b"]
    assert client.device_guid_for_persistence == DEVICE_GUID
    assert_cleanup(streams, transports)


def test_byte_at_a_time_and_multiple_ping_before_and_after_code(streams, transports):
    sequence = b"\x0a\x0a\x2f\x0a\x0a" + OPENED
    streams.reader.read.side_effect = [bytes([value]) for value in sequence]
    provider = AsyncMock(return_value=CODE)
    result = asyncio.run(
        make_client().async_associate(authorization_code_provider=provider)
    )
    assert result.profile is StoveProfile.V4
    assert emitted(streams) == [
        OPEN_REQUEST,
        b"\x0b",
        b"\x0b",
        AUTH_RESPONSE,
        b"\x0b",
        b"\x0b",
    ]
    assert streams.reader.read.await_count == len(sequence)
    provider.assert_awaited_once_with()
    assert_cleanup(streams, transports)


@pytest.mark.parametrize("after_code", [False, True])
@pytest.mark.parametrize("fragmented", [False, True])
@pytest.mark.parametrize(
    ("subcode", "reason"),
    [
        (2, CloseClientReason.INVALID_IDENTIFIER),
        (3, CloseClientReason.STOVE_CONNECTION_REQUIRED),
        (4, CloseClientReason.AUTHORIZATION_REJECTED),
        (5, CloseClientReason.AUTHORIZATION_TIMEOUT),
        (6, CloseClientReason.SERVER_MAINTENANCE),
        (255, CloseClientReason.UNKNOWN),
    ],
)
def test_close_before_or_after_code_preserves_reason_without_retry(
    streams, transports, capsys, caplog, after_code, fragmented, subcode, reason
):
    closed = bytes([5, subcode]) + b"\x0a\x2fPRIVATE"
    chunks = [closed[:1], closed[1:]] if fragmented else [closed]
    streams.reader.read.side_effect = ([b"\x2f"] if after_code else []) + chunks
    provider = AsyncMock(return_value=CODE)
    client = make_client()
    error = HobenInvalidCredentialsError if subcode == 2 else HobenClosedError
    with caplog.at_level("DEBUG"), pytest.raises(error) as caught:
        asyncio.run(client.async_associate(authorization_code_provider=provider))
    assert caught.value.reason is reason
    assert caught.value.safe_report()["reason"] == reason.value
    assert provider.await_count == int(after_code)
    assert emitted(streams) == [OPEN_REQUEST] + ([AUTH_RESPONSE] if after_code else [])
    assert client.device_guid_for_persistence == INITIAL_DEVICE_GUID
    assert_private_output(client, caught.value, capsys, caplog)
    assert_cleanup(streams, transports)


def test_close_without_subcode_after_code_remains_unknown(streams, transports):
    streams.reader.read.side_effect = [b"\x2f", b"\x05", b""]
    with pytest.raises(HobenClosedError) as caught:
        asyncio.run(
            make_client().async_associate(
                authorization_code_provider=AsyncMock(return_value=CODE)
            )
        )
    assert caught.value.reason is CloseClientReason.UNKNOWN
    assert emitted(streams) == [OPEN_REQUEST, AUTH_RESPONSE]
    assert_cleanup(streams, transports)


@pytest.mark.parametrize(
    "reply",
    [
        b"\xffPRIVATE",
        b"PRIVATE\x04" + OPENED,
        b"\x30PRIVATE",
        OPENED[:14] + b"\xff" + OPENED[15:],
    ],
)
def test_malformed_association_response_is_sanitized_without_adoption_or_retry(
    streams, transports, capsys, caplog, reply
):
    # Retained coalesced data must not be dropped or scanned for an OpenedClient.
    streams.reader.read.side_effect = [b"\x2f" + reply]
    client = make_client()
    with caplog.at_level("DEBUG"), pytest.raises(HobenProtocolError) as caught:
        asyncio.run(
            client.async_associate(
                authorization_code_provider=AsyncMock(return_value=CODE)
            )
        )
    assert emitted(streams) == [OPEN_REQUEST, AUTH_RESPONSE]
    assert not client.has_assigned_device_guid
    assert client.profile is None
    assert_private_output(client, caught.value, capsys, caplog)
    assert_cleanup(streams, transports)


@pytest.mark.parametrize("suffix", [b"\x0a", OPENED, READ_RESPONSE, b"PRIVATE"])
def test_opened_suffix_after_association_is_never_reframed_or_adopted(
    streams, transports, suffix
):
    streams.reader.read.side_effect = [b"\x2f", OPENED + suffix]
    client = make_client()
    with pytest.raises(HobenAmbiguousSessionError):
        asyncio.run(
            client.async_associate(
                authorization_code_provider=AsyncMock(return_value=CODE)
            )
        )
    assert emitted(streams) == [OPEN_REQUEST, AUTH_RESPONSE]
    assert not client.has_assigned_device_guid and client.last_snapshot is None
    assert_cleanup(streams, transports)


@pytest.mark.parametrize("size", [0, 1, 14, 47])
def test_eof_after_request_or_truncated_opened_never_retries_code(
    streams, transports, size
):
    streams.reader.read.side_effect = [b"\x2f", OPENED[:size], b""]
    provider = AsyncMock(return_value=CODE)
    client = make_client()
    with pytest.raises(HobenTransportError):
        asyncio.run(client.async_associate(authorization_code_provider=provider))
    provider.assert_awaited_once_with()
    assert emitted(streams) == [OPEN_REQUEST, AUTH_RESPONSE]
    assert not client.has_assigned_device_guid
    assert_cleanup(streams, transports)


def test_eof_before_one_byte_request_is_not_a_request(streams, transports):
    streams.reader.read.return_value = b""
    provider = AsyncMock(return_value=CODE)
    with pytest.raises(HobenTransportError):
        asyncio.run(make_client().async_associate(authorization_code_provider=provider))
    provider.assert_not_called()
    assert emitted(streams) == [OPEN_REQUEST]
    assert_cleanup(streams, transports)


@pytest.mark.parametrize("coalesced", [False, True])
def test_repeated_request_cannot_resubmit_code_or_reinvoke_provider(
    streams, transports, coalesced
):
    streams.reader.read.side_effect = (
        [b"\x2f\x0a\x2f"] if coalesced else [b"\x2f", b"\x0a\x2f"]
    )
    provider = AsyncMock(return_value=CODE)
    with pytest.raises(HobenProtocolError):
        asyncio.run(make_client().async_associate(authorization_code_provider=provider))
    provider.assert_awaited_once_with()
    assert emitted(streams) == [OPEN_REQUEST, AUTH_RESPONSE, b"\x0b"]
    assert_cleanup(streams, transports)


@pytest.mark.parametrize(
    "value", [-1, 65536, True, False, "PRIVATE", str(CODE), 1.5, None, b"PRIVATE"]
)
def test_invalid_code_is_not_coerced_sent_or_exposed(
    streams, transports, capsys, caplog, value
):
    streams.reader.read.side_effect = [b"\x2f"]
    client = make_client()
    with caplog.at_level("DEBUG"), pytest.raises(HobenAuthorizationCodeError) as caught:
        asyncio.run(
            client.async_associate(
                authorization_code_provider=AsyncMock(return_value=value)
            )
        )
    assert str(caught.value) == "authorization_code_unavailable"
    assert emitted(streams) == [OPEN_REQUEST]
    assert_private_output(client, caught.value, capsys, caplog)
    assert_cleanup(streams, transports)


@pytest.mark.parametrize("failure", [ValueError("PRIVATE"), TimeoutError("PRIVATE")])
def test_provider_exception_is_a_local_sanitized_failure_not_server_expiration(
    streams, transports, capsys, caplog, failure
):
    streams.reader.read.side_effect = [b"\x2f"]
    client = make_client()
    with caplog.at_level("DEBUG"), pytest.raises(HobenAuthorizationCodeError) as caught:
        asyncio.run(
            client.async_associate(
                authorization_code_provider=AsyncMock(side_effect=failure)
            )
        )
    assert emitted(streams) == [OPEN_REQUEST]
    assert_private_output(client, caught.value, capsys, caplog)
    assert_cleanup(streams, transports)


def test_sync_provider_return_is_rejected_without_secret_text(streams, transports):
    streams.reader.read.side_effect = [b"\x2f"]
    with pytest.raises(HobenAuthorizationCodeError):
        asyncio.run(
            make_client().async_associate(authorization_code_provider=lambda: CODE)
        )
    assert emitted(streams) == [OPEN_REQUEST]
    assert_cleanup(streams, transports)


@pytest.mark.parametrize("provider", [7, True, "PRIVATE"])
def test_noncallable_provider_fails_before_network(streams, transports, provider):
    with pytest.raises(HobenInvalidInputError):
        asyncio.run(make_client().async_associate(authorization_code_provider=provider))
    assert transports == []
    streams.connect.assert_not_awaited()


@pytest.mark.parametrize("product_type", [2, 3, 255])
def test_unsupported_profile_after_code_never_adopts_device_guid(
    streams, transports, product_type
):
    opened = bytearray(OPENED)
    opened[8] = product_type
    streams.reader.read.side_effect = [b"\x2f", bytes(opened)]
    client = make_client()
    with pytest.raises(HobenUnsupportedProfileError):
        asyncio.run(
            client.async_associate(
                authorization_code_provider=AsyncMock(return_value=CODE)
            )
        )
    assert client.device_guid_for_persistence == INITIAL_DEVICE_GUID
    assert emitted(streams) == [OPEN_REQUEST, AUTH_RESPONSE]
    assert_cleanup(streams, transports)


@pytest.mark.parametrize(
    "phase", ["connect", "open-write", "code-write", "read", "close"]
)
@pytest.mark.parametrize("failure", [OSError("PRIVATE"), TimeoutError("PRIVATE")])
def test_association_transport_failure_never_retries(
    streams, transports, capsys, caplog, phase, failure
):
    streams.reader.read.side_effect = [b"\x2f", OPENED]
    if phase == "connect":
        streams.connect.side_effect = failure
    elif phase == "open-write":
        streams.writer.drain.side_effect = failure
    elif phase == "code-write":
        streams.writer.drain.side_effect = [None, failure]
    elif phase == "read":
        streams.reader.read.side_effect = [b"\x2f", failure]
    else:
        streams.writer.wait_closed.side_effect = failure
    client = make_client()  # max_attempts=2 only applies to async_refresh.
    error = (
        HobenTimeoutError if isinstance(failure, TimeoutError) else HobenTransportError
    )
    with caplog.at_level("DEBUG"), pytest.raises(error) as caught:
        asyncio.run(
            client.async_associate(
                authorization_code_provider=AsyncMock(return_value=CODE)
            )
        )
    assert type(caught.value) is error
    assert client.has_assigned_device_guid == (phase == "close")
    assert client.last_snapshot is None
    assert_private_output(client, caught.value, capsys, caplog)
    assert_cleanup(streams, transports, connected=phase != "connect")


@pytest.mark.parametrize("phase", ["provider", "opened", "endless-ping"])
def test_same_overall_handshake_budget_bounds_association(
    streams, transports, deadlines, phase
):
    async def expire_handshake():
        context = next(ctx for seconds, ctx in deadlines.contexts if seconds == 23.0)
        context.reschedule(asyncio.get_running_loop().time())

    async def provider():
        if phase == "provider":
            await expire_handshake()
            await asyncio.Future()
        return CODE

    async def receive(max_bytes):
        if streams.reader.read.await_count == 1:
            return b"\x2f"
        if phase == "opened" and streams.reader.read.await_count == 2:
            return OPENED[:47]
        await expire_handshake()
        if phase == "endless-ping":
            return b"\x0a"
        await asyncio.Future()

    streams.reader.read.side_effect = receive
    client = make_client(handshake_timeout=23.0)
    with pytest.raises(HobenTimeoutError):
        asyncio.run(client.async_associate(authorization_code_provider=provider))
    assert streams.reader.read.await_count <= 4
    assert not client.has_assigned_device_guid
    assert_cleanup(streams, transports)


@pytest.mark.parametrize("phase", ["connect", "provider", "code-write", "read"])
def test_cancellation_during_association_closes_and_propagates(
    streams, transports, phase
):
    client = make_client()

    async def run():
        waiting = asyncio.Event()

        async def blocked(*args, **kwargs):
            waiting.set()
            await asyncio.Future()

        provider = AsyncMock(return_value=CODE)
        streams.reader.read.side_effect = [b"\x2f", OPENED]
        if phase == "connect":
            streams.connect.side_effect = blocked
        elif phase == "provider":
            provider.side_effect = blocked
        elif phase == "code-write":

            async def drain():
                if streams.writer.drain.await_count == 2:
                    await blocked()

            streams.writer.drain.side_effect = drain
        else:

            async def receive(max_bytes):
                if streams.reader.read.await_count == 1:
                    return b"\x2f"
                await blocked()

            streams.reader.read.side_effect = receive
        task = asyncio.create_task(
            client.async_associate(authorization_code_provider=provider)
        )
        await waiting.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await client.async_close()
        await client.async_close()

    asyncio.run(asyncio.wait_for(run(), 2))
    assert not client.has_assigned_device_guid
    assert_cleanup(streams, transports, connected=phase != "connect")


def test_close_cancels_code_provider_and_rejects_queued_association_and_refresh(
    streams, transports
):
    client = make_client()
    streams.reader.read.side_effect = [b"\x2f", OPENED]

    async def run():
        waiting = asyncio.Event()

        async def provider():
            waiting.set()
            await asyncio.Future()

        active = asyncio.create_task(
            client.async_associate(authorization_code_provider=provider)
        )
        await waiting.wait()
        queued = [
            asyncio.create_task(client.async_associate()),
            asyncio.create_task(client.async_refresh()),
        ]
        await asyncio.sleep(0)
        await client.async_close()
        with pytest.raises(asyncio.CancelledError):
            await active
        for task in queued:
            with pytest.raises(HobenClientClosedError):
                await task
        with pytest.raises(HobenClientClosedError):
            await client.async_associate()

    asyncio.run(asyncio.wait_for(run(), 2))
    assert emitted(streams) == [OPEN_REQUEST]
    assert_cleanup(streams, transports)


def test_association_serializes_with_refresh_and_reuses_assignment_on_fresh_tls(
    streams, transports
):
    client = make_client()
    streams.reader.read.side_effect = [b"\x2f", OPENED, OPENED, READ_RESPONSE]

    async def run():
        waiting = asyncio.Event()
        release = asyncio.Event()

        async def provider():
            waiting.set()
            await release.wait()
            return CODE

        association = asyncio.create_task(
            client.async_associate(authorization_code_provider=provider)
        )
        await waiting.wait()
        refresh = asyncio.create_task(client.async_refresh())
        await asyncio.sleep(0)
        assert len(transports) == streams.connect.await_count == 1
        assert client.device_guid_for_persistence == INITIAL_DEVICE_GUID
        assert not association.done() and not refresh.done()
        release.set()
        result = await association
        assert result.profile is StoveProfile.V4
        snapshot = await refresh
        assert snapshot.registers == (0,) * 20
        assert client.last_snapshot is snapshot

    asyncio.run(asyncio.wait_for(run(), 2))
    assert emitted(streams) == [
        OPEN_REQUEST,
        AUTH_RESPONSE,
        OPEN_REQUEST[:37] + DEVICE_GUID.encode() + OPEN_REQUEST[69:],
        READ_REQUEST,
    ]
    assert_cleanup(streams, transports, attempts=2)


def test_association_failure_preserves_previous_identity_profile_and_snapshot(
    streams, transports
):
    streams.reader.read.side_effect = [OPENED, READ_RESPONSE, b"\x2f", b"\x05\x04"]
    client = make_client()

    async def run():
        previous = await client.async_refresh()
        with pytest.raises(HobenClosedError):
            await client.async_associate(
                authorization_code_provider=AsyncMock(return_value=CODE)
            )
        assert client.last_snapshot is previous
        assert client.profile is StoveProfile.V4
        assert client.device_guid_for_persistence == DEVICE_GUID

    asyncio.run(run())
    assert emitted(streams) == [
        OPEN_REQUEST,
        READ_REQUEST,
        OPEN_REQUEST[:37] + DEVICE_GUID.encode() + OPEN_REQUEST[69:],
        AUTH_RESPONSE,
    ]
    assert_cleanup(streams, transports, attempts=2)


def test_secondary_shutdown_failure_does_not_hide_authorization_rejection(
    streams, transports
):
    streams.reader.read.side_effect = [b"\x2f", b"\x05\x04PRIVATE"]
    streams.writer.wait_closed.side_effect = OSError("PRIVATE")
    with pytest.raises(HobenClosedError) as caught:
        asyncio.run(
            make_client().async_associate(
                authorization_code_provider=AsyncMock(return_value=CODE)
            )
        )
    assert caught.value.reason is CloseClientReason.AUTHORIZATION_REJECTED
    streams.writer.transport.abort.assert_called_once_with()
    assert_cleanup(streams, transports)


def test_successful_association_rotates_identity_without_replacing_snapshot(
    streams, transports
):
    rotated = "Z" * 32
    streams.reader.read.side_effect = [
        OPENED,
        READ_RESPONSE,
        b"\x2f",
        OPENED[:14] + rotated.encode("ascii") + OPENED[46:],
    ]
    client = make_client()

    async def run():
        previous = await client.async_refresh()
        await client.async_associate(
            authorization_code_provider=AsyncMock(return_value=CODE)
        )
        assert client.last_snapshot is previous
        assert client.device_guid_for_persistence == rotated

    asyncio.run(run())
    assert emitted(streams) == [
        OPEN_REQUEST,
        READ_REQUEST,
        OPEN_REQUEST[:37] + DEVICE_GUID.encode() + OPEN_REQUEST[69:],
        AUTH_RESPONSE,
    ]
    assert_cleanup(streams, transports, attempts=2)


def test_only_explicit_caller_attempt_can_retry_after_authorization_rejection(
    streams, transports
):
    streams.reader.read.side_effect = [b"\x2f", b"\x05\x04", b"\x2f", OPENED]
    client = make_client()

    async def run():
        with pytest.raises(HobenClosedError):
            await client.async_associate(
                authorization_code_provider=AsyncMock(return_value=CODE)
            )
        assert len(transports) == streams.connect.await_count == 1
        assert not client.has_assigned_device_guid
        streams.writer.wait_closed.assert_awaited_once_with()
        result = await client.async_associate(
            authorization_code_provider=AsyncMock(return_value=CODE)
        )
        assert result.profile is StoveProfile.V4
        assert client.device_guid_for_persistence == DEVICE_GUID

    asyncio.run(run())
    assert emitted(streams) == [OPEN_REQUEST, AUTH_RESPONSE] * 2
    assert_cleanup(streams, transports, attempts=2)
