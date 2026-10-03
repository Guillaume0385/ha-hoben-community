"""Manual utility behavior over synthetic streams, never the live service."""

import importlib
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock

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
    "HOBEN_USER_GUID": "SYNTHETIC-USER",
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


def test_session_output_and_allowed_writes(streams, capsys, caplog) -> None:
    """Only one OpenClient/Pong are sent; UNKNOWN and suffix count are safe output."""
    streams.reader.read.return_value = b"\x0a" + OPENED + b"\x0aSYNTHETIC-AUTH-CODE"
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
        b"\x03SYNTHETIC-USER\x00\x01\x22\x00SYNTHETIC-DEVICESynthetic/Maker/Model",
        b"\x0b",
    ]
    for identifier in ("SYNTHETIC", OPENED[14:46].decode()):
        assert identifier not in output.out + output.err + caplog.text
    streams.writer.wait_closed.assert_awaited_once_with()


@pytest.mark.parametrize("missing", ENVIRONMENT)
def test_missing_inputs_do_not_connect(streams, monkeypatch, capsys, missing) -> None:
    """No identifier or build is invented when a required value is absent."""
    monkeypatch.delenv(missing)
    assert probe.main(["--session"]) == 1
    assert json.loads(capsys.readouterr().out)["error"] == "invalid_session_inputs"
    streams.connect.assert_not_awaited()


@pytest.mark.parametrize("build", ["SYNTHETIC-PRIVATE", "-1", "65536"])
def test_invalid_build_is_redacted(streams, monkeypatch, capsys, build) -> None:
    """Invalid integer text and UInt16 bounds fail before opening a socket."""
    monkeypatch.setenv("HOBEN_BUILD", build)
    assert probe.main(["--session"]) == 1
    output = capsys.readouterr()
    assert json.loads(output.out)["error"] == "invalid_session_inputs"
    assert "SYNTHETIC-PRIVATE" not in output.out + output.err
    streams.connect.assert_not_awaited()


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            UnexpectedMessageType(47),
            {"error": "unexpected_message_type", "message_type": 47},
        ),
        (TransportTimeout("read"), {"error": "timeout", "operation": "read"}),
        (SessionTimeout(), {"error": "timeout", "operation": "handshake"}),
        (TransportEOF(), {"error": "eof"}),
        (TransportTlsError(), {"error": "tls_verification_or_negotiation_failed"}),
        (TransportError(), {"error": "transport_failed"}),
        (SessionProtocolError(), {"error": "invalid_opened_client"}),
        (RuntimeError("SYNTHETIC-PRIVATE"), {"error": "probe_failed"}),
        (KeyboardInterrupt(), {"error": "cancelled"}),
    ],
)
def test_failure_reports_are_allowlisted(monkeypatch, capsys, error, expected) -> None:
    """Errors produce structured outcomes rather than exception text/tracebacks."""
    monkeypatch.setattr(probe, "_probe", AsyncMock(side_effect=error))
    assert probe.main(["--session"]) == 1
    output = capsys.readouterr()
    assert json.loads(output.out) == {
        "host": "myhoben.fr",
        "port": 465,
        "state": "error",
        **expected,
    }
    assert output.err == ""


def test_tls_only_connect_error_still_closes(streams, monkeypatch, capsys) -> None:
    """The no-session path owns cleanup even when connection setup fails."""
    close = AsyncMock()
    monkeypatch.setattr(probe.AsyncTlsTransport, "close", close)
    streams.connect.side_effect = OSError("SYNTHETIC-PRIVATE")
    assert probe.main(["--tls-only"]) == 1
    close.assert_awaited_once_with()
    assert json.loads(capsys.readouterr().out)["error"] == "transport_failed"


@pytest.mark.parametrize(
    "args", [[], ["--tls-only", "--session"], ["SYNTHETIC-PRIVATE"]]
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
    assert "HOBEN_BUILD" in result.stdout
