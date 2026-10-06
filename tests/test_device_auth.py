"""The proven authorization response codec, without a guessed receive boundary."""

import traceback

import pytest

from custom_components.hoben.myhoben import encode_device_auth_response


@pytest.mark.parametrize(
    ("code", "packet"),
    [
        (0, b"\x30\x00\x00"),
        (1, b"\x30\x01\x00"),
        (255, b"\x30\xff\x00"),
        (256, b"\x30\x00\x01"),
        (0x0B0A, b"\x30\x0a\x0b"),
        (0xABCD, b"\x30\xcd\xab"),
        (65535, b"\x30\xff\xff"),
    ],
)
def test_device_auth_response_wire_bytes(code, packet, caplog, capsys):
    """Independent byte literals check type, UInt16 limits and little-endian order."""
    with caplog.at_level("DEBUG"):
        assert encode_device_auth_response(code) == packet
    output = capsys.readouterr()
    assert output.out == output.err == caplog.text == ""


@pytest.mark.parametrize("code", [-73491, 73491])
def test_unrepresentable_code_is_rejected_without_echo(code):
    """Wire validation must not disclose a caller's code in exception output."""
    with pytest.raises(
        ValueError, match="^Authorization code must fit UInt16$"
    ) as caught:
        encode_device_auth_response(code)
    public = repr(caught.value) + "".join(traceback.format_exception(caught.value))
    assert str(code) not in public


@pytest.mark.parametrize(
    "code", [True, False, None, "SYNTHETIC-PRIVATE-CODE", b"73491", 3.5]
)
def test_code_types_are_not_implicitly_coerced_or_disclosed(code):
    """No bool/string/float coercion invents a UI convention for a future flow."""
    with pytest.raises(
        TypeError, match="^Authorization code must be an integer$"
    ) as caught:
        encode_device_auth_response(code)
    public = repr(caught.value) + "".join(traceback.format_exception(caught.value))
    assert "SYNTHETIC-PRIVATE-CODE" not in public
    assert "73491" not in public
