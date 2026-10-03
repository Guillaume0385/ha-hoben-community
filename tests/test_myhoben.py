"""Deterministic client framing fixtures, without a network or real identifiers."""

from collections.abc import Callable

import pytest

from custom_components.hoben.modbus import (
    ModbusExceptionResponse,
    ModbusReadResponse,
    decode_read_response,
)
from custom_components.hoben.myhoben import (
    decode_data_response_client,
    encode_data_request_client,
)


@pytest.mark.parametrize(
    ("frame", "expected"),
    [
        pytest.param(
            "FF FF 00 00 00 06 01 04 04 00 00 6E",
            "0D FF FF 00 00 00 06 01 04 04 00 00 6E",
            id="confirmed-v6-v6v16",
        ),
        pytest.param(
            "12 34 00 00 00 06 AB 03 56 78 00 7B",
            "0D 12 34 00 00 00 06 AB 03 56 78 00 7B",
            id="synthetic-asymmetric-fields",
        ),
    ],
)
def test_encode_data_request_client(frame: str, expected: str) -> None:
    """Add exactly one 0x0D byte without changing any MBAP or PDU byte."""
    assert encode_data_request_client(bytes.fromhex(frame)) == bytes.fromhex(expected)


@pytest.mark.parametrize(
    ("message", "frame", "expected"),
    [
        pytest.param(
            "0E 12 34 00 00 00 09 AB 04 06 56 78 9A BC 00 01",
            "12 34 00 00 00 09 AB 04 06 56 78 9A BC 00 01",
            ModbusReadResponse(0x1234, 0xAB, 0x04, (0x5678, 0x9ABC, 0x0001)),
            id="input-registers",
        ),
        pytest.param(
            "0E AB CD 00 00 00 05 FE 03 02 12 34",
            "AB CD 00 00 00 05 FE 03 02 12 34",
            ModbusReadResponse(0xABCD, 0xFE, 0x03, (0x1234,)),
            id="holding-registers",
        ),
    ],
)
def test_extract_and_decode_read_response(
    message: str, frame: str, expected: ModbusReadResponse
) -> None:
    """Literal fixtures verify exact extraction and composition of both layers."""
    extracted = decode_data_response_client(bytes.fromhex(message))
    assert isinstance(extracted, bytes)
    assert extracted == bytes.fromhex(frame)
    assert decode_read_response(extracted) == expected


@pytest.mark.parametrize(
    ("message", "frame", "expected"),
    [
        (
            "0E 12 34 00 00 00 03 AB 84 02",
            "12 34 00 00 00 03 AB 84 02",
            ModbusExceptionResponse(0x1234, 0xAB, 0x04, 0x02),
        ),
        (
            "0E AB CD 00 00 00 03 FE 83 FF",
            "AB CD 00 00 00 03 FE 83 FF",
            ModbusExceptionResponse(0xABCD, 0xFE, 0x03, 0xFF),
        ),
    ],
)
def test_extract_and_decode_exception(
    message: str, frame: str, expected: ModbusExceptionResponse
) -> None:
    """Framing preserves exceptions for the Modbus decoder to identify."""
    extracted = decode_data_response_client(bytes.fromhex(message))
    assert extracted == bytes.fromhex(frame)
    assert decode_read_response(extracted) == expected


def test_response_pdu_remains_opaque() -> None:
    """Only the read decoder checks a byte_count inconsistent with register data."""
    frame = bytes.fromhex("12 34 00 00 00 05 AB 04 04 56 78")
    extracted = decode_data_response_client(
        bytes.fromhex("0E 12 34 00 00 00 05 AB 04 04 56 78")
    )
    assert extracted == frame
    with pytest.raises(ValueError, match="byte_count does not match"):
        decode_read_response(extracted)


