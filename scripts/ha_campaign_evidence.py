"""Closed HA campaign evidence; validates observations before projecting metrics."""

import json

from scripts.campaign_runtime_contract import (
    ERRORS,
    empty_metrics,
    ha_limits,
    integer,
    keys,
    need,
)
from scripts.ha_live_proof import empty_evidence, results, validate_observation
from scripts.ha_session_evidence import observation, outcome, progress


def empty(scenario):
    evidence = empty_evidence()
    if scenario != "hoben-live":
        evidence["terminal"] = "none"
    if scenario == "session-reconnect":
        evidence["recovery"] = empty_recovery()
    return evidence


def empty_recovery():
    return dict(
        mode="pong_inhibition_after_120s",
        boundary_proven=False,
        outcome="not_exercised",
        accepted_at_ms=None,
        suppressed_pongs=0,
        loss_generation=None,
        loss_after_ms=None,
        reopened_after_ms=None,
        read_generation=None,
        read_sequence=None,
        recovery_pongs=0,
        stable_ms=0,
    )


def controlled_recovery(e):
    """Strict test proof, independent from process success or a natural loss.

    Old reports remain readable, but their natural-reconnection Boolean cannot
    attest the newly authorized controlled test or its stable final generation.
    """
    if "recovery" not in e:
        return False
    r = e["recovery"]
    keys(r, set(empty_recovery()) | ({"diagnostic"} if "diagnostic" in r else set()))
    if "diagnostic" in r:
        diagnostic = r["diagnostic"]
        keys(diagnostic, ("interruption", "cleanup"))
        for slot, value in diagnostic.items():
            if value is None:
                continue
            keys(
                value,
                ("category", "owner", "generation", "inhibition_exercised", "subcode"),
            )
            need(
                type(value["category"]) is str
                and value["category"]
                in {
                    "eof",
                    "timeout",
                    "tls",
                    "transport",
                    "close_client",
                    "closed",
                    "cancelled",
                    "internal",
                    "protocol",
                }
            )
            need(
                type(value["owner"]) is str
                and value["owner"]
                in (
                    {"transport_close", "observer_cleanup"}
                    if slot == "cleanup"
                    else {"transport_read", "transport_write", "opening", "session"}
                )
            )
            need(integer(value["generation"], 1, 2))
            need(type(value["inhibition_exercised"]) is bool)
            need(
                integer(value["subcode"], 0, 255)
                if value["category"] == "close_client"
                else value["subcode"] is None
            )
        need(diagnostic["interruption"] is None or r["outcome"] != "verified")
        need(
            diagnostic["cleanup"] is None
            or e["cleanup"]["observation"]["cleanup_failed"]
            or not e["cleanup"]["completed"]
        )
    need(r["mode"] == "pong_inhibition_after_120s" and r["boundary_proven"] is False)
    need(
        type(r["outcome"]) is str
        and r["outcome"]
        in {
            "not_exercised",
            "no_disconnect",
            "reopen_failed",
            "stability_lost",
            "verified",
            "timeout",
            "internal",
            "closed",
        }
    )
    for name in ("accepted_at_ms", "loss_after_ms", "reopened_after_ms"):
        need(r[name] is None or integer(r[name], 0, 600000))
    for name in ("loss_generation", "read_generation"):
        need(r[name] is None or integer(r[name], 1, 2))
    need(r["read_sequence"] is None or integer(r["read_sequence"], 1, 6))
    for name in ("suppressed_pongs", "recovery_pongs"):
        need(integer(r[name], 0, 1048576))
    need(integer(r["stable_ms"], 0, 120000))
    w = e["window"]
    o = w["observation"]
    proven = (
        r["accepted_at_ms"] is not None
        and r["suppressed_pongs"] > 0
        and r["recovery_pongs"] > 0
        and r["loss_generation"] == 1
        and r["read_generation"] == 2
        and r["read_sequence"] is not None
        and r["stable_ms"] == 120000
        and r["loss_after_ms"] is not None
        and r["reopened_after_ms"] is not None
        and 120000 <= r["loss_after_ms"] < r["reopened_after_ms"] < 240000
        and r["accepted_at_ms"] + r["reopened_after_ms"] + 120000 <= w["elapsed_ms"]
        and w["active"]
        and o is not None
        and o["generation"] == o["read_generation"] == 2
        and o["loss_generation"] == 1
        and o["loss_kind"] in {"transport", "close_client"}
        and not o["stopped"]
        and not o["cleanup_failed"]
        and any(
            s["decoded"]
            and s["available"]
            and s["at_ms"] >= r["accepted_at_ms"] + r["reopened_after_ms"]
            and s["observation"]["read_generation"] == 2
            and s["observation"]["read_sequence"] == r["read_sequence"]
            and s["observation"]["loss_generation"] == 1
            and s["observation"]["cleaned_generation"] == 1
            for s in e["samples"]
        )
    )
    need(r["outcome"] != "verified" or proven)
    return r["outcome"] == "verified" and proven


