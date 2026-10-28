"""Synthetic receipts and actual control scripts; no Hoben or Docker connection."""

import copy
import json
import subprocess
from dataclasses import asdict
from pathlib import Path

import pytest
import yaml

from scripts.campaign_runtime_contract import (
    CHOICES,
    SECONDS,
    CampaignLimits,
    empty_metrics,
    ha_limits,
    plan,
    stage,
    validate_report,
)
from scripts.ha_campaign_evidence import project
from scripts.run_campaign import context, identity, run
from tests.test_campaign_minimal_admission import controller
from tests.test_ha_live_proof import receipt
from tests.test_ha_live_proof import report as baseline_report

ROOT = Path(__file__).resolve().parents[1]
PROVENANCE = {
    "ref": "refs/heads/experimental",
    "sha": "a" * 40,
    "run_id": 123,
    "run_attempt": 10,
}
CASES = [(c, s) for c in CHOICES for s in CHOICES[c][:-1]]


def ha_detail(scenario, *, recovered=False, clock="monotonic"):
    old = baseline_report(recovered)
    evidence = {
        k: copy.deepcopy(old[k]) for k in ("completed", "samples", "window", "cleanup")
    }
    elapsed = 309000 if scenario == "hoben-live" else 8000
    evidence["window"]["clock"] = clock
    if scenario != "hoben-live":
        evidence["terminal"] = "none"
        evidence["window"]["elapsed_ms"] = 6000
        for i, sample in enumerate(evidence["samples"]):
            sample.update(at_ms=i * 1000, available=True, error="none")
    supervisor = receipt(
        **asdict(ha_limits(scenario)), elapsed_ms=elapsed, network="fixed_tls"
    )
    return {"supervisor": supervisor, "evidence": evidence}


def observed(campaign, scenario, *, recovered=False):
    if campaign == "ha":
        detail = ha_detail(scenario, recovered=recovered)
        metrics = project(scenario, detail)
        elapsed = detail["supervisor"]["elapsed_ms"]
    else:
        metrics = empty_metrics(campaign, scenario)
        metrics.update(completed=True, cleanup=True, opens=1)
        if scenario == "h1h2":
            metrics.update(opens=12, h1_sessions=6, h2_sessions=6)
        elif scenario not in {"tls-only", "session-open"}:
            metrics.update(reads=1, reads_ok=1)
        if scenario == "session-300":
            metrics["useful_ms"] = 300000
        if recovered:
            metrics.update(opens=2, loss_kind="transport", recovered=True)
        detail = {"rx_bytes": 1000, "rx_chunks": 1}
        elapsed = max(1000, metrics["useful_ms"])
    return stage(
        campaign,
        scenario,
        started=True,
        reason="observed",
        elapsed_ms=elapsed,
        metrics=metrics,
        detail=detail,
    )


def envelope(campaign, selection, stages=None):
    stages = (
        [observed(campaign, s) for s in plan(campaign, selection)]
        if stages is None
        else stages
    )
    return {
        "schema": 1,
        "campaign": campaign,
        "selection": selection,
        "provenance": dict(PROVENANCE),
        "elapsed_ms": sum(s["elapsed_ms"] for s in stages),
        "stages": stages,
        "collection_result": "success",
        "actions_result": "SUCCESS"
        if all(s["status"] == "SUCCESS" for s in stages)
        else "FAILURE",
    }


def node_accepts(value):
    code = """
const m=require('node:module'),load=m._load;
m._load=function(n,...a){
  if(/http|https|net|tls|child_process|dns/.test(n))throw Error('network forbidden');
  return load.call(this,n,...a);};
const p=require('./.github/scripts/campaign-report.cjs');let s='';
process.stdin.on('data',d=>s+=d);process.stdin.on('end',()=>{try{p.validate(JSON.parse(s));process.stdout.write('ok');}catch(_){process.exitCode=1;}});
"""
    result = subprocess.run(
        ["node", "-e", code],
        input=json.dumps(value),
        text=True,
        capture_output=True,
        cwd=ROOT,
        timeout=5,
    )
    assert result.stderr == "" and "PRIVATE_PAYLOAD" not in result.stdout
    return result.returncode == 0


