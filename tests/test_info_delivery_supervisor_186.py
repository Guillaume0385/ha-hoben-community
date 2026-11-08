"""Synthetic supervision: no process or network operation proves completion."""

import ast
import asyncio
import copy
import json
import subprocess
from pathlib import Path

import pytest

from scripts.info_delivery_supervisor import (
    LIMITS,
    InfoSupervisor,
    InvalidSupervision,
    encode_supervision_report,
    validate_supervision_report,
)
from tests.info_delivery_fixture_186 import run_case


class Clock:
    def __init__(self):
        self.now = 0

    def __call__(self):
        return self.now


@pytest.fixture
def evidence(monkeypatch):
    return asyncio.run(run_case(monkeypatch)).report


@pytest.fixture
def absent(monkeypatch):
    return asyncio.run(run_case(monkeypatch, deliveries=())).report


def model(report, *, at=None):
    clock = Clock()
    policy = InfoSupervisor(clock_ms=clock)
    policy.start()
    clock.now = report["elapsed_ms"] if at is None else at
    policy.observe(report)
    return clock, policy


def cleaned(policy):
    policy.event("transport_closed")
    policy.event("rx_reaped")
    policy.event("worker_reaped")
    result = policy.finish()
    assert validate_supervision_report(result) == result
    assert len(encode_supervision_report(result).encode()) <= 8192
    return result


def test_real_C_evidence_and_separate_cleanup_acknowledgments(evidence):
    clock, policy = model(evidence)
    assert policy.state == "CLEANING"
    report = cleaned(policy)
    assert report["result"] == "SUCCESS"
    assert report["proof_scope"] == "synthetic_events"
    assert report["live_provenance"] == "not_proven"
    assert report["observation"] == evidence
    assert report["cleanup_attested"] and report["worker_reaped"]
    assert report["cleanup_deadline_ms"] == evidence["elapsed_ms"] + 60000
    assert not report["boundary_proven"] and report["info_framing"] == "INCONCLUSIVE"
    clock.now = 4_000_000  # Already stopped/reaped model, no deadline rearmed.
    assert policy.finish() == report
    with pytest.raises(InvalidSupervision):
        policy.start()


def test_info_absent_waits_for_entire_window_and_cleanup(absent):
    clock, policy = model(absent)
    clock.now = LIMITS["observation_ms"] - 1
    policy.tick()
    assert policy.state == "OBSERVING"
    clock.now += 1
    policy.tick()
    assert policy.state == "CLEANING"
    clock.now = LIMITS["total_ms"] - 1
    report = cleaned(policy)
    assert report["result"] == "INCONCLUSIVE" and report["reason"] == "info_absent"
    assert report["elapsed_ms"] == 3_599_999
    assert report["cleanup_started_ms"] == 3_540_000
    assert report["cleanup_deadline_ms"] == 3_600_000


@pytest.mark.parametrize("at", [3_600_000, 3_600_001, 3_700_000])
def test_global_equality_and_late_poll_never_extend_cleanup(absent, at):
    clock, policy = model(absent)
    clock.now = at
    policy.tick()
    report = policy.finish()
    assert report["result"] == "FAILURE"
    assert report["stop_reason"] == "global_timeout"
    assert report["elapsed_ms"] == at  # Honest overrun, never clamped to budget.
    assert report["cleanup_started_ms"] == 3_540_000
    assert report["cleanup_deadline_ms"] == 3_600_000
    assert report["abort_requested"] and report["reap_requested"]
    assert not report["worker_reaped"] and not report["cleanup_attested"]
    assert validate_supervision_report(report) == report


@pytest.mark.parametrize(
    "delta,expected", [(59999, "SUCCESS"), (60000, "FAILURE"), (60001, "FAILURE")]
)
def test_early_cleanup_has_its_own_nonrenewable_reserve(evidence, delta, expected):
    clock, policy = model(evidence)
    clock.now += delta
    policy.tick()
    report = cleaned(policy) if expected == "SUCCESS" else policy.finish()
    assert report["result"] == expected
    assert report["cleanup_deadline_ms"] == evidence["elapsed_ms"] + 60000
    if expected == "FAILURE":
        assert report["first_error"] == "cleanup_timeout"
        assert not report["cleanup_attested"]


@pytest.mark.parametrize("at", [3_539_999, 3_540_000, 3_540_001])
def test_success_evidence_must_arrive_before_observation_deadline(evidence, at):
    clock, policy = model(evidence, at=at)
    report = cleaned(policy)
    if at < LIMITS["observation_ms"]:
        assert report["result"] == "SUCCESS"
    else:
        assert report["result"] == "FAILURE"
        assert report["first_error"] == "evidence_missing"
        assert report["observation"] is None


def test_absence_of_evidence_is_not_evidence_of_absent_info():
    clock = Clock()
    policy = InfoSupervisor(clock_ms=clock)
    policy.start()
    clock.now = LIMITS["observation_ms"]
    policy.tick()
    report = cleaned(policy)
    assert report["result"] == "FAILURE" and report["first_error"] == "evidence_missing"
    assert not report["cleanup_attested"]


