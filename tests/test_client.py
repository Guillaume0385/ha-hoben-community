"""Offline reusable client lifecycle over real verified TLS transport primitives."""

import asyncio
import json
import ssl
import traceback
from dataclasses import FrozenInstanceError, asdict
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.hoben import client as client_module
from custom_components.hoben.client import HobenClient, RawStoveSnapshot
from custom_components.hoben.exceptions import (
    HobenAmbiguousSessionError,
    HobenAuthorizationRequiredError,
    HobenClientClosedError,
    HobenClosedError,
    HobenInvalidCredentialsError,
    HobenInvalidInputError,
    HobenModbusError,
    HobenProtocolError,
    HobenRefreshExhaustedError,
    HobenTimeoutError,
    HobenUnsupportedProfileError,
)
from custom_components.hoben.myhoben import (
    INITIAL_DEVICE_GUID,
    CloseClientReason,
    OpenedClient,
)
from custom_components.hoben.profiles import StoveProfile
from custom_components.hoben.session import OpenSessionResult
from custom_components.hoben.transport import AsyncTlsTransport

# Independent, wholly synthetic identities/frames, never production captures.
USER_GUID = "01234567-89AB-CDEF-0123-456789ABCDEF"
NORMALIZED_USER_GUID = "0123456789abcdef0123456789abcdef"
DEVICE_GUID = "ABCDabcdABCDabcdABCDabcdABCDabcd"
OPENED = (
    b"\x04\x00\x0a\x0b\x00\x00\x00\x00\x05\x02\x08\x00\x00\x00"
    + DEVICE_GUID.encode()
    + b"\x00\x02"
)
REGISTERS = (0, 1, 0x0A0B, 0x7FFF, 0x8000, 0xFFFF, *range(14))
READ_REQUEST = bytes.fromhex("0D FF FF 00 00 00 06 01 04 04 00 00 14")
OPEN_REQUEST = (
    b"\x030123456789abcdef0123456789abcdef\x00\x01\x22\x00"
    b"00000000000000000000000000000000Synthetic/HobenClient"
)


def read_response(registers=REGISTERS):
    """Independent fixed read response; the production encoder is not the oracle."""
    data = b"".join(value.to_bytes(2, "big") for value in registers)
    return (
        b"\x0e\xff\xff\x00\x00"
        + (len(data) + 3).to_bytes(2, "big")
        + bytes([1, 4, len(data)])
        + data
    )


RESPONSE = read_response()


def make_client(**overrides):
    return HobenClient(
        **({"user_guid": USER_GUID, "device_info": "Synthetic/HobenClient"} | overrides)
    )


@pytest.fixture
def tls(monkeypatch):
    """Two distinct TLS stream pairs and tracked fresh real transport instances."""
    pairs = []
    for _ in range(2):
        pairs.append(
            SimpleNamespace(
                reader=SimpleNamespace(read=AsyncMock(side_effect=[OPENED, RESPONSE])),
                writer=SimpleNamespace(
                    write=Mock(),
                    drain=AsyncMock(),
                    close=Mock(),
                    wait_closed=AsyncMock(),
                    transport=SimpleNamespace(abort=Mock()),
                ),
            )
        )
    connect = AsyncMock(side_effect=[(pair.reader, pair.writer) for pair in pairs])
    monkeypatch.setattr(asyncio, "open_connection", connect)
    transports = []

    def fresh_transport():
        transport = AsyncTlsTransport()
        transport.close = AsyncMock(wraps=transport.close)
        transports.append(transport)
        return transport

    factory = Mock(side_effect=fresh_transport)
    monkeypatch.setattr(client_module, "AsyncTlsTransport", factory)
    return SimpleNamespace(
        pairs=pairs, connect=connect, factory=factory, transports=transports
    )


@pytest.fixture(autouse=True)
def backoff(monkeypatch):
    """Keep real scheduler yields, but make positive retry delays deterministic."""
    original = asyncio.sleep
    delays = []

    async def sleep(delay):
        if delay:
            delays.append(delay)
        await original(0)

    monkeypatch.setattr(asyncio, "sleep", sleep)
    return SimpleNamespace(delays=delays, original=original)


def emitted(pair):
    return [call.args[0] for call in pair.writer.write.call_args_list]