@pytest.mark.parametrize(
    "campaign,scenario", CASES + [("protocol", "all"), ("ha", "all")]
)
def test_each_closed_report_has_independent_python_and_node_validation(
    campaign, scenario
):
    value = envelope(campaign, scenario)
    assert validate_report(value) == value and node_accepts(value)
    assert "pr_number" not in json.dumps(value) and "merge_sha" not in json.dumps(value)
    assert value["actions_result"] == (
        "FAILURE" if scenario in {"all", "h1h2", "session-reconnect"} else "SUCCESS"
    )


@pytest.mark.parametrize("campaign", CHOICES)
def test_reconnection_without_natural_loss_never_succeeds(campaign):
    value = envelope(campaign, "session-reconnect")
    assert value["stages"][0]["status"] == "INCONCLUSIVE"
    value["stages"][0]["status"] = "SUCCESS"
    value["actions_result"] = "SUCCESS"
    with pytest.raises(ValueError):
        validate_report(value)
    assert not node_accepts(value)


@pytest.mark.parametrize("scenario", CHOICES["ha"][:-1])
def test_ha_metrics_are_bound_to_real_observation_fields(scenario):
    value = envelope("ha", scenario)
    value["stages"][0]["metrics"]["reads_ok"] -= 1
    with pytest.raises(ValueError):
        validate_report(value)
    assert not node_accepts(value)


@pytest.mark.parametrize("campaign,scenario", CASES)
@pytest.mark.parametrize(
    "where", ["envelope", "provenance", "stage", "metrics", "detail"]
)
def test_private_unknown_keys_refuse_in_every_public_layer(campaign, scenario, where):
    value = envelope(campaign, scenario)
    target = {
        "envelope": value,
        "provenance": value["provenance"],
        "stage": value["stages"][0],
        "metrics": value["stages"][0]["metrics"],
        "detail": value["stages"][0]["detail"],
    }[where]
    target["private"] = "PRIVATE_PAYLOAD"
    with pytest.raises(ValueError):
        validate_report(value)
    assert not node_accepts(value)


@pytest.mark.parametrize("campaign,scenario", CASES)
def test_absolute_stage_limits_fail_closed(campaign, scenario):
    value = envelope(campaign, scenario)
    value["stages"][0]["elapsed_ms"] = SECONDS[campaign][scenario] * 1000 + 1
    value["elapsed_ms"] = value["stages"][0]["elapsed_ms"]
    with pytest.raises(ValueError):
        validate_report(value)
    assert not node_accepts(value)


@pytest.mark.parametrize("campaign", CHOICES)
@pytest.mark.parametrize("stop_at", range(7))
def test_all_is_sequential_with_cleanup_and_not_run_after_failure(campaign, stop_at):
    clock = [0.0]
    visited = []

    def executor(c, name, payload, deadline, **kwargs):
        assert (
            c == campaign and payload == b"synthetic" and deadline <= SECONDS[c]["all"]
        )
        value = observed(c, name)
        if len(visited) == stop_at:
            value.update(reason="cleanup_failed", status="FAILURE")
        clock[0] += value["elapsed_ms"] / 1000
        visited.append(name)
        return value

    value = run(
        campaign,
        "all",
        PROVENANCE,
        b"synthetic",
        executor=executor,
        clock=lambda: clock[0],
    )
    expected = min(len(CHOICES[campaign]) - 1, stop_at + 1)
    assert visited == list(CHOICES[campaign][:expected])
    assert all(v["status"] == "NOT RUN" for v in value["stages"][expected:])
    assert node_accepts(value)


