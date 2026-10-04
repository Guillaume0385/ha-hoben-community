"""One-shot V4 reads over verified transport code and deterministic TLS doubles."""

import asyncio
import json
import traceback
from pathlib import Path
from unittest.mock import AsyncMock, Mock, call

import pytest

from custom_components.hoben import v4_read
from custom_components.hoben.modbus import decode_mbap
from custom_components.hoben.myhoben import decode_opened_client
from custom_components.hoben.profiles import StoveProfile, select_stove_profile
from custom_components.hoben.session import (
    OpenSessionResult,
    SessionProtocolError,
    SessionTimeout,
    UnexpectedMessageType,
)
from custom_components.hoben.transport import (
    AsyncTlsTransport,
    TransportEOF,
    TransportError,
    TransportTimeout,
)
from custom_components.hoben.v4_read import (
    V4ReadBlockedResult,
    V4ReadProtocolError,
    V4ReadTimeout,
    open_and_read_v4_once,
)

# Synthetic bytes, NOT a real capture. Only public metadata matches the fixture.
OPENED_V4 = (
    b"\x04\x00\x0a\x0b\x00\x00\x00\x00\x05\x02\x08\x00\x00\x00"
    b"ABCDabcdABCDabcdABCDabcdABCDabcd\x00\x02"
)
FIELDS = {
    "user_guid": "01234567-89AB-CDEF-0123-456789ABCDEF",
    "device_guid": "00000000000000000000000000000000",
    "build": 34,
    "device_info": "Synthetic/V4",
}
OPEN_REQUEST = (
    b"\x030123456789abcdef0123456789abcdef\x00\x01\x22\x00"
    b"00000000000000000000000000000000Synthetic/V4"
)
READ_REQUEST = bytes.fromhex("0D FF FF 00 00 00 06 01 04 04 00 00 14")
REGISTERS = (0, 1, 0x0A0B, 0x7FFF, 0x8000, 0xFFFF, *range(14))
RESPONSE = bytes.fromhex("0E FF FF 00 00 00 2B 01 04 28") + b"".join(
    value.to_bytes(2, "big") for value in REGISTERS
)
EXCEPTION = bytes.fromhex("0E FF FF 00 00 00 03 01 84 FF")


def read_once(**overrides):
    """Use synthetic inputs with the public one-shot operation."""
    return open_and_read_v4_once(AsyncTlsTransport(), **(FIELDS | overrides))


def assert_closed_with_only_allowed_writes(streams, *, application_read=True):
    """No writes, command transactions, pairing, reconnects or extra reads."""
    writes = [entry.args[0] for entry in streams.writer.write.call_args_list]
    assert writes[0] == OPEN_REQUEST
    assert all(packet in (OPEN_REQUEST, READ_REQUEST, b"\x0b") for packet in writes)
    assert writes.count(OPEN_REQUEST) == 1
    assert writes.count(READ_REQUEST) == int(application_read)
    streams.connect.assert_awaited_once()
    streams.writer.close.assert_called_once_with()
    streams.writer.wait_closed.assert_awaited_once_with()


def test_exact_documented_request_and_raw_uint16_result(streams, monkeypatch):
    """Compose existing codecs, with no semantic conversion or caller-set read."""
    streams.reader.read.side_effect = [OPENED_V4, RESPONSE, b"SHOULD-NOT-BE-READ"]
    encoder = Mock(wraps=v4_read.encode_data_request_client)
    builder = Mock(wraps=v4_read.build_read_input_registers)
    monkeypatch.setattr(v4_read, "encode_data_request_client", encoder)
    monkeypatch.setattr(v4_read, "build_read_input_registers", builder)
    result = asyncio.run(read_once())
    builder.assert_called_once_with(0xFFFF, 1024, 20, unit_id=1)
    encoder.assert_called_once_with(READ_REQUEST[1:])
    frame = decode_mbap(READ_REQUEST[1:])
    assert (frame.transaction_id, frame.unit_id) == (0xFFFF, 1)
    assert frame.pdu == bytes.fromhex("04 04 00 00 14")
    assert result.safe_report() == {
        "state": "read",
        "profile": "v4",
        "function": 4,
        "start_address": 1024,
        "quantity": 20,
        "registers": list(REGISTERS),
    }
    assert len(result.response.registers) == 20
    assert all(0 <= value <= 65535 for value in result.response.registers)
    streams.reader.read.assert_has_awaits([call(4096), call(4096)])
    assert streams.reader.read.await_count == 2
    assert_closed_with_only_allowed_writes(streams)