def assert_cleanup(tls, attempts=1):
    assert tls.factory.call_count == attempts
    assert len({id(transport) for transport in tls.transports}) == attempts
    for transport in tls.transports:
        transport.close.assert_awaited_once_with()
        assert transport._writer is None
    for pair in tls.pairs[: tls.connect.await_count]:
        pair.writer.close.assert_called_once_with()
        pair.writer.wait_closed.assert_awaited_once_with()


def test_first_refresh_normalizes_identity_and_returns_immutable_raw_snapshot(tls):
    client = make_client()
    assert client.device_guid_for_persistence == INITIAL_DEVICE_GUID
    assert client.has_assigned_device_guid is False
    assert client.profile is None and client.last_snapshot is None
    snapshot = asyncio.run(client.async_refresh())
    assert isinstance(snapshot, RawStoveSnapshot)
    assert snapshot == RawStoveSnapshot(StoveProfile.V4, REGISTERS, 5, 0, 8, 2, 512)
    assert emitted(tls.pairs[0]) == [OPEN_REQUEST, READ_REQUEST]
    assert client.device_guid_for_persistence == DEVICE_GUID
    assert client.has_assigned_device_guid is True
    assert client.profile is StoveProfile.V4
    assert client.last_snapshot is snapshot
    with pytest.raises(FrozenInstanceError):
        snapshot.product_type = 2
    with pytest.raises(TypeError):
        snapshot.registers[0] = 7
    assert_cleanup(tls)
    args, kwargs = tls.connect.call_args
    assert args == ("myhoben.fr", 465)
    assert kwargs["server_hostname"] == "myhoben.fr"
    assert kwargs["ssl"].verify_mode == ssl.CERT_REQUIRED
    assert kwargs["ssl"].check_hostname is True


def test_default_client_uses_documented_stable_device_info(tls):
    """The coordinator-facing default must send the documented community identity."""
    client = HobenClient(user_guid=USER_GUID)
    asyncio.run(client.async_refresh())
    descriptor = b"ha-hoben-community/GitHubActions/en/Python/Linux/0/0/1/0/0,0"
    assert emitted(tls.pairs[0])[0] == OPEN_REQUEST[:69] + descriptor
    assert client_module.DEFAULT_DEVICE_INFO == descriptor.decode()
    assert_cleanup(tls)


@pytest.mark.parametrize(
    "device_guid", [DEVICE_GUID, "\x00 \taZz!\x7f" * 4, " " * 32, "Z" * 32]
)
def test_persisted_identity_is_used_first_without_inventing_hex_restrictions(
    tls, device_guid
):
    client = make_client(device_guid=device_guid)
    assert client.device_guid_for_persistence == device_guid
    asyncio.run(client.async_refresh())
    assert emitted(tls.pairs[0])[0][37:69] == device_guid.encode("ascii")
    assert_cleanup(tls)


@pytest.mark.parametrize(
    "device_guid", ["", "X" * 31, "X" * 33, "é" * 32, "\ud800" * 32, b"X" * 32, 7, True]
)
def test_bad_persisted_identity_fails_before_transport_creation(tls, device_guid):
    with pytest.raises(HobenInvalidInputError) as caught:
        make_client(device_guid=device_guid)
    assert str(caught.value) == "invalid_client_inputs"
    tls.factory.assert_not_called()
    tls.connect.assert_not_awaited()


@pytest.mark.parametrize(
    "overrides",
    [
        {"user_guid": "PRIVATE"},
        {"user_guid": None},
        {"user_guid": " PRIVATE "},
        *[{"max_attempts": value} for value in (0, 3, True, 1.5, "PRIVATE")],
        *[
            {"retry_delay": value}
            for value in (-1, 31, True, float("nan"), float("inf"), "PRIVATE")
        ],
        *[
            {field: value}
            for field in ("handshake_timeout", "read_timeout")
            for value in (0, True, float("nan"), float("inf"), "PRIVATE")
        ],
        {"build": -1},
        {"build": True},
        {"device_info": None},
        {"device_info": "PRIVATE\ud800"},
    ],
)
def test_all_invalid_settings_are_sanitized_before_network(tls, overrides):
    with pytest.raises(HobenInvalidInputError) as caught:
        make_client(**overrides)
    assert "PRIVATE" not in "".join(traceback.format_exception(caught.value))
    tls.factory.assert_not_called()


