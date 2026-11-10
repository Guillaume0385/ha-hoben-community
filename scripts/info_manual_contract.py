"""Closed D8 continuous TLS-delivery evidence; no inferred Info frame or V4 recovery.

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
    "candidate_delivery_offset": None,
    "discarded_deliveries": 0,
    "continuation": "not_proven",
    "post_candidate_reads": 0,
    "tls_deliveries_since_candidate": 0,
    "tls_bytes_since_candidate": 0,
    "delivery_timeline": [],
    "delivery_timeline_omitted": 0,
    "candidate_leads_unproven": 0,
    "ping_leads_unproven": 0,
    "response_leads_unproven": 0,
    "data_updated_leads_unproven": 0,
    "candidate_segments": [],
    "candidate_segments_omitted": 0,
    "peer_eof": False,
    "unconfirmed_read_requests": 0,
    "first_post_info_valid_v4_at_ms": None,
    "recovery_stability_start_ms": None,
    "recovery_stability_elapsed_ms": 0,
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
    """Strict D8 scalar/sequence projection; TLS deliveries are not messages."""
    exact(value, OBSERVATION)
    for key, default in OBSERVATION.items():
        if type(default) is bool:
            need(type(value[key]) is bool)
    need(integer(value["connections"], 1))
    need(integer(value["discarded_deliveries"], 1))
    for key in (
        "deliveries", "post_candidate_reads", "tls_deliveries_since_candidate",
        "delivery_timeline_omitted", "candidate_leads_unproven",
        "ping_leads_unproven", "response_leads_unproven",
        "data_updated_leads_unproven", "pings_validated", "pongs_written",
        "read_requests", "verified_reads", "unconfirmed_read_requests",
    ):
        need(integer(value[key], 8192))
    need(integer(value["candidate_segments_omitted"], 8192))
    for key in ("received_bytes", "tls_bytes_since_candidate"):
        need(integer(value[key], 1048576))
    need(integer(value["candidate_delivery_bytes"], 4096))
    need(integer(value["elapsed_ms"], LIMITS["total_ms"]))
    for key in (
        "candidate_at_ms", "cleanup_started_ms",
        "first_post_info_valid_v4_at_ms", "recovery_stability_start_ms",
    ):
        need(value[key] is None or integer(value[key], value["elapsed_ms"]))
    need(type(value["first_error"]) is str and value["first_error"] in ERRORS)
    need(type(value["cleanup_error"]) is str and value["cleanup_error"] in ERRORS)
    need(value["continuation"] == "not_proven")
    need(
        value["verified_reads"] <= value["read_requests"] - value["unconfirmed_read_requests"]
        and value["first_post_info_valid_v4_at_ms"] is None
        and value["recovery_stability_start_ms"] is None
        and value["recovery_stability_elapsed_ms"] == 0
    )
    need(value["pongs_written"] <= value["pings_validated"])
    need(
        value["post_candidate_reads"] + bool(value["candidate_observed"])
        == value["tls_deliveries_since_candidate"]
        and value["tls_deliveries_since_candidate"] <= value["deliveries"]
        and value["tls_bytes_since_candidate"] <= value["received_bytes"]
    )
    heads = sum(value[k] for k in (
        "candidate_leads_unproven", "ping_leads_unproven",
        "response_leads_unproven", "data_updated_leads_unproven",
    ))
    need(heads <= value["post_candidate_reads"])
    timeline = value["delivery_timeline"]
    need(type(timeline) is list and len(timeline) <= 96)
    need(value["delivery_timeline_omitted"] ==
         value["tls_deliveries_since_candidate"] - len(timeline))
    previous = -1
    for entry in timeline:
        need(type(entry) is list and len(entry) == 2)
        at, size = entry
        need(integer(at, value["elapsed_ms"]) and at >= previous)
        need(integer(size, 4096) and size >= 1)
        previous = at
    if timeline:
        need(sum(entry[1] for entry in timeline) <= value["tls_bytes_since_candidate"])
        if not value["delivery_timeline_omitted"]:
            need(sum(entry[1] for entry in timeline) == value["tls_bytes_since_candidate"])
    segments = value["candidate_segments"]
    need(type(segments) is list and len(segments) <= 16)
    need(len(segments) + value["candidate_segments_omitted"]
         == int(value["candidate_observed"]) + value["candidate_leads_unproven"])
    for segment in segments:
        exact(segment, {
            "start_at_ms", "observed_bytes_between_candidates",
            "tls_deliveries", "end_kind",
        })
        need(integer(segment["start_at_ms"], value["elapsed_ms"]))
        need(integer(segment["observed_bytes_between_candidates"], 1048576))
        need(integer(segment["tls_deliveries"], 8192))
        need(segment["observed_bytes_between_candidates"] >= segment["tls_deliveries"] >= 1)
        need(segment["end_kind"] in (
            "delivery_lead_unproven", "tls_eof", "observation_end",
        ))
    if value["candidate_observed"]:
        need(value["started"] and value["opening_accepted"])
        need(value["candidate_at_ms"] is not None)
        need(value["candidate_at_ms"] < LIMITS["observation_ms"])
        need(value["candidate_delivery_offset"] == 0)
        need(1 <= value["candidate_delivery_bytes"] <= 4096)
        need(value["discarded_deliveries"] == 1)
        need(value["received_bytes"] >= value["candidate_delivery_bytes"])
        need(value["tls_bytes_since_candidate"] >= value["candidate_delivery_bytes"])
        need(timeline and timeline[0] == [
            value["candidate_at_ms"], value["candidate_delivery_bytes"],
        ])
    else:
        need(value["candidate_at_ms"] is value["candidate_delivery_offset"] is None)
        need(value["candidate_delivery_bytes"] == value["discarded_deliveries"] == 0)
        need(value["tls_deliveries_since_candidate"] == 0)
        need(value["tls_bytes_since_candidate"] == 0)
        need(not timeline and not segments)
        need(heads == 0 and value["candidate_segments_omitted"] == 0)
    if value["observation_complete"]:
        need(value["cleanup_started_ms"] is not None)
        need(value["cleanup_started_ms"] >= LIMITS["observation_ms"])
    if value["opening_accepted"]:
        need(value["started"] and value["tls_verified"] and value["connections"] == 1)
    if value["peer_eof"]:
        need(value["started"] and value["opening_accepted"])
    if value["cleanup_attested"]:
        need(value["cleanup_started_ms"] is not None)
        need(
            all(value[k] for k in (
                "transport_close_requested", "transport_close_completed",
                "rx_stopped", "operations_stopped",
            ))
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
    if o["peer_eof"]:
        return "INCONCLUSIVE", "server_eof"
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
        "schema": 3,
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
