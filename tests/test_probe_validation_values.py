"""Manual private V4 capture on synthetic TLS streams; never a live appliance."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.hoben.client import RawStoveSnapshot
from custom_components.hoben.profiles import StoveProfile
from scripts import probe_hoben_connection as probe

# Invented identities and household values; no production capture is used.
USER_GUID = "01234567-89AB-CDEF-0123-456789ABCDEF"
NORMALIZED_USER_GUID = "0123456789abcdef0123456789abcdef"
DEVICE_GUID = "B" * 32
OPENED = (
    b"\x04\x00\x00\x00\x00\x00\x00\x00\x05\x02\x08\x00\x00\x00"
    + DEVICE_GUID.encode()
    + b"\x00\x02"
)
OPEN_REQUEST = (
    b"\x03"
    + NORMALIZED_USER_GUID.encode()
    + b"\x00\x01\x22\x00"
    + b"0" * 32
    + b"ha-hoben-community/GitHubActions/en/Python/Linux/0/0/1/0/0,0"
)
READ_REQUEST = bytes.fromhex("0D FF FF 00 00 00 06 01 04 04 00 00 14")
WORDS = (
    0x0201,
    211,
    37,
    181,
    2,
    360,
    0x4305,
    213,
    201,
    0x1234,
    0x8000,
    0x0060,
    0x260A,
    0x010C,
    0x2238,
    219,
    278,
    1103,
    17,
    224,
)
TIMESTAMP = "2026-10-05T12:34:56Z"
MODE = "--live-v4-validation-values"
EXPECTED = {
    "ambient_temperature": (1031, 213, 21.3),
    "target_temperature": (1032, 201, 20.1),
    "power_level": (1030, 67, 67),
    "operation_state": (1030, 5, "combustion_management"),
    "operation_mode": (1024, 2, "manual"),
    "ventilation_mode": (1028, 2, "boost"),
    "smoke_temperature": (1041, 1103, 110.3),
    "combustion_air_temperature": (1040, 278, 27.8),
    "wired_ambient_temperature": (1039, 219, 21.9),
    "rf_ambient_temperature": (1043, 224, 22.4),
    "derogation_temperature": (1025, 211, 21.1),
    "derogation_start_delay": (1026, 37, 37),
    "derogation_duration": (1027, 181, 181),
    "derogation_active": (1035, 1, True),
    "derogation_scheduled": (1035, 1, True),
    "controller_on_off": (1024, 1, True),
}


def response(words):
    """Independent correlated function-04 frame with a 40-byte register payload."""
    return bytes.fromhex("0E FF FF 00 00 00 2B 01 04 28") + b"".join(
        value.to_bytes(2, "big") for value in words
    )


@pytest.fixture(autouse=True)
def manual_environment(monkeypatch):
    """Simulate a local run even when the deterministic tests themselves run in CI."""
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setenv("HOBEN_USER_GUID", USER_GUID)
    for name in ("HOBEN_DEVICE_GUID", "HOBEN_BUILD", "HOBEN_DEVICE_INFO"):
        monkeypatch.setenv(name, "PRIVATE-IGNORED")
    monkeypatch.setattr(
        probe,
        "datetime",
        Mock(now=Mock(return_value=datetime(2026, 10, 5, 12, 34, 56, tzinfo=UTC))),
    )


def capture(streams, capsys, words=WORDS):
    """Run the actual CLI/client/decoder, replacing only the TLS connection."""
    streams.reader.read.side_effect = [OPENED, response(words)]
    assert probe.main([MODE]) == 0
    output = capsys.readouterr()
    assert len(output.out.splitlines()) == 1
    assert output.err == ""
    for value in (USER_GUID, NORMALIZED_USER_GUID, DEVICE_GUID, "PRIVATE", "Traceback"):
        assert value not in output.out + output.err
    return json.loads(output.out)


def test_complete_addressed_report_one_client_refresh_and_only_read_frames(
    streams, monkeypatch, capsys, caplog
):
    client_factory = Mock(wraps=probe.HobenClient)
    monkeypatch.setattr(probe, "HobenClient", client_factory)
    legacy = Mock(side_effect=AssertionError("Private capture must use HobenClient"))
    monkeypatch.setattr(probe, "open_and_read_v4_once", legacy)
    monkeypatch.setattr(probe, "open_session_once", legacy)
    with caplog.at_level("DEBUG"):
        report = capture(streams, capsys)
    assert set(report) == {
        "host",
        "port",
        "mode",
        "state",
        "timestamp_utc",
        "profile",
        "registers",
        "entities",
    }
    assert report["state"] == "v4_validation_values_captured"
    assert report["mode"] == "live-v4-validation-values"
    assert report["timestamp_utc"] == TIMESTAMP
    probe.datetime.now.assert_called_once_with(UTC)
    assert report["profile"] == "v4"
    assert report["registers"] == dict(
        zip(map(str, range(1024, 1044)), WORDS, strict=True)
    )
    assert len(report["registers"]) == 20
    assert set(report["entities"]) == set(EXPECTED)
    for key, (address, raw, decoded) in EXPECTED.items():
        expected = {
            "register_address": address,
            "raw_value": raw,
            "decoded_value": decoded,
            "ha_value": decoded,
        }
        if key == "derogation_active":
            expected["bit_mask"] = 0x20
        elif key == "derogation_scheduled":
            expected["bit_mask"] = 0x40
        assert report["entities"][key] == expected
    client_factory.assert_called_once_with(
        user_guid=NORMALIZED_USER_GUID, max_attempts=1
    )
    legacy.assert_not_called()
    assert [call.args[0] for call in streams.writer.write.call_args_list] == [
        OPEN_REQUEST,
        READ_REQUEST,
    ]
    streams.connect.assert_awaited_once()
    streams.writer.wait_closed.assert_awaited_once_with()
    for value in (USER_GUID, NORMALIZED_USER_GUID, DEVICE_GUID, "PRIVATE"):
        assert value not in caplog.text


@pytest.mark.parametrize("information", [0, 0x20, 0x40, 0x60, 0xFF9F])
def test_derogation_model_values_retained_and_ha_effective_values_masked(
    streams, capsys, information
):
    words = list(WORDS)
    words[1035 - 1024] = information
    report = capture(streams, capsys, words)
    entities = report["entities"]
    for key, raw, decoded in (
        ("derogation_temperature", 211, 21.1),
        ("derogation_start_delay", 37, 37),
        ("derogation_duration", 181, 181),
    ):
        assert entities[key]["raw_value"] == raw
        assert entities[key]["decoded_value"] == decoded
        assert entities[key]["ha_value"] == (decoded if information & 0x60 else None)
    assert entities["derogation_active"]["decoded_value"] is bool(information & 0x20)
    assert entities["derogation_scheduled"]["decoded_value"] is bool(information & 0x40)
    assert report["registers"]["1035"] == information


@pytest.mark.parametrize(
    ("address", "word", "key", "raw"),
    [
        (1024, 0xFF01, "operation_mode", 255),
        (1024, 0x02FF, "controller_on_off", 255),
        (1028, 65535, "ventilation_mode", 65535),
        (1030, 0x43FF, "operation_state", 255),
        (1030, 0xFF05, "power_level", 255),
    ],
)
def test_unknown_codes_remain_null_with_raw_code_and_full_word(
    streams, capsys, address, word, key, raw
):
    words = list(WORDS)
    words[address - 1024] = word
    report = capture(streams, capsys, words)
    assert report["registers"][str(address)] == word
    assert report["entities"][key] == {
        "register_address": address,
        "raw_value": raw,
        "decoded_value": None,
        "ha_value": None,
    }


@pytest.mark.parametrize(
    ("address", "word", "key", "expected"),
    [
        (1031, 0x0FFF, "ambient_temperature", None),
        (1032, 49, "target_temperature", None),
        (1039, 0xFFFF, "wired_ambient_temperature", -0.1),
        (1043, 65536 - 123, "rf_ambient_temperature", -12.3),
    ],
)
def test_temperature_conversion_sentinel_and_target_mask(
    streams, capsys, address, word, key, expected
):
    words = list(WORDS)
    words[address - 1024] = word
    entity = capture(streams, capsys, words)["entities"][key]
    assert entity["raw_value"] == word
    assert entity["decoded_value"] == entity["ha_value"] == expected


@pytest.mark.parametrize("marker", ["true", "TRUE", " true "])
def test_actions_guard_precedes_identity_lookup_client_and_transport(
    streams, monkeypatch, capsys, marker
):
    class GuardEnvironment(dict):
        def __getitem__(self, key):
            if key.startswith("HOBEN_"):
                raise AssertionError("No credential read in GitHub Actions")
            return super().__getitem__(key)

    monkeypatch.setattr(probe.os, "environ", GuardEnvironment(GITHUB_ACTIONS=marker))
    client = Mock(side_effect=AssertionError("No client construction in Actions"))
    transport = Mock(side_effect=AssertionError("No transport construction in Actions"))
    monkeypatch.setattr(probe, "HobenClient", client)
    monkeypatch.setattr(probe, "AsyncTlsTransport", transport)
    monkeypatch.setattr("custom_components.hoben.client.AsyncTlsTransport", transport)
    assert probe.main([MODE]) == 1
    output = capsys.readouterr()
    assert json.loads(output.out) == {
        "host": "myhoben.fr",
        "port": 465,
        "mode": "live-v4-validation-values",
        "state": "error",
        "error": "private_capture_forbidden_in_github_actions",
    }
    assert len(output.out.splitlines()) == 1
    assert output.err == ""
    client.assert_not_called()
    transport.assert_not_called()
    streams.connect.assert_not_awaited()


@pytest.mark.parametrize("user_guid", [None, "", "PRIVATE-INVALID"])
def test_invalid_credential_refused_before_client_or_transport(
    streams, monkeypatch, capsys, user_guid
):
    if user_guid is None:
        monkeypatch.delenv("HOBEN_USER_GUID")
    else:
        monkeypatch.setenv("HOBEN_USER_GUID", user_guid)
    client = Mock(side_effect=AssertionError("Preflight must finish first"))
    monkeypatch.setattr(probe, "HobenClient", client)
    assert probe.main([MODE]) == 1
    output = capsys.readouterr()
    assert json.loads(output.out)["error"] == "invalid_session_inputs"
    assert "PRIVATE" not in output.out + output.err
    client.assert_not_called()
    streams.connect.assert_not_awaited()


@pytest.mark.parametrize("opening", [b"\x2fPRIVATE", b"\x05\x02PRIVATE"])
def test_authorization_rejection_closes_without_read_pairing_or_values(
    streams, capsys, opening
):
    streams.reader.read.return_value = opening
    assert probe.main([MODE]) == 1
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert report["state"] == "error"
    assert "entities" not in report and "registers" not in report
    assert "PRIVATE" not in output.out + output.err
    streams.writer.write.assert_called_once_with(OPEN_REQUEST)
    streams.writer.wait_closed.assert_awaited_once_with()


@pytest.mark.parametrize("failure", ["decoder", "close", "cancel"])
def test_failure_has_one_sanitized_json_no_partial_household_values_or_traceback(
    streams, monkeypatch, capsys, caplog, failure
):
    streams.reader.read.side_effect = [OPENED, response(WORDS)]
    if failure == "decoder":
        monkeypatch.setattr(
            probe, "build_private_v4_report", Mock(side_effect=RuntimeError("PRIVATE"))
        )
    else:
        client = Mock(
            async_refresh=AsyncMock(
                return_value=RawStoveSnapshot(StoveProfile.V4, WORDS, 5, 0, 8, 2, 512)
            ),
            async_close=AsyncMock(),
            has_assigned_device_guid=True,
        )
        if failure == "close":
            client.async_close.side_effect = RuntimeError("PRIVATE")
        else:
            client.async_refresh.side_effect = asyncio.CancelledError("PRIVATE")
        monkeypatch.setattr(probe, "HobenClient", Mock(return_value=client))
    assert probe.main([MODE]) == 1
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert report["state"] == "error"
    assert "entities" not in report and "registers" not in report
    assert len(output.out.splitlines()) == 1
    assert output.err == ""
    for value in ("PRIVATE", "Traceback", USER_GUID, NORMALIZED_USER_GUID, DEVICE_GUID):
        assert value not in output.out + output.err + caplog.text
    if failure != "decoder":
        client.async_close.assert_awaited_once_with()
    else:
        streams.writer.wait_closed.assert_awaited_once_with()


def test_live_premerge_still_exports_only_existing_public_metadata_in_actions(
    streams, monkeypatch, capsys
):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    private_capture = AsyncMock(
        side_effect=AssertionError("Public gate cannot capture values")
    )
    monkeypatch.setattr(probe, "_capture_private_v4_values", private_capture)
    streams.reader.read.side_effect = [
        OPENED,
        response(WORDS),
        OPENED,
        response(list(reversed(WORDS))),
    ]
    assert probe.main(["--live-premerge"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "host": "myhoben.fr",
        "port": 465,
        "mode": "live-premerge",
        "state": "client_refresh_validated",
        "profile": "v4",
        "product_type": 5,
        "product_revision": 0,
        "software_major": 8,
        "software_minor": 2,
        "application_version": 512,
        "device_guid_reuse": "validated",
        "refresh_count": 2,
        "register_count": 20,
        "v4_decode_count": 2,
    }
    private_capture.assert_not_awaited()
    assert [call.args[0] for call in streams.writer.write.call_args_list] == [
        OPEN_REQUEST,
        READ_REQUEST,
        OPEN_REQUEST[:37] + DEVICE_GUID.encode() + OPEN_REQUEST[69:],
        READ_REQUEST,
    ]


def test_private_capture_is_never_invoked_by_workflows():
    workflows = Path(__file__).resolve().parents[1] / ".github/workflows"
    for workflow in workflows.glob("*.yml"):
        assert MODE not in workflow.read_text()
        assert "_capture_private_v4_values" not in workflow.read_text()


@pytest.mark.parametrize(
    "other_mode",
    [
        "--tls-only",
        "--session",
        "--session-negative",
        "--read-v4-state",
        "--live-premerge",
    ],
)
def test_private_capture_requires_its_own_explicit_exclusive_mode(
    streams, capsys, other_mode
):
    with pytest.raises(SystemExit) as caught:
        probe.main([MODE, other_mode])
    assert caught.value.code == 2
    streams.connect.assert_not_awaited()
    assert "PRIVATE" not in capsys.readouterr().err
