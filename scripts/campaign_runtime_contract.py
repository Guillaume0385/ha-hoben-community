"""Closed run contracts for #126; no admission API, credentials or network I/O.

The bounds below are design ceilings explicitly decided in #126 on 27 October,
not measurements of Hoben behavior. Historical planning modules remain archives.
"""

import json
import re
from dataclasses import dataclass

from scripts.ha_campaign_plan import CHOICES as HA_CHOICES
from scripts.protocol_campaign_plan import CHOICES as PROTOCOL_CHOICES

CHOICES = {"protocol": PROTOCOL_CHOICES, "ha": HA_CHOICES}
SECONDS = {
    "protocol": dict(zip(PROTOCOL_CHOICES, (15, 30, 45, 1800, 360, 480, 2820))),
    "ha": dict(zip(HA_CHOICES, (360, 90, 120, 180, 600, 60, 120, 1800))),
}
MAX_REPORT_BYTES = 64 * 1024
STATUSES = {"SUCCESS", "FAILURE", "INCONCLUSIVE", "NOT RUN"}
REASONS = {
    "observed",
    "not_observed",
    "not_started",
    "context_refused",
    "identity_refused",
    "worker_failure",
    "timeout",
    "cancelled",
    "cleanup_failed",
    "report_refused",
    "supervisor_refused",
    "memory",
    "processes",
    "previous_failure",
    "budget",
}


def need(value):
    if not value:
        raise ValueError("campaign_contract_refused")


def keys(value, expected):
    need(type(value) is dict and value.keys() == set(expected))


def integer(value, low, high):
    return type(value) is int and low <= value <= high


def plan(campaign, selection):
    need(type(campaign) is str and campaign in CHOICES)
    need(type(selection) is str and selection in CHOICES[campaign])
    return CHOICES[campaign][:-1] if selection == "all" else (selection,)


def validate_context(value):
    """Informative native run metadata, never a PR/merge/SHA admission gate."""
    keys(value, ("ref", "sha", "run_id", "run_attempt"))
    need(value["ref"] in {"refs/heads/experimental", "refs/heads/main"})
    need(type(value["sha"]) is str and re.fullmatch("[a-f0-9]{40}", value["sha"]))
    for name in ("run_id", "run_attempt"):
        need(integer(value[name], 1, 2**53 - 1))
    return value


@dataclass(frozen=True)
class CampaignLimits:
    """C2a-compatible shape; only the exact new HA design ceilings are valid."""

    memory_bytes: int
    pids: int
    useful_ms: int | None
    process_ms: int

    def __post_init__(self):
        need(type(self.memory_bytes) is int and self.memory_bytes == 1024**3)
        need(type(self.pids) is int and self.pids == 128)
        need(
            type(self.process_ms) is int
            and self.process_ms in {60000, 90000, 120000, 180000, 360000, 600000}
        )
        need(
            type(self.useful_ms) is int and self.useful_ms == 300000
            if self.process_ms == 360000
            else self.useful_ms is None
        )


def ha_limits(scenario):
    need(scenario in HA_CHOICES[:-1])
    return CampaignLimits(
        1024**3,
        128,
        300000 if scenario == "hoben-live" else None,
        SECONDS["ha"][scenario] * 1000,
    )


def empty_metrics(campaign="protocol", scenario=None):
    """Uniform closed projection. HA deliberately has no RX counter or quota."""
    value = {
        "opens": 0,
        "reads": 0,
        "reads_ok": 0,
        "pings": 0,
        "pongs": 0,
        "h1_sessions": 0,
        "h2_sessions": 0,
        "useful_ms": 0,
        "completed": False,
        "cleanup": False,
        "reused": False,
        "recovered": False,
        "available": False,
        "continuous": False,
        "loss_kind": "none",
        "close_client_subcode": None,
        "error": "none",
    }
    if campaign == "ha":
        for name in ("pings", "pongs", "h1_sessions", "h2_sessions"):
            value[name] = None
    elif scenario == "h1h2":
        value.update(pings=None, pongs=None)
    return value


ERRORS = {
    "none",
    "authentication",
    "authorization",
    "transport",
    "protocol",
    "timeout",
    "closed",
    "budget",
    "unexpected",
}


