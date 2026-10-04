"""Deterministic MyHOBEN fixtures, without a network or real identifiers."""

from collections.abc import Callable
from dataclasses import FrozenInstanceError

import pytest

from custom_components.hoben.modbus import (
    ModbusExceptionResponse,
    ModbusReadResponse,
    decode_read_response,
)
from custom_components.hoben.myhoben import (
    CloseClientReason,
    OpenedClient,
    decode_close_client,
    decode_data_response_client,
    decode_opened_client,
    encode_data_request_client,
    encode_open_client,
    normalize_user_guid,
)

SYNTHETIC_USER_GUID = "0123456789abcdef0123456789abcdef"
INITIAL_DEVICE_GUID = "00000000000000000000000000000000"

# Literal complete 48-byte response, independent of any encoder or real capture.
# Undocumented bytes are synthetic too; the four product/software bytes differ.
OPENED_CLIENT_MESSAGE = (
    b"\x04\xa1\xb2\xc3\xd4\xe5\xf6\x17\x28\x39\x4a\xab\xbc\xcd"
    b"ABCDabcdABCDabcdABCDabcdABCDabcd"
    b"\x34\x12"
)


def test_encode_open_client() -> None:
    """Check the complete wire bytes, including 34 12 and no length field."""
    message = encode_open_client(
        "01234567-89AB-CDEF-0123-456789ABCDEF",
        0x1234,
        INITIAL_DEVICE_GUID,
        "Maker/Model/fr/Android/16/1080/2400/2.5/Portrait/0,0",
    )
    assert isinstance(message, bytes)
    assert message == (
        b"\x030123456789abcdef0123456789abcdef\x00\x01\x34\x12"
        b"00000000000000000000000000000000"
        b"Maker/Model/fr/Android/16/1080/2400/2.5/Portrait/0,0"
    )


@pytest.mark.parametrize(
    ("build", "expected"),
    [
        (0, b"\x00\x00"),
        (0xFFFF, b"\xff\xff"),
    ],
)
def test_open_client_build_boundaries(build: int, expected: bytes) -> None:
    """Both ends of the UInt16 range occupy exactly two bytes."""
    assert encode_open_client(
        SYNTHETIC_USER_GUID, build, INITIAL_DEVICE_GUID, "INFO"
    ) == (
        b"\x030123456789abcdef0123456789abcdef\x00\x01"
        + expected
        + b"00000000000000000000000000000000INFO"
    )


def test_open_client_preserves_utf8() -> None:
    """Keep case, whitespace and Unicode (including decomposed text) in DeviceInfo."""
    assert encode_open_client(
        SYNTHETIC_USER_GUID, 34, INITIAL_DEVICE_GUID, " Ma\u0301ker/模型\t"
    ) == (
        b"\x030123456789abcdef0123456789abcdef\x00\x01\x22\x00"
        b"00000000000000000000000000000000 "
        b"Ma\xcc\x81ker/\xe6\xa8\xa1\xe5\x9e\x8b\t"
    )


@pytest.mark.parametrize(
    "value",
    [
        SYNTHETIC_USER_GUID,
        SYNTHETIC_USER_GUID.upper(),
        "01234567-89AB-CDEF-0123-456789ABCDEF",
    ],
)
def test_normalize_user_guid(value) -> None:
    """Both documented notations produce exactly 32 ASCII hex digits."""
    normalized = normalize_user_guid(value)
    assert normalized == SYNTHETIC_USER_GUID
    assert len(normalized.encode("ascii")) == 32


def test_zero_user_guid_has_valid_syntax() -> None:
    """The negative identity is synthetic/unassigned, not syntactically malformed."""
    assert normalize_user_guid("00000000-0000-0000-0000-000000000000") == "0" * 32


