"""Manual utility behavior over synthetic streams, never the live service."""

import importlib
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.hoben.session import (
    SessionProtocolError,
    SessionTimeout,
    UnexpectedMessageType,
)
from custom_components.hoben.transport import (
    TransportEOF,
    TransportError,
    TransportTimeout,
    TransportTlsError,
)
from scripts import probe_hoben_connection as probe

ENVIRONMENT = {
    "HOBEN_USER_GUID": "01234567-89AB-CDEF-0123-456789ABCDEF",
    "HOBEN_DEVICE_GUID": "SYNTHETIC-DEVICE",
    "HOBEN_DEVICE_INFO": "Synthetic/Maker/Model",
    "HOBEN_BUILD": "34",
}
OPENED = (
    b"\x04\x00\x00\x00\x00\x00\x00\x01\x03\x06\x00\x00\x00\x00"
    b"ABCDabcdABCDabcdABCDabcdABCDabcd\x22\x00"
)


@pytest.fixture(autouse=True)
def synthetic_environment(monkeypatch):
    """Session tests never read any real identifiers from the host environment."""
    for name, value in ENVIRONMENT.items():
        monkeypatch.setenv(name, value)


def test_tls_only_needs_no_inputs_or_writes(streams, monkeypatch, capsys) -> None:
    """TLS-only mode verifies the connection and closes without an OpenClient."""
    for name in ENVIRONMENT:
        monkeypatch.delenv(name)
    assert probe.main(["--tls-only"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "host": "myhoben.fr",
        "port": 465,
        "state": "tls_connected",
    }
    streams.writer.write.assert_not_called()
    streams.reader.read.assert_not_awaited()
    streams.writer.close.assert_called_once_with()
    streams.writer.wait_closed.assert_awaited_once_with()


def test_session_output_and_allowed_writes(
    streams, monkeypatch, capsys, caplog
) -> None:
    """Only one OpenClient/Pong are sent; UNKNOWN and suffix count are safe output."""
    streams.reader.read.return_value = b"\x0a" + OPENED + b"\x0aSYNTHETIC-AUTH-CODE"
    open_once = AsyncMock(wraps=probe.open_session_once)
    monkeypatch.setattr(probe, "open_session_once", open_once)
    with caplog.at_level("DEBUG"):
        assert probe.main(["--session"]) == 0
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert report == {
        "host": "myhoben.fr",
        "port": 465,
        "state": "opened",
        "message_type": 4,
        "product_revision": 1,
        "product_type": 3,
        "software_major": 0,
        "software_minor": 6,
        "application_version": 34,
        "profile": "unknown",
        "unclassified_bytes": 20,
    }
    assert [args.args[0] for args in streams.writer.write.call_args_list] == [
        b"\x030123456789abcdef0123456789abcdef\x00\x01\x22\x00"
        b"00000000000000000000000000000000Synthetic/Maker/Model",
        b"\x0b",
    ]
    open_once.assert_awaited_once()
    for identifier in (
        "SYNTHETIC",
        ENVIRONMENT["HOBEN_USER_GUID"],
        "0123456789abcdef0123456789abcdef",
        OPENED[14:46].decode(),
    ):
        assert identifier not in output.out + output.err + caplog.text
    streams.writer.wait_closed.assert_awaited_once_with()


@pytest.mark.parametrize(
    "user_guid",
    [
        None,
        "",
        " \t\n",
        "SYNTHETIC-USER",
        "a" * 31,
        "a" * 33,
        "g" * 32,
        "０" * 32,
        "a" * 32 + "\n",
        "012345678-9ab-cdef-0123-456789abcdef",
    ],
)
def test_invalid_user_guid_rejected_before_transport(
    streams, monkeypatch, capsys, caplog, user_guid
) -> None:
    """Invalid/missing Identifiant HOBEN fails before transport construction."""
    if user_guid is None:
        monkeypatch.delenv("HOBEN_USER_GUID")
    else:
        monkeypatch.setenv("HOBEN_USER_GUID", user_guid)
    monkeypatch.delenv("HOBEN_BUILD")
    monkeypatch.delenv("HOBEN_DEVICE_INFO")
    transport = Mock(side_effect=AssertionError("Preflight must run first"))
    open_once = AsyncMock(side_effect=AssertionError("No session with invalid input"))
    monkeypatch.setattr(probe, "AsyncTlsTransport", transport)
    monkeypatch.setattr(probe, "open_session_once", open_once)
    with caplog.at_level("DEBUG"):
        assert probe.main(["--session"]) == 1
    output = capsys.readouterr()
    assert json.loads(output.out) == {
        "host": "myhoben.fr",
        "port": 465,
        "state": "error",
        "error": "invalid_session_inputs",
    }
    assert output.err == ""
    assert "SYNTHETIC" not in output.out + output.err + caplog.text
    if user_guid:
        assert user_guid not in output.out + output.err + caplog.text
    transport.assert_not_called()
    open_once.assert_not_awaited()
    streams.connect.assert_not_awaited()
    streams.writer.write.assert_not_called()


@pytest.mark.parametrize(
    "user_guid",
    [
        "01234567-89AB-CDEF-0123-456789ABCDEF",
        "0123456789abcdef0123456789abcdef",
    ],
)
@pytest.mark.parametrize("legacy_device_guid", [None, "PRIVATE-IGNORED"])
def test_session_defaults_use_existing_one_shot_path(
    streams, monkeypatch, capsys, caplog, user_guid, legacy_device_guid
) -> None:
    """Normalize the sole secret; never read a legacy DeviceGuid, even if set."""

    class EnvironmentWithoutDeviceGuidReads(dict):
        def __getitem__(self, key):
            assert key != "HOBEN_DEVICE_GUID"
            return super().__getitem__(key)

        def get(self, key, default=None):
            assert key != "HOBEN_DEVICE_GUID"
            return super().get(key, default)

    environment = EnvironmentWithoutDeviceGuidReads(HOBEN_USER_GUID=user_guid)
    if legacy_device_guid is not None:
        environment["HOBEN_DEVICE_GUID"] = legacy_device_guid
    monkeypatch.setattr(probe.os, "environ", environment)
    open_once = AsyncMock(wraps=probe.open_session_once)
    monkeypatch.setattr(probe, "open_session_once", open_once)
    streams.reader.read.return_value = OPENED
    with caplog.at_level("DEBUG"):
        assert probe.main(["--session"]) == 0
    output = capsys.readouterr()
    assert json.loads(output.out)["state"] == "opened"
    open_once.assert_awaited_once()
    assert open_once.call_args.kwargs == {
        "user_guid": "0123456789abcdef0123456789abcdef",
        "device_guid": "00000000000000000000000000000000",
        "build": 34,
        "device_info": "ha-hoben-community/GitHubActions/en/Python/Linux/0/0/1/0/0,0",
    }
    streams.writer.write.assert_called_once_with(
        b"\x030123456789abcdef0123456789abcdef\x00\x01\x22\x00"
        b"00000000000000000000000000000000"
        b"ha-hoben-community/GitHubActions/en/Python/Linux/0/0/1/0/0,0"
    )
    streams.writer.wait_closed.assert_awaited_once_with()
    for sensitive in (user_guid, "0123456789abcdef0123456789abcdef", "PRIVATE"):
        assert sensitive not in output.out + output.err + caplog.text


def test_session_overrides_preserve_caller_values(streams, monkeypatch, capsys) -> None:
    """Explicit non-secret build/descriptor overrides keep the existing interface."""
    monkeypatch.setenv("HOBEN_BUILD", "4660")
    monkeypatch.setenv("HOBEN_DEVICE_GUID", " SYNTHETIC-DEVICE ")
    streams.reader.read.return_value = OPENED
    assert probe.main(["--session"]) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "opened"
    streams.writer.write.assert_called_once_with(
        b"\x030123456789abcdef0123456789abcdef\x00\x01\x34\x12"
        b"00000000000000000000000000000000Synthetic/Maker/Model"
    )


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("HOBEN_BUILD", "SYNTHETIC-PRIVATE"),
        ("HOBEN_BUILD", "-1"),
        ("HOBEN_BUILD", "65536"),
        ("HOBEN_DEVICE_INFO", ""),
        ("HOBEN_DEVICE_INFO", " \t\n"),
    ],
)
def test_invalid_overrides_are_redacted(
    streams, monkeypatch, capsys, name, value
) -> None:
    """Invalid build or empty descriptor fails before transport construction."""
    monkeypatch.setenv(name, value)
    transport = Mock(side_effect=AssertionError("Preflight must run first"))
    monkeypatch.setattr(probe, "AsyncTlsTransport", transport)
    assert probe.main(["--session"]) == 1
    output = capsys.readouterr()
    assert json.loads(output.out)["error"] == "invalid_session_inputs"
    assert "SYNTHETIC-PRIVATE" not in output.out + output.err
    transport.assert_not_called()
    streams.connect.assert_not_awaited()
    streams.writer.write.assert_not_called()


