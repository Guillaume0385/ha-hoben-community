"""Deterministic Modbus/TCP fixtures, without a MyHOBEN envelope or network."""

from collections.abc import Callable
from dataclasses import FrozenInstanceError

import pytest

from custom_components.hoben.modbus import (
    ModbusExceptionResponse,
    ModbusReadResponse,
    ModbusTcpFrame,
    build_read_holding_registers,
    build_read_input_registers,
    decode_mbap,
    decode_read_response,
    encode_mbap,
    modbus_tcp_frame_size,
)


@pytest.mark.parametrize("size", range(6))
def test_stream_frame_size_needs_complete_mbap_prefix(size):
    """No stream layer can derive a length from a partial UInt16 field."""
    with pytest.raises(ValueError, match="Truncated MBAP prefix"):
        modbus_tcp_frame_size(bytes.fromhex("FF FF 00 00 00 2B")[:size])


@pytest.mark.parametrize("length", [2, 3, 43, 254])
def test_stream_frame_size_from_bounded_mbap_prefix(length):
    """Size includes the six-byte prefix and the Unit ID counted by Length."""
    prefix = b"\xff\xff\x00\x00" + length.to_bytes(2, "big")
    assert modbus_tcp_frame_size(prefix) == 6 + length


@pytest.mark.parametrize("length", [0, 1, 255, 65535])
def test_stream_frame_size_rejects_invalid_length(length):
    """Reject oversized declarations before waiting for a response body."""
    with pytest.raises(ValueError, match="MBAP length"):
        modbus_tcp_frame_size(b"\xff\xff\x00\x00" + length.to_bytes(2, "big"))


def test_stream_frame_size_rejects_nonzero_protocol_and_nonbytes():
    """The prefix API enforces the same protocol/type rules as complete frames."""
    with pytest.raises(ValueError, match="protocol ID"):
        modbus_tcp_frame_size(bytes.fromhex("FF FF 00 01 00 2B"))
    with pytest.raises(TypeError, match="prefix must be bytes"):
        modbus_tcp_frame_size(bytearray.fromhex("FF FF 00 00 00 2B"))


@pytest.mark.parametrize(
    ("quantity", "expected"),
    [
        pytest.param(110, "FF FF 00 00 00 06 01 04 04 00 00 6E", id="v6-v6v16"),
        pytest.param(20, "FF FF 00 00 00 06 01 04 04 00 00 14", id="v4"),
    ],
)
def test_documented_input_register_reads(quantity: int, expected: str) -> None:
    """Reproduce the two documented application reads byte for byte."""
    assert build_read_input_registers(0xFFFF, 1024, quantity) == bytes.fromhex(expected)


def test_holding_register_read() -> None:
    """Use asymmetric synthetic fields to verify function 03 and byte order."""
    assert build_read_holding_registers(0x1234, 0x5678, 0x007B) == bytes.fromhex(
        "12 34 00 00 00 06 01 03 56 78 00 7B"
    )


def test_encode_mbap() -> None:
    """The Length field counts Unit ID plus PDU, not the entire header."""
    assert encode_mbap(0x1234, 0xAB, bytes.fromhex("03 56 78 00 7B")) == bytes.fromhex(
        "12 34 00 00 00 06 AB 03 56 78 00 7B"
    )


def test_decode_mbap() -> None:
    """Decode a literal fixture independently of the encoder."""
    frame = decode_mbap(bytes.fromhex("12 34 00 00 00 06 AB 04 04 00 00 6E"))
    assert frame == ModbusTcpFrame(0x1234, 0xAB, bytes.fromhex("04 04 00 00 6E"))
    with pytest.raises(FrozenInstanceError):
        frame.unit_id = 2


@pytest.mark.parametrize(
    ("transaction_id", "unit_id", "pdu"),
    [
        (0, 0, b"\x03"),
        (0xFFFF, 0xFF, bytes.fromhex("04 04 00 00 6E")),
        (0x1234, 1, b"\x04" + bytes(252)),
    ],
)
def test_mbap_round_trip(transaction_id: int, unit_id: int, pdu: bytes) -> None:
    """Preserve fields at integer and MBAP Length boundaries."""
    encoded = encode_mbap(transaction_id, unit_id, pdu)
    assert int.from_bytes(encoded[4:6], "big") == len(pdu) + 1
    assert decode_mbap(encoded) == ModbusTcpFrame(transaction_id, unit_id, pdu)


