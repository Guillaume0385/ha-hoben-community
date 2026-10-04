"""Sanitized raw V4 CLI reports and failure codes over offline TLS streams."""

import json
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.hoben.session import SessionProtocolError, SessionTimeout
from custom_components.hoben.transport import (
    TransportEOF,
    TransportError,
    TransportTimeout,
    TransportTlsError,
)
from custom_components.hoben.v4_read import V4ReadProtocolError, V4ReadTimeout
from scripts import probe_hoben_connection as probe

USER_GUID = "01234567-89AB-CDEF-0123-456789ABCDEF"
OPENED = (
    b"\x04\x00\x00\x00\x00\x00\x00\x00\x05\x02\x08\x00\x00\x00"
    b"ABCDabcdABCDabcdABCDabcdABCDabcd\x00\x02"
)
RESPONSE = bytes.fromhex("0E FF FF 00 00 00 2B 01 04 28") + b"\xff\xff" * 20
BASE_REPORT = {"host": "myhoben.fr", "port": 465, "mode": "read-v4-state"}


@pytest.fixture(autouse=True)
def synthetic_environment(monkeypatch):
    """No test reads any actual Hoben credentials from the execution environment."""
    monkeypatch.setenv("HOBEN_USER_GUID", USER_GUID)
    monkeypatch.setenv("HOBEN_DEVICE_GUID", "PRIVATE-IGNORED")
    monkeypatch.delenv("HOBEN_BUILD", raising=False)
    monkeypatch.delenv("HOBEN_DEVICE_INFO", raising=False)


def test_read_success_uses_one_shot_defaults_and_safe_output(
    streams, monkeypatch, capsys, caplog
):
    """The only safe artifact/stdout input is the explicit raw-value allowlist."""
    streams.reader.read.side_effect = [OPENED, RESPONSE]
    operation = AsyncMock(wraps=probe.open_and_read_v4_once)
    monkeypatch.setattr(probe, "open_and_read_v4_once", operation)
    with caplog.at_level("DEBUG"):
        assert probe.main(["--read-v4-state"]) == 0
    output = capsys.readouterr()
    assert json.loads(output.out) == BASE_REPORT | {
        "state": "read",
        "profile": "v4",
        "function": 4,
        "start_address": 1024,
        "quantity": 20,
        "registers": [65535] * 20,
    }
    operation.assert_awaited_once()
    assert operation.call_args.kwargs == {
        "user_guid": "0123456789abcdef0123456789abcdef",
        "device_guid": "00000000000000000000000000000000",
        "build": 34,
        "device_info": probe.DEFAULT_DEVICE_INFO,
    }
    assert [c.args[0][0] for c in streams.writer.write.call_args_list] == [3, 13]
    public = output.out + output.err + caplog.text
    for sensitive in (
        USER_GUID,
        USER_GUID.replace("-", "").lower(),
        OPENED[14:46].decode(),
        "PRIVATE",
        "0" * 32,
    ):
        assert sensitive not in public
    assert output.err == ""


@pytest.mark.parametrize("user_guid", [None, "", "PRIVATE", "g" * 32])
def test_invalid_user_guid_blocks_before_transport(
    streams, monkeypatch, capsys, user_guid
):
    """Read mode has the same secret preflight as session-open, with no fallback."""
    if user_guid is None:
        monkeypatch.delenv("HOBEN_USER_GUID")
    else:
        monkeypatch.setenv("HOBEN_USER_GUID", user_guid)
    transport = Mock(side_effect=AssertionError("Preflight first"))
    monkeypatch.setattr(probe, "AsyncTlsTransport", transport)
    assert probe.main(["--read-v4-state"]) == 1
    output = capsys.readouterr()
    assert json.loads(output.out) == BASE_REPORT | {
        "state": "error",
        "error": "invalid_session_inputs",
    }
    assert "PRIVATE" not in output.out + output.err
    transport.assert_not_called()
    streams.connect.assert_not_awaited()


def test_device_guid_override_is_never_read(streams, monkeypatch, capsys):
    """The V4 mode builds the normal initial DeviceGuid internally too."""

    class EnvironmentWithoutDeviceGuidReads(dict):
        def __getitem__(self, key):
            assert key != "HOBEN_DEVICE_GUID"
            return super().__getitem__(key)

        def get(self, key, default=None):
            assert key != "HOBEN_DEVICE_GUID"
            return super().get(key, default)

    monkeypatch.setattr(
        probe.os, "environ", EnvironmentWithoutDeviceGuidReads(probe.os.environ)
    )
    streams.reader.read.side_effect = [OPENED, RESPONSE]
    assert probe.main(["--read-v4-state"]) == 0
    assert "PRIVATE" not in capsys.readouterr().out


