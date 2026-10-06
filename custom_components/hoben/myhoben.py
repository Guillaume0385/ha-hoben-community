"""Pure MyHOBEN session codecs and Modbus framing (protocol.md §§2, 4 and 5).

Each helper handles one already-delimited message/frame or confirmed session prefix.
MyHOBEN adds only a message-type byte, with no independent length field. Stream
buffering belongs to the session layer, not these helpers.
For Modbus messages, the PDU remains opaque; MBAP validation uses its own codec.
"""

import re
from dataclasses import dataclass, field
from enum import StrEnum

from .modbus import decode_mbap

OPEN_CLIENT = 0x03
OPENED_CLIENT = 0x04
CLOSE_CLIENT = 0x05
DATA_REQUEST_CLIENT = 0x0D
DATA_RESPONSE_CLIENT = 0x0E
DEVICE_AUTH_REQ = 0x2F
DEVICE_AUTH_RES = 0x30
# Guid.Empty without dashes is the normal first-association client identity.
INITIAL_DEVICE_GUID = "00000000000000000000000000000000"


class CloseClientReason(StrEnum):
    """Allowlisted meanings from protocol.md §5, never server-supplied text."""

    INVALID_IDENTIFIER = "invalid_identifier"
    STOVE_CONNECTION_REQUIRED = "stove_connection_required"
    AUTHORIZATION_REJECTED = "authorization_rejected"
    AUTHORIZATION_TIMEOUT = "authorization_timeout"
    SERVER_MAINTENANCE = "server_maintenance"
    UNKNOWN = "unknown"


_CLOSE_CLIENT_REASONS = {
    0x02: CloseClientReason.INVALID_IDENTIFIER,
    0x03: CloseClientReason.STOVE_CONNECTION_REQUIRED,
    0x04: CloseClientReason.AUTHORIZATION_REJECTED,
    0x05: CloseClientReason.AUTHORIZATION_TIMEOUT,
    0x06: CloseClientReason.SERVER_MAINTENANCE,
}


def normalize_user_guid(value: str) -> str:
    """Validate an Identifiant HOBEN and return 32 lowercase ASCII hex digits.

    Accept compact or canonical 8-4-4-4-12 GUID notation, without echoing inputs.
    No assigned-identity or authentication claim follows from valid syntax.
    """
    if not isinstance(value, str):
        raise TypeError("user_guid must be str")
    if (
        re.fullmatch(
            r"[0-9a-fA-F]{32}|[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}",
            value,
        )
        is None
    ):
        raise ValueError("Invalid UserGuid format")
    return value.replace("-", "").lower()


def decode_close_client(message: bytes) -> CloseClientReason:
    """Read only a documented 0x05 subcode; discard all other payload bytes.

    Missing/unknown subcodes have no inferred meaning. The session layer may
    supply a type-only prefix after EOF; this does not establish a frame length.
    """
    if not isinstance(message, bytes):
        raise TypeError("message must be bytes")
    if not message or message[0] != CLOSE_CLIENT:
        raise ValueError("Expected CloseClient message type 0x05")
    return _CLOSE_CLIENT_REASONS.get(
        message[1] if len(message) >= 2 else None, CloseClientReason.UNKNOWN
    )


def encode_device_auth_response(code: int) -> bytes:
    """Encode the documented 0x30 + UInt16 little-endian authorization code.

    This pure codec does not send, retain or persist the sensitive code. Never
    log the returned packet. UInt16 bounds describe the wire representation,
    not the server's accepted codes, UI digit count or expiration rules.
    protocol.md §5 records the MANAGER-reviewed static evidence for the one-byte
    DeviceAuthReq marker. Session buffering and authorization remain separate.
    """
    if not isinstance(code, int) or isinstance(code, bool):
        raise TypeError("Authorization code must be an integer")
    if not 0 <= code <= 0xFFFF:
        raise ValueError("Authorization code must fit UInt16")
    return bytes([DEVICE_AUTH_RES]) + code.to_bytes(2, "little")


@dataclass(frozen=True)
class OpenedClient:
    """Confirmed fields, with the sensitive DeviceGuid excluded from repr output."""

    product_revision: int
    product_type: int
    software_minor: int
    software_major: int
    device_guid: str = field(repr=False)
    application_version: int


def encode_open_client(
    user_guid: str, build: int, device_guid: str, device_info: str
) -> bytes:
    """Encode 0x03 + UserGuid + 00 01 + UInt16-LE build + DeviceGuid + DeviceInfo.

    UserGuid is validated/normalized to 32 ASCII hex digits (protocol.md §4).
    DeviceGuid and DeviceInfo are UTF-8 encoded as supplied. First-client callers
    use INITIAL_DEVICE_GUID; persistence of the returned DeviceGuid is separate.
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
        + normalize_user_guid(user_guid).encode("ascii")
        + b"\x00\x01"
        + build.to_bytes(2, "little")
        + device_guid.encode("utf-8")
        + device_info.encode("utf-8")
    )


def decode_opened_client(message: bytes) -> OpenedClient:
    """Parse confirmed offsets from a 0x04 OpenedClient prefix of at least 48 bytes.

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
