"""Synthetic R1 reports; Python/Node reject incomplete or falsified recovery."""

import copy
import json

import pytest

from scripts.campaign_runtime_contract import ha_limits, stage, validate_report
from scripts.ha_campaign_evidence import project
from tests.test_campaign_runtime import envelope, ha_detail, node_accepts
from tests.test_ha_live_proof import receipt

SCENARIOS = ("session-reuse", "availability")


def recovery_detail(scenario, category="eof"):
    count = 3 if scenario == "session-reuse" else 2
    e = ha_detail(scenario)["evidence"]
    end = (count - 1) * 60000

    def observation(generation, sequence, *, lost=False, clean=False, stopped=False):
        return dict(
            attempts=generation,
            generation=generation,
            read_generation=generation if sequence else None,
            read_sequence=sequence,
            loss_generation=1
            if lost and category not in {"timeout", "protocol"}
            else None,
            loss_kind=("close_client" if category == "close_client" else "transport")
            if lost and category not in {"timeout", "protocol"}
            else None,
            close_client_subcode=3 if category == "close_client" and lost else None,
            cleaned_generation=generation if stopped else 1 if clean else None,
            cleanup_failed=False,
            stopped=stopped,
        )

    e["samples"] = []
    for i in range(count):
        success = i != count - 2
        g = 2 if i == count - 1 else 1
        sequence = 1 if success else 1 if count == 3 else None
        o = observation(g, sequence, lost=i >= count - 2, clean=g == 2)
        e["samples"].append(
            dict(
                ordinal=i + 1,
                at_ms=i * 60000,
                decoded=success,
                available=success,
                error="none"
                if success
                else "closed"
                if category == "close_client"
                else "timeout"
                if category == "timeout"
                else "protocol"
                if category == "protocol"
                else "transport",
                observation=o,
            )
        )
    e["window"].update(
        clock="monotonic",
        elapsed_ms=end + 10,
        observation=observation(2, 1, lost=True, clean=True),
        active=True,
    )
    e["cleanup"].update(
        completed=True,
        observation=observation(2, 1, lost=True, clean=True, stopped=True),
    )
    lost_at = (count - 2) * 60000

    def owner(g, closed, read):
        return dict(
            role="a",
            generation=g,
            accepted=True,
            accepted_generation=g,
            close_client_subcode=3 if g == 1 and category == "close_client" else None,
            close=[closed, closed, closed + 1, closed + 1],
            stage="reaped",
            pending=0,
            last_read=[1, read, end + 11 - read] if read is not None else None,
        )

    e.update(
        diagnostic_schema=1,
        diagnostic=dict(
            end_ms=end + 11,
            first=[
                "a",
                1,
                lost_at,
                category,
                "post_open"
                if category == "close_client"
                else "message_classification"
                if category == "protocol"
                else "tls_read",
                "session"
                if category in {"close_client", "protocol"}
                else "transport_read",
                3 if category == "close_client" else None,
            ],
            terminal=None,
            cleanup=None,
            invalid=False,
            owners=[
                owner(1, lost_at, 0 if count == 3 else None),
                owner(2, end + 10, end),
            ],
        ),
    )
    limits = ha_limits(scenario)
    r = receipt(
        memory_bytes=limits.memory_bytes,
        pids=limits.pids,
        useful_ms=limits.useful_ms,
        process_ms=limits.process_ms,
        elapsed_ms=end + 12,
        network="fixed_tls",
    )
    return dict(supervisor=r, evidence=e)


def report(scenario, detail):
    m = project(scenario, detail)
    value = stage(
        "ha",
        scenario,
        started=True,
        reason="observed",
        elapsed_ms=detail["supervisor"]["elapsed_ms"],
        metrics=m,
        detail=detail,
    )
    return envelope("ha", scenario, [value])