@pytest.mark.parametrize(
    "builder", [build_read_holding_registers, build_read_input_registers]
)
@pytest.mark.parametrize(
    ("address", "quantity", "unit_id", "suffix"),
    [
        (0, 1, 0, "00 00 00 01"),
        (1024, 125, 1, "04 00 00 7D"),
        (0xFFFF, 1, 0xFF, "FF FF 00 01"),
        (0xFF83, 125, 1, "FF 83 00 7D"),
    ],
)
def test_read_field_boundaries(
    builder: Callable[..., bytes],
    address: int,
    quantity: int,
    unit_id: int,
    suffix: str,
) -> None:
    """Accept standard quantity limits and reads ending at address 0xFFFF."""
    frame = builder(0, address, quantity, unit_id=unit_id)
    assert frame[6] == unit_id
    assert frame[8:] == bytes.fromhex(suffix)


@pytest.mark.parametrize(
    "builder", [build_read_holding_registers, build_read_input_registers]
)
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("transaction_id", -1),
        ("transaction_id", 0x10000),
        ("unit_id", -1),
        ("unit_id", 0x100),
        ("address", -1),
        ("address", 0x10000),
        ("quantity", -1),
        ("quantity", 0),
        ("quantity", 126),
        ("quantity", 0x10000),
        ("transaction_id", True),
        ("unit_id", 1.0),
        ("address", "1024"),
        ("quantity", None),
    ],
)
def test_invalid_read_fields(
    builder: Callable[..., bytes], field: str, value: object
) -> None:
    """Both public read builders reject invalid fields before serialization."""
    fields = {"transaction_id": 0xFFFF, "unit_id": 1, "address": 1024, "quantity": 20}
    fields[field] = value
    with pytest.raises(ValueError, match=field):
        builder(**fields)


@pytest.mark.parametrize(
    ("transaction_id", "unit_id", "field"),
    [(-1, 1, "transaction_id"), (0x10000, 1, "transaction_id"), (0, 256, "unit_id")],
)
def test_invalid_mbap_fields(transaction_id: int, unit_id: int, field: str) -> None:
    """Direct MBAP encoding validates its fields too."""
    with pytest.raises(ValueError, match=field):
        encode_mbap(transaction_id, unit_id, b"\x04")


@pytest.mark.parametrize(
    "pdu", [b"", bytes(254), bytes(0xFFFF)], ids=["empty", "oversized", "overflow"]
)
def test_invalid_pdu_length(pdu: bytes) -> None:
    """Reject empty PDUs and sizes above the Modbus limit of 253 bytes."""
    with pytest.raises(ValueError, match="MBAP length"):
        encode_mbap(0, 1, pdu)


def test_maximum_pdu_length() -> None:
    """Both directions accept 253-byte PDUs (254-byte Length, 260-byte ADU)."""
    pdu = b"\x04" + bytes(252)
    frame = bytes.fromhex("12 34 00 00 00 FE 01") + pdu
    assert len(frame) == 260
    assert encode_mbap(0x1234, 1, pdu) == frame
    assert decode_mbap(frame) == ModbusTcpFrame(0x1234, 1, pdu)


@pytest.mark.parametrize("pdu_size", [254, 65534])
def test_decode_oversized_pdu(pdu_size: int) -> None:
    """Matching Length and actual size do not make an oversized ADU valid."""
    frame = (
        bytes.fromhex("12 34 00 00")
        + (pdu_size + 1).to_bytes(2, "big")
        + b"\x01\x04"
        + bytes(pdu_size - 1)
    )
    with pytest.raises(ValueError, match="MBAP length"):
        decode_mbap(frame)


@pytest.mark.parametrize(
    "builder", [build_read_holding_registers, build_read_input_registers]
)
@pytest.mark.parametrize(("address", "quantity"), [(0xFFFF, 2), (0xFF84, 125)])
def test_read_address_space_overflow(
    builder: Callable[..., bytes], address: int, quantity: int
) -> None:
    """Reject reads whose individually valid fields exceed the address space."""
    with pytest.raises(ValueError, match="address range"):
        builder(0, address, quantity)


@pytest.mark.parametrize("size", range(7))
def test_truncated_mbap_header(size: int) -> None:
    """Reject every incomplete header, including a missing Unit ID."""
    with pytest.raises(ValueError, match="Truncated MBAP header"):
        decode_mbap(bytes.fromhex("FF FF 00 00 00 06 01")[:size])


@pytest.mark.parametrize(
    ("frame", "message"),
    [
        ("FF FF 00 01 00 06 01 04 04 00 00 6E", "protocol ID"),
        ("FF FF 00 00 00 00 01", "MBAP length"),
        ("FF FF 00 00 00 01 01", "MBAP length"),
        ("FF FF 00 00 00 05 01 04 04 00 00 6E", "complete frame size"),
        ("FF FF 00 00 00 07 01 04 04 00 00 6E", "complete frame size"),
        ("FF FF 00 00 00 06 01 04 04 00 00", "complete frame size"),
        ("FF FF 00 00 00 06 01 04 04 00 00 6E FF", "complete frame size"),
    ],
    ids=["protocol", "zero-length", "no-pdu", "short", "long", "truncated", "trailing"],
)
def test_invalid_mbap_frame(frame: str, message: str) -> None:
    """Reject malformed frames instead of silently truncating or padding them."""
    with pytest.raises(ValueError, match=message):
        decode_mbap(bytes.fromhex(frame))


