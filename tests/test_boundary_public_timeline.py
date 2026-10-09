"""Synthetic H1/H2 timelines: read() != frame, raw data never public."""
from __future__ import annotations

import copy
import json

import pytest

from scripts.boundary_analysis import RxRead
from scripts.boundary_public_timeline import safe_timeline
from scripts.boundary_timeline import TimelineInvalid, metadata_timeline
from scripts.run_experimental_boundary import safe_report


def synthetic():
    reads = [
        RxRead(0, 0, 4096, 48, 3.1, 3.2, None),
        RxRead(1, 48, 4096, 3, 3.5, 3.2),
        RxRead(2, 51, 4096, 0, 3.5, 3.6, 3.5),
    ]
    # Keep reader starts monotonic here; one separate testcase tests tampering.
    reads[1] = RxRead(1, 48, 4096, 3, 3.5, 3.2)
    events = [
        {"kind": "tx_attempt", "category": "open_client", "started": 3.0},
        {"kind": "tx_complete", "category": "open_client", "started": 3.0,
         "ended": 3.001},
        {"kind": "rx", "status": "received", **reads[0].metadata()},
        {"kind": "rx", "status": "received", **reads[1].metadata()},
        {"kind": "rx", "status": "eof", **reads[2].metadata()},
        {"kind": "close_attempt", "at": 3.7},
        {"kind": "close_complete", "at": 3.75},
    ]
    return reads, events


def valid():
    reads, events = synthetic()
    reads[1] = RxRead(1, 48, 4096, 3, 3.5, 3.2)
    events[3] = {"kind": "rx", "status": "received", **reads[1].metadata()}
    # The virtual clock can run while a read is pending, but a distinct read
    # must begin no earlier than the last read completed.
    reads[1] = RxRead(1, 48, 4096, 3.2, 3.5, 3.2)
    events[3] = {"kind": "rx", "status": "received", **reads[1].metadata()}
    t = metadata_timeline(
        events, reads, rx_bytes=51, opening_offset=0,
        h2={"covered_bytes": 0, "unattributed_bytes": 3},
    )
    return t


def test_exact_read_and_eof_timing_and_unknown_three_byte_suffix():
    t = valid()
    assert t["basis"] == "client_monotonic_relative"
    assert [r["received"] for r in t["reads"]] == [48, 3, 0]
    assert [r["offset"] for r in t["reads"]] == [0, 48, 51]
    assert t["reads"][-1]["state"] == "eof"
    assert t["reads"][0]["started_ms"] == 100
    assert t["reads"][1]["gap_previous_ms"] == 0
    assert t["unattributed"] == [
        {"offset": 48, "length": 3, "basis": "h2_unproven_suffix"}
    ]
    assert t["tx"][0]["category"] == "open_client"
    assert t["close"]["state"] == "closed"
    assert t["close"]["duration_ms"] == 50
    assert safe_timeline(t, rx_bytes=51, read_calls=3) == t
    assert "user_guid" not in json.dumps(t)
    assert "payload" not in json.dumps(t)


def test_hypothetical_ping_and_fragmentation_have_no_protocol_proof():
    reads, events = synthetic()
    reads[1] = RxRead(1, 48, 4096, 3, 3.5, 3.2)
    reads[1] = RxRead(1, 48, 4096, 3.2, 3.5, 3.2)
    events[3] = {"kind": "rx", "status": "received", **reads[1].metadata()}
    events.insert(4, {"kind": "candidate_frame", "category": "ping_h2",
                      "offset": 48, "length": 1, "received_at": 3.5})
    events.insert(5, {"kind": "candidate_frame", "category": "notification_h2",
                      "offset": 49, "length": 2, "received_at": 3.5})
    t = metadata_timeline(events, reads, rx_bytes=51, opening_offset=0,
                          h2={"covered_bytes": 3, "unattributed_bytes": 0})
    assert [f["confidence"] for f in t["h2_candidates"]] == [
        "h2_hypothesis_only", "h2_hypothesis_only"
    ]
    assert t["fragmented_candidates"] == 0
    assert t["concatenated_reads"] == 1
    assert t["unattributed"] == []
    assert safe_timeline(t, rx_bytes=51, read_calls=3) == t


@pytest.mark.parametrize("corruption", [
    lambda t: t.update(private_payload="SYNTHETIC_PRIVATE_RX"),
    lambda t: t["reads"][0].update(device_guid="SYNTHETIC_PRIVATE_ID"),
    lambda t: t["reads"][0].update(received=49),
    lambda t: t["reads"][0].update(requested=True),
    lambda t: t["reads"][0].update(duration_ms=999),
    lambda t: t["reads"][0].update(started_ms=float("nan")),
    lambda t: t["reads"][1].update(offset=40),
    lambda t: t["reads"][1].update(gap_previous_ms=999),
    lambda t: t["tx"][0].update(category="SYNTHETIC_PRIVATE_PACKET"),
    lambda t: t["tx"][0].update(ended_ms=None),
    lambda t: t["unattributed"][0].update(basis="RAW_HEX"),
    lambda t: t["unattributed"][0].update(length=8000),
    lambda t: t["close"].update(data="SYNTHETIC_PRIVATE_PACKET"),
    lambda t: t.update(fragmented_candidates=1),
])
def test_public_timeline_refuses_raw_corruption_and_false_metadata(corruption):
    timeline = copy.deepcopy(valid())
    corruption(timeline)
    with pytest.raises(ValueError, match="invalid_public_timeline"):
        safe_timeline(timeline, rx_bytes=51, read_calls=3)


def test_measurement_builder_refuses_inconsistent_read_without_export():
    reads, events = synthetic()
    with pytest.raises(TimelineInvalid, match="invalid_timeline"):
        metadata_timeline(events, reads, rx_bytes=51, opening_offset=0,
                          h2={"covered_bytes": 0, "unattributed_bytes": 3})


def test_public_projection_includes_only_timing_fields_when_present(monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    monkeypatch.setenv("EXPERIMENTAL_APPROVED_SHA", "a" * 40)
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    s = {
        "mode": "H1", "pause_seconds": 0, "repetition": 1,
        "boundary_proven": False, "partial": True,
        "prefix_complete": True, "rx_bytes": 51, "read_calls": 3,
        "pongs_before_open": 0, "pongs_under_h2": 0,
        "v4_requests": 0, "correlated_responses": 0,
        "exception_responses": 0, "stop": "peer_eof",
        "emission_stop": None, "opening_context": {
            "eligible": True, "status": "accepted_v4_prefix",
        }, "h1": {"status": "inconclusive"}, "h2": {"status": "inconclusive"},
        "comparison": "insufficient_data",
        "timing_observations": valid(), "private": "SYNTHETIC_PRIVATE_ID",
    }
    report = safe_report({"boundary_proven": False, "sessions": [s]},
                         interrupted=True)
    assert report["result"] == "failure"
    assert report["sessions"][0]["timing_observations"] == valid()
    assert "SYNTHETIC_PRIVATE" not in json.dumps(report)