@pytest.mark.parametrize(
    "value",
    [
        "",
        "a" * 31,
        "a" * 33,
        "g" * 32,
        "０" * 32,
        "a" * 32 + "\n",
        " " + SYNTHETIC_USER_GUID,
        "{" + SYNTHETIC_USER_GUID + "}",
        "012345678-9ab-cdef-0123-456789abcdef",
        "SYNTHETIC-PRIVATE",
    ],
)
def test_invalid_user_guid_is_not_encoded(value) -> None:
    """No malformed GUID passes the shared codec or appears in its error."""
    for operation in (
        lambda: normalize_user_guid(value),
        lambda: encode_open_client(value, 34, INITIAL_DEVICE_GUID, "INFO"),
    ):
        with pytest.raises(ValueError, match="^Invalid UserGuid format$"):
            operation()


@pytest.mark.parametrize("value", [None, 123, b"SYNTHETIC-PRIVATE"])
def test_normalize_user_guid_requires_text(value) -> None:
    """No coercion of binary/non-text identifiers."""
    with pytest.raises(TypeError, match="^user_guid must be str$"):
        normalize_user_guid(value)


@pytest.mark.parametrize(
    ("message", "reason"),
    [
        (b"\x05\x02", CloseClientReason.INVALID_IDENTIFIER),
        (b"\x05\x03", CloseClientReason.STOVE_CONNECTION_REQUIRED),
        (b"\x05\x04", CloseClientReason.AUTHORIZATION_REJECTED),
        (b"\x05\x05", CloseClientReason.AUTHORIZATION_TIMEOUT),
        (b"\x05\x06", CloseClientReason.SERVER_MAINTENANCE),
        (b"\x05\xff", CloseClientReason.UNKNOWN),
        (b"\x05\x00", CloseClientReason.UNKNOWN),
        (b"\x05", CloseClientReason.UNKNOWN),
    ],
)
def test_close_client_reason(message, reason) -> None:
    """Only the documented subcode is interpreted; absence remains unknown."""
    assert decode_close_client(message) is reason
    if len(message) >= 2:
        assert decode_close_client(message + b"\x0aPRIVATE-AUTH-GUID") is reason


@pytest.mark.parametrize("message", [b"", b"\x04\x02", b"\xffPRIVATE"])
def test_close_client_requires_type(message) -> None:
    """No arbitrary payload or other message becomes a closure reason."""
    with pytest.raises(ValueError, match="^Expected CloseClient message type 0x05$"):
        decode_close_client(message)


@pytest.mark.parametrize("value", [None, "PRIVATE", bytearray(b"\x05\x02")])
def test_close_client_requires_bytes(value) -> None:
    """The pure decoder accepts only immutable bytes."""
    with pytest.raises(TypeError, match="^message must be bytes$"):
        decode_close_client(value)


@pytest.mark.parametrize("build", [-1, 0x10000, True, False, 34.0, "34", None])
def test_open_client_invalid_build(build: object) -> None:
    """Reject overflow, booleans and implicit integer conversions."""
    with pytest.raises(
        ValueError, match="build must be an integer between 0 and 65535"
    ):
        encode_open_client(SYNTHETIC_USER_GUID, build, INITIAL_DEVICE_GUID, "INFO")


@pytest.mark.parametrize("field", ["user_guid", "device_guid", "device_info"])
@pytest.mark.parametrize("value", [b"SYNTHETIC", bytearray(b"SYNTHETIC"), None, 123])
def test_open_client_requires_strings(field: str, value: object) -> None:
    """Each string argument rejects binary data and other non-str values."""
    fields = {
        "user_guid": SYNTHETIC_USER_GUID,
        "device_guid": INITIAL_DEVICE_GUID,
        "device_info": "INFO",
    }
    fields[field] = value
    with pytest.raises(TypeError, match=f"{field} must be str"):
        encode_open_client(build=34, **fields)


def test_decode_opened_client() -> None:
    """Distinct literal values expose field swaps and endian/offset mistakes."""
    assert len(OPENED_CLIENT_MESSAGE) == 48
    assert decode_opened_client(OPENED_CLIENT_MESSAGE) == OpenedClient(
        product_revision=0x17,
        product_type=0x28,
        software_minor=0x39,
        software_major=0x4A,
        device_guid="ABCDabcdABCDabcdABCDabcdABCDabcd",
        application_version=0x1234,
    )


