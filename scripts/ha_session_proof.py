"""C1 offline proof contract. No CLI, environment access, network or admission.

This historical report describes synthetic executions only. C2a uses a distinct
contract without an RX quota; C2b must separately attest any live admission.
"""

import json
import re

from scripts.ha_session_evidence import (  # noqa: F401 - retained public C1 API
    OBS_KEYS,
    InvalidProof,
    criteria,
    integer,
    keys,
    observation,
    outcome,
    progress,
    project_observation,
    require,
)

LIMITS = {
    "useful_ms": 300_000,
    "process_ms": 360_000,
    "cleanup_ms": 10_000,
    "refreshes": 6,
    "opens": 2,
    "rx_bytes": 1_048_576,
    "memory_bytes": 1_073_741_824,
    "report_bytes": 8192,
    "retention_days": 7,
    "connect_ms": 10_000,
    "transport_close_ms": 5000,
    "handshake_ms": 30_000,
    "read_ms": 30_000,
    "retry_ms": 1000,
}
REFRESH_AT_MS = (0, 50_000, 100_000, 150_000, 200_000, 250_000)


def validate_report(report):
    """Closed schema, strict numeric types and causal/sequence consistency."""
    keys(
        report,
        {
            "schema",
            "scenario",
            "execution",
            "provenance",
            "limits",
            "system_enforcement",
            "boundary_proven",
            "elapsed_ms",
            "completed",
            "samples",
            "cleanup",
            "criteria",
            "outcome",
        },
    )
    require(type(report["schema"]) is int and report["schema"] == 1)
    require(
        report["scenario"] == "ha-persistent-c1" and report["execution"] == "offline"
    )
    require(
        report["system_enforcement"] == "NOT RUN" and report["boundary_proven"] is False
    )
    keys(report["limits"], LIMITS.keys())
    require(all(type(v) is int and v == LIMITS[k] for k, v in report["limits"].items()))
    provenance = report["provenance"]
    keys(provenance, {"merge_sha", "pr_number", "run_id", "run_attempt"})
    require(
        type(provenance["merge_sha"]) is str
        and re.fullmatch(r"[0-9a-f]{40}", provenance["merge_sha"]) is not None
    )
    for name in ("pr_number", "run_id"):
        require(integer(provenance[name], 1, 2**53 - 1))
    require(type(provenance["run_attempt"]) is int and provenance["run_attempt"] == 1)
    require(integer(report["elapsed_ms"], 0, LIMITS["useful_ms"]))
    require(type(report["completed"]) is bool)
    samples = report["samples"]
    require(type(samples) is list and len(samples) <= 6)
    require(not report["completed"] or len(samples) == 6)
    previous = None
    for i, sample in enumerate(samples, 1):
        keys(sample, {"ordinal", "decoded", "observation"})
        require(type(sample["ordinal"]) is int and sample["ordinal"] == i)
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
    if previous:
        final = report["cleanup"]["observation"]
        progress(previous, final)
    keys(report["criteria"], {"collection", "tls_reuse", "reconnection", "cleanup"})
    require(report["criteria"] == criteria(report))
    require(report["outcome"] == outcome(report["criteria"]))
    require(
        len(json.dumps(report, separators=(",", ":"), allow_nan=False).encode()) <= 8192
    )
    return report


def build_report(*, provenance, samples, cleanup, elapsed_ms, completed):
    """Project only fixed evidence fields; validate before any serialization."""
    report = {
        "schema": 1,
        "scenario": "ha-persistent-c1",
        "execution": "offline",
        "provenance": dict(provenance),
        "limits": dict(LIMITS),
        "system_enforcement": "NOT RUN",
        "boundary_proven": False,
        "elapsed_ms": elapsed_ms,
        "completed": completed,
        "samples": samples,
        "cleanup": cleanup,
    }
    report["criteria"] = criteria(report)
    report["outcome"] = outcome(report["criteria"])
    return validate_report(report)


def encode_report(report):
    """Canonical bounded wire form; no file or stdout publication."""
    validate_report(report)
    return json.dumps(report, separators=(",", ":"), allow_nan=False)


def parse_report(text):
    """Require canonical encoding, rejecting duplicate keys and oversized input."""
    require(type(text) is str and len(text.encode()) <= LIMITS["report_bytes"])
    try:
        report = validate_report(json.loads(text))
        require(encode_report(report) == text)
        return report
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise InvalidProof() from None