@pytest.mark.parametrize(
    ("opened", "state", "error"),
    [
        (b"\x2fPRIVATE", "authorization_required", None),
        (b"\x05\x02PRIVATE", "closed", None),
        (
            OPENED + b"\x0aPRIVATE",
            "read_not_attempted",
            "unclassified_opened_client_bytes",
        ),
        (
            OPENED[:8] + b"\xff" + OPENED[9:],
            "read_not_attempted",
            "unsupported_profile",
        ),
    ],
)
def test_blocked_read_is_failure_without_modbus_or_private_output(
    streams, capsys, caplog, opened, state, error
):
    """A classified opening observation cannot be reported as a successful read."""
    streams.reader.read.side_effect = [opened, RESPONSE]
    with caplog.at_level("DEBUG"):
        assert probe.main(["--read-v4-state"]) == 1
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert report["state"] == state
    assert report.get("error") == error
    assert "registers" not in report
    streams.writer.write.assert_called_once()
    streams.reader.read.assert_awaited_once()
    assert "PRIVATE" not in output.out + output.err + caplog.text


def test_modbus_exception_is_numeric_sanitized_failure(streams, capsys):
    """A genuine exception is retained in artifacts but is not a normal read."""
    streams.reader.read.side_effect = [
        OPENED,
        bytes.fromhex("0E FF FF 00 00 00 03 01 84 FF"),
    ]
    assert probe.main(["--read-v4-state"]) == 1
    assert json.loads(capsys.readouterr().out) == BASE_REPORT | {
        "state": "modbus_exception",
        "profile": "v4",
        "function": 4,
        "start_address": 1024,
        "quantity": 20,
        "exception_code": 255,
    }
    assert streams.writer.write.call_count == 2


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (TransportTimeout("read"), {"error": "timeout", "operation": "read"}),
        (SessionTimeout(USER_GUID), {"error": "timeout", "operation": "handshake"}),
        (V4ReadTimeout(USER_GUID), {"error": "timeout", "operation": "v4_read"}),
        (TransportEOF(USER_GUID), {"error": "eof"}),
        (
            TransportTlsError(USER_GUID),
            {"error": "tls_verification_or_negotiation_failed"},
        ),
        (TransportError(USER_GUID), {"error": "transport_failed"}),
        (SessionProtocolError(USER_GUID), {"error": "invalid_opened_client"}),
        (V4ReadProtocolError(USER_GUID), {"error": "invalid_v4_read_response"}),
        (RuntimeError(USER_GUID), {"error": "probe_failed"}),
    ],
)
def test_all_exception_text_is_excluded_from_read_report(
    monkeypatch, capsys, caplog, error, expected
):
    """No exceptions containing a UserGuid may leak through logs/stdout/artifacts."""
    monkeypatch.setattr(probe, "open_and_read_v4_once", AsyncMock(side_effect=error))
    with caplog.at_level("DEBUG"):
        assert probe.main(["--read-v4-state"]) == 1
    output = capsys.readouterr()
    assert json.loads(output.out) == BASE_REPORT | {"state": "error", **expected}
    assert USER_GUID not in output.out + output.err + caplog.text
    assert output.err == ""


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (b"", "eof"),
        (RESPONSE[:7], "invalid_v4_read_response"),
        (RESPONSE + b"PRIVATE", "invalid_v4_read_response"),
    ],
)
def test_real_receive_failures_use_sanitized_error_codes(
    streams, capsys, response, expected
):
    """Exercise the actual framing/EOF error path through the CLI error boundary."""
    streams.reader.read.side_effect = [OPENED, response, b""]
    assert probe.main(["--read-v4-state"]) == 1
    assert json.loads(capsys.readouterr().out) == BASE_REPORT | {
        "state": "error",
        "error": expected,
    }
    streams.writer.close.assert_called_once_with()


@pytest.mark.parametrize(
    "other_mode", ["--tls-only", "--session", "--session-negative"]
)
def test_read_mode_is_explicit_and_mutually_exclusive(streams, capsys, other_mode):
    """No ambiguous invocation can connect or silently add a read to another mode."""
    with pytest.raises(SystemExit) as caught:
        probe.main([other_mode, "--read-v4-state"])
    assert caught.value.code == 2
    capsys.readouterr()
    streams.connect.assert_not_awaited()
