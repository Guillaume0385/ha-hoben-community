"""Shared evidence validation only; no campaign budgets, HA import or I/O."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from custom_components.hoben.session_observation import SessionObservation


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
    from custom_components.hoben.session_observation import (
        SessionLossKind,
        SessionObservation,
    )

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