@pytest.mark.parametrize("campaign", CHOICES)
def test_cancel_before_first_ack_cannot_attest_a_scenario(campaign):
    def forbidden(*args, **kwargs):
        raise AssertionError("worker must not start")

    value = run(
        campaign,
        "all",
        PROVENANCE,
        b"synthetic",
        executor=forbidden,
        cancelled=lambda: True,
    )
    assert value["actions_result"] == "FAILURE"
    assert all(not s["started"] and s["status"] == "NOT RUN" for s in value["stages"])
    assert node_accepts(value)


def test_design_budgets_are_exact_and_legacy_ha_limit_is_not_extended():
    from scripts.ha_session_supervisor import Limits

    assert list(SECONDS["protocol"].values()) == [15, 30, 45, 1800, 360, 480, 2820]
    assert list(SECONDS["ha"].values()) == [360, 90, 120, 180, 600, 60, 120, 1800]
    assert sum(SECONDS["protocol"][s] for s in CHOICES["protocol"][:-1]) == 2730
    assert sum(SECONDS["ha"][s] for s in CHOICES["ha"][:-1]) == 1530
    assert ha_limits("session-reconnect").process_ms == 600000
    with pytest.raises(ValueError):
        Limits(process_ms=600000)
    for values in [
        (2**30 + 1, 128, 1, 90000),
        (2**30, 129, 1, 90000),
        (2**30, 128, 1, 600001),
    ]:
        with pytest.raises(ValueError):
            CampaignLimits(*values)


@pytest.mark.parametrize("campaign", CHOICES)
@pytest.mark.parametrize("attempt", [1, 2, 10])
def test_native_context_allows_reruns_without_a_pr_and_never_compares_sha(
    campaign, attempt, tmp_path
):
    file = tmp_path / "event.json"
    file.write_text(json.dumps({"inputs": {"scenario": "all"}}))
    source = {
        "GITHUB_EVENT_PATH": str(file),
        "GITHUB_REPOSITORY": "Guillaume0385/ha-hoben-community",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_ACTOR": "Guillaume0385",
        "GITHUB_TRIGGERING_ACTOR": "Guillaume0385",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": "f" * 40,
        "GITHUB_RUN_ID": "1",
        "GITHUB_RUN_ATTEMPT": str(attempt),
    }
    selected, p = context(source, campaign)
    assert selected == "all" and p["run_attempt"] == attempt and p["sha"] == "f" * 40
    source["GITHUB_TRIGGERING_ACTOR"] = "unknown"
    with pytest.raises(ValueError):
        context(source, campaign)


@pytest.mark.parametrize("device", ["", "0" * 32, "invalid", "é" * 32])
def test_identity_never_defaults_to_association(device):
    with pytest.raises(ValueError):
        identity({"HOBEN_USER_GUID": "a" * 32, "HOBEN_DEVICE_GUID": device})
    assert identity({}, tls_only=True) == {"user_guid": "", "device_guid": ""}


@pytest.mark.parametrize(
    "campaign,scenario", [(c, s) for c in CHOICES for s in CHOICES[c]]
)
@pytest.mark.parametrize("ref", ["refs/heads/main", "refs/heads/experimental"])
@pytest.mark.parametrize("attempt", [1, 2, 10])
def test_actual_minimal_controller_reaches_only_protected_implemented_slot(
    campaign, scenario, ref, attempt, tmp_path, monkeypatch
):
    import tests.test_campaign_minimal_admission as historical

    filename = (
        "hoben-protocol-manual.yml" if campaign == "protocol" else "hoben-ha-manual.yml"
    )
    current = yaml.safe_load((ROOT / ".github/workflows" / filename).read_text())
    monkeypatch.setattr(historical, "workflow", lambda _: current)
    result, outputs, _ = controller(
        filename,
        "admission",
        historical.context(scenario, ref),
        tmp_path,
        {"GITHUB_RUN_ATTEMPT": str(attempt)},
    )
    assert result.returncode == 0 and outputs == {
        "admitted": "true",
        "collector_ready": "true",
    }
    assert current["jobs"]["collect"]["environment"] == (
        "hoben-experimental" if campaign == "protocol" else "hoben-live"
    )