def test_two_refreshes_close_first_then_reuse_assignment_on_fresh_transport(tls):
    client = make_client()
    rotated = "Z" * 32
    tls.pairs[1].reader.read.side_effect = [
        OPENED[:14] + rotated.encode() + OPENED[46:],
        read_response((42,) * 20),
    ]

    async def run():
        first = await client.async_refresh()
        tls.pairs[0].writer.wait_closed.assert_awaited_once_with()
        second = await client.async_refresh()
        assert first.registers == REGISTERS
        assert second.registers == (42,) * 20
        assert client.last_snapshot is second
        await client.async_close()
        await client.async_close()

    asyncio.run(run())
    assert emitted(tls.pairs[1]) == [
        OPEN_REQUEST[:37] + DEVICE_GUID.encode() + OPEN_REQUEST[69:],
        READ_REQUEST,
    ]
    assert client.device_guid_for_persistence == rotated
    assert_cleanup(tls, 2)


def test_persistence_accessor_can_seed_a_new_client(tls):
    async def run():
        first = make_client()
        await first.async_refresh()
        second = make_client(device_guid=first.device_guid_for_persistence)
        await first.async_close()
        await second.async_refresh()
        await second.async_close()

    asyncio.run(run())
    assert emitted(tls.pairs[1])[0][37:69] == DEVICE_GUID.encode()
    assert_cleanup(tls, 2)


def test_no_identity_in_repr_snapshot_generic_export_or_diagnostics(
    tls, capsys, caplog
):
    client = make_client()
    with caplog.at_level("DEBUG"):
        snapshot = asyncio.run(client.async_refresh())
    exported = asdict(snapshot)
    assert set(exported) == {
        "profile",
        "registers",
        "product_type",
        "product_revision",
        "software_major",
        "software_minor",
        "application_version",
    }
    with pytest.raises(TypeError):
        asdict(client)
    output = capsys.readouterr()
    public = (
        repr(client)
        + repr(snapshot)
        + repr(exported)
        + json.dumps(client.safe_report())
        + json.dumps(snapshot.safe_report())
        + output.out
        + output.err
        + caplog.text
    )
    for sensitive in (USER_GUID, NORMALIZED_USER_GUID, DEVICE_GUID):
        assert sensitive not in public
    assert "Synthetic/HobenClient" not in repr(client)
    assert snapshot.safe_report()["register_count"] == 20
    assert "registers" not in snapshot.safe_report()
    assert client.device_guid_for_persistence == DEVICE_GUID


@pytest.mark.parametrize(
    ("product_type", "revision", "major", "profile"),
    [
        (2, 0, 0, StoveProfile.V6),
        (2, 2, 0, StoveProfile.BOILER_V6_230),
        (3, 1, 0, StoveProfile.UNKNOWN),
        (255, 0, 8, StoveProfile.UNKNOWN),
    ],
)
def test_unsupported_dynamic_profile_fails_without_read_adoption_or_retry(
    tls, backoff, product_type, revision, major, profile
):
    opened = bytearray(OPENED)
    opened[7], opened[8], opened[10] = revision, product_type, major
    tls.pairs[0].reader.read.side_effect = [bytes(opened)]
    client = make_client()
    with pytest.raises(HobenUnsupportedProfileError) as caught:
        asyncio.run(client.async_refresh())
    assert caught.value.profile is profile
    assert emitted(tls.pairs[0]) == [OPEN_REQUEST]
    assert client.device_guid_for_persistence == INITIAL_DEVICE_GUID
    assert backoff.delays == []
    assert_cleanup(tls)


@pytest.mark.parametrize("suffix", [b"PRIVATE", b"\x0a", RESPONSE])
def test_unclassified_opening_fails_without_reframing_adoption_or_retry(tls, suffix):
    tls.pairs[0].reader.read.side_effect = [OPENED + suffix]
    client = make_client()
    with pytest.raises(HobenAmbiguousSessionError):
        asyncio.run(client.async_refresh())
    assert client.device_guid_for_persistence == INITIAL_DEVICE_GUID
    assert emitted(tls.pairs[0]) == [OPEN_REQUEST]
    assert_cleanup(tls)


