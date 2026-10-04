"""Synthetic negative session observations over fake TLS streams only."""

import json
import ssl
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.hoben.session import SessionTimeout
from scripts import probe_hoben_connection as probe

# Independently written request: two 32-byte ASCII-zero test identifiers.
REQUEST = (
    b"\x0300000000000000000000000000000000\x00\x01\x22\x00"
    b"00000000000000000000000000000000"
    b"ha-hoben-community/GitHubActions/en/Python/Linux/0/0/1/0/0,0"
)
OPENED = (
    b"\x04\x00\x00\x00\x00\x00\x00\x01\x03\x06\x00\x00\x00\x00"
    b"ABCDabcdABCDabcdABCDabcdABCDabcd\x22\x00"
)


@pytest.mark.parametrize("with_environment", [False, True])
def test_negative_uses_only_fixed_inputs(
    streams, monkeypatch, capsys, caplog, with_environment
) -> None:
    """No user inputs/default resolver, one OpenClient and only necessary Pong."""
    for name in (
        "HOBEN_USER_GUID",
        "HOBEN_DEVICE_GUID",
        "HOBEN_BUILD",
        "HOBEN_DEVICE_INFO",
    ):
        if with_environment:
            monkeypatch.setenv(name, "PRIVATE-SHOULD-NOT-BE-READ")
        else:
            monkeypatch.delenv(name, raising=False)
    resolver = Mock(side_effect=AssertionError("Negative mode has no real GUID source"))
    monkeypatch.setattr(probe, "_resolve_user_guid", resolver)
    open_once = AsyncMock(wraps=probe.open_session_once)
    monkeypatch.setattr(probe, "open_session_once", open_once)
    streams.reader.read.return_value = b"\x0a" + OPENED + b"PRIVATE-AUTH"
    with caplog.at_level("DEBUG"):
        assert probe.main(["--session-negative"]) == 0
    output = capsys.readouterr()
    assert json.loads(output.out) == {
        "host": "myhoben.fr",
        "port": 465,
        "mode": "session-negative",
        "state": "opened",
        "observation": "informative",
        "message_type": 4,
        "product_revision": 1,
        "product_type": 3,
        "software_minor": 6,
        "software_major": 0,
        "application_version": 34,
        "profile": "unknown",
        "unclassified_bytes": 12,
    }
    open_once.assert_awaited_once()
    assert open_once.call_args.kwargs == {
        "user_guid": "00000000000000000000000000000000",
        "device_guid": "00000000000000000000000000000000",
        "build": 34,
        "device_info": "ha-hoben-community/GitHubActions/en/Python/Linux/0/0/1/0/0,0",
    }
    assert [args.args[0] for args in streams.writer.write.call_args_list] == [
        REQUEST,
        b"\x0b",
    ]
    resolver.assert_not_called()
    streams.connect.assert_awaited_once()
    streams.writer.wait_closed.assert_awaited_once_with()
    public = output.out + output.err + caplog.text
    for sensitive in ("PRIVATE", "0" * 32, OPENED[14:46].decode()):
        assert sensitive not in public


@pytest.mark.parametrize("message_type", [0, 47, 255, None])
def test_negative_classifies_reply_or_eof_without_interpretation(
    streams, capsys, caplog, message_type
) -> None:
    """A first-byte observation/explicit EOF is informative, never authentication."""
    streams.reader.read.return_value = (
        b""
        if message_type is None
        else bytes([message_type]) + b"PRIVATE-AUTH-AND-GUID"
    )
    with caplog.at_level("DEBUG"):
        assert probe.main(["--session-negative"]) == 0
    output = capsys.readouterr()
    observation = (
        {"error": "eof"}
        if message_type is None
        else {"error": "unexpected_message_type", "message_type": message_type}
    )
    assert json.loads(output.out) == {
        "host": "myhoben.fr",
        "port": 465,
        "mode": "session-negative",
        "state": "error",
        "observation": "informative",
        **observation,
    }
    streams.connect.assert_awaited_once()
    streams.writer.write.assert_called_once_with(REQUEST)
    streams.reader.read.assert_awaited_once()
    streams.writer.wait_closed.assert_awaited_once_with()
    assert "PRIVATE" not in output.out + output.err + caplog.text
    assert "0" * 32 not in output.out + output.err + caplog.text


