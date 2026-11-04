"""Closed optional two-session proof; numeric metadata only, no collection I/O."""

import json

from custom_components.hoben.error_phases import PHASES
from custom_components.hoben.malformed import TEXT_FIELDS
from scripts.campaign_runtime_contract import ERRORS, empty_metrics, integer, keys, need
from scripts.ha_incident_evidence import extra_keys
from scripts.ha_incident_evidence import validate as validate_diagnostic

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


def _empty_v1():
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


def empty():
    """Schema 2 separates the first incident, terminal refusal and cleanup."""
    return {
        **_empty_v1(),
        "schema": 2,
        "owners": [],
        "incident": None,
        "terminal": None,
        "cleanup_errors": [],
    }


def owner_record(role, generation):
    return {
        "role": role,
        "generation": generation,
        **_empty_v1()["resources"][role],
        **dict.fromkeys(("open_ms", "accepted_ms", "closed_ms", "cleaned_ms")),
    }


def continuous(e):
    return (
        e.get("incident") is None
        and e.get("terminal") is None
        and not e.get("cleanup_errors")
        and _continuous(e)
        and (e["schema"] == 1 or e["end_ms"] < e["reads"][-1]["scheduled_ms"] + 60000)
    )


def recovered(e):
    """One interruption at the seventh acquisition, never an unproved boundary.

    This is a bounded campaign proof, not a change to HA's retry policy. The
    original failed acquisition remains in reads; pending polls are not TX.
    """
    f = e.get("incident")
    if not f or f["role"] != "a" or f["kind"] not in {"timeout", "eof", "close_client"}:
        return False
    reads, owners = e["reads"], e.get("owners", [])
    a = [o for o in owners if o["role"] == "a"]
    b = [o for o in owners if o["role"] == "b"]
    if (
        len(a) != 2
        or len(b) != 1
        or len(reads) < 12
        or not _b_positive(e)
        or len(e["transitions"]) != 6
    ):
        return False
    first, fresh = a
    resumed = [s for s in reads if s["decoded"] and s["generation"] == 2]
    if not resumed or not all(s["decoded"] for s in reads[:6]):
        return False
    fault = reads[6]
    if not (
        e["error"] == "none"
        and e["failure"] is None
        and e["terminal"] is None
        and not e["cleanup_errors"]
        and not e["overflow"]
        and e["a_end_active"]
        and not fault["decoded"]
        and (not fault["attempted"] or fault["error"] == f["category"])
        and f["generation"] == 1
        and (
            fault["attempted"]
            and fault["at_ms"] == f["read_ms"]
            and fault["at_ms"] <= f["at_ms"] <= fault["end_ms"]
            or not fault["attempted"]
            and f["read_ms"] is None
            and f["kind"] in {"close_client", "eof"}
            and 355000 <= f["at_ms"] <= 365000
            and f["at_ms"] <= fault["end_ms"]
        )
        and all(o["cleanup"] and o["close_completed"] for o in owners)
        and first["cleaned_ms"] is not None
        and fresh["open_ms"] is not None
        and first["cleaned_ms"] >= f["at_ms"]
        and fresh["open_ms"] >= first["cleaned_ms"] + 60000
        and fresh["accepted_ms"] is not None
        and fresh["open_ms"] <= fresh["accepted_ms"] <= resumed[0]["at_ms"]
        and e["end_ms"]
        >= max(660000, e["b"]["closed_ms"] + 300000, resumed[0]["end_ms"] + 300000)
        and all(s["decoded"] for s in reads if s["at_ms"] >= resumed[0]["at_ms"])
        and all(not s["attempted"] for s in reads[7:] if not s["decoded"])
        and all(s["at_ms"] - s["scheduled_ms"] <= MAX_DRIFT_MS for s in reads)
        and e["end_ms"] < reads[-1]["scheduled_ms"] + 60000
    ):
        return False
    if f["kind"] == "timeout" and not (
        f["category"] == "timeout"
        and f["subcode"] is None
        and f["deadline_ms"] == f["read_ms"] + 30000
        and f["at_ms"] >= f["deadline_ms"]
        and sum(p["a"]["eof"] for p in e["phases"]) == 0
    ):
        return False
    if f["kind"] == "eof" and not (
        f["category"] == "transport"
        and f["subcode"] is None
        and sum(p["a"]["eof"] for p in e["phases"]) == 1
    ):
        return False
    if f["kind"] == "close_client" and not (
        f["category"] == "closed"
        and type(f["subcode"]) is int
        and f["subcode"] not in {2, 4, 5}
        and sum(p["a"]["types"][3] for p in e["phases"]) == 1
    ):
        return False
    return (
        _b_positive(e)
        and _pongs_positive(e)
        and sum(p["b"]["eof"] for p in e["phases"]) == 0
        and sum(p["a"]["eof"] for p in e["phases"]) == (f["kind"] == "eof")
        and sum(p["a"]["types"][3] for p in e["phases"])
        == (f["kind"] == "close_client")
        and sum(p["b"]["types"][3] for p in e["phases"]) == 0
        and sorted((t["role"], t["state"], t["at_ms"]) for t in e["transitions"])
        == sorted(
            (role, state, at)
            for role, state, at in (
                ("a", "connected", 0),
                ("b", "connected", e["b"]["accepted_ms"]),
                ("a", "reconnecting", f["at_ms"]),
                ("b", "disconnected", e["b"]["closed_ms"]),
                ("a", "connected", fresh["accepted_ms"]),
                ("a", "disconnected", e["transitions"][-1]["at_ms"]),
            )
        )
        and e["transitions"][-1]["at_ms"] >= e["end_ms"]
        and all(
            not p[role][k]
            for p in e["phases"]
            for role in ROLES
            for k in ("invalid", "unexpected", "truncated")
        )
        and sum(p["a"]["types"][1] for p in e["phases"]) == 2
        and sum(p["a"]["types"][4] for p in e["phases"])
        == sum(s["decoded"] for s in reads) + (f["late_frame"] is not None)
        and sum(p["a"]["requests"] for p in e["phases"])
        == sum(s["attempted"] for s in reads)
    )


