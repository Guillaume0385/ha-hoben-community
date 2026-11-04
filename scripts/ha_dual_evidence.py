"""Closed optional two-session proof; numeric metadata only, no collection I/O."""

import json

from custom_components.hoben.error_phases import PHASES
from custom_components.hoben.malformed import TEXT_FIELDS
from scripts.campaign_runtime_contract import ERRORS, empty_metrics, integer, keys, need

SCENARIO = "dual-session-observation"
ROLES = ("a", "b")
PHASE_NAMES = ("before", "overlap", "after")
TYPES = (
    "unknown",
    "opened_client",
    "ping",
    "close_client",
    "data_response_client",
    "data_response_server",
    "data_updated",
    "device_auth_req",
)
COUNTS = (
    "rx_bytes",
    "rx_chunks",
    "fragments",
    "buffered_max",
    "pongs",
    "opening_pongs",
    "requests",
    "eof",
    "invalid",
    "unexpected",
    "truncated",
)
FRAME_KEYS = (
    "event",
    "generation",
    "message_type",
    "expected_total_bytes",
    "received_bytes",
    "length_scope",
    "provenance",
    "phase",
    "category",
    "status",
    "at_ms",
)
FRAME_CATEGORIES = {
    "none",
    "protocol",
    "transport",
    "timeout",
    "tls_verification",
    "closed",
    "modbus_exception",
    "unexpected_error",
}
STATES = {"connected", "reconnecting", "recovering", "disconnected"}
MAX_DRIFT_MS = 5000  # design tolerance, never a claim about server timing


def phase(at_ms):
    return 0 if at_ms < 180000 else 1 if at_ms < 360000 else 2


def empty_stats():
    return {**dict.fromkeys(COUNTS, 0), "types": [0] * len(TYPES), "last_frame": None}


def empty():
    return {
        "schema": 1,
        "boundary_proven": False,
        "clock": "unattested",
        "completed": False,
        "error": "none",
        "t0_ms": None,
        "end_ms": 0,
        "a_end_active": False,
        "reads": [],
        "b": dict.fromkeys(
            ("start_ms", "accepted_ms", "read_ms", "close_ms", "closed_ms")
        ),
        "b_read_sequence": 0,
        "b_active_at_close": False,
        "resources": {
            role: {
                "opens": 0,
                "accepted": False,
                "close_calls": 0,
                "close_completed": False,
                "cleanup": False,
            }
            for role in ROLES
        },
        "phases": [
            {"name": name, **{role: empty_stats() for role in ROLES}}
            for name in PHASE_NAMES
        ],
        "transitions": [],
        "failure": None,
        "overflow": False,
    }


def time_value(value):
    return value is None or integer(value, 0, 900000)


def validate_frame(frame):
    keys(frame, FRAME_KEYS)
    need(frame["event"] in {"header", "error"})
    need(frame["generation"] == "unknown" or integer(frame["generation"], 1, 2))
    need(frame["message_type"] in TEXT_FIELDS["message_type"])
    need(
        frame["received_bytes"] == "unknown"
        or integer(frame["received_bytes"], 0, 4096)
    )
    need(
        frame["expected_total_bytes"] == "unknown"
        or integer(frame["expected_total_bytes"], 1, 265)
    )
    need(frame["length_scope"] in {"frame", "post_open_hypothesis", "unproven"})
    need(frame["provenance"] in {"validated_header", "fixed_contract", "unproven"})
    need(frame["phase"] in PHASES and frame["category"] in FRAME_CATEGORIES)
    need(frame["status"] in {"complete", "partial", "invalid", "unknown"})
    need(time_value(frame["at_ms"]))
    t, n = frame["message_type"], frame["expected_total_bytes"]
    if n == "unknown":
        need(frame["provenance"] == frame["length_scope"] == "unproven")
    elif frame["provenance"] == "fixed_contract":
        need(
            (t, n, frame["length_scope"])
            in {
                ("ping", 1, "frame"),
                ("close_client", 2, "post_open_hypothesis"),
            }
        )
    else:
        need(
            frame["provenance"] == "validated_header"
            and frame["length_scope"] == "frame"
        )
        need(
            t in {"data_response_client", "data_response_server"}
            and 9 <= n <= 261
            or t == "data_updated"
            and 13 <= n <= 265
        )


