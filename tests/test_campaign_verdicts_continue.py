"""#126/030: operational verdicts and isolated continuation, entirely offline."""

import base64
import copy
import json

import pytest

from scripts.campaign_runtime_contract import CHOICES, stage, validate_report
from scripts.ha_campaign_evidence import project
from scripts.run_campaign import run
from tests.test_campaign_publication import node
from tests.test_campaign_runtime import PROVENANCE, envelope, node_accepts, observed


def reproject(value):
    """Keep metrics derived from owner/supervisor evidence, never patch a verdict."""
    return stage(
        "ha",
        value["scenario"],
        started=True,
        elapsed_ms=value["elapsed_ms"],
        reason=value["reason"],
        metrics=project(value["scenario"], value["detail"]),
        detail=value["detail"],
    )


def failure(scenario):
    value = observed("ha", scenario)
    value["detail"]["evidence"]["completed"] = False
    return reproject(value)


def attest(report):
    value = copy.deepcopy(report)
    value["collection_result"] = "success"
    value["actions_result"] = (
        "SUCCESS"
        if all(s["status"] == "SUCCESS" for s in value["stages"])
        else "FAILURE"
    )
    assert validate_report(value) == value and node_accepts(value)
    return value


def campaign(executor, *, cancelled=lambda: False):
    clock = [0.0]
    visited = []

    def execute(c, name, payload, deadline, **kwargs):
        assert c == "ha" and deadline <= 1800 and not kwargs["cancelled"]()
        visited.append(name)
        result = executor(name)
        clock[0] += result["elapsed_ms"] / 1000
        return result

    report = run(
        "ha",
        "all",
        PROVENANCE,
        b"synthetic",
        executor=execute,
        clock=lambda: clock[0],
        cancelled=cancelled,
    )
    return attest(report), visited


def test_h1h2_complete_is_operational_success_in_both_validators():
    value = envelope("protocol", "h1h2")
    assert value["stages"][0]["status"] == value["actions_result"] == "SUCCESS"
    assert validate_report(value) == value and node_accepts(value)


@pytest.mark.parametrize("kind", ["h1h2", "ha_continue"])
def test_independent_node_accepts_new_contract_receipts(kind):
    if kind == "h1h2":
        value = envelope("protocol", "h1h2")
        value["stages"][0]["status"] = value["actions_result"] = "SUCCESS"
    else:
        stages = [observed("ha", s) for s in CHOICES["ha"][:-1]]
        stages[0] = failure("hoben-live")
        value = envelope("ha", "all", stages)
    assert node_accepts(value)
    assert validate_report(value) == value


@pytest.mark.parametrize(
    "field,value",
    [
        ("h1_sessions", 5),
        ("h2_sessions", 5),
        ("opens", 11),
        ("reads", 11),
        ("reads_ok", 11),
        ("completed", False),
        ("cleanup", False),
        ("error", "transport"),
    ],
)
def test_h1h2_incomplete_or_failed_receipt_cannot_be_promoted(field, value):
    metrics = observed("protocol", "h1h2")["metrics"]
    metrics[field] = value
    if field == "reads":
        metrics["reads_ok"] = value
    result = observed("protocol", "h1h2")
    result = stage(
        "protocol",
        "h1h2",
        started=True,
        reason="observed",
        elapsed_ms=result["elapsed_ms"],
        detail=result["detail"],
        metrics=metrics,
    )
    assert result["status"] == "FAILURE"
    report = envelope("protocol", "h1h2", [result])
    assert validate_report(report) == report and node_accepts(report)
    result["status"] = report["actions_result"] = "SUCCESS"
    with pytest.raises(ValueError):
        validate_report(report)
    assert not node_accepts(report)


@pytest.mark.parametrize("failed_at", range(7))
def test_ha_all_continues_after_each_safe_failure_and_retains_every_result(failed_at):
    def execute(name):
        return (
            failure(name) if name == CHOICES["ha"][failed_at] else observed("ha", name)
        )

    report, visited = campaign(execute)
    assert visited == list(CHOICES["ha"][:-1])
    assert report["stages"][failed_at]["status"] == "FAILURE"
    assert all(s["started"] for s in report["stages"])
    assert report["actions_result"] == "FAILURE"