@pytest.mark.parametrize("split", range(1, len(RESPONSE)))
def test_every_response_fragmentation_boundary(streams, split):
    """Includes splits before/inside Length, Unit ID, byte count and register data."""
    streams.reader.read.side_effect = [
        OPENED_V4[:9],
        OPENED_V4[9:],
        RESPONSE[:split],
        RESPONSE[split:],
    ]
    assert asyncio.run(read_once()).response.registers == REGISTERS
    assert streams.reader.read.await_count == 4
    assert_closed_with_only_allowed_writes(streams)


def test_byte_at_a_time_for_both_responses(streams):
    """Never derive MBAP length before all six prefix bytes have been received."""
    streams.reader.read.side_effect = [bytes([b]) for b in OPENED_V4 + RESPONSE]
    assert asyncio.run(read_once()).response.registers == REGISTERS
    assert streams.reader.read.await_count == len(OPENED_V4) + len(RESPONSE)
    assert_closed_with_only_allowed_writes(streams)


@pytest.mark.parametrize(
    ("chunks", "pongs"),
    [
        ([b"\x0a", RESPONSE], 1),
        ([b"\x0a" + RESPONSE[:5], RESPONSE[5:]], 1),
        ([b"\x0a\x0a", b"\x0a" + RESPONSE], 3),
    ],
)
def test_leading_ping_pong_during_open_and_read(streams, chunks, pongs):
    """Pings before both phases are answered; 0A/0B in payloads stay opaque."""
    streams.reader.read.side_effect = [b"\x0a" + OPENED_V4] + chunks
    assert asyncio.run(read_once()).response.registers == REGISTERS
    assert [c.args[0] for c in streams.writer.write.call_args_list] == [
        OPEN_REQUEST,
        b"\x0b",
        READ_REQUEST,
        *([b"\x0b"] * pongs),
    ]
    assert streams.writer.drain.await_count == 3 + pongs
    assert_closed_with_only_allowed_writes(streams)


@pytest.mark.parametrize(
    ("product_type", "revision", "major", "profile"),
    [(2, 0, 0, "v6"), (2, 2, 0, "boiler_v6_230"), (3, 1, 0, "unknown")],
)
def test_non_v4_fails_closed(streams, product_type, revision, major, profile):
    """Dynamic selection happens before emitting any DataRequestClient."""
    opened = bytearray(OPENED_V4)
    opened[7], opened[8], opened[10] = revision, product_type, major
    streams.reader.read.side_effect = [bytes(opened), RESPONSE]
    result = asyncio.run(read_once())
    assert isinstance(result, V4ReadBlockedResult)
    assert result.safe_report()["state"] == "read_not_attempted"
    assert result.safe_report()["error"] == "unsupported_profile"
    assert result.safe_report()["profile"] == profile
    streams.reader.read.assert_awaited_once()
    assert_closed_with_only_allowed_writes(streams, application_read=False)


def test_v6v16_is_also_blocked(streams, monkeypatch):
    """Keep the gate exact even when the unresolved V6v16 selector is refined."""
    observation = OpenSessionResult(decode_opened_client(OPENED_V4), StoveProfile.V6V16)
    monkeypatch.setattr(v4_read, "_open_session", AsyncMock(return_value=observation))
    result = asyncio.run(read_once())
    assert result.safe_report()["error"] == "unsupported_profile"
    streams.connect.assert_not_awaited()
    streams.writer.write.assert_not_called()


@pytest.mark.parametrize(
    ("chunks", "state"),
    [
        ([b"\x2fPRIVATE-AUTH"], "authorization_required"),
        ([b"\x05", b"\x02PRIVATE-GUID"], "closed"),
        ([b"\x05", b""], "closed"),
        *[([bytes([5, code])], "closed") for code in (0, 3, 4, 5, 6, 255)],
    ],
)
def test_authorization_and_every_closure_stop_before_modbus(streams, chunks, state):
    """No code transmission and no read after any unsuccessful session outcome."""
    streams.reader.read.side_effect = chunks + [OPENED_V4, RESPONSE]
    result = asyncio.run(read_once())
    assert result.safe_report()["state"] == state
    assert streams.reader.read.await_count == len(chunks)
    assert "PRIVATE" not in repr(result) + json.dumps(result.safe_report())
    assert_closed_with_only_allowed_writes(streams, application_read=False)