def validate(e):
    keys(e, empty())
    need(type(e["schema"]) is int and e["schema"] == 1)
    need(e["boundary_proven"] is False)
    need(e["clock"] in {"unattested", "synthetic", "monotonic"})
    for k in ("completed", "a_end_active", "b_active_at_close", "overflow"):
        need(type(e[k]) is bool)
    need(e["error"] in ERRORS)
    need(time_value(e["t0_ms"]) and integer(e["end_ms"], 0, 900000))
    need(type(e["reads"]) is list and len(e["reads"]) <= 12)
    need(e["clock"] != "unattested" or not e["reads"] and e["t0_ms"] is None)
    previous = -1
    for i, s in enumerate(e["reads"]):
        keys(
            s,
            (
                "scheduled_ms",
                "at_ms",
                "end_ms",
                "decoded",
                "available",
                "state",
                "generation",
                "sequence",
                "error",
            ),
        )
        need(type(s["scheduled_ms"]) is int and s["scheduled_ms"] == i * 60000)
        need(integer(s["at_ms"], s["scheduled_ms"], 900000) and s["at_ms"] >= previous)
        need(integer(s["end_ms"], s["at_ms"], 900000))
        previous = s["end_ms"]
        need(type(s["decoded"]) is bool and type(s["available"]) is bool)
        need(s["state"] in STATES and s["error"] in ERRORS)
        need(s["generation"] is None or integer(s["generation"], 1, 2))
        need(s["sequence"] is None or integer(s["sequence"], 1, 12))
        need((s["generation"] is None) == (s["sequence"] is None))
        if s["decoded"]:
            need(s["available"] and s["state"] == "connected" and s["error"] == "none")
            need(s["generation"] == 1 and s["sequence"] == i + 1)
        need(e["t0_ms"] is not None and s["end_ms"] <= e["end_ms"])
    keys(e["b"], empty()["b"])
    prior = None
    for k in empty()["b"]:
        v = e["b"][k]
        need(time_value(v))
        if v is not None:
            need(prior is None or v >= prior)
            need(v <= e["end_ms"] or v == e["b"]["closed_ms"])
            prior = v
    need(integer(e["b_read_sequence"], 0, 1))
    need((e["b"]["read_ms"] is not None) == (e["b_read_sequence"] == 1))
    keys(e["resources"], ROLES)
    for role, r in e["resources"].items():
        keys(r, empty()["resources"][role])
        need(integer(r["opens"], 0, 1) and integer(r["close_calls"], 0, 1))
        for k in ("accepted", "close_completed", "cleanup"):
            need(type(r[k]) is bool)
        need(not r["accepted"] or r["opens"] == 1)
        need(not r["close_completed"] or r["close_calls"] == r["opens"] == 1)
        if r["cleanup"]:
            need(r["close_completed"] or r["opens"] == r["close_calls"] == 0)
    need(e["b"]["accepted_ms"] is None or e["resources"]["b"]["accepted"])
    need(e["b"]["closed_ms"] is None or e["resources"]["b"]["cleanup"])
    need(type(e["phases"]) is list and len(e["phases"]) == 3)
    for p, name in zip(e["phases"], PHASE_NAMES):
        keys(p, ("name", *ROLES))
        need(p["name"] == name)
        for role in ROLES:
            s = p[role]
            keys(s, empty_stats())
            for k in COUNTS:
                need(integer(s[k], 0, 1048576 if k == "rx_bytes" else 4096))
            need(s["fragments"] <= s["rx_chunks"])
            need(type(s["types"]) is list and len(s["types"]) == len(TYPES))
            need(all(integer(n, 0, 4096) for n in s["types"]))
            if s["last_frame"] is not None:
                validate_frame(s["last_frame"])
                at = s["last_frame"]["at_ms"]
                need(at is None or phase(at) == PHASE_NAMES.index(name))
    for role in ROLES:
        need(sum(p[role]["rx_bytes"] for p in e["phases"]) <= 1048576)
        need(
            sum(p[role]["requests"] for p in e["phases"]) <= (12 if role == "a" else 1)
        )
    need(type(e["transitions"]) is list and len(e["transitions"]) <= 8)
    last = -1
    for t in e["transitions"]:
        keys(t, ("role", "at_ms", "state"))
        need(t["role"] in ROLES and t["state"] in STATES)
        need(integer(t["at_ms"], 0, 900000) and t["at_ms"] >= last)
        last = t["at_ms"]
    if e["failure"] is not None:
        f = e["failure"]
        keys(f, ("role", "at_ms", "category", "phase", "subcode"))
        need(f["role"] in ROLES and time_value(f["at_ms"]))
        need(f["category"] in ERRORS - {"none"} and f["phase"] in PHASES)
        need(
            f["subcode"] is None
            or f["category"] == "closed"
            and integer(f["subcode"], 0, 255)
        )
        need(e["error"] != "none")
    need(not e["overflow"] or e["error"] == "budget")
    if e["completed"]:
        need(positive(e))
    return e