@pytest.mark.parametrize("scenario", SCENARIOS)
@pytest.mark.parametrize("category", ["eof", "close_client", "timeout", "protocol"])
def test_r1_success_is_derived_from_full_owner_proof_with_original_counts(
    scenario, category
):
    d = recovery_detail(scenario, category)
    r = report(scenario, d)
    m = r["stages"][0]["metrics"]
    assert r["actions_result"] == "SUCCESS"
    assert m["recovered"] and m["cleanup"]
    assert m["reads"] == (3 if scenario == "session-reuse" else 2)
    assert m["reads_ok"] == m["reads"] - 1
    assert not m["reused"]  # One successful read on each distinct generation.
    assert validate_report(r) and node_accepts(r)
    assert len(json.dumps(d, separators=(",", ":")).encode()) <= 8192
    if category in {"timeout", "protocol"}:
        assert m["loss_kind"] == "none"  # Neither proves a natural TLS EOF.


@pytest.mark.parametrize("scenario", SCENARIOS)
@pytest.mark.parametrize(
    "mutation",
    [
        "no_f1",
        "no_first",
        "terminal",
        "cleanup_error",
        "missing_owner_cleanup",
        "old_close_later_than_read",
        "auth",
        "protocol",
        "stopped",
        "window_inactive",
        "last_not_decoded",
        "sample_omitted",
        "same_generation",
        "unproven_open",
        "last_read_missing",
        "read_not_fresh",
        "cleanup_not_completed",
        "supervisor_timeout",
        "unreaped",
        "final_cleanup_failed",
        "failure_unexpected",
    ],
)
def test_incomplete_recovery_is_failure_or_refused_in_both_validators(
    scenario, mutation
):
    d = recovery_detail(scenario)
    e = d["evidence"]
    f = e["diagnostic"]
    last = e["samples"][-1]
    if mutation == "no_f1":
        del e["diagnostic_schema"]
        del e["diagnostic"]
    elif mutation == "no_first":
        f["first"] = None
    elif mutation == "terminal":
        f["terminal"] = f["first"].copy()
    elif mutation == "cleanup_error":
        f["cleanup"] = [
            "a",
            1,
            f["first"][2],
            "cleanup_failed",
            "cleanup",
            "session",
            None,
        ]
    elif mutation == "missing_owner_cleanup":
        f["owners"][0].update(close=[0, 0, 1, None], stage="tls_closed")
    elif mutation == "old_close_later_than_read":
        f["owners"][0]["close"] = [last["at_ms"] + 2] * 4
    elif mutation == "auth":
        f["first"][3:] = ["authentication", "opening", "session", None]
    elif mutation == "protocol":
        f["first"][3:] = ["protocol", "frame_boundary", "session", None]
        f["terminal"] = f["first"].copy()
    elif mutation == "stopped":
        last["observation"]["stopped"] = True
    elif mutation == "window_inactive":
        e["window"]["active"] = False
    elif mutation == "last_not_decoded":
        last.update(decoded=False, error="transport", available=True)
    elif mutation == "sample_omitted":
        e["samples"].pop(0)
    elif mutation == "same_generation":
        last["observation"]["read_generation"] = 1
    elif mutation == "unproven_open":
        f["owners"][1]["accepted"] = False
    elif mutation == "last_read_missing":
        f["owners"][1]["last_read"] = None
    elif mutation == "read_not_fresh":
        last["observation"]["read_sequence"] = None
    elif mutation == "cleanup_not_completed":
        e["cleanup"]["completed"] = False
    elif mutation == "supervisor_timeout":
        d["supervisor"]["reason"] = "timeout"
    elif mutation == "unreaped":
        d["supervisor"]["reaped"] = False
    elif mutation == "final_cleanup_failed":
        e["cleanup"]["observation"]["cleanup_failed"] = True
    elif mutation == "failure_unexpected":
        e["samples"][-2]["error"] = "unexpected"
    try:
        r = report(scenario, d)
    except ValueError:
        forged = report(scenario, recovery_detail(scenario))
        forged["stages"][0]["detail"] = d
        assert not node_accepts(forged)
        with pytest.raises(ValueError):
            validate_report(forged)
    else:
        assert r["actions_result"] == "FAILURE"
        assert validate_report(r) and node_accepts(r)
        forged = copy.deepcopy(r)
        forged["stages"][0]["status"] = "SUCCESS"
        forged["actions_result"] = "SUCCESS"
        with pytest.raises(ValueError):
            validate_report(forged)
        assert not node_accepts(forged)


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_nominal_metrics_and_other_scenarios_keep_their_contract(scenario):
    r = report(scenario, ha_detail(scenario))
    assert (
        r["actions_result"] == "SUCCESS" and not r["stages"][0]["metrics"]["recovered"]
    )
    assert validate_report(r) and node_accepts(r)