def logical_baseline(receipt, evidence):
    """Reuse all #112 window/read/reuse/cleanup checks, without a fake PR proof."""
    logical = {"supervisor": {**receipt, "network": "none"}, **evidence}
    logical["criteria"] = results(logical)
    logical["outcome"] = outcome(logical["criteria"])
    return validate_observation(logical)


def validate_detail(scenario, detail):
    keys(detail, ("supervisor", "evidence"))
    r, e = detail["supervisor"], detail["evidence"]
    limits = ha_limits(scenario)
    keys(
        r,
        (
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
        ),
    )
    for name in ("started", "oom_killed", "pids_limited", "reaped"):
        need(type(r[name]) is bool)
    for name in ("memory_bytes", "pids", "useful_ms", "process_ms"):
        expected = getattr(limits, name)
        need(
            r[name] is None
            if expected is None
            else type(r[name]) is int and r[name] == expected
        )
    need(integer(r["elapsed_ms"], 0, limits.process_ms))
    need(
        type(r["reason"]) is str
        and r["reason"]
        in {
            "completed",
            "unavailable",
            "cancelled",
            "timeout",
            "memory",
            "processes",
            "worker_failure",
        }
    )
    need(r["network"] == "fixed_tls")
    if r["reason"] == "completed":
        need(
            r["started"]
            and r["reaped"]
            and not r["oom_killed"]
            and not r["pids_limited"]
        )
    if r["oom_killed"]:
        need(r["reason"] == "memory")
    if r["pids_limited"] and not r["oom_killed"]:
        need(r["reason"] == "processes")
    if scenario == "hoben-live":
        keys(e, ("completed", "samples", "window", "cleanup"))
        logical_baseline(r, e)
    else:
        keys(
            e,
            {"completed", "samples", "window", "cleanup", "terminal"}
            | (
                {"recovery"}
                if scenario == "session-reconnect" and "recovery" in e
                else set()
            ),
        )
        need(type(e["terminal"]) is str and e["terminal"] in ERRORS)
        need(type(e["completed"]) is bool)
        need(type(e["samples"]) is list and len(e["samples"]) <= 6)
        need(r["started"] or not e["samples"])
        previous, at_ms = None, -1
        for ordinal, s in enumerate(e["samples"], 1):
            keys(
                s, ("ordinal", "at_ms", "decoded", "available", "error", "observation")
            )
            need(type(s["ordinal"]) is int and s["ordinal"] == ordinal)
            need(integer(s["at_ms"], 0, limits.process_ms - 1) and s["at_ms"] >= at_ms)
            need(type(s["decoded"]) is bool and type(s["available"]) is bool)
            need(type(s["error"]) is str and s["error"] in ERRORS)
            o = s["observation"]
            observation(o)
            if previous is not None:
                progress(previous, o)
            if s["decoded"]:
                need(
                    s["available"]
                    and s["error"] == "none"
                    and o["read_generation"] is not None
                    and not o["stopped"]
                    and not o["cleanup_failed"]
                )
                need(
                    previous is None
                    or o["read_generation"] != previous["read_generation"]
                    or o["read_sequence"] > previous["read_sequence"]
                )
            previous, at_ms = o, s["at_ms"]
        w = e["window"]
        keys(w, ("clock", "elapsed_ms", "observation", "active"))
        need(type(w["active"]) is bool)
        need(w["clock"] in {"unattested", "monotonic", "synthetic"})
        need(integer(w["elapsed_ms"], 0, limits.process_ms))
        if w["observation"] is not None:
            observation(w["observation"])
            need(r["started"] and w["clock"] != "unattested")
            if previous is not None:
                progress(previous, w["observation"])
                need(w["elapsed_ms"] >= at_ms)
            previous = w["observation"]
        else:
            need(not w["active"] and not e["samples"])
        if w["clock"] == "monotonic":
            need(w["elapsed_ms"] <= r["elapsed_ms"])
        if w["clock"] == "unattested":
            need(not e["samples"] and w["elapsed_ms"] == 0)
        need(
            not e["completed"]
            or bool(e["samples"])
            and e["terminal"] == "none"
            and w["observation"] is not None
        )
        keys(e["cleanup"], ("completed", "observation"))
        need(type(e["cleanup"]["completed"]) is bool)
        observation(e["cleanup"]["observation"])
        if previous is not None:
            progress(previous, e["cleanup"]["observation"])
        if scenario == "session-reconnect":
            controlled_recovery(e)
    need(
        len(json.dumps(detail, separators=(",", ":"), allow_nan=False).encode()) <= 8192
    )
    return detail