def test_later_successes_do_not_erase_two_prior_failures():
    report, visited = campaign(
        lambda name: (
            failure(name)
            if name in {"hoben-live", "session-reconnect"}
            else observed("ha", name)
        )
    )
    assert len(visited) == 7
    assert [s["status"] for s in report["stages"]] == [
        "FAILURE",
        "SUCCESS",
        "SUCCESS",
        "SUCCESS",
        "FAILURE",
        "SUCCESS",
        "SUCCESS",
    ]
    assert report["actions_result"] == "FAILURE"


def test_two_of_six_reads_fail_operationally_but_allow_independent_ha_observers():
    value = observed("ha", "hoben-live")
    e = value["detail"]["evidence"]
    for sample in e["samples"][2:]:
        sample["decoded"] = False
        sample["observation"]["read_sequence"] = 2
    e["window"]["observation"]["read_sequence"] = 2
    e["cleanup"]["observation"]["read_sequence"] = 2
    value = reproject(value)
    report, visited = campaign(
        lambda name: value if name == "hoben-live" else observed("ha", name)
    )
    assert len(visited) == 7
    assert report["stages"][0]["metrics"]["reads_ok"] == 2
    assert report["stages"][0]["metrics"]["completed"] is True
    assert report["stages"][0]["status"] == report["actions_result"] == "FAILURE"


def test_seven_successful_ha_observers_are_globally_successful():
    # Reuse a controlled recovery receipt already proven by the #126/027 tests.
    from tests.test_ha_controlled_evidence import controlled

    def execute(name):
        if name != "session-reconnect":
            return observed("ha", name)
        detail = controlled()
        return stage(
            "ha",
            name,
            started=True,
            reason="observed",
            elapsed_ms=detail["supervisor"]["elapsed_ms"],
            metrics=project(name, detail),
            detail=detail,
        )

    report, visited = campaign(execute)
    assert len(visited) == 7 and report["actions_result"] == "SUCCESS"


@pytest.mark.parametrize(
    "unsafe,reason",
    [
        ("cleanup", "cleanup_failed"),
        ("not_reaped", "cleanup_failed"),
        ("missing_detail", "supervisor_refused"),
        ("outer_worker", "worker_failure"),
        ("unattested_outer", "supervisor_refused"),
        ("budget", "budget"),
        ("timeout", "timeout"),
        ("cancelled", "cancelled"),
        ("memory", "memory"),
        ("processes", "processes"),
        ("worker_failure", "worker_failure"),
        ("unavailable", "supervisor_refused"),
    ],
)
def test_unsafe_failure_stops_and_forged_continuation_is_refused(unsafe, reason):
    value = failure("hoben-live")
    if unsafe == "missing_detail":
        value["detail"] = None
    elif unsafe in {"outer_worker", "unattested_outer"}:
        value["reason"] = (
            "worker_failure" if unsafe == "outer_worker" else "not_observed"
        )
    else:
        receipt = value["detail"]["supervisor"]
        if unsafe == "cleanup":
            value["detail"]["evidence"]["cleanup"]["completed"] = False
        elif unsafe == "not_reaped":
            receipt.update(reaped=False, reason="worker_failure")
        elif unsafe == "budget":
            # Only complementary observers expose a terminal error category.
            value = failure("open-errors")
            value["detail"]["evidence"]["terminal"] = "budget"
        else:
            receipt["reason"] = unsafe
            receipt["oom_killed"] = unsafe == "memory"
            receipt["pids_limited"] = unsafe == "processes"
        value = reproject(value)

    report, visited = campaign(
        lambda name: value if name == value["scenario"] else observed("ha", name)
    )
    at = CHOICES["ha"].index(value["scenario"])
    assert len(visited) == at + 1
    assert all(
        s["status"] == "NOT RUN" and s["reason"] == reason
        for s in report["stages"][at + 1 :]
    )
    report["stages"][at + 1] = observed("ha", CHOICES["ha"][at + 1])
    report["elapsed_ms"] += report["stages"][at + 1]["elapsed_ms"]
    with pytest.raises(ValueError):
        validate_report(report)
    assert not node_accepts(report)


