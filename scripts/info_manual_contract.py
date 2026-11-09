"""Closed D7 passive-worker evidence. JSON consistency is not live provenance.

Only the protected collector's independently authenticated receipt can publish
this as live evidence. D1's offline validator is deliberately not reused.
"""

import copy
import json

from scripts.info_delivery_supervisor import LIMITS as OFFLINE_LIMITS

LIMITS = {
    "observation_ms": OFFLINE_LIMITS["observation_ms"],
    "cleanup_ms": OFFLINE_LIMITS["cleanup_reserve_ms"],
    "total_ms": OFFLINE_LIMITS["total_ms"],
}
ERRORS = {
    "none",
    "context",
    "identity",
    "clock",
    "budget",
    "tls",
    "transport",
    "timeout",
    "authentication",
    "authorization",
    "protocol",
    "closed",
    "internal",
    "cancelled",
    "cleanup",
    "process",
    "provenance",
}
OBSERVATION = {
    "started": False,
    "opening_accepted": False,
    "tls_verified": False,
    "connections": 0,
    "deliveries": 0,
    "received_bytes": 0,
    "candidate_observed": False,
    "candidate_delivery_bytes": 0,
    "candidate_at_ms": None,
    "discarded_deliveries": 0,
    "continuation": "not_proven",
    "post_candidate_reads": 0,
    "pings_validated": 0,
    "pongs_written": 0,
    "read_requests": 0,
    "verified_reads": 0,
    "observation_complete": False,
    "first_error": "none",
    "cleanup_error": "none",
    "cleanup_started_ms": None,
    "transport_close_requested": False,
    "transport_close_completed": False,
    "rx_stopped": False,
    "operations_stopped": False,
    "cleanup_attested": False,
    "elapsed_ms": 0,
}
PROCESS = {
    "launch_attempted": False,
    "spawned": False,
    "isolated": False,
    "child_report_bound": False,
    "term_requested": False,
    "kill_requested": False,
    "children_reaped": 0,
    "group_empty": False,
    "guardian_waited": False,
    "control_closed": False,
    "exit_ok": False,
    "deadline_exceeded": False,
    "first_error": "none",
    "elapsed_ms": 0,
}
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
    "contract_digest",
    "launch_tag_sha",
}


class InvalidInfoManual(ValueError):
    def __init__(self):
        super().__init__("invalid_info_manual_evidence")


def need(value):
    if not value:
        raise InvalidInfoManual()


def exact(value, keys):
    need(type(value) is dict and set(value) == set(keys))


def integer(value, maximum):
    return type(value) is int and 0 <= value <= maximum


def validate_proof(proof):
    exact(proof, PROOF_KEYS)
    for key in ("merge_sha", "candidate_sha", "claim_sha", "launch_tag_sha"):
        need(type(proof[key]) is str and len(proof[key]) == 40)
        need(set(proof[key]) <= set("0123456789abcdef"))
    for key in ("environment_digest", "contract_digest"):
        need(type(proof[key]) is str and len(proof[key]) == 64)
        need(set(proof[key]) <= set("0123456789abcdef"))
    for key in ("pr_number", "ci_run_id", "run_id", "environment_id"):
        need(integer(proof[key], 9007199254740991) and proof[key] > 0)
    need(type(proof["run_attempt"]) is int and proof["run_attempt"] == 1)
    return copy.deepcopy(proof)


