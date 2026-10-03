"""Pure MyHOBEN session codecs and Modbus framing (protocol.md §§2 and 4).

Each helper handles exactly one complete, already-delimited message or frame.
MyHOBEN adds only a message-type byte, with no independent length field. Stream
buffering and splitting belong to a future transport layer, not these helpers.
For Modbus messages, the PDU remains opaque; MBAP validation uses its own codec.
"""

from dataclasses import dataclass

from .modbus import decode_mbap

OPEN_CLIENT = 0x03
OPENED_CLIENT = 0x04
DATA_REQUEST_CLIENT = 0x0D
DATA_RESPONSE_CLIENT = 0x0E


@dataclass(frozen=True)
class OpenedClient:
    """Confirmed session fields, preserved without interpreting the stove profile."""

    product_revision: int
    product_type: int
    software_minor: int
    software_major: int
    device_guid: str
    application_version: int


def encode_open_client(
    user_guid: str, build: int, device_guid: str, device_info: str
) -> bytes:
    """Encode 0x03 + UserGuid + 00 01 + UInt16-LE build + DeviceGuid + DeviceInfo.

    All three strings are UTF-8 encoded exactly as supplied: their lengths and
    formats are not established, so no normalization or separators are added.
    Raise TypeError for non-str fields and ValueError for a build outside UInt16
    or not an integer (including booleans). No identifier values enter errors.
    """
    for name, value in (
        ("user_guid", user_guid),
        ("device_guid", device_guid),
        ("device_info", device_info),
    ):
        if not isinstance(value, str):
            raise TypeError(f"{name} must be str")
    if (
        not isinstance(build, int)
        or isinstance(build, bool)
        or not 0 <= build <= 0xFFFF
    ):
        raise ValueError("build must be an integer between 0 and 65535")
    return (
        bytes([OPEN_CLIENT])
        + user_guid.encode("utf-8")
        + b"\x00\x01"
        + build.to_bytes(2, "little")
        + device_guid.encode("utf-8")
        + device_info.encode("utf-8")
    )


def decode_opened_client(message: bytes) -> OpenedClient:
    """Parse the confirmed offsets of a complete 0x04 OpenedClient message.

    Offsets are relative to the type byte: 7/8 are product revision/type, 9/10
    are software minor/major, 14:46 is the 32-byte ASCII DeviceGuid and 46:48
    is the UInt16 little-endian application version. Other bytes stay unparsed.
    The total length is not established: require at least 48 bytes and ignore
    undocumented trailing bytes until future captures can refine this policy.

    Raise TypeError for non-bytes input and ValueError for a short message,
    incorrect type or non-ASCII DeviceGuid, without exposing identifier values.
    """
    if not isinstance(message, bytes):
        raise TypeError("message must be bytes")
    if len(message) < 48:
        raise ValueError("OpenedClient requires at least 48 bytes")
    if message[0] != OPENED_CLIENT:
        raise ValueError("Expected OpenedClient message type 0x04")
    try:
        device_guid = message[14:46].decode("ascii")
    except UnicodeDecodeError:
        raise ValueError(
            "OpenedClient DeviceGuid must contain only ASCII bytes"
        ) from None
    return OpenedClient(
        product_revision=message[7],
        product_type=message[8],
        software_minor=message[9],
        software_major=message[10],
        device_guid=device_guid,
        application_version=int.from_bytes(message[46:48], "little"),
    )


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
