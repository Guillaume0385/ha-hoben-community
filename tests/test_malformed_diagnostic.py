"""Proved local structure only; synthetic bytes never become public RX data."""

import json
from dataclasses import FrozenInstanceError

import pytest

from custom_components.hoben.exceptions import HobenProtocolError
from custom_components.hoben.malformed import MalformedDiagnostic, response_diagnostic
from custom_components.hoben.v4_experiment import ExperimentalV4Framer

RESPONSE = bytes.fromhex("0effff0000002b010428") + b"\x00\x11" * 20


def test_unknown_discriminator_rejects_without_exporting_it_or_the_suffix():
    framer = ExperimentalV4Framer()
    with pytest.raises(HobenProtocolError) as caught:
        framer.feed(b"\xffPRIVATE_PAYLOAD" + RESPONSE, None)
    report = caught.value.safe_report()
    assert report | {} == {
        "state": "error",
        "error": "malformed_response",
        "phase": "message_classification",
        "message_type": "unknown",
        "received_length": 1,
        "expected_length": "not_proven",
        "length_scope": "not_proven",
        "missing_fields": "unknown",
        "rejection": "unknown_type",
    }
    assert "255" not in json.dumps(report) and "PRIVATE" not in repr(caught.value)


@pytest.mark.parametrize("split", range(1, len(RESPONSE)))
def test_fragmented_frame_reports_only_observed_bytes_and_proved_mbap_size(split):
    framer = ExperimentalV4Framer()
    assert framer.feed(RESPONSE[:split], None) == []
    report = framer.incomplete_error().safe_report()
    assert report["received_length"] == split
    assert report["message_type"] == "data_response_client"
    assert report["expected_length"] == (len(RESPONSE) if split >= 7 else "not_proven")
    assert report["missing_fields"] == ("message_body" if split >= 7 else "mbap_header")
    # Diagnosis does not consume bytes or change fragmentation/concatenation.
    assert framer.feed(RESPONSE[split:] + b"\x0a", None)[0].payload == RESPONSE


def test_invalid_mbap_does_not_publish_an_expected_length():
    framer = ExperimentalV4Framer()
    with pytest.raises(HobenProtocolError) as caught:
        framer.feed(bytes.fromhex("0effff0001002b"), None)
    report = caught.value.safe_report()
    assert report["phase"] == "frame_boundary"
    assert report["received_length"] == 7
    assert report["expected_length"] == "not_proven"
    assert report["rejection"] == "invalid_mbap"


def test_correlation_failure_has_no_transaction_or_register_values():
    report = response_diagnostic(RESPONSE, "request_correlation").safe_report()
    assert report["received_length"] == report["expected_length"] == 50
    assert report["rejection"] == "uncorrelated_response"
    assert "65535" not in json.dumps(report) and "register" not in json.dumps(report)


@pytest.mark.parametrize(
    "field,value",
    [
        ("phase", "PRIVATE"),
        ("message_type", "255"),
        ("received_length", True),
        ("expected_length", -1),
        ("missing_fields", "private_guid"),
    ],
)
def test_diagnostic_rejects_arbitrary_values(field, value):
    with pytest.raises(ValueError, match="^invalid_malformed_diagnostic$"):
        MalformedDiagnostic(**{field: value})


def test_diagnostic_is_immutable_and_default_does_not_invent_proof():
    diagnostic = MalformedDiagnostic()
    with pytest.raises(FrozenInstanceError):
        diagnostic.phase = "opening"
    assert HobenProtocolError().safe_report()["expected_length"] == "not_proven"


@pytest.mark.parametrize("split", [2, 17])
@pytest.mark.parametrize("raise_eof", [False, True])
def test_actual_rx_partial_eof_has_same_diagnostic_for_both_transport_forms(
    split, raise_eof
):
    import asyncio

    from custom_components.hoben.transport import TransportEOF
    from tests.test_v4_persistent import Factory

    async def scenario():
        factory = Factory()
        lifecycle = factory.lifecycle(retry_delays=())
        await lifecycle.connect()
        factory.streams[0].chunks = [
            RESPONSE[:split],
            TransportEOF("PRIVATE") if raise_eof else b"",
        ]
        with pytest.raises(HobenProtocolError) as caught:
            await lifecycle.request_v4_data()
        report = caught.value.safe_report()
        assert report["received_length"] == split
        assert report["expected_length"] == (50 if split >= 7 else "not_proven")
        assert report["rejection"] == "incomplete_frame"
        assert "PRIVATE" not in str(report)
        await lifecycle.close()
        factory.assert_clean()

    asyncio.run(scenario())