@pytest.mark.parametrize(
    ("operation", "error", "expected"),
    [
        (
            "connect",
            ssl.SSLError("PRIVATE"),
            {"error": "tls_verification_or_negotiation_failed"},
        ),
        ("connect", OSError("PRIVATE"), {"error": "transport_failed"}),
        (
            "connect",
            TimeoutError("PRIVATE"),
            {"error": "timeout", "operation": "connect"},
        ),
        ("write", TimeoutError("PRIVATE"), {"error": "timeout", "operation": "write"}),
        ("read", TimeoutError("PRIVATE"), {"error": "timeout", "operation": "read"}),
        ("read", OSError("PRIVATE"), {"error": "transport_failed"}),
        ("close", OSError("PRIVATE"), {"error": "transport_failed"}),
    ],
)
def test_negative_transport_failure_is_inconclusive(
    streams, capsys, caplog, operation, error, expected
) -> None:
    """No timeout/TLS/transport failure is relabeled as a useful server reaction."""
    streams.reader.read.return_value = OPENED
    target = {
        "connect": streams.connect,
        "write": streams.writer.drain,
        "read": streams.reader.read,
        "close": streams.writer.wait_closed,
    }[operation]
    target.side_effect = error
    with caplog.at_level("DEBUG"):
        assert probe.main(["--session-negative"]) == 1
    output = capsys.readouterr()
    assert json.loads(output.out) == {
        "host": "myhoben.fr",
        "port": 465,
        "mode": "session-negative",
        "state": "error",
        "observation": "inconclusive",
        **expected,
    }
    assert "PRIVATE" not in output.out + output.err + caplog.text
    if operation == "connect":
        streams.writer.write.assert_not_called()
    else:
        streams.writer.write.assert_called_once_with(REQUEST)
        streams.writer.close.assert_called_once_with()


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (SessionTimeout("PRIVATE"), {"error": "timeout", "operation": "handshake"}),
        (RuntimeError("PRIVATE"), {"error": "probe_failed"}),
    ],
)
def test_negative_other_failures_are_redacted(
    monkeypatch, capsys, error, expected
) -> None:
    """The shared error boundary also covers the negative-mode coroutine."""
    monkeypatch.setattr(probe, "_probe_negative", AsyncMock(side_effect=error))
    assert probe.main(["--session-negative"]) == 1
    output = capsys.readouterr()
    assert json.loads(output.out) == {
        "host": "myhoben.fr",
        "port": 465,
        "mode": "session-negative",
        "state": "error",
        "observation": "inconclusive",
        **expected,
    }
    assert output.err == ""


def test_negative_does_not_unlock_real_session(streams, monkeypatch, capsys) -> None:
    """Synthetic identifiers remain exclusive to the explicit negative mode."""
    for name in ("HOBEN_BUILD", "HOBEN_DEVICE_INFO"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOBEN_DEVICE_GUID", "PRIVATE-DEVICE")
    monkeypatch.setenv("HOBEN_USER_GUID", "0" * 32)
    assert probe.main(["--session-negative"]) == 0  # Synthetic EOF observation.
    capsys.readouterr()
    streams.connect.reset_mock()
    streams.writer.write.reset_mock()
    assert probe.main(["--session"]) == 3
    assert json.loads(capsys.readouterr().out) == {
        "host": "myhoben.fr",
        "port": 465,
        "state": "blocked",
        "error": "user_guid_unresolved",
    }
    streams.connect.assert_not_awaited()
    streams.writer.write.assert_not_called()
