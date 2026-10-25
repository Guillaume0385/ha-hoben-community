"""Inactive hoben-live contract; C2a never attests a GitHub admission or live run."""

import json
import re

from scripts.ha_session_evidence import (
    criteria,
    integer,
    keys,
    observation,
    outcome,
    progress,
    require,
)

MEMORY_BYTES = 1024**3
PIDS = 128
USEFUL_MS = 300_000
PROCESS_MS = 360_000
REPORT_BYTES = 8192
REFRESH_AT_MS = (0, 50_000, 100_000, 150_000, 200_000, 250_000)
REASONS = {
    "completed",
    "unavailable",
    "cancelled",
    "timeout",
    "memory",
    "processes",
    "worker_failure",
}


def validate_report(report):
    """Validate evidence and a separately owned supervisor receipt, fail closed."""
    keys(
        report,
        {
            "schema",
            "scenario",
            "execution",
            "admission",
            "boundary_proven",
            "provenance",
            "supervisor",
            "completed",
            "samples",
            "cleanup",
            "criteria",
            "outcome",
        },
    )
    require(type(report["schema"]) is int and report["schema"] == 2)
    require(report["scenario"] == "ha-persistent-live")
    # No C2a report can be relabelled into an admitted real-world observation.
    require(report["execution"] == "offline" and report["admission"] == "NOT RUN")
    require(report["boundary_proven"] is False)
    p = report["provenance"]
    keys(p, {"merge_sha", "pr_number", "run_id", "run_attempt"})
    require(
        type(p["merge_sha"]) is str
        and re.fullmatch("[0-9a-f]{40}", p["merge_sha"]) is not None
    )
    require(
        integer(p["pr_number"], 1, 2**53 - 1) and integer(p["run_id"], 1, 2**53 - 1)
    )
    require(type(p["run_attempt"]) is int and p["run_attempt"] == 1)
    r = report["supervisor"]
    keys(
        r,
        {
            "started",
            "reason",
            "memory_bytes",
            "pids",
            "useful_ms",
            "process_ms",
            "elapsed_ms",
            "oom_killed",
            "pids_limited",
            "reaped",
            "network",
        },
    )
    for name in ("started", "oom_killed", "pids_limited", "reaped"):
        require(type(r[name]) is bool)
    for name, maximum in (
        ("memory_bytes", MEMORY_BYTES),
        ("pids", PIDS),
        ("useful_ms", USEFUL_MS),
        ("process_ms", PROCESS_MS),
    ):
        require(integer(r[name], 1, maximum))
    require(integer(r["elapsed_ms"], 0, PROCESS_MS))
    require(r["useful_ms"] < r["process_ms"])
    require(type(r["reason"]) is str and r["reason"] in REASONS)
    require(r["network"] == "none")
    if r["reason"] == "completed":
        require(
            r["started"]
            and r["reaped"]
            and not r["oom_killed"]
            and not r["pids_limited"]
        )
        require(r["elapsed_ms"] <= r["process_ms"])
    if r["oom_killed"]:
        require(r["reason"] == "memory")
    if r["pids_limited"] and not r["oom_killed"]:
        require(r["reason"] == "processes")
    samples = report["samples"]
    require(
        type(samples) is list
        and len(samples) <= 6
        and type(report["completed"]) is bool
    )
    require(not report["completed"] or len(samples) == 6)
    require(r["started"] or not samples)
    previous = None
    for ordinal, sample in enumerate(samples, 1):
        keys(sample, {"ordinal", "decoded", "observation"})
        require(type(sample["ordinal"]) is int and sample["ordinal"] == ordinal)
        require(type(sample["decoded"]) is bool)
        o = sample["observation"]
        observation(o)
        if previous is not None:
            progress(previous, o)
        if sample["decoded"]:
            require(
                o["read_generation"] is not None
                and not o["stopped"]
                and not o["cleanup_failed"]
            )
            require(
                previous is None
                or o["read_generation"] != previous["read_generation"]
                or o["read_sequence"] > previous["read_sequence"]
            )
        previous = o
    keys(report["cleanup"], {"completed", "observation"})
    require(type(report["cleanup"]["completed"]) is bool)
    observation(report["cleanup"]["observation"])
    if previous is not None:
        progress(previous, report["cleanup"]["observation"])
    expected = results(report)
    keys(report["criteria"], expected.keys())
    require(report["criteria"] == expected)
    require(report["outcome"] == outcome(expected))
    require(
        len(json.dumps(report, separators=(",", ":"), allow_nan=False).encode())
        <= REPORT_BYTES
    )
    return report


def results(report):
    """A local resource stop never validates a natural recovery or TLS loss."""
    result = criteria(report)
    receipt = report["supervisor"]
    if not receipt["started"]:
        result = dict.fromkeys((*result, "supervision"), "NOT RUN")
        if receipt["reason"] != "unavailable":
            result["supervision"] = "FAILURE"
        return result
    safe = receipt["reason"] == "completed" and receipt["reaped"]
    result["supervision"] = (
        "SUCCESS" if safe else "NOT RUN" if not receipt["started"] else "FAILURE"
    )
    if not safe:
        result["reconnection"] = "INCONCLUSIVE" if report["samples"] else "NOT RUN"
    return result


def build_report(provenance, receipt, evidence):
    keys(evidence, {"completed", "samples", "cleanup"})
    report = {
        "schema": 2,
        "scenario": "ha-persistent-live",
        "execution": "offline",
        "admission": "NOT RUN",
        "boundary_proven": False,
        "provenance": dict(provenance),
        "supervisor": dict(receipt),
        **evidence,
    }
    report["criteria"] = results(report)
    report["outcome"] = outcome(report["criteria"])
    return validate_report(report)


def empty_evidence():
    """No protocol operation attested; does not construct any HA/client object."""
    return {
        "completed": False,
        "samples": [],
        "cleanup": {
            "completed": False,
            "observation": {
                "attempts": 0,
                "generation": None,
                "read_generation": None,
                "read_sequence": None,
                "loss_generation": None,
                "loss_kind": None,
                "close_client_subcode": None,
                "cleaned_generation": None,
                "cleanup_failed": False,
                "stopped": False,
            },
        },
    }


def encode_report(report):
    return json.dumps(validate_report(report), separators=(",", ":"), allow_nan=False)


def parse_report(text):
    try:
        require(type(text) is str and len(text.encode()) <= REPORT_BYTES)
        report = validate_report(json.loads(text))
        require(encode_report(report) == text)
        return report
    except (ValueError, TypeError, KeyError, RecursionError):
        raise ValueError("invalid inactive HA live proof") from None