def test_early_absent_report_cannot_shorten_the_observation(absent):
    _, policy = model(absent)
    report = policy.finish()
    assert report["result"] == "FAILURE"
    assert report["first_error"] == "observation_incomplete"
    assert validate_supervision_report(report) == report


@pytest.mark.parametrize("event", ["cancel", "worker_failed", "cleanup_failed"])
@pytest.mark.parametrize("phase", ["observing", "cleaning"])
def test_failure_and_cancel_latch_even_with_later_positive_acks(
    absent, evidence, event, phase
):
    clock, policy = model(absent if phase == "observing" else evidence)
    clock.now += 1
    policy.event(event)
    report = cleaned(policy)
    assert report["result"] == "FAILURE"
    assert report["first_error"] == ("cancelled" if event == "cancel" else event)
    assert report["abort_requested"] and report["stop_requested"]
    if event == "cleanup_failed":
        assert not report["cleanup_attested"]


def test_repeated_cancellation_never_restarts_cleanup_budget(evidence):
    clock, policy = model(evidence)
    initial = clock.now
    for extra in (10000, 30000, 59999):
        clock.now = initial + extra
        policy.event("cancel")
    report = cleaned(policy)
    assert report["result"] == "FAILURE" and report["first_error"] == "cancelled"
    assert report["cleanup_started_ms"] == initial
    assert report["cleanup_deadline_ms"] == initial + 60000


def test_first_incident_survives_cleanup_timeout(evidence):
    clock, policy = model(evidence)
    initial = clock.now
    policy.event("worker_failed")
    clock.now += 60000
    policy.tick()
    report = policy.finish()
    assert report["first_error"] == "worker_failed"
    assert report["stop_reason"] == "cleanup_timeout"
    assert report["cleanup_deadline_ms"] == initial + 60000
    assert validate_supervision_report(report) == report


@pytest.mark.parametrize("missing", ["transport_closed", "rx_reaped", "worker_reaped"])
def test_no_success_without_each_distinct_cleanup_confirmation(evidence, missing):
    _, policy = model(evidence)
    for event in ("transport_closed", "rx_reaped", "worker_reaped"):
        if event != missing:
            policy.event(event)
    report = policy.finish()
    assert report["result"] == "FAILURE" and not report["cleanup_attested"]
    assert report["abort_requested"] and report["reap_requested"]
    assert validate_supervision_report(report) == report


def test_cleanup_failure_in_real_C_evidence_is_not_overridden(monkeypatch):
    from custom_components.hoben.transport import TransportTlsError

    evidence = asyncio.run(
        run_case(monkeypatch, close_error=TransportTlsError())
    ).report
    _, policy = model(evidence)
    report = cleaned(policy)
    assert report["result"] == "FAILURE"
    assert report["first_error"] == "observation_failed"
    assert not report["cleanup_attested"]


@pytest.mark.parametrize(
    "bad", [None, True, -1, 1.5, float("inf"), float("nan"), "PRIVATE_D2"]
)
def test_invalid_initial_clocks_stop_without_claiming_a_worker(bad):
    policy = InfoSupervisor(clock_ms=lambda: bad)
    policy.start()
    report = policy.finish()
    assert report["result"] == "FAILURE" and report["first_error"] == "clock"
    assert not report["started"] and report["elapsed_ms"] is None
    assert not report["cleanup_attested"] and not report["worker_reaped"]
    assert validate_supervision_report(report) == report


def test_clock_rollback_is_latched_and_cannot_be_repaired(evidence):
    clock, policy = model(evidence)
    clock.now -= 1
    policy.tick()
    clock.now += 2
    policy.tick()
    report = policy.finish()
    assert report["result"] == "FAILURE" and report["first_error"] == "clock"
    assert not report["clock_valid"] and not report["cleanup_attested"]
    assert validate_supervision_report(report) == report


def test_admission_wait_does_not_consume_budget(evidence):
    clock = Clock()
    policy = InfoSupervisor(clock_ms=clock)
    clock.now = 9_000_000
    policy.start()
    clock.now += evidence["elapsed_ms"]
    policy.observe(evidence)
    report = cleaned(policy)
    assert report["elapsed_ms"] == evidence["elapsed_ms"]
    assert "9000000" not in encode_supervision_report(report)


def test_clock_exception_cannot_escape_into_report(evidence):
    _, policy = model(evidence)

    def private_failure():
        raise RuntimeError("PRIVATE_D2_CLOCK")

    policy._clock = private_failure
    policy.tick()
    report = policy.finish()
    assert report["first_error"] == "clock" and report["result"] == "FAILURE"
    assert "PRIVATE_D2" not in encode_supervision_report(report)
    assert report["abort_requested"] and not report["cleanup_attested"]