def test_concatenated_frames_rejected() -> None:
    """Splitting a stream into frames is the responsibility of a future layer."""
    frame = bytes.fromhex("FF FF 00 00 00 06 01 04 04 00 00 14")
    with pytest.raises(ValueError, match="complete frame size"):
        decode_mbap(frame + frame)


@pytest.mark.parametrize("value", [None, "04", bytearray(b"\x04")])
def test_bytes_required(value: object) -> None:
    """The public byte API rejects accidental text and mutable input."""
    with pytest.raises(TypeError, match="pdu must be bytes"):
        encode_mbap(0, 1, value)
    with pytest.raises(TypeError, match="frame must be bytes"):
        decode_mbap(value)


@pytest.mark.parametrize(
    ("frame", "expected"),
    [
        (
            "12 34 00 00 00 09 01 04 06 12 34 AB CD 00 01",
            ModbusReadResponse(0x1234, 1, 0x04, (0x1234, 0xABCD, 0x0001)),
        ),
        (
            "AB CD 00 00 00 09 FE 03 06 56 78 9A BC 01 23",
            ModbusReadResponse(0xABCD, 0xFE, 0x03, (0x5678, 0x9ABC, 0x0123)),
        ),
    ],
    ids=["input-registers", "holding-registers"],
)
def test_decode_read_response(frame: str, expected: ModbusReadResponse) -> None:
    """Literal synthetic responses preserve IDs, order, count and byte order."""
    response = decode_read_response(bytes.fromhex(frame))
    assert response == expected
    assert isinstance(response.registers, tuple)
    with pytest.raises(FrozenInstanceError):
        response.registers = ()


@pytest.mark.parametrize(
    "frame",
    [
        "12 34 00 00 00 0B 01 03 08 00 00 7F FF 80 00 FF FF",
        "12 34 00 00 00 0B 01 04 08 00 00 7F FF 80 00 FF FF",
    ],
)
def test_read_response_uint16_boundaries(frame: str) -> None:
    """High-bit register values remain unsigned, with no physical conversion."""
    response = decode_read_response(bytes.fromhex(frame))
    assert isinstance(response, ModbusReadResponse)
    assert response.registers == (0x0000, 0x7FFF, 0x8000, 0xFFFF)
    assert all(0 <= value <= 0xFFFF for value in response.registers)


@pytest.mark.parametrize(
    ("frame", "expected"),
    [
        ("00 00 00 00 00 05 00 03 02 12 34", ModbusReadResponse(0, 0, 3, (0x1234,))),
        (
            "FF FF 00 00 00 05 FF 04 02 12 34",
            ModbusReadResponse(0xFFFF, 0xFF, 4, (0x1234,)),
        ),
        ("00 00 00 00 00 03 00 83 02", ModbusExceptionResponse(0, 0, 3, 2)),
        ("FF FF 00 00 00 03 FF 84 02", ModbusExceptionResponse(0xFFFF, 0xFF, 4, 2)),
    ],
)
def test_read_response_id_boundaries(
    frame: str, expected: ModbusReadResponse | ModbusExceptionResponse
) -> None:
    """Both response kinds preserve the full Transaction ID and Unit ID ranges."""
    assert decode_read_response(bytes.fromhex(frame)) == expected


@pytest.mark.parametrize("function_code", [0x03, 0x04])
def test_read_response_maximum_registers(function_code: int) -> None:
    """125 registers occupy 250 data bytes and MBAP Length 253 (0xFD)."""
    frame = (
        bytes.fromhex("12 34 00 00 00 FD 01")
        + bytes([function_code, 0xFA])
        + b"\x12\x34" * 125
    )
    assert decode_read_response(frame) == ModbusReadResponse(
        0x1234, 1, function_code, (0x1234,) * 125
    )