@pytest.mark.parametrize(
    ("opening", "error", "reason"),
    [
        (b"\x2fPRIVATE", HobenAuthorizationRequiredError, None),
        *[
            (
                bytes([5, code]) + b"PRIVATE",
                HobenInvalidCredentialsError if code == 2 else HobenClosedError,
                reason,
            )
            for code, reason in [
                (2, CloseClientReason.INVALID_IDENTIFIER),
                (3, CloseClientReason.STOVE_CONNECTION_REQUIRED),
                (4, CloseClientReason.AUTHORIZATION_REJECTED),
                (5, CloseClientReason.AUTHORIZATION_TIMEOUT),
                (6, CloseClientReason.SERVER_MAINTENANCE),
                (255, CloseClientReason.UNKNOWN),
            ]
        ],
    ],
)
def test_authorization_or_server_close_never_reads_or_retries(
    tls, backoff, capsys, caplog, opening, error, reason
):
    tls.pairs[0].reader.read.side_effect = [opening]
    with caplog.at_level("DEBUG"), pytest.raises(error) as caught:
        asyncio.run(make_client().async_refresh())
    if reason is not None:
        assert caught.value.reason is reason
        assert caught.value.safe_report()["reason"] == reason.value
    output = capsys.readouterr()
    public = (
        "".join(traceback.format_exception(caught.value))
        + repr(caught.value)
        + json.dumps(caught.value.safe_report())
        + output.out
        + output.err
        + caplog.text
    )
    for sensitive in ("PRIVATE", USER_GUID, NORMALIZED_USER_GUID, DEVICE_GUID):
        assert sensitive not in public
    assert backoff.delays == []
    assert emitted(tls.pairs[0]) == [OPEN_REQUEST]
    assert_cleanup(tls)


@pytest.mark.parametrize(
    "reply",
    [
        read_response((0,) * 19),
        read_response((0,) * 21),
        RESPONSE[:1] + b"\xff\xf0" + RESPONSE[3:],
        RESPONSE[:7] + b"\x02" + RESPONSE[8:],
        *[
            RESPONSE[:8] + bytes([function]) + RESPONSE[9:]
            for function in (3, 6, 16, 22)
        ],
        RESPONSE + b"PRIVATE",
        RESPONSE[:10],
        bytes.fromhex("0E FF FF 00 01 00 2B"),
        b"\x1bPRIVATE",
    ],
)
def test_malformed_or_uncorrelated_read_never_retries(tls, backoff, reply):
    tls.pairs[0].reader.read.side_effect = [OPENED, reply, b""]
    client = make_client()
    with pytest.raises(HobenProtocolError):
        asyncio.run(client.async_refresh())
    assert client.has_assigned_device_guid
    assert client.last_snapshot is None
    assert backoff.delays == []
    assert emitted(tls.pairs[0]) == [OPEN_REQUEST, READ_REQUEST]
    assert_cleanup(tls)


@pytest.mark.parametrize("code", [0, 2, 255])
def test_correlated_modbus_exception_is_distinct_and_not_retried(tls, backoff, code):
    tls.pairs[0].reader.read.side_effect = [
        OPENED,
        bytes.fromhex("0E FF FF 00 00 00 03 01 84") + bytes([code]),
    ]
    with pytest.raises(HobenModbusError) as caught:
        asyncio.run(make_client().async_refresh())
    assert caught.value.exception_code == code
    assert caught.value.safe_report()["exception_code"] == code
    assert backoff.delays == []
    assert_cleanup(tls)


def test_invalid_returned_identity_never_adopted(tls, monkeypatch):
    session = OpenSessionResult(
        OpenedClient(0, 5, 2, 8, "INVALID", 512), StoveProfile.V4
    )
    monkeypatch.setattr(client_module, "_open_session", AsyncMock(return_value=session))
    client = make_client()
    with pytest.raises(HobenProtocolError):
        asyncio.run(client.async_refresh())
    assert client.device_guid_for_persistence == INITIAL_DEVICE_GUID
    assert client.profile is None
    tls.connect.assert_not_awaited()
    tls.pairs[0].writer.write.assert_not_called()
    assert_cleanup(tls)


@pytest.mark.parametrize(
    "opening", [OPENED[:14] + b"\xff" + OPENED[15:], b"\xffPRIVATE"]
)
def test_malformed_opening_is_not_retried(tls, opening):
    tls.pairs[0].reader.read.side_effect = [opening]
    client = make_client()
    with pytest.raises(HobenProtocolError):
        asyncio.run(client.async_refresh())
    assert not client.has_assigned_device_guid
    assert_cleanup(tls)


def test_leading_ping_and_fragmented_responses_preserve_exact_read(tls):
    tls.pairs[0].reader.read.side_effect = [
        b"\x0a" + OPENED[:9],
        OPENED[9:],
        b"\x0a" + RESPONSE[:5],
        RESPONSE[5:],
    ]
    assert asyncio.run(make_client().async_refresh()).registers == REGISTERS
    assert emitted(tls.pairs[0]) == [OPEN_REQUEST, b"\x0b", READ_REQUEST, b"\x0b"]
    assert_cleanup(tls)


