"""R2 campaign receipts are fixtures, independently checked by Python and Node."""

import copy
import json

import pytest

from scripts.campaign_runtime_contract import stage, validate_report
from scripts.ha_campaign_evidence import project
from tests.test_campaign_runtime import envelope, ha_detail, node_accepts


def recovered_detail(category="eof"):
    d = ha_detail("hoben-live", recovered=True)
    e = d["evidence"]
    e["window"]["clock"] = "monotonic"
    d["supervisor"]["elapsed_ms"] = 300002
    for s in e["samples"][2:]:
        o = s["observation"]
        o["loss_kind"] = "close_client" if category == "close_client" else "transport"
        o["close_client_subcode"] = 3 if category == "close_client" else None
    e["window"]["observation"] = copy.deepcopy(e["samples"][-1]["observation"])
    e["cleanup"]["observation"] = {
        **e["window"]["observation"],
        "cleaned_generation": 2,
        "stopped": True,
    }
    e.update(
        diagnostic_schema=1,
        diagnostic=dict(
            end_ms=300002,
            invalid=False,
            first=[
                "a",
                1,
                100000,
                category,
                "post_open" if category == "close_client" else "tls_read",
                "session" if category == "close_client" else "transport_read",
                3 if category == "close_client" else None,
            ],
            terminal=None,
            cleanup=None,
            owners=[
                dict(
                    role="a",
                    generation=1,
                    accepted=True,
                    accepted_generation=1,
                    close_client_subcode=3 if category == "close_client" else None,
                    close=[100000, 100000, 100001, 100001],
                    stage="reaped",
                    pending=0,
                    last_read=[2, 50000, 250002],
                ),
                dict(
                    role="a",
                    generation=2,
                    accepted=True,
                    accepted_generation=2,
                    close_client_subcode=None,
                    close=[300000, 300000, 300001, 300001],
                    stage="reaped",
                    pending=0,
                    last_read=[3, 250000, 50002],
                ),
            ],
        ),
    )
    return d


def report(d):
    v = stage(
        "ha",
        "hoben-live",
        started=True,
        reason="observed",
        elapsed_ms=d["supervisor"]["elapsed_ms"],
        metrics=project("hoben-live", d),
        detail=d,
    )
    return envelope("ha", "hoben-live", [v])


@pytest.mark.parametrize(
    "category", ["eof", "close_client", "timeout", "transport", "tls"]
)
@pytest.mark.parametrize("engine", ["python", "node"])
def test_recovery_with_full_300s_proof_keeps_real_metrics(category, engine):
    r = report(recovered_detail(category))
    m = r["stages"][0]["metrics"]
    assert m["recovered"] and not m["continuous"]
    assert m["reads"] == 6 and m["reads_ok"] == 5 and m["useful_ms"] == 300000
    r["actions_result"] = r["stages"][0]["status"] = "SUCCESS"
    assert (validate_report(r) == r) if engine == "python" else node_accepts(r)
    assert len(json.dumps(r["stages"][0]["detail"]).encode()) <= 8192


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_f1",
        "first_missing",
        "unaccepted_old",
        "new_without_read",
        "old_cleanup_missing",
        "late_old_cleanup",
        "terminal",
        "cleanup_error",
        "auth",
        "internal",
        "protocol",
        "cancelled",
        "opening",
        "unknown_phase",
        "last_stale",
        "short_window",
        "tail_loss",
        "inactive",
        "supervisor_timeout",
        "unreaped",
        "false_read_count",
        "extra_sample",
        "private",
        "age_tamper",
        "first_read_missing",
        "first_new_unclean",
        "second_generation_failure",
        "final_cleanup_missing",
        "close_unrecognized",
        "phase_boundary",
        "clock_synthetic",
        "read_sequence_gap",
        "new_close_missing",
        "process_overrun",
        "useful_budget",
        "extra_key",
    ],
)
def test_incomplete_or_unsafe_recovery_never_accepts_success(mutation):
    forged = report(recovered_detail())
    d = recovered_detail()
    e, f = d["evidence"], d["evidence"]["diagnostic"]
    if mutation == "missing_f1":
        del e["diagnostic_schema"], e["diagnostic"]
    elif mutation == "first_missing":
        f["first"] = None
    elif mutation == "unaccepted_old":
        f["owners"][0].update(accepted=False, accepted_generation=None, last_read=None)
        f["owners"][1]["accepted_generation"] = 1
    elif mutation == "new_without_read":
        f["owners"][1]["last_read"] = None
    elif mutation == "old_cleanup_missing":
        f["owners"][0].update(close=[100000, 100000, 100001, None], stage="tls_closed")
    elif mutation == "late_old_cleanup":
        f["owners"][0]["close"] = [250001] * 4
    elif mutation == "terminal":
        f["terminal"] = f["first"].copy()
    elif mutation == "cleanup_error":
        f["cleanup"] = ["a", 2, 300000, "cleanup_failed", "cleanup", "session", None]
    elif mutation in {"auth", "internal", "protocol", "cancelled"}:
        f["first"][3] = "authentication" if mutation == "auth" else mutation
    elif mutation == "opening":
        f["first"][4] = "opening"
    elif mutation == "unknown_phase":
        f["first"][4] = "unknown"
    elif mutation == "last_stale":
        e["samples"][-1]["decoded"] = False
    elif mutation == "short_window":
        e["window"]["elapsed_ms"] = 299999
    elif mutation == "tail_loss":
        e["cleanup"]["observation"].update(loss_generation=2)
    elif mutation == "inactive":
        e["window"]["active"] = False
    elif mutation == "supervisor_timeout":
        d["supervisor"]["reason"] = "timeout"
    elif mutation == "unreaped":
        d["supervisor"]["reaped"] = False
    elif mutation == "false_read_count":
        f["owners"][1]["last_read"][0] = 4
    elif mutation == "extra_sample":
        e["samples"].append(copy.deepcopy(e["samples"][-1]))
    elif mutation == "private":
        e["payload"] = "PRIVATE_PAYLOAD"
    elif mutation == "age_tamper":
        f["owners"][1]["last_read"][2] = 0
    elif mutation == "first_read_missing":
        e["samples"][0]["decoded"] = False
    elif mutation == "first_new_unclean":
        e["samples"][3]["observation"]["cleaned_generation"] = None
    elif mutation == "second_generation_failure":
        e["samples"][4]["decoded"] = False
    elif mutation == "final_cleanup_missing":
        e["cleanup"]["completed"] = False
    elif mutation == "close_unrecognized":
        f["first"][3:] = ["close_client", "post_open", "session", 7]
        f["owners"][0]["close_client_subcode"] = 7
        for s in e["samples"][2:]:
            s["observation"].update(loss_kind="close_client", close_client_subcode=7)
        for o in (e["window"]["observation"], e["cleanup"]["observation"]):
            o.update(loss_kind="close_client", close_client_subcode=7)
    elif mutation == "phase_boundary":
        f["first"][4] = "frame_boundary"
    elif mutation == "clock_synthetic":
        e["window"]["clock"] = "synthetic"
    elif mutation == "read_sequence_gap":
        e["samples"][3]["observation"]["read_sequence"] = 2
    elif mutation == "new_close_missing":
        f["owners"][1].update(close=[300000, 300000, None, None], stage="tls_close")
    elif mutation == "process_overrun":
        d["supervisor"]["elapsed_ms"] = 360001
    elif mutation == "useful_budget":
        d["supervisor"]["useful_ms"] = 300001
    elif mutation == "extra_key":
        f["first"].append("PRIVATE_PAYLOAD")
    try:
        r = report(d)
    except ValueError:
        forged["stages"][0]["detail"] = d
        with pytest.raises(ValueError):
            validate_report(forged)
        assert not node_accepts(forged)
        return
    assert r["actions_result"] == "FAILURE"
    assert validate_report(r) and node_accepts(r)
    forged = copy.deepcopy(r)
    forged["actions_result"] = forged["stages"][0]["status"] = "SUCCESS"
    with pytest.raises(ValueError):
        validate_report(forged)
    assert not node_accepts(forged)


