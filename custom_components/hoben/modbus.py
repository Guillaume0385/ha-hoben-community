"""Pure Modbus/TCP framing and read requests, as documented in protocol.md.

The caller supplies exactly one complete frame. This module has no transport,
MyHOBEN envelope, register decoding, or Home Assistant dependencies.
"""

from dataclasses import dataclass
from struct import Struct

MODBUS_PROTOCOL_ID = 0x0000
HOBEN_UNIT_ID = 1
READ_HOLDING_REGISTERS = 0x03
READ_INPUT_REGISTERS = 0x04

_UINT8_MAX = 0xFF
_UINT16_MAX = 0xFFFF
# Network byte order: transaction, protocol, length (UInt16), then unit (UInt8).
_MBAP_HEADER = Struct(">HHHB")
_READ_PDU = Struct(">BHH")
_UNIT_ID_SIZE = 1
_MIN_MBAP_LENGTH = _UNIT_ID_SIZE + 1  # Unit ID and at least the function byte.
_MBAP_PREFIX_SIZE = _MBAP_HEADER.size - _UNIT_ID_SIZE


@dataclass(frozen=True)
class ModbusTcpFrame:
    """Decoded MBAP fields and opaque PDU bytes from one Modbus/TCP frame."""

    transaction_id: int
    unit_id: int
    pdu: bytes


def _validate_integer(name: str, value: int, minimum: int, maximum: int) -> None:
    """Reject out-of-range fields and implicit conversions, including booleans."""
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not minimum <= value <= maximum
    ):
        raise ValueError(f"{name} must be an integer between {minimum} and {maximum}")


def encode_mbap(transaction_id: int, unit_id: int, pdu: bytes) -> bytes:
    """Wrap a nonempty PDU in a big-endian MBAP header with protocol ID zero.

    Raise ValueError for invalid integer fields or an unrepresentable length,
    and TypeError for a PDU that is not bytes. The PDU is otherwise opaque.
    Only the documented field widths are enforced, not device-specific limits.
    """
    _validate_integer("transaction_id", transaction_id, 0, _UINT16_MAX)
    _validate_integer("unit_id", unit_id, 0, _UINT8_MAX)
    if not isinstance(pdu, bytes):
        raise TypeError("pdu must be bytes")
    # Length counts everything after the first six bytes, including Unit ID.
    length = len(pdu) + _UNIT_ID_SIZE
    if not _MIN_MBAP_LENGTH <= length <= _UINT16_MAX:
        raise ValueError("MBAP length must include a PDU and fit in UInt16")
    return _MBAP_HEADER.pack(transaction_id, MODBUS_PROTOCOL_ID, length, unit_id) + pdu


def decode_mbap(frame: bytes) -> ModbusTcpFrame:
    """Validate exactly one complete Modbus/TCP frame and return its fields.

    Raise ValueError for a truncated header, nonzero protocol ID, missing PDU,
    or inconsistent length. Trailing bytes (including another frame) are rejected.
    Raise TypeError if frame is not bytes. PDU contents are not interpreted.
    """
    if not isinstance(frame, bytes):
        raise TypeError("frame must be bytes")
    if len(frame) < _MBAP_HEADER.size:
        raise ValueError("Truncated MBAP header")
    transaction_id, protocol_id, length, unit_id = _MBAP_HEADER.unpack_from(frame)
    if protocol_id != MODBUS_PROTOCOL_ID:
        raise ValueError("MBAP protocol ID must be zero")
    if length < _MIN_MBAP_LENGTH:
        raise ValueError("MBAP length must include Unit ID and a PDU")
    if len(frame) != _MBAP_PREFIX_SIZE + length:
        raise ValueError("MBAP length does not match the complete frame size")
    return ModbusTcpFrame(transaction_id, unit_id, frame[_MBAP_HEADER.size :])


def _build_read_request(
    function_code: int, transaction_id: int, address: int, quantity: int, unit_id: int
) -> bytes:
    """Encode the common read PDU: function byte, UInt16 address and quantity."""
    _validate_integer("address", address, 0, _UINT16_MAX)
    _validate_integer("quantity", quantity, 1, _UINT16_MAX)
    pdu = _READ_PDU.pack(function_code, address, quantity)
    return encode_mbap(transaction_id, unit_id, pdu)


def build_read_holding_registers(
    transaction_id: int, address: int, quantity: int, *, unit_id: int = HOBEN_UNIT_ID
) -> bytes:
    """Build a function 03 request; default Unit ID is the documented Hoben ID.

    Fields must fit UInt16 (Unit ID: UInt8), and quantity must be nonzero.
    Invalid fields raise ValueError. No register-map or device limits are assumed.
    """
    return _build_read_request(
        READ_HOLDING_REGISTERS, transaction_id, address, quantity, unit_id
    )


def build_read_input_registers(
    transaction_id: int, address: int, quantity: int, *, unit_id: int = HOBEN_UNIT_ID
) -> bytes:
    """Build a function 04 request with the same field rules as function 03.

    Unit ID defaults to the documented Hoben ID; invalid fields raise ValueError.
    The transaction ID is supplied by the caller, not fixed to a stove profile.
    """
    return _build_read_request(
        READ_INPUT_REGISTERS, transaction_id, address, quantity, unit_id
    )