@pytest.mark.parametrize("scenario", ["refresh-v4", "open-errors", "cleanup"])
def test_r1_recovery_does_not_apply_to_other_scenarios(scenario):
    source = recovery_detail("availability")
    try:
        r = report(scenario, source)
    except ValueError:
        forged = envelope("ha", scenario)
        forged["stages"][0]["detail"] = source
        with pytest.raises(ValueError):
            validate_report(forged)
        assert not node_accepts(forged)
        return
    assert r["actions_result"] == "FAILURE"
    assert validate_report(r) and node_accepts(r)


@pytest.mark.parametrize("scenario", SCENARIOS)
@pytest.mark.parametrize("slot", ["top", "sample", "owner", "diagnostic"])
def test_unknown_fields_and_private_strings_are_refused_by_both(scenario, slot):
    r = report(scenario, recovery_detail(scenario))
    d = r["stages"][0]["detail"]
    target = {
        "top": d,
        "sample": d["evidence"]["samples"][0],
        "owner": d["evidence"]["diagnostic"]["owners"][0],
        "diagnostic": d["evidence"]["diagnostic"],
    }[slot]
    target["PRIVATE_PAYLOAD"] = "b" * 32
    with pytest.raises(
        ValueError, match="campaign_contract_refused|invalid offline HA session proof"
    ):
        validate_report(r)
    assert not node_accepts(r)


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_reopened_session_without_a_valid_read_cannot_credit_a_b7_value(scenario):
    d = recovery_detail(scenario)
    e = d["evidence"]
    last = e["samples"][-1]
    last.update(decoded=False, available=True, error="transport")
    for o in (
        last["observation"],
        e["window"]["observation"],
        e["cleanup"]["observation"],
    ):
        o.update(read_generation=None, read_sequence=None)
    e["diagnostic"]["owners"][1]["last_read"] = None
    r = report(scenario, d)
    m = r["stages"][0]["metrics"]
    assert m["available"] and not m["recovered"] and r["actions_result"] == "FAILURE"
    assert validate_report(r) and node_accepts(r)
    forged = copy.deepcopy(r)
    fm = forged["stages"][0]["metrics"]
    fm.update(recovered=True, reads_ok=max(1, fm["reads_ok"]))
    forged["stages"][0]["status"] = "SUCCESS"
    forged["actions_result"] = "SUCCESS"
    with pytest.raises(ValueError):
        validate_report(forged)
    assert not node_accepts(forged)


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_f1_and_sample_relative_origins_need_not_be_identical(scenario):
    d = recovery_detail(scenario)
    f = d["evidence"]["diagnostic"]
    # F1 is installed before the scenario window starts; its times can include
    # setup overhead. Compare its close/read times only within that same clock.
    f["end_ms"] += 100
    f["first"][2] += 100
    for owner in f["owners"]:
        owner["close"] = [v + 100 for v in owner["close"]]
        if owner["last_read"] is not None:
            owner["last_read"][1] += 100
    d["supervisor"]["elapsed_ms"] += 100
    r = report(scenario, d)
    assert r["actions_result"] == "SUCCESS"
    assert validate_report(r) and node_accepts(r)


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_public_summary_keeps_the_incident_and_counts_visible(tmp_path, scenario):
    import base64
    import os
    import subprocess

    from tests.test_campaign_runtime import ROOT

    r = report(scenario, recovery_detail(scenario))
    event = tmp_path / "event.json"
    event.write_text(json.dumps(dict(inputs=dict(scenario=scenario))))
    output = tmp_path / "output"
    summary = tmp_path / "summary"
    script = """
const m=require('node:module'),load=m._load;
m._load=function(n,...args){
 if(/http|https|net|tls|child_process|dns/.test(n))throw Error('network forbidden');
 return load.call(this,n,...args);};
require('./.github/scripts/campaign-report.cjs').publish();
"""
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
        env=dict(
            PATH=os.environ["PATH"],
            CAMPAIGN="ha",
            RUNNER_TEMP=str(tmp_path),
            GITHUB_EVENT_PATH=str(event),
            GITHUB_OUTPUT=str(output),
            GITHUB_STEP_SUMMARY=str(summary),
            COLLECT_RESULT="success",
            PUBLIC_REPORT_B64=base64.b64encode(
                json.dumps(r, separators=(",", ":")).encode()
            ).decode(),
        ),
    )
    assert result.returncode == 0 and result.stderr == ""
    text = summary.read_text()
    assert (
        "récupération prouvée true" in text
        and "réutilisation réellement attestée false" in text
    )
    assert "Premier incident : a / génération 1 / eof" in text
    assert "PRIVATE_PAYLOAD" not in text + result.stdout + result.stderr
    published = json.loads(
        (tmp_path / "hoben-campaign-published" / "report.json").read_text()
    )
    assert (
        published["stages"][0]["metrics"]["reads_ok"]
        == published["stages"][0]["metrics"]["reads"] - 1
    )