@pytest.mark.parametrize("message_type", [0, 255])
def test_unexpected_message_payload_never_reaches_output(
    streams, capsys, caplog, message_type
) -> None:
    """Unknown response decoding stops at the numeric type, hiding all payloads."""
    streams.reader.read.return_value = bytes([message_type]) + b"SYNTHETIC-AUTH-CODE"
    with caplog.at_level("DEBUG"):
        assert probe.main(["--session"]) == 1
    output = capsys.readouterr()
    assert json.loads(output.out) == {
        "host": "myhoben.fr",
        "port": 465,
        "state": "error",
        "error": "unexpected_message_type",
        "message_type": message_type,
    }
    assert "SYNTHETIC" not in output.out + output.err + caplog.text
    streams.writer.write.assert_called_once()
    streams.writer.wait_closed.assert_awaited_once_with()


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            UnexpectedMessageType(255),
            {"error": "unexpected_message_type", "message_type": 255},
        ),
        (TransportTimeout("read"), {"error": "timeout", "operation": "read"}),
        (
            SessionTimeout(ENVIRONMENT["HOBEN_USER_GUID"]),
            {"error": "timeout", "operation": "handshake"},
        ),
        (TransportEOF(ENVIRONMENT["HOBEN_USER_GUID"]), {"error": "eof"}),
        (
            TransportTlsError(ENVIRONMENT["HOBEN_USER_GUID"]),
            {"error": "tls_verification_or_negotiation_failed"},
        ),
        (TransportError(ENVIRONMENT["HOBEN_USER_GUID"]), {"error": "transport_failed"}),
        (
            SessionProtocolError(ENVIRONMENT["HOBEN_USER_GUID"]),
            {"error": "invalid_opened_client"},
        ),
        (RuntimeError("SYNTHETIC-PRIVATE"), {"error": "probe_failed"}),
        (KeyboardInterrupt(), {"error": "cancelled"}),
    ],
)
def test_failure_reports_are_allowlisted(
    monkeypatch, capsys, caplog, error, expected
) -> None:
    """Errors produce structured outcomes rather than exception text/tracebacks."""
    monkeypatch.setattr(probe, "_probe", AsyncMock(side_effect=error))
    with caplog.at_level("DEBUG"):
        assert probe.main(["--session"]) == 1
    output = capsys.readouterr()
    assert json.loads(output.out) == {
        "host": "myhoben.fr",
        "port": 465,
        "state": "error",
        **expected,
    }
    assert output.err == ""
    assert ENVIRONMENT["HOBEN_USER_GUID"] not in output.out + output.err + caplog.text