def validate_metrics(m, campaign, scenario):
    keys(m, empty_metrics())
    opens = (
        12
        if scenario == "h1h2"
        else 2
        if campaign == "ha"
        else 3
        if scenario in {"session-300", "session-reconnect"}
        else 1
    )
    reads = (
        6
        if campaign == "ha" or scenario == "session-300"
        else {
            "tls-only": 0,
            "session-open": 0,
            "read-v4-state": 1,
            "h1h2": 12,
            "session-reconnect": 10,
        }[scenario]
    )
    for name, cap in {
        "opens": opens,
        "reads": reads,
        "reads_ok": reads,
        "pings": 1048576,
        "pongs": 1048576,
        "h1_sessions": 6,
        "h2_sessions": 6,
        "useful_ms": SECONDS[campaign][scenario] * 1000,
    }.items():
        if (
            (scenario == "h1h2" and name in {"pings", "pongs"})
            or campaign == "ha"
            and name
            in {
                "pings",
                "pongs",
                "h1_sessions",
                "h2_sessions",
            }
        ):
            need(m[name] is None)
        else:
            need(integer(m[name], 0, cap))
    need(m["reads_ok"] <= m["reads"])
    if campaign == "protocol" and scenario != "h1h2":
        need(m["pongs"] <= m["pings"])
    for name in (
        "completed",
        "cleanup",
        "reused",
        "recovered",
        "available",
        "continuous",
    ):
        need(type(m[name]) is bool)
    need(
        type(m["loss_kind"]) is str
        and m["loss_kind"] in {"none", "transport", "close_client"}
    )
    need(
        integer(m["close_client_subcode"], 0, 255)
        if m["loss_kind"] == "close_client"
        else m["close_client_subcode"] is None
    )
    need(type(m["error"]) is str and m["error"] in ERRORS)
    return m


def observed_status(campaign, scenario, m):
    """Success needs positive operation evidence, including terminal cleanup."""
    validate_metrics(m, campaign, scenario)
    if not m["cleanup"] or not m["completed"] or m["error"] != "none":
        return "FAILURE"
    if scenario == "h1h2":
        return (
            "INCONCLUSIVE" if m["h1_sessions"] == m["h2_sessions"] == 6 else "FAILURE"
        )
    if scenario == "session-reconnect":
        return (
            "SUCCESS"
            if m["recovered"]
            and m["reads_ok"] > 0
            and m["opens"] > 1
            and m["loss_kind"] != "none"
            else "INCONCLUSIVE"
        )
    if campaign == "protocol":
        if scenario in {"tls-only", "session-open"}:
            return "SUCCESS" if m["opens"] == 1 else "FAILURE"
        if scenario == "session-300":
            return (
                "SUCCESS"
                if m["useful_ms"] >= 300000
                and m["reads_ok"] > 0
                and m["pings"] == m["pongs"]
                else "FAILURE"
            )
        return "SUCCESS" if m["reads_ok"] == 1 else "FAILURE"
    if scenario == "hoben-live":
        return (
            "SUCCESS"
            if m["continuous"]
            and m["useful_ms"] >= 300000
            and m["reads_ok"] == 6
            and m["reused"]
            else "FAILURE"
        )
    if scenario == "session-reuse":
        return "SUCCESS" if m["reused"] and m["reads_ok"] >= 2 else "FAILURE"
    if scenario == "availability":
        return "SUCCESS" if m["available"] and m["reads_ok"] > 0 else "FAILURE"
    return "SUCCESS" if m["reads_ok"] > 0 else "FAILURE"


def stage(
    campaign,
    scenario,
    *,
    started=False,
    elapsed_ms=0,
    reason="not_started",
    metrics=None,
    detail=None,
):
    m = empty_metrics(campaign, scenario) if metrics is None else metrics
    status = observed_status(campaign, scenario, m) if started else "NOT RUN"
    if started and reason not in {"observed", "not_observed"}:
        status = "FAILURE"
    return {
        "scenario": scenario,
        "started": started,
        "elapsed_ms": elapsed_ms,
        "reason": reason,
        "status": status,
        "metrics": m,
        "detail": detail,
    }