def positive(e):
    b = e["b"]
    return (
        e["t0_ms"] is not None
        and e["error"] == "none"
        and not e["overflow"]
        and e["failure"] is None
        and len(e["reads"]) == 12
        and e["a_end_active"]
        and all(
            s["decoded"]
            and s["available"]
            and s["at_ms"] - s["scheduled_ms"] <= MAX_DRIFT_MS
            for s in e["reads"]
        )
        and all(
            r["accepted"]
            and r["opens"] == r["close_calls"] == 1
            and r["close_completed"]
            and r["cleanup"]
            for r in e["resources"].values()
        )
        and all(b[k] is not None for k in b)
        and 180000 <= b["start_ms"] <= 180000 + MAX_DRIFT_MS
        and b["accepted_ms"] <= 180000 + MAX_DRIFT_MS
        and b["accepted_ms"] <= b["read_ms"] < 360000
        and b["read_ms"] <= b["accepted_ms"] + 30000
        and 360000 <= b["close_ms"] <= 360000 + MAX_DRIFT_MS
        and b["close_ms"] <= b["closed_ms"] <= b["close_ms"] + 10000
        and e["b_read_sequence"] == 1
        and e["b_active_at_close"]
        and e["end_ms"] >= max(660000, b["closed_ms"] + 300000)
        and [(t["role"], t["state"]) for t in e["transitions"]]
        == [
            ("a", "connected"),
            ("b", "connected"),
            ("b", "disconnected"),
            ("a", "disconnected"),
        ]
        and [t["at_ms"] for t in e["transitions"][:3]]
        == [0, b["accepted_ms"], b["closed_ms"]]
        and e["transitions"][-1]["at_ms"] >= e["end_ms"]
        and all(
            not p[role][k]
            for p in e["phases"]
            for role in ROLES
            for k in ("eof", "invalid", "unexpected", "truncated")
        )
        and sum(p["a"]["requests"] for p in e["phases"]) == 12
        and sum(p["b"]["requests"] for p in e["phases"]) == 1
        and all(
            sum(p[role]["types"][1] for p in e["phases"]) == 1
            and sum(p[role]["types"][4] for p in e["phases"])
            == (12 if role == "a" else 1)
            for role in ROLES
        )
        and all(
            sum(p[role]["pongs"] for p in e["phases"])
            == sum(
                p[role]["types"][TYPES.index("ping")] + p[role]["opening_pongs"]
                for p in e["phases"]
            )
            for role in ROLES
        )
    )


def validate_detail(detail):
    keys(detail, ("supervisor", "evidence"))
    r, e = detail["supervisor"], detail["evidence"]
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
    for k in ("started", "oom_killed", "pids_limited", "reaped"):
        need(type(r[k]) is bool)
    need(type(r["memory_bytes"]) is int and r["memory_bytes"] == 1024**3)
    need(type(r["pids"]) is int and r["pids"] == 128)
    need(
        type(r["process_ms"]) is int
        and r["process_ms"] == 900000
        and r["useful_ms"] is None
    )
    need(integer(r["elapsed_ms"], 0, 900000) and r["network"] == "fixed_tls")
    need(
        r["reason"]
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
    if r["reason"] == "completed":
        need(
            r["started"]
            and r["reaped"]
            and not r["oom_killed"]
            and not r["pids_limited"]
        )
    need(not r["oom_killed"] or r["reason"] == "memory")
    need(not r["pids_limited"] or r["oom_killed"] or r["reason"] == "processes")
    validate(e)
    need(
        r["started"]
        or not e["reads"]
        and all(x["opens"] == 0 for x in e["resources"].values())
    )
    if e["clock"] == "monotonic" and e["t0_ms"] is not None:
        need(e["t0_ms"] + e["end_ms"] <= r["elapsed_ms"])
    need(
        len(json.dumps(detail, separators=(",", ":"), allow_nan=False).encode()) <= 8192
    )
    return detail


def project(detail):
    validate_detail(detail)
    r, e = detail["supervisor"], detail["evidence"]
    m = empty_metrics("ha")
    m.update(
        opens=sum(x["opens"] for x in e["resources"].values()),
        reads=sum(p[role]["requests"] for p in e["phases"] for role in ROLES),
        reads_ok=sum(s["decoded"] for s in e["reads"]) + e["b_read_sequence"],
        useful_ms=e["end_ms"],
        completed=e["completed"]
        and e["clock"] == "monotonic"
        and r["reason"] == "completed"
        and r["reaped"],
        cleanup=r["reaped"] and all(x["cleanup"] for x in e["resources"].values()),
        continuous=positive(e),
        reused=len(e["reads"]) > 1 and all(s["decoded"] for s in e["reads"]),
        available=e["a_end_active"]
        and bool(e["reads"])
        and e["reads"][-1]["available"],
        error=e["error"],
    )
    f = e["failure"]
    if f is not None and f["category"] in {"transport", "closed"}:
        m["loss_kind"] = "close_client" if f["subcode"] is not None else "transport"
        m["close_client_subcode"] = f["subcode"]
    return m