@pytest.mark.parametrize("mode", ["--session", "--session-negative"])
@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (b"\x2f", {"state": "authorization_required", "message_type": 47}),
        (
            b"\x05\x02",
            {"state": "closed", "message_type": 5, "reason": "invalid_identifier"},
        ),
        (
            b"\x05\x03",
            {
                "state": "closed",
                "message_type": 5,
                "reason": "stove_connection_required",
            },
        ),
        (
            b"\x05\x04",
            {"state": "closed", "message_type": 5, "reason": "authorization_rejected"},
        ),
        (
            b"\x05\x05",
            {"state": "closed", "message_type": 5, "reason": "authorization_timeout"},
        ),
        (
            b"\x05\x06",
            {"state": "closed", "message_type": 5, "reason": "server_maintenance"},
        ),
        (b"\x05\xff", {"state": "closed", "message_type": 5, "reason": "unknown"}),
    ],
)
def test_known_response_is_a_safe_observation(
    streams, capsys, caplog, mode, response, expected
) -> None:
    """Both modes report documented outcomes without assuming authentication."""
    streams.reader.read.side_effect = [
        response + b"\x0aPRIVATE-AUTH-GUID" + ENVIRONMENT["HOBEN_USER_GUID"].encode(),
        OPENED,
    ]
    with caplog.at_level("DEBUG"):
        assert probe.main([mode]) == 0
    output = capsys.readouterr()
    report = {"host": "myhoben.fr", "port": 465, **expected}
    if mode == "--session-negative":
        report.update(mode="session-negative", observation="informative")
    assert json.loads(output.out) == report
    streams.writer.write.assert_called_once()  # OpenClient only, never DeviceAuthRes.
    assert streams.writer.write.call_args.args[0][0] == 3
    streams.reader.read.assert_awaited_once()
    streams.writer.wait_closed.assert_awaited_once_with()
    for sensitive in (
        "PRIVATE",
        ENVIRONMENT["HOBEN_USER_GUID"],
        "0123456789abcdef0123456789abcdef",
    ):
        assert sensitive not in output.out + output.err + caplog.text


def test_tls_only_connect_error_still_closes(streams, monkeypatch, capsys) -> None:
    """The no-session path owns cleanup even when connection setup fails."""
    close = AsyncMock()
    monkeypatch.setattr(probe.AsyncTlsTransport, "close", close)
    streams.connect.side_effect = OSError("SYNTHETIC-PRIVATE")
    assert probe.main(["--tls-only"]) == 1
    close.assert_awaited_once_with()
    assert json.loads(capsys.readouterr().out)["error"] == "transport_failed"


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--tls-only", "--session"],
        ["--tls-only", "--session-negative"],
        ["--session", "--session-negative"],
        ["SYNTHETIC-PRIVATE"],
    ],
)
def test_explicit_mode_required_and_arguments_not_echoed(streams, capsys, args) -> None:
    """Import, accidental invocation and bad arguments cannot open a connection."""
    with pytest.raises(SystemExit) as caught:
        probe.main(args)
    assert caught.value.code == 2
    output = capsys.readouterr()
    assert "SYNTHETIC-PRIVATE" not in output.out + output.err
    streams.connect.assert_not_awaited()


def test_import_has_no_side_effect(streams, capsys) -> None:
    """The main guard keeps normal imports and HA startup inert."""
    importlib.reload(probe)
    streams.connect.assert_not_awaited()
    assert capsys.readouterr().out == ""


def test_direct_script_help_from_outside_checkout(tmp_path) -> None:
    """The documented script entry point works without PYTHONPATH or HA installed."""
    script = Path(probe.__file__).resolve()
    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert "--tls-only" in result.stdout
    assert "--session-negative" in result.stdout
    assert "HOBEN_BUILD" in result.stdout