def nominal_two_opens_detail(scenario):
    """Historical nominal report, with fresh reads but no F1 recovery claim."""
    d = ha_detail(scenario)
    e = d["evidence"]
    for index, sample in enumerate(e["samples"]):
        if index:
            sample["observation"].update(
                attempts=2,
                generation=2,
                read_generation=2,
                read_sequence=index,
                cleaned_generation=1,
            )
    e["window"]["observation"] = copy.deepcopy(e["samples"][-1]["observation"])
    e["cleanup"]["observation"] = {
        **e["window"]["observation"],
        "stopped": True,
        "cleaned_generation": 2,
    }
    return d


@pytest.mark.parametrize("scenario", SCENARIOS)
@pytest.mark.parametrize("engine", ["python", "node"])
def test_historical_nominal_predicate_allows_two_opens_without_f1_claim(
    scenario, engine
):
    r = report(scenario, nominal_two_opens_detail(scenario))
    value = r["stages"][0]
    m = value["metrics"]
    assert m["opens"] == 2 and m["available"] and m["cleanup"]
    assert m["reads"] == m["reads_ok"] == (3 if scenario == "session-reuse" else 2)
    assert not m["recovered"] and "diagnostic_schema" not in value["detail"]["evidence"]
    assert m["reused"] is (scenario == "session-reuse")
    # Exact base predicate: every planned read succeeds and is available;
    # session-reuse additionally needs reused. No opens==1 clause existed.
    value["status"] = r["actions_result"] = "SUCCESS"
    if engine == "python":
        assert validate_report(r) == r
    else:
        assert node_accepts(r)


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_nominal_success_without_f1_cannot_be_relabelled_as_recovered(scenario):
    r = report(scenario, nominal_two_opens_detail(scenario))
    assert r["actions_result"] == "SUCCESS"
    forged = copy.deepcopy(r)
    forged["stages"][0]["metrics"]["recovered"] = True
    with pytest.raises(ValueError):
        validate_report(forged)
    assert not node_accepts(forged)


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_failed_read_with_two_opens_still_needs_strict_f1_recovery(scenario):
    d = nominal_two_opens_detail(scenario)
    d["evidence"]["samples"][0].update(
        decoded=False, available=False, error="transport"
    )
    r = report(scenario, d)
    assert not r["stages"][0]["metrics"]["recovered"]
    assert r["actions_result"] == "FAILURE"
    assert validate_report(r) and node_accepts(r)
    forged = copy.deepcopy(r)
    forged["stages"][0]["status"] = forged["actions_result"] = "SUCCESS"
    with pytest.raises(ValueError):
        validate_report(forged)
    assert not node_accepts(forged)