@pytest.mark.parametrize(
    "case", ["invalid", "missing", "future", "duplicate", "second-start"]
)
def test_false_or_replaced_observation_cannot_produce_success(evidence, case):
    clock = Clock()
    policy = InfoSupervisor(clock_ms=clock)
    policy.start()
    clock.now = evidence["elapsed_ms"]
    candidate = copy.deepcopy(evidence)
    if case == "invalid":
        candidate["payload"] = "PRIVATE_D2"
    elif case == "missing":
        candidate = None
    elif case == "future":
        clock.now = 0
    elif case == "duplicate":
        policy.observe(candidate)
    elif case == "second-start":
        policy.start()
        report = policy.finish()
        assert report["result"] == "FAILURE"
        assert validate_supervision_report(report) == report
        return
    policy.observe(candidate)
    report = cleaned(policy)
    assert report["result"] == "FAILURE"
    assert "PRIVATE_D2" not in encode_supervision_report(report)


def test_never_started_and_cancel_before_start_are_distinct():
    def forbidden_clock():
        raise AssertionError("clock_not_needed_before_start")

    policy = InfoSupervisor(clock_ms=forbidden_clock)
    report = policy.finish()
    assert report["result"] == "NOT RUN"
    assert validate_supervision_report(report) == report
    policy = InfoSupervisor(clock_ms=forbidden_clock)
    policy.event("cancel")
    report = policy.finish()
    assert report["result"] == "FAILURE" and report["first_error"] == "cancelled"
    assert validate_supervision_report(report) == report


def test_event_flood_stops_with_bounded_audit_and_no_fake_cleanup():
    clock = Clock()
    policy = InfoSupervisor(clock_ms=clock)
    policy.start()
    for _ in range(63):
        policy.tick()
    report = policy.finish()
    assert len(report["events"]) == 64
    assert report["first_error"] == "event_budget"
    assert report["result"] == "FAILURE" and not report["cleanup_attested"]
    assert report["abort_requested"] and not report["worker_reaped"]
    assert validate_supervision_report(report) == report


@pytest.mark.parametrize(
    "change",
    ["result", "cleanup", "clock", "budget", "mode", "wire", "extra", "trace", "child"],
)
def test_closed_report_refuses_tampering(evidence, change):
    _, policy = model(evidence)
    report = cleaned(policy)
    if change == "result":
        report["result"] = "INCONCLUSIVE"
    elif change == "cleanup":
        report["worker_reaped"] = False
    elif change == "clock":
        report["elapsed_ms"] += 1
    elif change == "budget":
        report["limits"]["total_ms"] += 1
    elif change == "mode":
        report["mode"] = "live"
    elif change == "wire":
        report["boundary_proven"] = True
    elif change == "extra":
        report["payload"] = "PRIVATE_D2"
    elif change == "trace":
        report["events"][2]["at_ms"] = 3_600_000
    else:
        report["observation"]["first_error"] = "PRIVATE_D2"
    with pytest.raises(InvalidSupervision, match="^invalid_offline_info_supervision$"):
        encode_supervision_report(report)


def test_D1_live_refusal_is_unchanged_and_supervisor_has_no_runtime_io(evidence):
    _, policy = model(evidence)
    report = cleaned(policy)
    result = subprocess.run(
        [
            "node",
            "-e",
            """
const api=require('./.github/scripts/info-delivery-manual-report.cjs');
const r=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
try {api.validateForLivePublication(r); process.exit(2);}
catch(e) {if(e.message!=='info_live_provenance_not_proven')process.exit(3);}
""",
        ],
        input=json.dumps(report),
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0
    source = Path("scripts/info_delivery_supervisor.py").read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in {
                "connect",
                "read",
                "write",
                "abort",
                "kill",
                "waitpid",
                "run",
                "create_task",
                "sleep",
                "open_connection",
                "request_v4_data",
            }
    assert "__main__" not in source and "_InfoDeliveryDropExperiment" not in source


def test_all_missing_fields_and_wrong_types_are_refused(evidence):
    _, policy = model(evidence)
    report = cleaned(policy)
    for key in report:
        missing = copy.deepcopy(report)
        del missing[key]
        with pytest.raises(InvalidSupervision):
            validate_supervision_report(missing)
    changes = [
        ("started", 1),
        ("clock_valid", 1),
        ("elapsed_ms", True),
        ("schema", True),
        ("phase", None),
        ("result", "PRIVATE_D2"),
        ("first_error", "PRIVATE_D2"),
        ("stop_reason", "PRIVATE_D2"),
        ("proof_scope", "real_worker"),
        ("live_provenance", "authenticated"),
        ("events", report["events"] * 20),
        ("observation", "PRIVATE_D2"),
        ("elapsed_ms", 2**53),
        ("limits", {**LIMITS, "total_ms": 3600000.0}),
    ]
    for key, value in changes:
        changed = copy.deepcopy(report)
        changed[key] = value
        with pytest.raises(InvalidSupervision):
            encode_supervision_report(changed)
