"""Pure MyHOBEN client Modbus framing, as documented in protocol.md §2.

Each helper handles exactly one complete, already-delimited message or frame.
MyHOBEN adds only a message-type byte, with no independent length field. Stream
buffering and splitting belong to a future transport layer, not these helpers.
The embedded Modbus PDU remains opaque; MBAP validation uses the existing codec.
"""

from .modbus import decode_mbap

DATA_REQUEST_CLIENT = 0x0D
DATA_RESPONSE_CLIENT = 0x0E


def encode_data_request_client(modbus_frame: bytes) -> bytes:
    """Prepend 0x0D to exactly one valid Modbus/TCP frame, preserving its bytes.

    The MBAP header starts immediately after the single MyHOBEN type byte.
    Raise TypeError for non-bytes input and propagate ValueError from decode_mbap
    for incomplete, malformed or concatenated frames, including trailing bytes.
    """
    decode_mbap(modbus_frame)
    return bytes([DATA_REQUEST_CLIENT]) + modbus_frame


def decode_data_response_client(message: bytes) -> bytes:
    """Remove exactly the leading 0x0E and return the validated Modbus/TCP frame.

    Raise TypeError for non-bytes input and ValueError for a missing payload,
    another message type or invalid MBAP framing (including trailing bytes).
    Only decode_mbap validates the embedded frame. Callers may pass the returned
    bytes to decode_read_response to interpret normal or exception read PDUs.
    """
    if not isinstance(message, bytes):
        raise TypeError("message must be bytes")
    if len(message) < 2:
        raise ValueError("DataResponseClient requires a type and Modbus/TCP frame")
    if message[0] != DATA_RESPONSE_CLIENT:
        raise ValueError("Expected DataResponseClient message type 0x0E")
    modbus_frame = message[1:]
    decode_mbap(modbus_frame)
    return modbus_frame