def test_nominal_contract_and_legacy_recovery_without_f1_remain_distinct():
    d = ha_detail("hoben-live")
    d["evidence"]["window"]["clock"] = "monotonic"
    nominal = report(d)
    assert nominal["actions_result"] == "SUCCESS"
    assert nominal["stages"][0]["metrics"]["continuous"]
    assert not nominal["stages"][0]["metrics"]["recovered"]
    assert validate_report(nominal) and node_accepts(nominal)
    d = recovered_detail()
    del d["evidence"]["diagnostic_schema"], d["evidence"]["diagnostic"]
    legacy = report(d)
    assert legacy["actions_result"] == "FAILURE"
    assert not legacy["stages"][0]["metrics"]["recovered"]
    assert validate_report(legacy) and node_accepts(legacy)


def test_recovery_cannot_be_forged_from_legacy_generation_witnesses():
    d = recovered_detail()
    del d["evidence"]["diagnostic_schema"], d["evidence"]["diagnostic"]
    r = report(d)
    r["stages"][0]["metrics"]["recovered"] = True
    r["actions_result"] = r["stages"][0]["status"] = "SUCCESS"
    with pytest.raises(ValueError):
        validate_report(r)
    assert not node_accepts(r)


def test_f1_time_origin_can_precede_the_first_sample():
    d = recovered_detail()
    f = d["evidence"]["diagnostic"]
    f["end_ms"] += 1000
    f["first"][2] += 1000
    for row in f["owners"]:
        row["close"] = [v + 1000 for v in row["close"]]
        row["last_read"][1] += 1000
    d["supervisor"]["elapsed_ms"] += 1000
    r = report(d)
    assert r["actions_result"] == "SUCCESS"
    assert validate_report(r) and node_accepts(r)


def test_publication_distinguishes_300s_observation_from_continuity(tmp_path):
    import base64
    import os
    import subprocess

    from tests.test_campaign_runtime import ROOT

    r = report(recovered_detail())
    event, output, summary = (tmp_path / n for n in ("event", "output", "summary"))
    event.write_text(json.dumps(dict(inputs=dict(scenario="hoben-live"))))
    result = subprocess.run(
        [
            "node",
            "-e",
            """
const m=require('node:module'),load=m._load;
m._load=function(n,...a){
 if(/http|https|net|tls|child_process|dns/.test(n))throw Error('network forbidden');
 return load.call(this,n,...a)};
require('./.github/scripts/campaign-report.cjs').publish();
""",
        ],
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
    assert "continuité false ; récupération prouvée true" in text
    assert "observation utile 300.000 s ; lectures fraîches 5 / tentées 6" in text
    assert "Premier incident : a / génération 1 / eof" in text
    assert "PRIVATE_PAYLOAD" not in text + result.stdout + result.stderr
    assert (
        json.loads((tmp_path / "hoben-campaign-published/report.json").read_text()) == r
    )
