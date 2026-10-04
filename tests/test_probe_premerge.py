"""Fixed authenticated pre-merge suite on synthetic, verified TLS streams only."""

import json
import ssl
from unittest.mock import Mock

import pytest

from scripts import probe_hoben_connection as probe

USER_GUID = "01234567-89AB-CDEF-0123-456789ABCDEF"
OPENED = (
    b"\x04\x00\x00\x00\x00\x00\x00\x00\x05\x02\x08\x00\x00\x00"
    b"ABCDabcdABCDabcdABCDabcdABCDabcd\x00\x02"
)
OPEN_REQUEST = (
    b"\x030123456789abcdef0123456789abcdef\x00\x01\x22\x00"
    b"00000000000000000000000000000000"
    b"ha-hoben-community/GitHubActions/en/Python/Linux/0/0/1/0/0,0"
)
READ_REQUEST = bytes.fromhex("0D FF FF 00 00 00 06 01 04 04 00 00 14")


def response(registers):
    """Independent synthetic function 04 response; no production register fixture."""
    payload = bytes([4, len(registers) * 2]) + b"".join(
        value.to_bytes(2, "big") for value in registers
    )
    return (
        b"\x0e\xff\xff\x00\x00"
        + (len(payload) + 1).to_bytes(2, "big")
        + b"\x01"
        + payload
    )


@pytest.fixture(autouse=True)
def synthetic_environment(monkeypatch):
    """The fixed suite must ignore every exploratory input, even invalid values."""
    monkeypatch.setenv("HOBEN_USER_GUID", USER_GUID)
    for name in ("HOBEN_DEVICE_GUID", "HOBEN_BUILD", "HOBEN_DEVICE_INFO"):
        monkeypatch.setenv(name, "PRIVATE-IGNORED")


@pytest.mark.parametrize("registers", [[0] * 20, [65535] * 20, list(range(20))])
@pytest.mark.parametrize("major", [8, 9])
def test_current_suite_opens_once_reads_once_and_does_not_freeze_values(
    streams, monkeypatch, capsys, caplog, registers, major
):
    """One correlated read passes for changing UInt16 values and software metadata."""

    class OnlyCredentialEnvironment(dict):
        def __getitem__(self, key):
            assert not key.startswith("HOBEN_") or key == "HOBEN_USER_GUID"
            return super().__getitem__(key)

        def get(self, key, default=None):
            assert not key.startswith("HOBEN_"), "No exploratory override reads"
            return super().get(key, default)

    monkeypatch.setattr(
        probe.os, "environ", OnlyCredentialEnvironment(HOBEN_USER_GUID=USER_GUID)
    )
    opened = OPENED[:10] + bytes([major]) + OPENED[11:]
    streams.reader.read.side_effect = [b"\x0a" + opened, b"\x0a" + response(registers)]
    with caplog.at_level("DEBUG"):
        assert probe.main(["--live-premerge"]) == 0
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert report == {
        "host": "myhoben.fr",
        "port": 465,
        "mode": "live-premerge",
        "state": "read",
        "message_type": 4,
        "product_type": 5,
        "product_revision": 0,
        "software_major": major,
        "software_minor": 2,
        "application_version": 512,
        "profile": "v4",
        "unclassified_bytes": 0,
        "function": 4,
        "transaction_id": 65535,
        "unit_id": 1,
        "start_address": 1024,
        "quantity": 20,
        "register_count": 20,
    }
    assert [c.args[0] for c in streams.writer.write.call_args_list] == [
        OPEN_REQUEST,
        b"\x0b",
        READ_REQUEST,
        b"\x0b",
    ]
    streams.connect.assert_awaited_once()
    kwargs = streams.connect.call_args.kwargs
    assert streams.connect.call_args.args == ("myhoben.fr", 465)
    assert kwargs["server_hostname"] == "myhoben.fr"
    assert kwargs["ssl"].verify_mode == ssl.CERT_REQUIRED
    assert kwargs["ssl"].check_hostname is True
    streams.writer.wait_closed.assert_awaited_once_with()
    for sensitive in (
        USER_GUID,
        USER_GUID.replace("-", "").lower(),
        OPENED[14:46].decode(),
        "PRIVATE",
    ):
        assert sensitive not in output.out + output.err + caplog.text


