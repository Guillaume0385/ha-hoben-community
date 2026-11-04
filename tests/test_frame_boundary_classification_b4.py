"""B4 origin proof and default-off framing, independent synthetic vectors."""

import pytest

from custom_components.hoben.exceptions import (
    HobenFrameBoundaryError,
    HobenInternalError,
    HobenProtocolError,
)
from custom_components.hoben.malformed import MalformedDiagnostic
from custom_components.hoben.v4_experiment import (
    ExperimentalV4Framer,
    UnsupportedMessageTypeError,
)


@pytest.mark.parametrize(
    "data,kind",
    [
        (b"\x04", "unsupported_type"),
        (b"\xff", "unknown_type"),
        (b"\x0e\xff\xff\x00\x00\xff\xff", "invalid_mbap"),
    ],
    ids=["unsupported", "unknown", "mbap"],
)
def test_only_structural_wire_rejections_get_closed_origin(data, kind):
    framer = ExperimentalV4Framer(classify_frame_boundary=True)
    with pytest.raises(HobenFrameBoundaryError) as caught:
        framer.feed(data, None)
    assert framer.boundary_failure is caught.value
    report = caught.value.safe_report()
    assert report["error"] == "malformed_response"
    assert report["phase"] == "frame_boundary"
    assert report["frame_boundary_provenance"] == kind
    assert report["expected_length"] == "not_proven"
    framer.clear()
    assert framer.boundary_failure is None


def test_partial_eof_is_distinct_from_complete_closeclient():
    framer = ExperimentalV4Framer(classify_frame_boundary=True)
    assert framer.feed(b"\x05", None) == []
    error = framer.incomplete_error()
    assert type(error) is HobenFrameBoundaryError and framer.boundary_failure is error
    report = error.safe_report()
    assert report["frame_boundary_provenance"] == "partial_eof"
    assert (
        report["received_length"] == 1 and report["missing_fields"] == "close_subcode"
    )
    assert "subcode" not in report


@pytest.mark.parametrize(
    "data,cls", [(b"\xff", HobenProtocolError), (b"\x04", UnsupportedMessageTypeError)]
)
def test_campaign_default_retains_exact_previous_classes(data, cls):
    framer = ExperimentalV4Framer()
    with pytest.raises(cls) as caught:
        framer.feed(data, None)
    assert type(caught.value) is cls and framer.boundary_failure is None


@pytest.mark.parametrize(
    "data",
    [None, bytearray(b"\x0a"), b"\x0a" * 4097],
    ids=["not-bytes", "mutable", "oversized"],
)
def test_local_delivery_contract_is_not_reclassified(data):
    framer = ExperimentalV4Framer(classify_frame_boundary=True)
    with pytest.raises(HobenInternalError):
        framer.feed(data, None)
    assert framer.boundary_failure is None


def test_python_exception_in_framer_keeps_its_type_and_no_origin(monkeypatch, caplog):
    framer = ExperimentalV4Framer(classify_frame_boundary=True)

    def bug(*args):
        raise RuntimeError("PRIVATE_B4")

    monkeypatch.setattr(framer, "_feed", bug)
    with pytest.raises(RuntimeError):
        framer.feed(b"\x0a", None)
    assert framer.boundary_failure is None and "PRIVATE_B4" not in caplog.text


def test_invalid_dataupdated_alone_keeps_160_recovery_without_boundary_failure():
    framer = ExperimentalV4Framer(
        classify_frame_boundary=True, recover_data_updated=True
    )
    assert framer.feed(b"\x1bMETA\xff\xff\x00\x00\xff\xff", None) == []
    assert framer.invalid_data_updated == (65535, "invalid_length")
    assert framer.boundary_failure is None


@pytest.mark.parametrize("provenance", ["PRIVATE_B4", None, False, {}, []])
def test_unclassified_provenance_is_refused(provenance):
    with pytest.raises(ValueError, match="invalid_frame_boundary_incident"):
        HobenFrameBoundaryError(MalformedDiagnostic(), provenance)


@pytest.mark.parametrize("flag", [None, 1, "true", {}])
def test_classifier_optin_is_strict_boolean(flag):
    with pytest.raises(ValueError, match="invalid_frame_boundary_policy"):
        ExperimentalV4Framer(classify_frame_boundary=flag)


@pytest.mark.parametrize("result", [None, False, 0, 9999])
def test_broken_mbap_return_contract_is_not_a_wire_boundary(monkeypatch, result):
    monkeypatch.setattr(
        "custom_components.hoben.v4_experiment.modbus_tcp_frame_size", lambda _: result
    )
    framer = ExperimentalV4Framer(classify_frame_boundary=True)
    with pytest.raises(HobenInternalError):
        framer.feed(b"\x0e\xff\xff\x00\x00\x00\x02", None)
    assert framer.boundary_failure is None


def test_mbap_typeerror_is_not_retried_as_server_data(monkeypatch):
    def broken(_):
        raise TypeError("PRIVATE_B4")

    monkeypatch.setattr(
        "custom_components.hoben.v4_experiment.modbus_tcp_frame_size", broken
    )
    framer = ExperimentalV4Framer(classify_frame_boundary=True)
    with pytest.raises(HobenInternalError):
        framer.feed(b"\x0e\xff\xff\x00\x00\x00\x02", None)
    assert framer.boundary_failure is None


@pytest.mark.parametrize("split", range(1, 50))
def test_classification_does_not_change_valid_fragmentation_or_concatenation(split):
    response = bytes.fromhex("0effff0000002b010428") + b"\x00\x11" * 20
    framer = ExperimentalV4Framer(classify_frame_boundary=True)
    assert framer.feed(response[:split], None) == []
    events = framer.feed(response[split:] + b"\x0a", None)
    assert (
        len(events) == 2
        and events[0].payload == response
        and events[1].payload == b"\x0a"
    )
    assert framer.boundary_failure is None and not framer.partial
