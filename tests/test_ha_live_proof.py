"""Closed inactive live contract and independent Node validator; no network."""

import copy
import json
import subprocess

import pytest

from scripts.ha_live_proof import (
    build_report,
    empty_evidence,
    encode_report,
    parse_report,
)
from scripts.ha_session_proof import parse_report as parse_c1
from tests.test_ha_session_proof import ROOT, proof

PROVENANCE = {"merge_sha": "a" * 40, "pr_number": 1, "run_id": 2, "run_attempt": 1}


def receipt(**updates):
    return {
        "started": True,
        "reason": "completed",
        "memory_bytes": 1024**3,
        "pids": 128,
        "useful_ms": 300000,
        "process_ms": 360000,
        "elapsed_ms": 1000,
        "oom_killed": False,
        "pids_limited": False,
        "reaped": True,
        "network": "none",
        **updates,
    }


def report(recovered=False, **updates):
    old = proof(recovered=recovered)
    evidence = {k: old[k] for k in ("completed", "samples", "cleanup")}
    return build_report(PROVENANCE, receipt(**updates), evidence)


def node_accepts(text):
    result = subprocess.run(
        [
            "node",
            "-e",
            "const p=require('./scripts/ha-live-proof.cjs');let s='';"
            "process.stdin.on('data',x=>s+=x);process.stdin.on('end',()=>{"
            "try{p.parseReport(s);process.stdout.write('ok')}"
            "catch(e){process.stdout.write(e.message);process.exitCode=1}});",
        ],
        cwd=ROOT,
        input=text,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.stderr == ""
    assert result.stdout in {"ok", "invalid inactive HA live proof"}
    return result.returncode == 0


@pytest.mark.parametrize("recovered", [False, True])
def test_actual_evidence_contract_is_distinct_from_c1_and_never_admitted(recovered):
    r = report(recovered)
    text = encode_report(r)
    assert parse_report(text) == r and node_accepts(text)
    assert r["outcome"] == ("SUCCESS" if recovered else "INCONCLUSIVE")
    with pytest.raises(ValueError):
        parse_c1(text)
    with pytest.raises(ValueError):
        parse_report(json.dumps(proof(), separators=(",", ":")))


@pytest.mark.parametrize(
    "reason", ["cancelled", "timeout", "memory", "processes", "worker_failure"]
)
def test_local_stop_cannot_claim_natural_reconnection(reason):
    r = report(
        True,
        reason=reason,
        oom_killed=reason == "memory",
        pids_limited=reason == "processes",
    )
    assert r["criteria"]["reconnection"] == "INCONCLUSIVE"
    assert r["outcome"] == "FAILURE"
    assert node_accepts(encode_report(r))


def test_missing_confinement_is_not_run_without_invented_cleanup():
    r = build_report(
        PROVENANCE,
        receipt(started=False, reason="unavailable", reaped=False),
        empty_evidence(),
    )
    assert r["outcome"] == "NOT RUN"
    assert set(r["criteria"].values()) == {"NOT RUN"}
    assert node_accepts(encode_report(r))


BAD = [
    ((), "schema", True),
    ((), "execution", "live"),
    ((), "admission", "VERIFIED"),
    ((), "boundary_proven", True),
    ((), "private", "PRIVATE_PAYLOAD"),
    (("provenance",), "merge_sha", "PRIVATE_PAYLOAD"),
    (("provenance",), "run_attempt", 2),
    (("supervisor",), "memory_bytes", 1024**3 + 1),
    (("supervisor",), "memory_bytes", True),
    (("supervisor",), "pids", 129),
    (("supervisor",), "pids", 0),
    (("supervisor",), "process_ms", 360001),
    (("supervisor",), "useful_ms", 300001),
    (("supervisor",), "elapsed_ms", 360001),
    (("supervisor",), "network", "bridge"),
    (("supervisor",), "reaped", False),
    (("supervisor",), "started", False),
    (("supervisor",), "oom_killed", True),
    (("supervisor",), "pids_limited", True),
    (("samples", 0, "observation"), "read_sequence", 0),
    (("samples", 1, "observation"), "read_sequence", 1),
    (("samples", 3, "observation"), "read_generation", 1),
    (("samples", 3, "observation"), "cleaned_generation", None),
    (("samples", 2, "observation"), "close_client_subcode", 256),
    (("criteria",), "supervision", "NOT RUN"),
    (("criteria",), "reconnection", "INCONCLUSIVE"),
    ((), "outcome", "FAILURE"),
]


@pytest.mark.parametrize("path,key,value", BAD)
def test_forged_private_or_inconsistent_reports_are_rejected(path, key, value):
    r = report(True)
    target = r
    for part in path:
        target = target[part]
    target[key] = value
    raw = json.dumps(r, separators=(",", ":"))
    with pytest.raises(ValueError, match="^invalid inactive HA live proof$"):
        parse_report(raw)
    assert not node_accepts(raw)


@pytest.mark.parametrize("raw", ["{}", "null", "[]", "PRIVATE_PAYLOAD", " " * 8193])
def test_invalid_input_is_bounded_and_never_echoed(raw):
    with pytest.raises(ValueError, match="^invalid inactive HA live proof$"):
        parse_report(raw)
    assert not node_accepts(raw)


def test_canonical_encoding_and_evidence_cannot_override_parent_receipt():
    raw = encode_report(report())
    for text in [" " + raw, raw.replace('"schema":2', '"schema":2,"schema":2')]:
        with pytest.raises(ValueError):
            parse_report(text)
        assert not node_accepts(text)
    bad = copy.deepcopy(empty_evidence())
    bad["supervisor"] = receipt()
    with pytest.raises(ValueError):
        build_report(PROVENANCE, receipt(), bad)