@pytest.mark.parametrize("suffix", [b"\x0a", RESPONSE, b"PRIVATE-GUID"])
def test_unclassified_opened_bytes_forbid_read_and_reframing(streams, suffix):
    """A suffix resembling Ping/response remains opaque, even on a V4 prefix."""
    streams.reader.read.side_effect = [OPENED_V4 + suffix, RESPONSE]
    result = asyncio.run(read_once())
    assert result.safe_report()["error"] == "unclassified_opened_client_bytes"
    assert result.safe_report()["unclassified_bytes"] == len(suffix)
    streams.reader.read.assert_awaited_once()
    assert_closed_with_only_allowed_writes(streams, application_read=False)


@pytest.mark.parametrize("response", [b"\x00PRIVATE", b"\xffPRIVATE"])
def test_unexpected_handshake_type_never_reads(streams, response):
    """Unsupported message payloads do not reach the application phase."""
    streams.reader.read.return_value = response
    with pytest.raises(UnexpectedMessageType):
        asyncio.run(read_once())
    assert_closed_with_only_allowed_writes(streams, application_read=False)


def test_malformed_opened_client_never_reads(streams):
    """Reuse the strict prefix parser before any Modbus traffic."""
    streams.reader.read.return_value = OPENED_V4[:14] + b"\xff" + OPENED_V4[15:]
    with pytest.raises(SessionProtocolError):
        asyncio.run(read_once())
    assert_closed_with_only_allowed_writes(streams, application_read=False)


@pytest.mark.parametrize("exception_code", [0, 2, 255])
def test_modbus_exception_preserves_numeric_code_without_retry(streams, exception_code):
    """Exceptions have the same correlation rules and no guessed meaning."""
    streams.reader.read.side_effect = [
        OPENED_V4,
        EXCEPTION[:-1] + bytes([exception_code]),
        RESPONSE,
    ]
    assert asyncio.run(read_once()).safe_report() == {
        "state": "modbus_exception",
        "profile": "v4",
        "function": 4,
        "start_address": 1024,
        "quantity": 20,
        "exception_code": exception_code,
    }
    assert streams.reader.read.await_count == 2
    assert_closed_with_only_allowed_writes(streams)


@pytest.mark.parametrize("response", [RESPONSE, EXCEPTION], ids=["normal", "exception"])
@pytest.mark.parametrize(
    ("offset", "value"),
    [(1, 0xFE), (2, 0xF0), (7, 2), (8, 3)],
    ids=["transaction-high", "command-transaction", "unit", "function"],
)
def test_response_correlation_mismatches_rejected(streams, response, offset, value):
    """Do not accept another transaction/unit/function, even for exceptions."""
    message = bytearray(response)
    # For exceptions, preserve the exception flag while changing the function.
    message[offset] = value | 0x80 if offset == 8 and response == EXCEPTION else value
    streams.reader.read.side_effect = [OPENED_V4, bytes(message), RESPONSE]
    with pytest.raises(V4ReadProtocolError, match="Uncorrelated"):
        asyncio.run(read_once())
    assert streams.reader.read.await_count == 2
    assert_closed_with_only_allowed_writes(streams)


@pytest.mark.parametrize(
    "prefix",
    [
        "0E FF FF 00 01 00 2B",
        "0E FF FF 00 00 00 00",
        "0E FF FF 00 00 00 01",
        "0E FF FF 00 00 00 FF",
        "0E FF FF 00 00 FF FF",
    ],
    ids=["protocol", "zero-length", "no-function", "oversized", "overflow"],
)
def test_malformed_mbap_rejected_before_body_read(streams, prefix):
    """Validate Length before buffering a potentially oversized response."""
    streams.reader.read.side_effect = [OPENED_V4, bytes.fromhex(prefix), RESPONSE]
    with pytest.raises(V4ReadProtocolError, match="MBAP prefix"):
        asyncio.run(read_once())
    assert streams.reader.read.await_count == 2
    assert_closed_with_only_allowed_writes(streams)