@pytest.mark.parametrize(
    "reason", ["cancelled", "identity_refused", "supervisor_refused", "context_refused"]
)
def test_unstarted_refusal_never_allows_a_later_scenario(reason):
    report, visited = campaign(lambda name: stage("ha", name, reason=reason))
    assert visited == ["hoben-live"]
    assert all(
        s["status"] == "NOT RUN" and s["reason"] == reason for s in report["stages"]
    )


@pytest.mark.parametrize("cancel", [False, True])
def test_parent_budget_or_cancellation_after_safe_failure_prevents_next_worker(cancel):
    clock = [0.0]
    visited = []

    def execute(c, name, *args, **kwargs):
        visited.append(name)
        clock[0] = 1799 if not cancel else 309
        return failure(name)

    report = attest(
        run(
            "ha",
            "all",
            PROVENANCE,
            b"synthetic",
            executor=execute,
            clock=lambda: clock[0],
            cancelled=lambda: cancel and bool(visited),
        )
    )
    assert visited == ["hoben-live"]
    assert all(
        s["status"] == "NOT RUN"
        and s["reason"] == ("cancelled" if cancel else "timeout")
        for s in report["stages"][1:]
    )


def test_protocol_all_still_refuses_continuation_after_functional_failure():
    stages = [observed("protocol", s) for s in CHOICES["protocol"][:-1]]
    stages[0]["metrics"]["completed"] = False
    stages[0]["status"] = "FAILURE"
    report = envelope("protocol", "all", stages)
    with pytest.raises(ValueError):
        validate_report(report)
    assert not node_accepts(report)


def test_protocol_all_complete_observations_can_succeed_without_proving_framing():
    stages = [observed("protocol", s) for s in CHOICES["protocol"][:-1]]
    recovery = stages[-1]
    recovery["metrics"].update(
        recovered=True,
        opens=2,
        loss_kind="transport",
        useful_ms=310000,
        pings=20,
        pongs=10,
    )
    recovery["elapsed_ms"] = 311000
    recovery["detail"]["recovery_witness"] = dict(
        mode="pong_inhibition_after_120s",
        boundary_proven=False,
        outcome="verified",
        suppressed_pongs=10,
        loss_after_ms=130000,
        reopened_after_ms=132000,
        recovery_pongs=10,
        loss_generation=1,
        read_generation=2,
        read_sequence=1,
        stable_ms=120000,
    )
    recovery["status"] = "SUCCESS"
    report = envelope("protocol", "all", stages)
    assert report["actions_result"] == "SUCCESS"
    assert validate_report(report) == report and node_accepts(report)
    recovery["detail"]["recovery_witness"]["boundary_proven"] = True
    with pytest.raises(ValueError):
        validate_report(report)
    assert not node_accepts(report)


@pytest.mark.parametrize(
    "field,value",
    [
        ("network", "bridge"),
        ("memory_bytes", 0),
        ("pids", 129),
    ],
)
def test_continuation_never_repairs_an_unproven_isolation_receipt(field, value):
    stages = [observed("ha", s) for s in CHOICES["ha"][:-1]]
    stages[0] = failure("hoben-live")
    stages[0]["detail"]["supervisor"][field] = value
    report = envelope("ha", "all", stages)
    with pytest.raises(ValueError):
        validate_report(report)
    assert not node_accepts(report)


def test_publication_keeps_all_seven_rows_and_failed_global_result(tmp_path):
    report, _ = campaign(
        lambda name: failure(name) if name == "hoben-live" else observed("ha", name)
    )
    encoded = base64.b64encode(
        json.dumps(report, separators=(",", ":")).encode()
    ).decode()
    result = node("publish", tmp_path, "ha", "all", encoded=encoded)
    assert result.returncode == 1
    public = json.loads((tmp_path / "hoben-campaign-published/report.json").read_text())
    assert public == report
    summary = (tmp_path / "summary").read_text()
    assert "Résultat global : **FAILURE**" in summary
    for s in report["stages"]:
        assert f"| {s['scenario']} | {s['status']} |" in summary
    assert "PRIVATE_PAYLOAD" not in summary