def test_two_opens_do_not_replace_session_reuse_evidence():
    d = nominal_two_opens_detail("session-reuse")
    for o in (
        d["evidence"]["samples"][-1]["observation"],
        d["evidence"]["window"]["observation"],
        d["evidence"]["cleanup"]["observation"],
    ):
        o["read_sequence"] = 3  # No two adjacent reads prove contiguous reuse.
    r = report("session-reuse", d)
    assert not r["stages"][0]["metrics"]["reused"]
    assert r["actions_result"] == "FAILURE"
    assert validate_report(r) and node_accepts(r)


def nominal_initial_retry_detail(scenario):
    """Two attempts, only one accepted session; all scheduled reads succeed."""
    d = ha_detail(scenario)
    e = d["evidence"]
    for s in e["samples"]:
        s["observation"]["attempts"] = 2
    last = e["samples"][-1]
    e["window"]["observation"] = copy.deepcopy(last["observation"])
    e["cleanup"]["observation"] = {
        **last["observation"],
        "stopped": True,
        "cleaned_generation": 1,
    }
    end = e["window"]["elapsed_ms"] + 1
    e.update(
        diagnostic_schema=1,
        diagnostic=dict(
            end_ms=end,
            first=["a", 1, 0, "tls", "opening", "transport_connect", None],
            terminal=None,
            cleanup=None,
            invalid=False,
            owners=[
                dict(
                    role="a",
                    generation=1,
                    accepted=False,
                    accepted_generation=None,
                    close_client_subcode=None,
                    close=[0, 0, 0, 0],
                    stage="reaped",
                    pending=0,
                    last_read=None,
                ),
                dict(
                    role="a",
                    generation=2,
                    accepted=True,
                    accepted_generation=1,
                    close_client_subcode=None,
                    close=[end - 1, end - 1, end, end],
                    stage="reaped",
                    pending=0,
                    last_read=[len(e["samples"]), last["at_ms"], end - last["at_ms"]],
                ),
            ],
        ),
    )
    return d


@pytest.mark.parametrize("scenario", SCENARIOS)
@pytest.mark.parametrize("engine", ["python", "node"])
def test_nominal_f1_transient_opening_failure_is_not_an_unproved_recovery(
    scenario, engine
):
    r = report(scenario, nominal_initial_retry_detail(scenario))
    r["stages"][0]["status"] = r["actions_result"] = "SUCCESS"
    r["stages"][0]["metrics"]["error"] = "none"  # Historical nominal projection.
    assert not r["stages"][0]["metrics"]["recovered"]
    if engine == "python":
        assert validate_report(r) == r
    else:
        assert node_accepts(r)
    forged = copy.deepcopy(r)
    forged["stages"][0]["metrics"]["recovered"] = True
    with pytest.raises(ValueError):
        validate_report(forged)
    assert not node_accepts(forged)


@pytest.mark.parametrize("scenario", SCENARIOS)
@pytest.mark.parametrize(
    "unsafe",
    [
        "terminal",
        "cleanup",
        "authentication",
        "authorization",
        "internal",
        "cancelled",
        "exhausted",
        "closed",
    ],
)
def test_terminal_or_unsafe_f1_events_still_refuse_nominal_success(scenario, unsafe):
    d = nominal_initial_retry_detail(scenario)
    f = d["evidence"]["diagnostic"]
    if unsafe == "terminal":
        f["terminal"] = ["a", 2, 1000, "internal", "unknown", "session", None]
    elif unsafe == "cleanup":
        f["cleanup"] = ["a", 2, 1000, "cleanup_failed", "cleanup", "session", None]
    else:
        f["first"][3] = unsafe
    r = report(scenario, d)
    assert (
        r["actions_result"] == "FAILURE" and not r["stages"][0]["metrics"]["recovered"]
    )
    assert validate_report(r) and node_accepts(r)