def project(scenario, detail):
    """Only fixed counters and owner-origin witnesses; no snapshots or identifiers."""
    validate_detail(scenario, detail)
    r, e = detail["supervisor"], detail["evidence"]
    m = empty_metrics("ha")
    final = e["cleanup"]["observation"]
    m.update(
        opens=final["attempts"],
        reads=len(e["samples"]),
        reads_ok=sum(s["decoded"] for s in e["samples"]),
        useful_ms=e["window"]["elapsed_ms"],
    )
    m["completed"] = (
        e["completed"]
        and r["reason"] == "completed"
        and r["reaped"]
        and e["window"]["clock"] == "monotonic"
    )
    m["cleanup"] = (
        r["reaped"]
        and e["cleanup"]["completed"]
        and final["stopped"]
        and not final["cleanup_failed"]
        and final["cleaned_generation"] == final["generation"]
    )
    m["reused"] = any(
        a["decoded"]
        and b["decoded"]
        and a["observation"]["read_generation"] == b["observation"]["read_generation"]
        and b["observation"]["read_sequence"] == a["observation"]["read_sequence"] + 1
        for a, b in zip(e["samples"], e["samples"][1:])
    )
    m["recovered"] = any(
        s["decoded"]
        and (o := s["observation"])["loss_generation"] is not None
        and o["read_generation"] > o["loss_generation"]
        and o["cleaned_generation"] is not None
        and o["cleaned_generation"] >= o["loss_generation"]
        and not o["cleanup_failed"]
        for s in e["samples"]
    )
    if scenario == "session-reconnect":
        m["recovered"] = controlled_recovery(e)
    w = e["window"]["observation"]
    if w is not None:
        m["loss_kind"] = w["loss_kind"] or "none"
        m["close_client_subcode"] = w["close_client_subcode"]
    m["available"] = (
        e["window"]["active"]
        and bool(e["samples"])
        and (
            e["samples"][-1]["decoded"]
            if scenario == "hoben-live"
            else e["samples"][-1]["available"]
        )
    )
    if scenario == "hoben-live":
        m["continuous"] = (
            logical_baseline(r, e)["criteria"]["continuous_300s"] == "SUCCESS"
        )
    elif e["terminal"] != "none":
        m["error"] = e["terminal"]
    elif e["samples"] and not e["samples"][-1]["decoded"]:
        m["error"] = e["samples"][-1]["error"]
    return m