@pytest.mark.parametrize(
    "pdu",
    [
        b"\x04",
        b"\x04\x00",
        b"\x04\x01\x00",
        b"\x04\x28\x00\x01",
        b"\x04\x28" + bytes(42),
        b"\x84",
        b"\x84\x02\xff",
        b"\x06\x02",
    ],
)
def test_malformed_or_write_response_pdu_rejected(streams, pdu):
    """A valid MBAP size cannot override strict read/exception PDU validation."""
    response = b"\x0e\xff\xff\x00\x00" + (len(pdu) + 1).to_bytes(2, "big")
    streams.reader.read.side_effect = [OPENED_V4, response + b"\x01" + pdu]
    with pytest.raises(V4ReadProtocolError, match="Invalid V4 read response"):
        asyncio.run(read_once())
    assert_closed_with_only_allowed_writes(streams)


@pytest.mark.parametrize("quantity", [1, 19, 21, 125])
def test_exactly_twenty_registers_required(streams, quantity):
    """Even a well-formed function 04 reply with another quantity is rejected."""
    length = 3 + 2 * quantity
    response = (
        b"\x0e\xff\xff\x00\x00"
        + length.to_bytes(2, "big")
        + bytes([1, 4, 2 * quantity])
        + bytes(2 * quantity)
    )
    streams.reader.read.side_effect = [OPENED_V4, response]
    with pytest.raises(V4ReadProtocolError, match="exactly 20 registers"):
        asyncio.run(read_once())
    assert_closed_with_only_allowed_writes(streams)


@pytest.mark.parametrize("size", range(len(RESPONSE)))
def test_every_truncated_response_rejected_and_closed(streams, size):
    """No partial prefix/header/PDU/register becomes a successful read."""
    streams.reader.read.side_effect = [OPENED_V4, RESPONSE[:size], b""]
    error = TransportEOF if size == 0 else V4ReadProtocolError
    with pytest.raises(error):
        asyncio.run(read_once())
    assert_closed_with_only_allowed_writes(streams)


@pytest.mark.parametrize("suffix", [b"\x0a", RESPONSE, EXCEPTION, b"PRIVATE-GUID"])
def test_trailing_response_bytes_are_rejected_without_reframing(streams, suffix):
    """Do not interpret a second response, Ping or private arbitrary payload."""
    streams.reader.read.side_effect = [OPENED_V4, RESPONSE + suffix]
    with pytest.raises(V4ReadProtocolError, match="trailing response bytes"):
        asyncio.run(read_once())
    assert_closed_with_only_allowed_writes(streams)


@pytest.mark.parametrize("message_type", [0x04, 0x05, 0x0B, 0x1B, 0x2F, 0xFF])
def test_unexpected_read_type_is_numeric_only(streams, message_type):
    """No alternate server message is silently treated as the requested reply."""
    streams.reader.read.side_effect = [OPENED_V4, bytes([message_type]) + b"PRIVATE"]
    with pytest.raises(UnexpectedMessageType) as caught:
        asyncio.run(read_once())
    assert caught.value.message_type == message_type
    assert "PRIVATE" not in "".join(traceback.format_exception(caught.value))
    assert_closed_with_only_allowed_writes(streams)


@pytest.mark.parametrize("pending", [b"\x0a", RESPONSE[:1], RESPONSE[:7]])
def test_overall_read_deadline_includes_ping_and_fragments(streams, deadlines, pending):
    """Neither endless keepalive nor partial framing restarts the total deadline."""

    async def receive(max_bytes):
        if streams.reader.read.await_count == 1:
            return OPENED_V4
        if streams.reader.read.await_count == 2:
            return pending
        deadline = next(ctx for delay, ctx in deadlines.contexts if delay == 23.0)
        deadline.reschedule(asyncio.get_running_loop().time())
        if pending == b"\x0a":
            return pending
        await asyncio.Future()

    streams.reader.read.side_effect = receive
    with pytest.raises(V4ReadTimeout):
        asyncio.run(read_once(read_timeout=23.0))
    assert streams.reader.read.await_count <= 4
    assert_closed_with_only_allowed_writes(streams)


@pytest.mark.parametrize("phase", ["handshake", "read"])
def test_cancellation_in_each_phase_closes(streams, phase):
    """The operation always releases its connection on caller cancellation."""

    async def run():
        waiting = asyncio.Event()

        async def receive(max_bytes):
            if phase == "read" and streams.reader.read.await_count == 1:
                return OPENED_V4
            waiting.set()
            await asyncio.Future()

        streams.reader.read.side_effect = receive
        task = asyncio.create_task(read_once())
        await waiting.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    assert_closed_with_only_allowed_writes(streams, application_read=phase == "read")


