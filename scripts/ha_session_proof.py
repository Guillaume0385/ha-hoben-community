"""C1 offline proof contract. No CLI, environment access, network or admission.

This report can describe synthetic executions only. C2 must separately attest
admission/provenance and apply process/RX/memory limits before any live use.
"""

import json
import re

from custom_components.hoben.session_observation import (
    SessionLossKind,
    SessionObservation,
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
OBS_KEYS = {
    "attempts",
    "generation",
    "read_generation",
    "read_sequence",
    "loss_generation",
    "loss_kind",
    "close_client_subcode",
    "cleaned_generation",
    "cleanup_failed",
    "stopped",
}


class InvalidProof(ValueError):
    """Fixed error only: never interpolate rejected keys or private values."""

    def __init__(self):
        super().__init__("invalid offline HA session proof")


def require(condition):
    if not condition:
        raise InvalidProof()


def integer(value, low, high):
    return type(value) is int and low <= value <= high


def keys(value, expected):
    require(type(value) is dict and value.keys() == expected)


def project_observation(value: SessionObservation) -> dict:
    """Explicit projection; no generic dataclass, client or snapshot export."""
    require(type(value) is SessionObservation)
    require(value.loss_kind is None or type(value.loss_kind) is SessionLossKind)
    projected = {
        "attempts": value.attempts,
        "generation": value.generation,
        "read_generation": value.read_generation,
        "read_sequence": value.read_sequence,
        "loss_generation": value.loss_generation,
        "loss_kind": value.loss_kind.value if value.loss_kind is not None else None,
        "close_client_subcode": value.close_client_subcode,
        "cleaned_generation": value.cleaned_generation,
        "cleanup_failed": value.cleanup_failed,
        "stopped": value.stopped,
    }
    observation(projected)
    return projected


def observation(value):
    keys(value, OBS_KEYS)
    require(integer(value["attempts"], 0, 2))
    for name in (
        "generation",
        "read_generation",
        "loss_generation",
        "cleaned_generation",
    ):
        require(value[name] is None or integer(value[name], 1, 2))
    generation = value["generation"]
    require(generation is None or generation <= value["attempts"])
    for name in ("read_generation", "loss_generation", "cleaned_generation"):
        require(
            value[name] is None
            or (generation is not None and value[name] <= generation)
        )
    sequence = value["read_sequence"]
    require((sequence is None) == (value["read_generation"] is None))
    require(sequence is None or integer(sequence, 1, 6))
    require(value["read_generation"] is None or value["read_generation"] == generation)
    kind = value["loss_kind"]
    require(kind is None or type(kind) is str and kind in {"transport", "close_client"})
    require((kind is None) == (value["loss_generation"] is None))
    subcode = value["close_client_subcode"]
    require(integer(subcode, 0, 255) if kind == "close_client" else subcode is None)
    require(type(value["cleanup_failed"]) is bool and type(value["stopped"]) is bool)


def criteria(report):
    """Derive results from bounded evidence, never from GUID equality/open alone."""
    samples = report["samples"]
    collection = (
        "NOT RUN" if not samples else "SUCCESS" if report["completed"] else "FAILURE"
    )
    reuse = any(
        a["decoded"]
        and b["decoded"]
        and a["observation"]["read_generation"] == b["observation"]["read_generation"]
        and b["observation"]["read_sequence"] == a["observation"]["read_sequence"] + 1
        for a, b in zip(samples, samples[1:])
    )
    recovered = any(
        s["decoded"]
        and (o := s["observation"])["loss_generation"] is not None
        and o["read_generation"] > o["loss_generation"]
        and o["cleaned_generation"] is not None
        and o["cleaned_generation"] >= o["loss_generation"]
        and not o["cleanup_failed"]
        for s in samples
    )
    cleanup = report["cleanup"]
    o = cleanup["observation"]
    clean = (
        cleanup["completed"]
        and o["stopped"]
        and not o["cleanup_failed"]
        and (o["cleaned_generation"] == o["generation"])
    )
    return {
        "collection": collection,
        "tls_reuse": "SUCCESS"
        if reuse
        else "FAILURE"
        if report["completed"]
        else "INCONCLUSIVE"
        if samples
        else "NOT RUN",
        "reconnection": "SUCCESS"
        if recovered
        else "INCONCLUSIVE"
        if samples
        else "NOT RUN",
        "cleanup": "SUCCESS" if clean else "FAILURE",
    }


def outcome(results):
    if "FAILURE" in results.values():
        return "FAILURE"
    if results["collection"] == "NOT RUN":
        return "NOT RUN"
    return "SUCCESS" if set(results.values()) == {"SUCCESS"} else "INCONCLUSIVE"


def progress(previous, current):
    """A later sample cannot erase terminal failure, loss or cleanup evidence."""
    require(current["attempts"] >= previous["attempts"])
    for name in ("generation", "loss_generation", "cleaned_generation"):
        require((current[name] or 0) >= (previous[name] or 0))
    for name in ("cleanup_failed", "stopped"):
        require(not previous[name] or current[name])
    if current["loss_generation"] == previous["loss_generation"]:
        require(current["loss_kind"] == previous["loss_kind"])
        require(current["close_client_subcode"] == previous["close_client_subcode"])
    if (
        current["generation"] == previous["generation"]
        and previous["read_sequence"] is not None
    ):
        require(
            current["read_sequence"] is not None
            and current["read_sequence"] >= previous["read_sequence"]
        )


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