@pytest.mark.parametrize(
    "opening",
    [
        b"\x2fPRIVATE",
        b"\x05\x02PRIVATE",
        OPENED + b"PRIVATE",
        OPENED[:8] + b"\x02" + OPENED[9:],
    ],
)
def test_unsuccessful_or_unsupported_session_never_reads(streams, capsys, opening):
    streams.reader.read.side_effect = [opening, response([0] * 20)]
    assert probe.main(["--live-premerge"]) == 1
    output = capsys.readouterr()
    assert "register_count" not in json.loads(output.out)
    assert "PRIVATE" not in output.out + output.err
    streams.writer.write.assert_called_once_with(OPEN_REQUEST)
    streams.writer.wait_closed.assert_awaited_once_with()


@pytest.mark.parametrize(
    "reply",
    [
        response([0] * 19),
        response([0] * 21),
        b"\x0e\xff\xf0" + response([0] * 20)[3:],
        response([0] * 20)[:7] + b"\x02" + response([0] * 20)[8:],
        *[
            response([0] * 20)[:8] + bytes([function]) + response([0] * 20)[9:]
            for function in (3, 6, 16, 22)
        ],
        bytes.fromhex("0E FF FF 00 00 00 03 01 84 02"),
        response([0] * 20) + b"PRIVATE",
        b"",
    ],
)
def test_mismatch_or_exception_fails_with_only_the_allowed_request(
    streams, capsys, reply
):
    """Wrong count, function, transaction or unit cannot produce a passed gate."""
    streams.reader.read.side_effect = [OPENED, reply]
    assert probe.main(["--live-premerge"]) == 1
    output = capsys.readouterr()
    assert json.loads(output.out)["state"] != "read"
    assert "PRIVATE" not in output.out + output.err
    assert [c.args[0] for c in streams.writer.write.call_args_list] == [
        OPEN_REQUEST,
        READ_REQUEST,
    ]
    # Byte-exact emission also excludes pairing, function 06/16/22 and FFF0.
    streams.writer.wait_closed.assert_awaited_once_with()


@pytest.mark.parametrize("user_guid", [None, "", "PRIVATE-INVALID"])
def test_bad_credential_fails_before_transport_creation(
    streams, monkeypatch, capsys, user_guid
):
    if user_guid is None:
        monkeypatch.delenv("HOBEN_USER_GUID")
    else:
        monkeypatch.setenv("HOBEN_USER_GUID", user_guid)
    transport = Mock(side_effect=AssertionError("Preflight required"))
    monkeypatch.setattr(probe, "AsyncTlsTransport", transport)
    assert probe.main(["--live-premerge"]) == 1
    assert json.loads(capsys.readouterr().out)["error"] == "invalid_session_inputs"
    transport.assert_not_called()
    streams.connect.assert_not_awaited()


@pytest.mark.parametrize(
    "error", [RuntimeError("PRIVATE"), ssl.SSLError("PRIVATE"), TimeoutError("PRIVATE")]
)
def test_live_failure_never_exports_arbitrary_exception_text(
    streams, capsys, caplog, error
):
    streams.connect.side_effect = error
    with caplog.at_level("DEBUG"):
        assert probe.main(["--live-premerge"]) == 1
    output = capsys.readouterr()
    assert "PRIVATE" not in output.out + output.err + caplog.text
    assert json.loads(output.out)["state"] == "error"


@pytest.mark.parametrize(
    "args",
    [
        ["--live-premerge", "--host", "PRIVATE"],
        ["--live-premerge", "--register", "2304"],
        ["--live-premerge", "--function", "6"],
        ["--live-pre"],
        *[
            ["--live-premerge", mode]
            for mode in (
                "--tls-only",
                "--session",
                "--session-negative",
                "--read-v4-state",
            )
        ],
    ],
)
def test_suite_has_one_explicit_fixed_cli_and_no_freeform_arguments(
    streams, capsys, args
):
    with pytest.raises(SystemExit) as caught:
        probe.main(args)
    assert caught.value.code == 2
    output = capsys.readouterr()
    assert "PRIVATE" not in output.out + output.err
    streams.connect.assert_not_awaited()
