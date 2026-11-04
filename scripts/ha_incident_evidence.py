"""Versioned HA-F1 metadata only; independent of HA, I/O and scenario verdicts."""

from custom_components.hoben.error_phases import PHASES
from scripts.campaign_runtime_contract import integer, keys, need

FIELDS = {"diagnostic_schema", "diagnostic"}
CATEGORIES = {
    "timeout",
    "eof",
    "close_client",
    "transport",
    "tls",
    "protocol",
    "internal",
    "cancelled",
    "authentication",
    "authorization",
    "cleanup_failed",
    "closed",
    "exhausted",
}
SOURCES = {
    "transport_connect",
    "transport_read",
    "transport_write",
    "transport_close",
    "session",
    "observer",
}
STAGES = (
    "active",
    "stop_operations",
    "session_close",
    "transport_release",
    "tls_close",
    "tls_closed",
    "reaped",
    "construction_failed",
)


def extra_keys(e):
    """Legacy evidence has no F1 attestation; the versioned pair is indivisible."""
    need(type(e) is dict)
    if FIELDS.intersection(e):
        need(FIELDS <= e.keys())
        need(type(e["diagnostic_schema"]) is int and e["diagnostic_schema"] == 1)
        return FIELDS
    return set()


def validate(e, receipt, *, dual=False):
    if not extra_keys(e):
        return  # Historical reports cannot attest a HA-F1 diagnostic.
    d = e["diagnostic"]
    keys(d, {"end_ms", "first", "terminal", "cleanup", "owners", "invalid"})
    need(d["invalid"] is False and integer(d["end_ms"], 0, receipt["process_ms"]))
    clock = e["clock"] if dual else e["window"]["clock"]
    if clock == "monotonic":
        need(d["end_ms"] <= receipt["elapsed_ms"])
    rows = d["owners"]
    need(type(rows) is list and len(rows) <= (3 if dual else 2))
    identifiers, accepted_counts = [], {"a": 0, "b": 0}
    for row in rows:
        keys(
            row,
            {
                "role",
                "generation",
                "accepted",
                "accepted_generation",
                "close_client_subcode",
                "close",
                "stage",
                "pending",
                "last_read",
            },
        )
        role, generation = row["role"], row["generation"]
        need(type(role) is str and role in ({"a", "b"} if dual else {"a"}))
        need(integer(generation, 1, 1 if role == "b" else 2))
        need(generation == 1 + sum(r == role for r, _ in identifiers))
        need((role, generation) not in identifiers)
        identifiers.append((role, generation))
        need(type(row["accepted"]) is bool)
        if row["accepted"]:
            accepted_counts[role] += 1
            need(
                type(row["accepted_generation"]) is int
                and row["accepted_generation"] == accepted_counts[role]
            )
        else:
            need(row["accepted_generation"] is None)
        need(
            row["close_client_subcode"] is None
            or integer(row["close_client_subcode"], 0, 255)
        )
        need(type(row["stage"]) is str and row["stage"] in STAGES)
        if row["stage"] == "construction_failed":
            need(
                not row["accepted"]
                and row["close"] == [None] * 4
                and row["pending"] is None
                and row["last_read"] is None
                and row["close_client_subcode"] is None
            )
            continue
        close = row["close"]
        need(type(close) is list and len(close) == 4)
        previous = -1
        for value in close:
            need(value is None or integer(value, 0, d["end_ms"]))
            if value is not None:
                need(value >= previous)
                previous = value
        for index in range(1, 4):
            need(close[index] is None or close[index - 1] is not None)
        pending = row["pending"]
        need(integer(pending, 0, 127))
        if close[3] is not None:
            need(pending == 0 and row["stage"] == "reaped")
        if row["stage"] == "reaped":
            need(close[3] is not None)
        if close[2] is not None:
            need(STAGES.index(row["stage"]) >= STAGES.index("tls_closed"))
        read = row["last_read"]
        if read is not None:
            need(type(read) is list and len(read) == 3 and row["accepted"])
            need(integer(read[0], 1, 12 if dual else 6))
            need(integer(read[1], 0, d["end_ms"]) and read[2] == d["end_ms"] - read[1])
            need(type(read[2]) is int)
            need(close[0] is None or read[1] <= close[0])
    for name in ("first", "terminal", "cleanup"):
        event = d[name]
        if event is None:
            continue
        need(type(event) is list and len(event) == 7)
        role, generation, at, category, phase, source, subcode = event
        need(type(role) is str and (generation is None or integer(generation, 1, 2)))
        need(
            (role, generation) in identifiers
            or role == "a"
            and generation is None
            and not rows
        )
        need(integer(at, 0, d["end_ms"]))
        need(type(category) is str and category in CATEGORIES)
        need(type(phase) is str and phase in PHASES)
        need(type(source) is str and source in SOURCES)
        need(
            integer(subcode, 0, 255) if category == "close_client" else subcode is None
        )
        if name != "first":
            need(d["first"] is not None and d["first"][2] <= at)
        if name == "cleanup":
            need(
                phase == "cleanup"
                and source in {"transport_close", "session", "observer"}
            )
            owner = next(
                (
                    o
                    for o in rows
                    if o["role"] == role and o["generation"] == generation
                ),
                None,
            )
            if source == "transport_close":
                need(
                    owner is not None
                    and owner["close"][2] is None
                    and owner["close"][3] is None
                )
        if category == "eof":
            need(phase == "tls_read" and source == "transport_read")
            if dual:
                need(sum(p[role]["eof"] for p in e["phases"]) > 0)
        if category == "close_client":
            need(source in {"session", "observer"})
            need(any(o["role"] == role and o["generation"] == generation for o in rows))
            owner = next(
                o for o in rows if o["role"] == role and o["generation"] == generation
            )
            need(owner["close_client_subcode"] == subcode)
            if dual:
                proof = e["incident"] if name == "first" else e["terminal"]
                need(
                    proof is not None
                    and proof["role"] == role
                    and proof["subcode"] == subcode
                )
            else:
                witnesses = [s["observation"] for s in e["samples"]] + [
                    e["cleanup"]["observation"]
                ]
                need(
                    any(
                        w["loss_kind"] == "close_client"
                        and w["loss_generation"] == owner["accepted_generation"]
                        and w["close_client_subcode"] == subcode
                        for w in witnesses
                    )
                    or (
                        e["cleanup"]["observation"]["cleanup_failed"]
                        and e["cleanup"]["observation"]["loss_kind"] is None
                        and owner["accepted"]
                    )
                )
    if dual:
        need(e["schema"] == 2)
        core = e["owners"]
        need(identifiers == [(o["role"], o["generation"]) for o in core])
        offset = e["t0_ms"] or 0
        for row, original in zip(rows, core, strict=True):
            need(row["accepted"] == original["accepted"])
            need((row["close"][2] is not None) == original["close_completed"])
            need((row["close"][3] is not None) == original["cleanup"])
            if original["closed_ms"] is not None:
                need(row["close"][2] >= offset + original["closed_ms"] - 1)
            if e["completed"]:
                need(row["close"][3] is not None)
            successful = (
                [
                    s
                    for s in e["reads"]
                    if s["decoded"] and s["generation"] == row["accepted_generation"]
                ]
                if row["role"] == "a"
                else []
            )
            expected = (
                max((s["sequence"] for s in successful), default=0)
                if row["role"] == "a"
                else e["b_read_sequence"]
            )
            read = row["last_read"]
            need((read is None) == (expected == 0))
            if read is not None:
                need(read[0] == expected)
                if row["role"] == "a":
                    sample = successful[-1]
                    need(
                        offset + sample["at_ms"] - 1
                        <= read[1]
                        <= offset + sample["end_ms"] + 1
                    )
                else:
                    need(
                        offset + e["b"]["accepted_ms"] - 1
                        <= read[1]
                        <= offset + e["b"]["read_ms"] + 1
                    )
        first = e["incident"]
        if first is not None:
            need(
                d["first"] is not None
                and d["first"][0:2] == [first["role"], first["generation"]]
            )
            need(first["at_ms"] is None or d["first"][2] <= offset + first["at_ms"])
            allowed = {
                "timeout": {"timeout"},
                "protocol": {"protocol"},
                "transport": {"transport", "tls", "eof"},
                "closed": {"closed", "close_client", "cancelled"},
                "unexpected": {"internal", "cancelled"},
                "authentication": {"authentication"},
                "authorization": {"authorization"},
            }
            need(d["first"][3] in allowed.get(first["category"], set()))
        need(not e["cleanup_errors"] or d["cleanup"] is not None)
        need(d["cleanup"] is None or any(not o["cleanup"] for o in core))
        if e["terminal"] is not None:
            need(
                d["terminal"] is not None
                and d["terminal"][0] == e["terminal"]["role"]
                and d["terminal"][4] == e["terminal"]["phase"]
            )
    else:
        final = e["cleanup"]["observation"]
        need(len(rows) == final["attempts"])
        need(sum(r["accepted"] for r in rows) == (final["generation"] or 0))
        need(not final["cleanup_failed"] or d["cleanup"] is not None)
        need(not any(not s["decoded"] for s in e["samples"]) or d["first"] is not None)
        for row in rows:
            clean_generation = (
                not final["cleanup_failed"] or row["generation"] < final["attempts"]
            )
            if (
                row["accepted"]
                and clean_generation
                and (final["cleaned_generation"] or 0) >= row["accepted_generation"]
            ):
                need(row["close"][3] is not None)
            if row["close"][3] is not None:
                need(
                    (
                        not final["cleanup_failed"]
                        or row["generation"] < final["attempts"]
                    )
                    and (
                        not row["accepted"]
                        or (final["cleaned_generation"] or 0)
                        >= row["accepted_generation"]
                    )
                )
            read = row["last_read"]
            successes = [
                s["observation"]["read_sequence"]
                for s in e["samples"]
                if s["decoded"]
                and s["observation"]["read_generation"] == row["accepted_generation"]
            ]
            expected = max(successes, default=0)
            need((read is None) == (expected == 0))
            need(read is None or read[0] == expected)
            witnesses = [s["observation"] for s in e["samples"]]
            if e["window"]["observation"] is not None:
                witnesses.append(e["window"]["observation"])
            if read is not None:
                need(
                    any(
                        w["read_generation"] == row["accepted_generation"]
                        and w["read_sequence"] == read[0]
                        for w in witnesses
                    )
                )
    return d