@pytest.mark.parametrize(
    "helper", [encode_data_request_client, decode_data_response_client]
)
@pytest.mark.parametrize(
    "value",
    [
        None,
        "0E 12 34 00 00 00 05 AB 04 02 56 78",
        14,
        [0x0E, 0x12, 0x34],
        bytearray.fromhex("0E 12 34 00 00 00 05 AB 04 02 56 78"),
        memoryview(bytes.fromhex("0E 12 34 00 00 00 05 AB 04 02 56 78")),
    ],
    ids=["none", "text", "integer", "list", "bytearray", "memoryview"],
)
def test_bytes_required(helper: Callable[[bytes], bytes], value: object) -> None:
    """Reject implicit conversion and mutable buffers at either public boundary."""
    with pytest.raises(TypeError, match="must be bytes"):
        helper(value)


def test_empty_request_frame() -> None:
    """An empty payload fails the existing MBAP validator."""
    with pytest.raises(ValueError, match="Truncated MBAP header"):
        encode_data_request_client(b"")


@pytest.mark.parametrize("message", [b"", b"\x0e"])
def test_missing_response_payload(message: bytes) -> None:
    """A response needs both the type byte and an embedded frame."""
    with pytest.raises(ValueError, match="requires a type and Modbus/TCP frame"):
        decode_data_response_client(message)


@pytest.mark.parametrize("message_type", [0x0D, 0x07, 0x1B, 0x00, 0xFF])
def test_wrong_response_type(message_type: int) -> None:
    """A valid embedded frame does not permit another MyHOBEN message type."""
    frame = bytes.fromhex("12 34 00 00 00 05 AB 04 02 56 78")
    with pytest.raises(ValueError, match="Expected DataResponseClient.*0x0E"):
        decode_data_response_client(bytes([message_type]) + frame)


@pytest.mark.parametrize(
    ("helper", "prefix"),
    [(encode_data_request_client, b""), (decode_data_response_client, b"\x0e")],
    ids=["request", "response"],
)
@pytest.mark.parametrize(
    ("frame", "error"),
    [
        ("12", "Truncated MBAP header"),
        ("12 34 00 00 00 06", "Truncated MBAP header"),
        ("12 34 00 01 00 06 AB 03 56 78 00 7B", "protocol ID"),
        ("12 34 00 00 00 00 AB", "MBAP length"),
        ("12 34 00 00 00 01 AB", "MBAP length"),
        ("12 34 00 00 00 05 AB 03 56 78 00 7B", "complete frame size"),
        ("12 34 00 00 00 07 AB 03 56 78 00 7B", "complete frame size"),
        ("12 34 00 00 00 06 AB 03 56 78 00", "complete frame size"),
    ],
    ids=[
        "one-byte",
        "missing-unit-id",
        "nonzero-protocol",
        "zero-length",
        "no-pdu",
        "length-too-small",
        "length-too-large",
        "truncated-pdu",
    ],
)
def test_invalid_mbap(
    helper: Callable[[bytes], bytes], prefix: bytes, frame: str, error: str
) -> None:
    """Both framing directions propagate the existing codec's MBAP errors."""
    with pytest.raises(ValueError, match=error):
        helper(prefix + bytes.fromhex(frame))


@pytest.mark.parametrize(
    ("helper", "prefix"),
    [(encode_data_request_client, b""), (decode_data_response_client, b"\x0e")],
    ids=["request", "response"],
)
@pytest.mark.parametrize(
    "suffix",
    [
        "FF",
        "12 34 00 00 00 05 AB 04 02 56 78",
        "0E 12 34 00 00 00 05 AB 04 02 56 78",
    ],
    ids=["trailing-byte", "concatenated-modbus", "concatenated-myhoben"],
)
def test_trailing_bytes_rejected(
    helper: Callable[[bytes], bytes], prefix: bytes, suffix: str
) -> None:
    """Never silently truncate trailing data or split a stream of frames."""
    frame = bytes.fromhex("12 34 00 00 00 05 AB 04 02 56 78")
    with pytest.raises(ValueError, match="complete frame size"):
        helper(prefix + frame + bytes.fromhex(suffix))
