"""Deterministic Modbus/TCP fixtures, without a MyHOBEN envelope or network."""

from collections.abc import Callable
from dataclasses import FrozenInstanceError

import pytest

from custom_components.hoben.modbus import (
    ModbusTcpFrame,
    build_read_holding_registers,
    build_read_input_registers,
    decode_mbap,
    encode_mbap,
)


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