def validate_stage(value, campaign):
    keys(
        value,
        ("scenario", "started", "elapsed_ms", "reason", "status", "metrics", "detail"),
    )
    scenario = value["scenario"]
    need(type(scenario) is str and scenario in CHOICES[campaign][:-1])
    need(type(value["started"]) is bool)
    need(integer(value["elapsed_ms"], 0, SECONDS[campaign][scenario] * 1000))
    need(type(value["reason"]) is str and value["reason"] in REASONS)
    need(type(value["status"]) is str and value["status"] in STATUSES)
    validate_metrics(value["metrics"], campaign, scenario)
    expected = stage(
        campaign,
        scenario,
        started=value["started"],
        elapsed_ms=value["elapsed_ms"],
        reason=value["reason"],
        metrics=value["metrics"],
        detail=value["detail"],
    )
    need(value == expected)
    if not value["started"]:
        need(
            value["metrics"] == empty_metrics(campaign, scenario)
            and value["detail"] is None
        )
    if campaign == "protocol":
        if value["started"]:
            d = value["detail"]
            need(
                type(d) is dict
                and set(d) - {"recovery_witness"}
                in (
                    {"rx_bytes", "rx_chunks"},
                    {"rx_bytes", "rx_chunks", "ignored_messages"},
                )
            )
            cap = 12 * 1048576 if scenario == "h1h2" else 1048576
            need(
                integer(d["rx_bytes"], 0, cap)
                and integer(d["rx_chunks"], 0, d["rx_bytes"])
            )
            need(
                d["rx_bytes"]
                >= value["metrics"]["reads_ok"] * 50 + (value["metrics"]["pings"] or 0)
            )
            if "recovery_witness" in d:
                need(scenario == "session-reconnect")
                w = d["recovery_witness"]
                keys(
                    w,
                    (
                        "loss_generation",
                        "read_generation",
                        "read_sequence",
                        "stable_ms",
                    ),
                )
                for name in ("loss_generation", "read_generation"):
                    need(w[name] is None or integer(w[name], 1, 3))
                need(w["read_sequence"] is None or integer(w["read_sequence"], 1, 10))
                need(integer(w["stable_ms"], 0, 480000))
            if value["metrics"]["recovered"]:
                need("recovery_witness" in d)
                w = d["recovery_witness"]
                need(
                    w["loss_generation"] is not None
                    and w["read_generation"] is not None
                    and w["read_generation"] > w["loss_generation"]
                    and w["read_sequence"] is not None
                    and w["stable_ms"] >= 120000
                )
            if "ignored_messages" in d:
                from scripts.run_session_300 import valid_ignored_messages

                need(valid_ignored_messages(d["ignored_messages"], d["rx_bytes"]))
    elif value["detail"] is not None:
        from scripts.ha_campaign_evidence import project, validate_detail

        validate_detail(scenario, value["detail"])
        need(value["metrics"] == project(scenario, value["detail"]))
        need(value["detail"]["supervisor"]["elapsed_ms"] <= value["elapsed_ms"])
    if value["status"] in {"SUCCESS", "INCONCLUSIVE"}:
        need(value["metrics"]["useful_ms"] <= value["elapsed_ms"])
        need(campaign != "ha" or value["detail"] is not None)
    return value


def validate_report(report):
    keys(
        report,
        (
            "schema",
            "campaign",
            "selection",
            "provenance",
            "elapsed_ms",
            "stages",
            "collection_result",
            "actions_result",
        ),
    )
    need(type(report["schema"]) is int and report["schema"] == 1)
    campaign, selection = report["campaign"], report["selection"]
    names = plan(campaign, selection)
    validate_context(report["provenance"])
    need(integer(report["elapsed_ms"], 0, SECONDS[campaign][selection] * 1000))
    need(type(report["stages"]) is list and len(report["stages"]) == len(names))
    stopped = False
    for name, value in zip(names, report["stages"]):
        need(value["scenario"] == name)
        validate_stage(value, campaign)
        if stopped:
            need(not value["started"] and value["status"] == "NOT RUN")
        stopped |= value["status"] in {"FAILURE", "NOT RUN"}
    need(sum(s["elapsed_ms"] for s in report["stages"]) <= report["elapsed_ms"])
    if campaign == "ha":
        need(sum(s["metrics"]["opens"] for s in report["stages"]) <= 15)
        need(sum(s["metrics"]["reads"] for s in report["stages"]) <= 42)
    need(
        report["collection_result"]
        in {"pending", "success", "failure", "cancelled", "skipped", "unattested"}
    )
    success = report["collection_result"] == "success" and all(
        s["status"] == "SUCCESS" for s in report["stages"]
    )
    need(report["actions_result"] == ("SUCCESS" if success else "FAILURE"))
    need(
        len(json.dumps(report, separators=(",", ":"), allow_nan=False).encode())
        <= MAX_REPORT_BYTES
    )
    return report
