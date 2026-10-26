"""C2b live envelope, bound to independent admission/provenance expectations.

C1/C2a reports remain offline formats. Their pure validator is reused only for
resource/logical evidence, never as a relabelled source of live provenance.
"""

import json
import re

from scripts.ha_live_proof import build_report as logical_report
from scripts.ha_live_proof import empty_evidence
from scripts.ha_session_evidence import integer, keys, require

PROOF_KEYS = {
    "merge_sha",
    "candidate_sha",
    "pr_number",
    "ci_run_id",
    "run_id",
    "run_attempt",
    "environment_id",
    "environment_digest",
    "claim_sha",
}
EVIDENCE_KEYS = ("completed", "samples", "window", "cleanup")


def validate_proof(proof):
    keys(proof, PROOF_KEYS)
    for name in ("merge_sha", "candidate_sha", "claim_sha"):
        require(type(proof[name]) is str and re.fullmatch(r"[a-f0-9]{40}", proof[name]))
    require(
        type(proof["environment_digest"]) is str
        and re.fullmatch(r"[a-f0-9]{64}", proof["environment_digest"])
    )
    for name in ("pr_number", "ci_run_id", "run_id", "environment_id"):
        require(integer(proof[name], 1, 2**53 - 1))
    require(type(proof["run_attempt"]) is int and proof["run_attempt"] == 1)
    return proof


def build_live_report(proof, receipt, evidence):
    """Called only by the live supervisor after configuration/receipt validation."""
    validate_proof(proof)
    core = logical_report(
        {k: proof[k] for k in ("merge_sha", "pr_number", "run_id", "run_attempt")},
        receipt,
        evidence,
    )
    if core["window"]["clock"] != "unattested":
        require(core["window"]["clock"] == "monotonic")
    report = {
        "schema": 3,
        "scenario": "hoben-live",
        "execution": "live" if receipt["started"] else "NOT RUN",
        "admission": "VERIFIED",
        "boundary_proven": False,
        "proof": dict(proof),
        "supervisor": {**receipt, "network": "fixed_tls"},
        **{k: core[k] for k in EVIDENCE_KEYS},
        "criteria": core["criteria"],
        "outcome": (
            "SUCCESS"
            if all(
                core["criteria"][k] == "SUCCESS"
                for k in (
                    "collection",
                    "tls_reuse",
                    "continuous_300s",
                    "cleanup",
                    "supervision",
                )
            )
            else "NOT RUN"
            if core["outcome"] == "NOT RUN"
            else "FAILURE"
        ),
    }
    require(
        len(json.dumps(report, separators=(",", ":"), allow_nan=False).encode()) <= 8192
    )
    return report


def validate_live_report(report, expected):
    validate_proof(expected)
    keys(
        report,
        {
            "schema",
            "scenario",
            "execution",
            "admission",
            "boundary_proven",
            "proof",
            "supervisor",
            *EVIDENCE_KEYS,
            "criteria",
            "outcome",
        },
    )
    require(report["schema"] == 3 and type(report["schema"]) is int)
    require(report["scenario"] == "hoben-live" and report["admission"] == "VERIFIED")
    validate_proof(report["proof"])
    require(report["proof"] == expected and report["boundary_proven"] is False)
    require(report["supervisor"]["network"] == "fixed_tls")
    receipt = {**report["supervisor"], "network": "none"}
    rebuilt = build_live_report(
        expected, receipt, {k: report[k] for k in EVIDENCE_KEYS}
    )
    require(report == rebuilt)
    return report


def not_run(proof):
    from scripts.ha_live_proof import MEMORY_BYTES, PIDS, PROCESS_MS, USEFUL_MS

    return build_live_report(
        proof,
        {
            "started": False,
            "reason": "unavailable",
            "memory_bytes": MEMORY_BYTES,
            "pids": PIDS,
            "useful_ms": USEFUL_MS,
            "process_ms": PROCESS_MS,
            "elapsed_ms": 0,
            "oom_killed": False,
            "pids_limited": False,
            "reaped": False,
            "network": "none",
        },
        empty_evidence(),
    )
