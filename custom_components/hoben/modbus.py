"""Pure Modbus/TCP framing and read messages, as documented in protocol.md.

The caller supplies exactly one complete frame. This module has no transport,
MyHOBEN envelope, register interpretation, or Home Assistant dependencies.
"""

from dataclasses import dataclass
from struct import Struct

MODBUS_PROTOCOL_ID = 0x0000
HOBEN_UNIT_ID = 1
READ_HOLDING_REGISTERS = 0x03
READ_INPUT_REGISTERS = 0x04

# MODBUS Application Protocol V1.1b3, sections 4.1, 6.3 and 6.4.
# Normative reference and the derived MBAP limits are recorded in protocol.md §6.
_MAX_PDU_SIZE = 253
_MAX_READ_REGISTERS = 125
_UINT8_MAX = 0xFF
_UINT16_MAX = 0xFFFF
# Network byte order: transaction, protocol, length (UInt16), then unit (UInt8).
_MBAP_HEADER = Struct(">HHHB")
_READ_PDU = Struct(">BHH")
_UNIT_ID_SIZE = 1
_MIN_MBAP_LENGTH = _UNIT_ID_SIZE + 1  # Unit ID and at least the function byte.
_MAX_MBAP_LENGTH = _UNIT_ID_SIZE + _MAX_PDU_SIZE
_MBAP_PREFIX_SIZE = _MBAP_HEADER.size - _UNIT_ID_SIZE


@dataclass(frozen=True)
class ModbusTcpFrame:
    """Decoded MBAP fields and opaque PDU bytes from one Modbus/TCP frame."""

    transaction_id: int
    unit_id: int
    pdu: bytes


@dataclass(frozen=True)
class ModbusReadResponse:
    """A function 03/04 response with ordered, unsigned 16-bit register values."""

    transaction_id: int
    unit_id: int
    function_code: int
    registers: tuple[int, ...]