@pytest.mark.parametrize("operation", ["write", "read"])
@pytest.mark.parametrize("failure", [TimeoutError("PRIVATE"), OSError("PRIVATE")])
def test_application_transport_error_does_not_retry(streams, operation, failure):
    """One application attempt, sanitized error and closure on drain/read failure."""
    streams.reader.read.side_effect = (
        [OPENED_V4, failure] if operation == "read" else None
    )
    streams.reader.read.return_value = OPENED_V4
    if operation == "write":
        streams.writer.drain.side_effect = [None, failure]
    expected = TransportTimeout if isinstance(failure, TimeoutError) else TransportError
    with pytest.raises(expected) as caught:
        asyncio.run(read_once())
    assert "PRIVATE" not in "".join(traceback.format_exception(caught.value))
    assert_closed_with_only_allowed_writes(streams)


@pytest.mark.parametrize("response", [RESPONSE, RESPONSE + b"\x0a"])
def test_shutdown_failure_preserves_earlier_protocol_error(streams, response):
    """Close failure is reported after success but cannot hide a malformed reply."""
    streams.reader.read.side_effect = [OPENED_V4, response]
    streams.writer.wait_closed.side_effect = OSError("PRIVATE")
    expected = TransportError if response == RESPONSE else V4ReadProtocolError
    with pytest.raises(expected):
        asyncio.run(read_once())
    streams.writer.transport.abort.assert_called_once_with()
    streams.writer.close.assert_called_once_with()


@pytest.mark.parametrize(
    "overrides",
    [
        {"read_timeout": 0},
        {"read_timeout": True},
        {"read_timeout": float("inf")},
        {"read_timeout": float("nan")},
        {"handshake_timeout": -1},
        {"user_guid": "PRIVATE"},
        {"build": -1},
        {"device_info": "PRIVATE\ud800"},
    ],
)
def test_invalid_inputs_close_without_connecting(streams, overrides):
    """Validate configuration before TLS and hide invalid sensitive input values."""
    transport = AsyncTlsTransport()
    transport.close = AsyncMock(wraps=transport.close)
    with pytest.raises(ValueError) as caught:
        asyncio.run(open_and_read_v4_once(transport, **(FIELDS | overrides)))
    assert "PRIVATE" not in "".join(traceback.format_exception(caught.value))
    streams.connect.assert_not_awaited()
    transport.close.assert_awaited_once_with()


def test_existing_handshake_deadline_still_applies(streams, deadlines):
    """A stalled opening cannot reach the later read deadline."""

    async def receive(max_bytes):
        handshake = next(ctx for delay, ctx in deadlines.contexts if delay == 23.0)
        handshake.reschedule(asyncio.get_running_loop().time())
        await asyncio.Future()

    streams.reader.read.side_effect = receive
    with pytest.raises(SessionTimeout):
        asyncio.run(read_once(handshake_timeout=23.0))
    assert_closed_with_only_allowed_writes(streams, application_read=False)


@pytest.mark.parametrize("function", [6, 16, 22])
def test_api_cannot_emit_write_function_request(streams, function):
    """There is no generic request/function argument that could enable a write."""
    with pytest.raises(TypeError):
        asyncio.run(read_once(function_code=function))
    streams.connect.assert_not_awaited()
    streams.writer.write.assert_not_called()
    streams.reader.read.side_effect = [OPENED_V4, RESPONSE]
    asyncio.run(read_once())
    requests = [
        c.args[0] for c in streams.writer.write.call_args_list if c.args[0][0] == 0x0D
    ]
    assert requests == [READ_REQUEST]
    request = decode_mbap(requests[0][1:])
    assert request.pdu[0] == 4
    assert request.transaction_id == 0xFFFF
    assert all(c.args[0][0] != 0x30 for c in streams.writer.write.call_args_list)
    assert_closed_with_only_allowed_writes(streams)


def test_sanitized_real_v4_metadata_fixture(streams):
    """Regression of confirmed 2026-10-04 metadata, without any real GUID/frame."""
    path = (
        Path(__file__).parent / "fixtures/opened_client_v4_production_2026_10_04.json"
    )
    observed = json.loads(path.read_text(encoding="utf-8"))
    opened = decode_opened_client(OPENED_V4)
    assert (
        OpenSessionResult(opened, select_stove_profile(opened)).safe_report()
        == observed
    )
    assert not any("guid" in key.lower() for key in observed)
    streams.reader.read.side_effect = [OPENED_V4, RESPONSE]
    assert asyncio.run(read_once()).safe_report()["state"] == "read"