@pytest.mark.parametrize("function_code", [0x03, 0x04])
@pytest.mark.parametrize(
    ("header", "data", "message"),
    [
        ("12 34 00 00 00 02 01", "", "missing byte_count"),
        ("12 34 00 00 00 03 01", "00", "nonzero and even"),
        ("12 34 00 00 00 06 01", "03 12 34 56", "nonzero and even"),
        ("12 34 00 00 00 03 01", "02", "byte_count does not match"),
        ("12 34 00 00 00 04 01", "02 12", "byte_count does not match"),
        ("12 34 00 00 00 07 01", "06 12 34 AB CD", "byte_count does not match"),
        ("12 34 00 00 00 07 01", "02 12 34 AB CD", "byte_count does not match"),
        ("12 34 00 00 00 06 01", "02 12 34 FF", "byte_count does not match"),
    ],
    ids=[
        "missing-byte-count",
        "zero-byte-count",
        "odd-byte-count",
        "missing-register-data",
        "truncated-register",
        "byte-count-too-large",
        "extra-register",
        "extra-byte",
    ],
)
def test_invalid_read_response_pdu(
    function_code: int, header: str, data: str, message: str
) -> None:
    """Keep MBAP Length valid so malformed read PDUs reach the response parser."""
    frame = bytes.fromhex(header) + bytes([function_code]) + bytes.fromhex(data)
    with pytest.raises(ValueError, match=message):
        decode_read_response(frame)


@pytest.mark.parametrize("function_code", [0x03, 0x04])
def test_read_response_excessive_register_count(function_code: int) -> None:
    """A legal MBAP size does not allow a byte_count claiming 126 registers."""
    frame = (
        bytes.fromhex("12 34 00 00 00 FD 01")
        + bytes([function_code, 0xFC])
        + b"\x12\x34" * 125
    )
    with pytest.raises(ValueError, match="at most 125 registers"):
        decode_read_response(frame)


@pytest.mark.parametrize(
    ("frame", "expected"),
    [
        ("12 34 00 00 00 03 01 83 02", ModbusExceptionResponse(0x1234, 1, 3, 2)),
        ("AB CD 00 00 00 03 FE 84 02", ModbusExceptionResponse(0xABCD, 0xFE, 4, 2)),
    ],
)
def test_decode_read_exception(frame: str, expected: ModbusExceptionResponse) -> None:
    """Exceptions are immutable data with the original, unflagged function code."""
    response = decode_read_response(bytes.fromhex(frame))
    assert response == expected
    with pytest.raises(FrozenInstanceError):
        response.exception_code = 0


@pytest.mark.parametrize("function_code", [0x03, 0x04])
@pytest.mark.parametrize("exception_code", [0x00, 0xFF])
def test_read_exception_raw_code(function_code: int, exception_code: int) -> None:
    """Preserve raw UInt8 exception codes without an exception-code allowlist."""
    frame = bytes.fromhex("12 34 00 00 00 03 01") + bytes(
        [function_code | 0x80, exception_code]
    )
    assert decode_read_response(frame) == ModbusExceptionResponse(
        0x1234, 1, function_code, exception_code
    )


@pytest.mark.parametrize("function_code", [0x83, 0x84])
@pytest.mark.parametrize(
    ("header", "data"),
    [
        ("12 34 00 00 00 02 01", ""),
        ("12 34 00 00 00 04 01", "02 FF"),
        ("12 34 00 00 00 05 01", "02 FF FF"),
    ],
    ids=["missing-code", "extra-byte", "extra-bytes"],
)
def test_invalid_read_exception_pdu(function_code: int, header: str, data: str) -> None:
    """Exception PDUs must contain exactly the function and one exception byte."""
    frame = bytes.fromhex(header) + bytes([function_code]) + bytes.fromhex(data)
    with pytest.raises(ValueError, match="exception PDU must contain exactly 2 bytes"):
        decode_read_response(frame)


@pytest.mark.parametrize(
    "function_code",
    [
        0x00,
        0x01,
        0x02,
        0x05,
        0x06,
        0x10,
        0x16,
        0x7F,
        0x80,
        0x81,
        0x82,
        0x86,
        0x90,
        0x96,
        0xFF,
    ],
)
def test_unsupported_read_response_function(function_code: int) -> None:
    """Reject other functions, including writes and their exception variants."""
    frame = bytes.fromhex("12 34 00 00 00 03 01") + bytes([function_code, 0x02])
    with pytest.raises(ValueError, match=f"Unsupported.*0x{function_code:02X}"):
        decode_read_response(frame)


@pytest.mark.parametrize(
    ("frame", "message"),
    [
        ("", "Truncated MBAP header"),
        ("12 34 00 00 00 01 01", "MBAP length"),
        ("12 34 00 01 00 05 01 04 02 12 34", "protocol ID"),
        ("12 34 00 00 00 06 01 04 02 12 34", "complete frame size"),
    ],
    ids=["empty-frame", "empty-pdu", "nonzero-protocol", "inconsistent-length"],
)
def test_read_response_invalid_mbap(frame: str, message: str) -> None:
    """Reuse MBAP validation before accessing or interpreting any PDU byte."""
    with pytest.raises(ValueError, match=message):
        decode_read_response(bytes.fromhex(frame))