@pytest.mark.parametrize("phase", ["connect", "handshake", "read", "write", "close"])
@pytest.mark.parametrize("failure", [OSError("PRIVATE"), TimeoutError("PRIVATE")])
def test_one_transport_failure_gets_one_async_delay_and_fresh_success(
    tls, backoff, phase, failure
):
    client = make_client(retry_delay=0.25)
    if phase == "connect":
        tls.connect.side_effect = [failure, (tls.pairs[1].reader, tls.pairs[1].writer)]
    elif phase == "handshake":
        tls.pairs[0].reader.read.side_effect = [failure]
    elif phase == "read":
        tls.pairs[0].reader.read.side_effect = [OPENED, failure]
    elif phase == "write":
        tls.pairs[0].writer.drain.side_effect = [None, failure]
    else:
        tls.pairs[0].writer.wait_closed.side_effect = failure
    assert asyncio.run(client.async_refresh()).registers == REGISTERS
    assert backoff.delays == [0.25]
    assert tls.factory.call_count == tls.connect.await_count == 2
    assert len({id(transport) for transport in tls.transports}) == 2
    for transport in tls.transports:
        transport.close.assert_awaited_once_with()
        assert transport._writer is None
    tls.pairs[1].writer.wait_closed.assert_awaited_once_with()
    expected_guid = (
        INITIAL_DEVICE_GUID if phase in ("connect", "handshake") else DEVICE_GUID
    )
    assert emitted(tls.pairs[1])[0][37:69] == expected_guid.encode()
    if phase != "connect":
        tls.pairs[0].writer.wait_closed.assert_awaited_once_with()
    assert client.last_snapshot is not None


@pytest.mark.parametrize("max_attempts", [1, 2])
@pytest.mark.parametrize(
    "failure", [OSError("PRIVATE"), TimeoutError("PRIVATE"), ssl.SSLError("PRIVATE")]
)
def test_retry_exhaustion_is_finite_typed_and_sanitized(
    tls, backoff, caplog, max_attempts, failure
):
    tls.connect.side_effect = failure
    with caplog.at_level("DEBUG"), pytest.raises(HobenRefreshExhaustedError) as caught:
        asyncio.run(make_client(max_attempts=max_attempts).async_refresh())
    assert caught.value.attempts == max_attempts
    assert caught.value.safe_report()["attempts"] == max_attempts
    assert isinstance(caught.value.last_error, HobenTimeoutError) == isinstance(
        failure, TimeoutError
    )
    assert tls.connect.await_count == tls.factory.call_count == max_attempts
    assert backoff.delays == ([1.0] if max_attempts == 2 else [])
    assert "PRIVATE" not in "".join(
        traceback.format_exception(caught.value)
    ) + caplog.text + json.dumps(caught.value.safe_report())
    for transport in tls.transports:
        transport.close.assert_awaited_once_with()


@pytest.mark.parametrize("phase", ["handshake", "read"])
def test_overall_deadline_is_typed_transport_failure(tls, deadlines, phase):
    async def receive(max_bytes):
        if phase == "read" and tls.pairs[0].reader.read.await_count == 1:
            return OPENED
        context = next(
            ctx for delay, ctx in reversed(deadlines.contexts) if delay == 23.0
        )
        context.reschedule(asyncio.get_running_loop().time())
        await asyncio.Future()

    tls.pairs[0].reader.read.side_effect = receive
    client = make_client(max_attempts=1, handshake_timeout=23.0, read_timeout=23.0)
    with pytest.raises(HobenRefreshExhaustedError) as caught:
        asyncio.run(client.async_refresh())
    assert isinstance(caught.value.last_error, HobenTimeoutError)
    assert_cleanup(tls)


def test_shutdown_failure_cannot_turn_protocol_error_into_retry(tls, backoff):
    tls.pairs[0].reader.read.side_effect = [OPENED, RESPONSE + b"PRIVATE"]
    tls.pairs[0].writer.wait_closed.side_effect = OSError("PRIVATE")
    with pytest.raises(HobenProtocolError):
        asyncio.run(make_client().async_refresh())
    assert backoff.delays == []
    tls.pairs[0].writer.transport.abort.assert_called_once_with()
    assert_cleanup(tls)