@pytest.mark.parametrize(
    ("version_bytes", "expected"),
    [(b"\x34\x12", 0x1234), (b"\x00\x00", 0), (b"\xff\xff", 0xFFFF)],
)
def test_opened_client_application_version(version_bytes: bytes, expected: int) -> None:
    """Application version is unsigned UInt16 little-endian at offsets 46..47."""
    message = OPENED_CLIENT_MESSAGE[:46] + version_bytes
    assert decode_opened_client(message).application_version == expected


@pytest.mark.parametrize(
    ("field", "value"), [("product_type", 0), ("device_guid", "X")]
)
def test_opened_client_immutable(field: str, value: object) -> None:
    """Both numeric fields and the identifier are frozen on the parsed result."""
    result = decode_opened_client(OPENED_CLIENT_MESSAGE)
    with pytest.raises(FrozenInstanceError):
        setattr(result, field, value)


@pytest.mark.parametrize(
    "value",
    [
        None,
        "SYNTHETIC",
        4,
        list(OPENED_CLIENT_MESSAGE),
        bytearray(OPENED_CLIENT_MESSAGE),
        memoryview(OPENED_CLIENT_MESSAGE),
    ],
    ids=["none", "text", "integer", "list", "bytearray", "memoryview"],
)
def test_opened_client_requires_bytes(value: object) -> None:
    """Only immutable bytes are accepted, even for a valid complete buffer."""
    with pytest.raises(TypeError, match="message must be bytes"):
        decode_opened_client(value)


@pytest.mark.parametrize("size", range(48))
def test_opened_client_short_message(size: int) -> None:
    """Reject every truncation, including empty input and the 47-byte boundary."""
    with pytest.raises(ValueError, match="OpenedClient requires at least 48 bytes"):
        decode_opened_client(OPENED_CLIENT_MESSAGE[:size])


@pytest.mark.parametrize("message_type", [0x00, 0x03, 0x0E, 0xFF])
def test_opened_client_wrong_type(message_type: int) -> None:
    """A complete payload still requires exactly the 0x04 response type."""
    message = bytes([message_type]) + OPENED_CLIENT_MESSAGE[1:]
    with pytest.raises(ValueError, match="Expected OpenedClient message type 0x04"):
        decode_opened_client(message)


@pytest.mark.parametrize("offset", [14, 29, 45])
@pytest.mark.parametrize("value", [0x80, 0xC3, 0xFF])
def test_opened_client_non_ascii_guid(offset: int, value: int) -> None:
    """Strict ASCII applies across the whole 32-byte field, including its edges."""
    message = (
        OPENED_CLIENT_MESSAGE[:offset]
        + bytes([value])
        + OPENED_CLIENT_MESSAGE[offset + 1 :]
    )
    with pytest.raises(ValueError, match="OpenedClient DeviceGuid.*ASCII"):
        decode_opened_client(message)


def test_opened_client_preserves_ascii_guid() -> None:
    """ASCII decoding adds no UUID, case, whitespace or padding interpretation."""
    message = (
        OPENED_CLIENT_MESSAGE[:14] + b"\x00 \taZz!\x7f" * 4 + OPENED_CLIENT_MESSAGE[46:]
    )
    assert decode_opened_client(message).device_guid == "\x00 \taZz!\x7f" * 4


def test_opened_client_undocumented_bytes() -> None:
    """No inferred meaning is assigned to the unparsed bytes before DeviceGuid."""
    message = (
        b"\x04"
        + bytes(6)
        + OPENED_CLIENT_MESSAGE[7:11]
        + bytes(3)
        + OPENED_CLIENT_MESSAGE[14:]
    )
    assert decode_opened_client(message) == decode_opened_client(OPENED_CLIENT_MESSAGE)


@pytest.mark.parametrize("suffix", [b"\xff", b"\x00\x80TRAILING\x78\x56"])
def test_opened_client_trailing_bytes(suffix: bytes) -> None:
    """An unknown suffix cannot extend the ASCII field or change app version."""
    assert decode_opened_client(OPENED_CLIENT_MESSAGE + suffix) == decode_opened_client(
        OPENED_CLIENT_MESSAGE
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