def positive(e):
    return continuous(e) or recovered(e)


def _b_positive(e):
    b = e["b"]
    return (
        all(b[k] is not None for k in b)
        and 180000 <= b["start_ms"] <= 185000
        and b["accepted_ms"] <= 185000
        and b["accepted_ms"] <= b["read_ms"] < 360000
        and b["read_ms"] <= b["accepted_ms"] + 30000
        and 360000 <= b["close_ms"] <= 365000
        and b["close_ms"] <= b["closed_ms"] <= b["close_ms"] + 10000
        and e["b_read_sequence"] == 1
        and e["b_active_at_close"]
        and e["resources"]["b"]["cleanup"]
        and sum(p["b"]["requests"] for p in e["phases"]) == 1
        and sum(p["b"]["types"][1] for p in e["phases"]) == 1
        and sum(p["b"]["types"][4] for p in e["phases"]) == 1
    )


def _pongs_positive(e):
    return all(
        sum(p[role]["pongs"] for p in e["phases"])
        == sum(p[role]["types"][2] + p[role]["opening_pongs"] for p in e["phases"])
        for role in ROLES
    )


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
    modern = e.get("schema") == 2
    keys(e, set(empty() if modern else _empty_v1()) | extra_keys(e))
    need(type(e["schema"]) is int and e["schema"] in {1, 2})
    need(e["boundary_proven"] is False)
    need(e["clock"] in {"unattested", "synthetic", "monotonic"})
    for k in ("completed", "a_end_active", "b_active_at_close", "overflow"):
        need(type(e[k]) is bool)
    need(e["error"] in ERRORS)
    need(time_value(e["t0_ms"]) and integer(e["end_ms"], 0, 900000))
    need(type(e["reads"]) is list and len(e["reads"]) <= (14 if modern else 12))
    need(e["clock"] != "unattested" or not e["reads"] and e["t0_ms"] is None)
    previous = -1
    sequences = {1: 0, 2: 0}
    last_success = None
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
            )
            + (("attempted", "held", "last_success_ms", "age_ms") if modern else ()),
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
            if modern:
                need(s["generation"] in {1, 2})
                sequences[s["generation"]] += 1
                need(s["sequence"] == sequences[s["generation"]])
            else:
                need(s["generation"] == 1 and s["sequence"] == i + 1)
        if modern:
            need(type(s["attempted"]) is bool and type(s["held"]) is bool)
            need(time_value(s["last_success_ms"]) and time_value(s["age_ms"]))
            need(not s["available"] or s["decoded"] or s["held"])
            need(not s["decoded"] or s["attempted"] and not s["held"])
            need(not s["held"] or not s["decoded"] and s["available"])
            if s["decoded"]:
                last_success = s["end_ms"]
            need(s["last_success_ms"] == last_success)
            need(
                s["age_ms"]
                == (None if last_success is None else s["end_ms"] - last_success)
            )
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
        cap = 2 if modern and role == "a" else 1
        need(integer(r["opens"], 0, cap) and integer(r["close_calls"], 0, cap))
        for k in ("accepted", "close_completed", "cleanup"):
            need(type(r[k]) is bool)
        need(not r["accepted"] or r["opens"] >= 1)
        need(not r["close_completed"] or r["close_calls"] == r["opens"] >= 1)
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
            sum(p[role]["requests"] for p in e["phases"])
            <= ((14 if modern else 12) if role == "a" else 1)
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
    if modern:
        _validate_recovery(e)
    if e["completed"]:
        need(positive(e))
    return e