def test_failed_later_refresh_keeps_last_successful_snapshot(tls):
    tls.pairs[1].reader.read.side_effect = [OPENED, RESPONSE + b"PRIVATE"]
    client = make_client()

    async def run():
        previous = await client.async_refresh()
        with pytest.raises(HobenProtocolError):
            await client.async_refresh()
        assert client.last_snapshot is previous

    asyncio.run(run())
    assert_cleanup(tls, 2)


@pytest.mark.parametrize("phase", ["connect", "handshake", "read", "backoff"])
def test_cancellation_propagates_closes_and_does_not_retry(
    tls, backoff, monkeypatch, phase
):
    client = make_client()

    async def run():
        waiting = asyncio.Event()

        async def blocked(*args, **kwargs):
            waiting.set()
            await asyncio.Future()

        if phase == "connect":
            tls.connect.side_effect = blocked
        elif phase == "backoff":
            tls.connect.side_effect = OSError("PRIVATE")

            async def sleep(delay):
                if delay:
                    await blocked()
                await backoff.original(0)

            monkeypatch.setattr(asyncio, "sleep", sleep)
        else:

            async def receive(max_bytes):
                if phase == "read" and tls.pairs[0].reader.read.await_count == 1:
                    return OPENED
                await blocked()

            tls.pairs[0].reader.read.side_effect = receive
        task = asyncio.create_task(client.async_refresh())
        await waiting.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await client.async_close()
        await client.async_close()

    asyncio.run(asyncio.wait_for(run(), 2))
    assert tls.factory.call_count == tls.connect.await_count == 1
    tls.transports[0].close.assert_awaited_once_with()
    if phase in ("handshake", "read"):
        tls.pairs[0].writer.wait_closed.assert_awaited_once_with()
    assert client.last_snapshot is None


def test_concurrent_refreshes_serialize_identity_read_and_transport_cleanup(
    tls, backoff
):
    client = make_client()
    rotated = "Z" * 32
    tls.pairs[1].reader.read.side_effect = [
        OPENED[:14] + rotated.encode() + OPENED[46:],
        RESPONSE,
    ]

    async def run():
        first_reading = asyncio.Event()
        release_first = asyncio.Event()

        async def receive(max_bytes):
            if tls.pairs[0].reader.read.await_count == 1:
                return OPENED
            first_reading.set()
            await release_first.wait()
            return RESPONSE

        tls.pairs[0].reader.read.side_effect = receive
        first = asyncio.create_task(client.async_refresh())
        await first_reading.wait()
        second = asyncio.create_task(client.async_refresh())
        await backoff.original(0)
        assert tls.factory.call_count == tls.connect.await_count == 1
        assert client.device_guid_for_persistence == DEVICE_GUID

        async def connect(*args, **kwargs):
            tls.pairs[0].writer.wait_closed.assert_awaited_once_with()
            return tls.pairs[1].reader, tls.pairs[1].writer

        tls.connect.side_effect = connect
        release_first.set()
        results = await asyncio.gather(first, second)
        assert len(results) == 2
        assert client.device_guid_for_persistence == rotated
        await client.async_close()

    asyncio.run(asyncio.wait_for(run(), 2))
    assert emitted(tls.pairs[1])[0][37:69] == DEVICE_GUID.encode()
    assert_cleanup(tls, 2)


def test_close_cancels_active_refresh_and_blocks_queued_or_new_calls(tls, backoff):
    client = make_client()

    async def run():
        reading = asyncio.Event()

        async def receive(max_bytes):
            reading.set()
            await asyncio.Future()

        tls.pairs[0].reader.read.side_effect = receive
        active = asyncio.create_task(client.async_refresh())
        await reading.wait()
        queued = asyncio.create_task(client.async_refresh())
        await backoff.original(0)
        await client.async_close()
        with pytest.raises(asyncio.CancelledError):
            await active
        with pytest.raises(HobenClientClosedError):
            await queued
        await client.async_close()
        with pytest.raises(HobenClientClosedError):
            await client.async_refresh()

    asyncio.run(asyncio.wait_for(run(), 2))
    assert_cleanup(tls)


def test_zero_delay_and_closed_unused_client_need_no_network(tls):
    client = make_client(retry_delay=0)

    async def run():
        await client.async_close()
        await client.async_close()
        with pytest.raises(HobenClientClosedError):
            await client.async_refresh()

    asyncio.run(run())
    tls.factory.assert_not_called()