def validate_observation(value):
    exact(value, OBSERVATION)
    for key, default in OBSERVATION.items():
        if type(default) is bool:
            need(type(value[key]) is bool)
    for key in ("connections", "discarded_deliveries", "post_candidate_reads"):
        need(integer(value[key], 1))
    for key in (
        "deliveries",
        "pings_validated",
        "pongs_written",
        "read_requests",
        "verified_reads",
    ):
        need(integer(value[key], 8192))
    need(integer(value["received_bytes"], 1048576))
    need(integer(value["candidate_delivery_bytes"], 4096))
    need(integer(value["elapsed_ms"], LIMITS["total_ms"]))
    for key in ("candidate_at_ms", "cleanup_started_ms"):
        need(value[key] is None or integer(value[key], value["elapsed_ms"]))
    need(type(value["first_error"]) is str and value["first_error"] in ERRORS)
    need(type(value["cleanup_error"]) is str and value["cleanup_error"] in ERRORS)
    # Current strategy never advances the parser after an opaque candidate.
    # A future SUCCESS implementation needs its own independent proof contract.
    need(value["continuation"] == "not_proven" and value["post_candidate_reads"] == 0)
    need(value["pongs_written"] <= value["pings_validated"])
    need(value["verified_reads"] <= value["read_requests"])
    if value["candidate_observed"]:
        need(value["started"] and value["opening_accepted"])
        need(value["candidate_at_ms"] is not None)
        need(value["candidate_at_ms"] < LIMITS["observation_ms"])
        need(1 <= value["candidate_delivery_bytes"] <= 4096)
        need(value["deliveries"] >= 1)
        need(value["received_bytes"] >= value["candidate_delivery_bytes"])
    else:
        need(value["candidate_at_ms"] is None)
        need(value["candidate_delivery_bytes"] == value["discarded_deliveries"] == 0)
    if value["discarded_deliveries"]:
        need(value["candidate_observed"])
    if value["observation_complete"]:
        need(value["cleanup_started_ms"] is not None)
        need(value["cleanup_started_ms"] >= LIMITS["observation_ms"])
    if value["opening_accepted"]:
        need(value["started"] and value["tls_verified"] and value["connections"] == 1)
    if value["cleanup_attested"]:
        need(value["cleanup_started_ms"] is not None)
        need(
            all(
                value[k]
                for k in (
                    "transport_close_requested",
                    "transport_close_completed",
                    "rx_stopped",
                    "operations_stopped",
                )
            )
        )
        need(value["cleanup_error"] == "none")
    return copy.deepcopy(value)


def validate_process(value):
    exact(value, PROCESS)
    for key, default in PROCESS.items():
        if type(default) is bool:
            need(type(value[key]) is bool)
    need(integer(value["children_reaped"], 16))
    need(integer(value["elapsed_ms"], LIMITS["total_ms"]))
    need(type(value["first_error"]) is str and value["first_error"] in ERRORS)
    if value["isolated"]:
        need(value["spawned"])
    if value["spawned"]:
        need(value["launch_attempted"])
    if value["group_empty"]:
        need(value["isolated"] and value["children_reaped"] >= 1)
    if value["exit_ok"]:
        need(value["guardian_waited"])
    if value["kill_requested"]:
        need(value["term_requested"])
    if value["deadline_exceeded"]:
        need(
            value["first_error"] == "timeout"
            and value["elapsed_ms"] == LIMITS["total_ms"]
        )
    return copy.deepcopy(value)


def verdict(observation, process):
    o, p = validate_observation(observation), validate_process(process)
    if not p["launch_attempted"] and not o["started"]:
        return "NOT RUN", "not_started"
    process_ok = (
        all(
            p[k]
            for k in (
                "spawned",
                "isolated",
                "child_report_bound",
                "group_empty",
                "guardian_waited",
                "control_closed",
                "exit_ok",
            )
        )
        and p["first_error"] == "none"
        and not p["term_requested"]
        and not p["kill_requested"]
    )
    if not process_ok:
        return "FAILURE", "process"
    if o["first_error"] != "none":
        return "FAILURE", o["first_error"]
    if not o["cleanup_attested"]:
        return "FAILURE", "cleanup"
    if not o["opening_accepted"] or o["connections"] != 1 or not o["tls_verified"]:
        return "FAILURE", "provenance"
    if o["candidate_observed"] and o["discarded_deliveries"] == 1:
        return "INCONCLUSIVE", "candidate_observed_continuation_not_proven"
    if not o["candidate_observed"] and o["observation_complete"]:
        return "INCONCLUSIVE", "candidate_absent"
    return "FAILURE", "provenance"


def build_report(proof, observation, process):
    if observation["started"]:
        need(process["spawned"] and observation["elapsed_ms"] <= process["elapsed_ms"])
    result, reason = verdict(observation, process)
    report = {
        "schema": 2,
        "scenario": "info-passive-observation",
        "selection": "hoben-live",
        "execution": "protected_worker",
        "info_framing": "INCONCLUSIVE",
        "boundary_proven": False,
        "limits": dict(LIMITS),
        "proof": validate_proof(proof),
        "observation": validate_observation(observation),
        "process": validate_process(process),
        "result": result,
        "reason": reason,
    }
    need(len(json.dumps(report, separators=(",", ":")).encode()) <= 8192)
    return report


def validate_report(report, proof):
    exact(
        report,
        {
            "schema",
            "scenario",
            "selection",
            "execution",
            "info_framing",
            "boundary_proven",
            "limits",
            "proof",
            "observation",
            "process",
            "result",
            "reason",
        },
    )
    expected = build_report(proof, report["observation"], report["process"])
    need(type(report["boundary_proven"]) is bool and report == expected)
    return expected