def _continuous(e):
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


def _validate_recovery(e):
    """Closed per-generation resources and original read/cleanup evidence."""
    owners = e["owners"]
    need(type(owners) is list and len(owners) <= 3)
    need(all(type(o) is dict for o in owners))
    for role in ROLES:
        rows = [o for o in owners if o.get("role") == role]
        need(len(rows) <= (2 if role == "a" else 1))
        for i, o in enumerate(rows, 1):
            keys(o, owner_record(role, i))
            need(o["generation"] == i and type(o["generation"]) is int)
            for k in ("opens", "close_calls"):
                need(integer(o[k], 0, 1))
            for k in ("accepted", "close_completed", "cleanup"):
                need(type(o[k]) is bool)
            for k in ("open_ms", "accepted_ms", "closed_ms", "cleaned_ms"):
                need(time_value(o[k]))
            need(not o["accepted"] or o["opens"] == 1 and o["accepted_ms"] is not None)
            need(not o["close_completed"] or o["close_calls"] == o["opens"] == 1)
            need(not o["cleanup"] or o["close_completed"])
            need(
                o["closed_ms"] is None
                or o["cleaned_ms"] is None
                or o["closed_ms"] <= o["cleaned_ms"]
            )
            if o["accepted_ms"] is not None:
                need(o["accepted"])
                need(
                    o["open_ms"] is None
                    and role == "a"
                    and i == 1
                    or o["open_ms"] is not None
                    and o["open_ms"] <= o["accepted_ms"]
                )
        r = e["resources"][role]
        if rows:
            for k in ("opens", "close_calls"):
                need(r[k] == sum(o[k] for o in rows))
            need(r["accepted"] == any(o["accepted"] for o in rows))
            need(r["close_completed"] == all(o["close_completed"] for o in rows))
            need(r["cleanup"] == all(o["cleanup"] for o in rows))
        else:
            need(r["opens"] == r["close_calls"] == 0 and not r["accepted"])
        if role == "b" and rows:
            need(rows[0]["accepted_ms"] == e["b"]["accepted_ms"])
            if e["b"]["closed_ms"] is not None:
                need(rows[0]["closed_ms"] == e["b"]["closed_ms"])
    need(all(o["role"] in ROLES for o in owners))
    for key in ("incident", "terminal"):
        f = e[key]
        if f is None:
            continue
        expected = ("role", "at_ms", "category", "phase", "subcode")
        if key == "incident":
            expected += (
                "kind",
                "generation",
                "read_ms",
                "deadline_ms",
                "frame",
                "late_frame",
            )
        keys(f, expected)
        need(f["role"] in ROLES and time_value(f["at_ms"]))
        need(f["category"] in ERRORS - {"none"} and f["phase"] in PHASES)
        need(
            f["subcode"] is None
            or f["category"] == "closed"
            and integer(f["subcode"], 0, 255)
        )
        if key == "incident":
            need(
                f["kind"]
                in {
                    "timeout",
                    "eof",
                    "close_client",
                    "protocol",
                    "unexpected",
                    "transport",
                    "closed",
                    "authentication",
                    "authorization",
                }
            )
            need(integer(f["generation"], 1, 2))
            need(time_value(f["read_ms"]) and time_value(f["deadline_ms"]))
            if f["frame"] is not None:
                validate_frame(f["frame"])
            if f["late_frame"] is not None:
                late = f["late_frame"]
                validate_frame(late)
                need(
                    f["role"] == "a"
                    and f["kind"] == "timeout"
                    and late["message_type"] == "data_response_client"
                    and late["generation"] == 1
                    and late["event"] == "header"
                    and late["provenance"] == "validated_header"
                    and late["category"] == "none"
                    and late["at_ms"] >= f["at_ms"]
                )
                first = next(
                    (o for o in owners if o["role"] == "a" and o["generation"] == 1),
                    None,
                )
                need(
                    first is not None
                    and first["closed_ms"] is not None
                    and late["at_ms"] <= first["closed_ms"]
                )
            if f["subcode"] is not None:
                need(f["frame"] is not None)
                frame = f["frame"]
                need(
                    frame["message_type"] == "close_client"
                    and frame["event"] == "error"
                    and frame["status"] == "complete"
                    and frame["category"] == "closed"
                    and frame["received_bytes"] == frame["expected_total_bytes"] == 2
                    and frame["length_scope"] == "post_open_hypothesis"
                    and (
                        frame["generation"] == f["generation"]
                        or f["role"] == "b"
                        and frame["generation"] == "unknown"
                    )
                )
    need(type(e["cleanup_errors"]) is list and len(e["cleanup_errors"]) <= 3)
    for f in e["cleanup_errors"]:
        keys(f, ("role", "generation", "at_ms", "category"))
        need(f["role"] in ROLES and integer(f["generation"], 1, 2))
        need(time_value(f["at_ms"]) and f["category"] in ERRORS - {"none"})
        o = next(
            (
                o
                for o in owners
                if o["role"] == f["role"] and o["generation"] == f["generation"]
            ),
            None,
        )
        need(o is not None and not o["cleanup"])
    if e["terminal"] is not None:
        need(e["failure"] is not None)
    if e["failure"] is not None and e["incident"] is not None:
        need(e["failure"] == {k: e["incident"][k] for k in e["failure"]})
    for s in e["reads"]:
        if s["decoded"]:
            o = next(
                (
                    o
                    for o in owners
                    if o["role"] == "a" and o["generation"] == s["generation"]
                ),
                None,
            )
            need(o is not None and o["accepted_ms"] <= s["at_ms"])
            need(o["closed_ms"] is None or s["end_ms"] <= o["closed_ms"])
    if e["completed"]:
        need(
            all(
                o["closed_ms"] is not None and o["cleaned_ms"] is not None
                for o in owners
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
    validate_diagnostic(e, r, dual=True)
    need(
        r["started"]
        or not e["reads"]
        and all(x["opens"] == 0 for x in e["resources"].values())
    )
    if e["clock"] == "monotonic" and e["t0_ms"] is not None:
        need(e["t0_ms"] + e["end_ms"] <= r["elapsed_ms"])
        need(
            all(
                o[k] is None or e["t0_ms"] + o[k] <= r["elapsed_ms"]
                for o in e.get("owners", [])
                for k in ("open_ms", "accepted_ms", "closed_ms", "cleaned_ms")
            )
        )
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
        cleanup=r["reaped"]
        and all(x["cleanup"] for x in e["resources"].values())
        and not e.get("cleanup_errors"),
        continuous=continuous(e),
        recovered=recovered(e),
        reused=len(e["reads"]) > 1 and all(s["decoded"] for s in e["reads"]),
        available=e["a_end_active"]
        and bool(e["reads"])
        and e["reads"][-1]["available"],
        error=e["error"],
    )
    f = e.get("incident") or e["failure"]
    if f is not None and f["category"] in {"transport", "closed"}:
        m["loss_kind"] = "close_client" if f["subcode"] is not None else "transport"
        m["close_client_subcode"] = f["subcode"]
    return m