@dataclass(frozen=True)
class ModbusExceptionResponse:
    """A read exception with the original function code and raw UInt8 error code."""

    transaction_id: int
    unit_id: int
    function_code: int
    exception_code: int


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

    Raise ValueError for invalid integer fields or a PDU outside 1..253 bytes,
    and TypeError for a PDU that is not bytes. The PDU is otherwise opaque.
    The size limit is defined by MODBUS Application Protocol V1.1b3 §4.1.
    """
    _validate_integer("transaction_id", transaction_id, 0, _UINT16_MAX)
    _validate_integer("unit_id", unit_id, 0, _UINT8_MAX)
    if not isinstance(pdu, bytes):
        raise TypeError("pdu must be bytes")
    # Length counts everything after the first six bytes, including Unit ID.
    length = len(pdu) + _UNIT_ID_SIZE
    if not _MIN_MBAP_LENGTH <= length <= _MAX_MBAP_LENGTH:
        raise ValueError("MBAP length must be between 2 and 254 (PDU: 1..253 bytes)")
    return _MBAP_HEADER.pack(transaction_id, MODBUS_PROTOCOL_ID, length, unit_id) + pdu


def decode_mbap(frame: bytes) -> ModbusTcpFrame:
    """Validate exactly one complete Modbus/TCP frame and return its fields.

    Raise ValueError for a truncated header, nonzero protocol ID, PDU outside
    1..253 bytes, or inconsistent length. Trailing bytes are rejected too.
    Raise TypeError if frame is not bytes. PDU contents are not interpreted.
    """
    if not isinstance(frame, bytes):
        raise TypeError("frame must be bytes")
    if len(frame) < _MBAP_HEADER.size:
        raise ValueError("Truncated MBAP header")
    transaction_id, protocol_id, length, unit_id = _MBAP_HEADER.unpack_from(frame)
    if protocol_id != MODBUS_PROTOCOL_ID:
        raise ValueError("MBAP protocol ID must be zero")
    if not _MIN_MBAP_LENGTH <= length <= _MAX_MBAP_LENGTH:
        raise ValueError("MBAP length must be between 2 and 254 (PDU: 1..253 bytes)")
    if len(frame) != _MBAP_PREFIX_SIZE + length:
        raise ValueError("MBAP length does not match the complete frame size")
    return ModbusTcpFrame(transaction_id, unit_id, frame[_MBAP_HEADER.size :])


def decode_read_response(
    frame: bytes,
) -> ModbusReadResponse | ModbusExceptionResponse:
    """Decode one complete function 03/04 response, including Modbus exceptions.

    A normal PDU is function, byte_count, then 1..125 big-endian UInt16 values.
    byte_count must be nonzero, even and match all remaining PDU bytes exactly.
    No signed or physical conversion is applied to the register values.

    An exception PDU is exactly two bytes: function | 0x80, exception_code.
    Return it as data, preserving the original function (03/04) and raw code.
    Transaction and Unit IDs are preserved without correlating a prior request.

    MBAP validation is delegated to decode_mbap. Raise ValueError for malformed
    frames or unsupported functions, and TypeError if frame is not bytes.
    """
    decoded = decode_mbap(frame)
    pdu = decoded.pdu
    # decode_mbap guarantees a nonempty PDU, including its function byte.
    function_code = pdu[0]
    if function_code in (READ_HOLDING_REGISTERS | 0x80, READ_INPUT_REGISTERS | 0x80):
        if len(pdu) != 2:
            raise ValueError("Modbus exception PDU must contain exactly 2 bytes")
        return ModbusExceptionResponse(
            decoded.transaction_id, decoded.unit_id, function_code & 0x7F, pdu[1]
        )

    if function_code not in (READ_HOLDING_REGISTERS, READ_INPUT_REGISTERS):
        raise ValueError(
            f"Unsupported read response function code: 0x{function_code:02X}"
        )
    if len(pdu) < 2:
        raise ValueError("Read response PDU is missing byte_count")
    byte_count = pdu[1]
    if byte_count == 0 or byte_count % 2:
        raise ValueError("Read response byte_count must be nonzero and even")
    if byte_count // 2 > _MAX_READ_REGISTERS:
        raise ValueError(
            f"Read response must contain at most {_MAX_READ_REGISTERS} registers"
        )
    if len(pdu) != 2 + byte_count:
        raise ValueError("Read response byte_count does not match the PDU data size")

    registers = tuple(
        int.from_bytes(pdu[offset : offset + 2], "big")
        for offset in range(2, len(pdu), 2)
    )
    return ModbusReadResponse(
        decoded.transaction_id, decoded.unit_id, function_code, registers
    )


def _build_read_request(
    function_code: int, transaction_id: int, address: int, quantity: int, unit_id: int
) -> bytes:
    """Encode the common read PDU: function byte, UInt16 address and quantity."""
    _validate_integer("address", address, 0, _UINT16_MAX)
    _validate_integer("quantity", quantity, 1, _MAX_READ_REGISTERS)
    # The last requested register, not just the starting address, must fit UInt16.
    if address + quantity > _UINT16_MAX + 1:
        raise ValueError("Read address range must not exceed 0xFFFF")
    pdu = _READ_PDU.pack(function_code, address, quantity)
    return encode_mbap(transaction_id, unit_id, pdu)


def build_read_holding_registers(
    transaction_id: int, address: int, quantity: int, *, unit_id: int = HOBEN_UNIT_ID
) -> bytes:
    """Build a function 03 request; default Unit ID is the documented Hoben ID.

    Transaction ID and address must fit UInt16, and Unit ID must fit UInt8.
    Quantity is 1..125 (MODBUS V1.1b3 §6.3); the last address must fit UInt16.
    Invalid fields raise ValueError. No register-map or device limits are assumed.
    """
    return _build_read_request(
        READ_HOLDING_REGISTERS, transaction_id, address, quantity, unit_id
    )


def build_read_input_registers(
    transaction_id: int, address: int, quantity: int, *, unit_id: int = HOBEN_UNIT_ID
) -> bytes:
    """Build a function 04 request with the same field rules as function 03.

    Quantity is 1..125 (MODBUS V1.1b3 §6.4); the last address must fit UInt16.
    Unit ID defaults to the documented Hoben ID; invalid fields raise ValueError.
    The transaction ID is supplied by the caller, not fixed to a stove profile.
    """
    return _build_read_request(
        READ_INPUT_REGISTERS, transaction_id, address, quantity, unit_id
    )
