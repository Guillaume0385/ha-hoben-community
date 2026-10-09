"""Independent strict allowlist for public H1/H2 timing observations.

Never serialize a private journal directly. All values here are copied through
bounded numeric/categorical checks; no RX bytes, identities or free text.
"""
from __future__ import annotations

MAX_MS = 180_000
MAX_BYTES = 1024 * 1024
FRAME = {"ping_h2", "response_h2", "notification_h2"}
TX = {"open_client", "pong_before_open", "read_v4_h2", "pong_h2"}
RX = {"received", "eof", "cancelled_read", "read_error"}


def require(ok: bool) -> None:
    if not ok:
        raise ValueError("invalid_public_timeline")


def keys(value: object, names: set[str]) -> dict:
    require(type(value) is dict and set(value) == names)
    return value


def integer(value: object, maximum: int = MAX_BYTES) -> int:
    require(type(value) is int and 0 <= value <= maximum)
    return value


def nullable(value: object, maximum: int = MAX_MS) -> int | None:
    return None if value is None else integer(value, maximum)


def kind(value: object, permitted: set[str]) -> str:
    require(type(value) is str and value in permitted)
    return value


def safe_timeline(value: object, *, rx_bytes: int, read_calls: int) -> dict:
    """Validate shape, limits and byte accounting; return only audited fields."""
    source = keys(value, {
        "basis", "reads", "tx", "h2_candidates", "unattributed", "close",
        "fragmented_candidates", "concatenated_reads",
    })
    require(source["basis"] == "client_monotonic_relative")
    require(type(source["reads"]) is list and len(source["reads"]) == read_calls <= 260)
    require(type(source["tx"]) is list and len(source["tx"]) <= 100)
    require(
        type(source["h2_candidates"]) is list
        and len(source["h2_candidates"]) <= 256
    )
    require(type(source["unattributed"]) is list and len(source["unattributed"]) <= 1)

    reads = []
    offset, previous_end = 0, None
    for index, raw in enumerate(source["reads"]):
        r = keys(raw, {
            "index", "offset", "requested", "received", "started_ms", "ended_ms",
            "duration_ms", "gap_previous_ms", "since_last_tx_ms", "state",
        })
        start, end = integer(r["started_ms"], MAX_MS), integer(r["ended_ms"], MAX_MS)
        received = integer(r["received"], 4096)
        require(
            integer(r["index"], 260) == index
            and integer(r["offset"]) == offset
            and 1 <= integer(r["requested"], 4096)
            and received <= r["requested"]
            and end >= start
            and integer(r["duration_ms"], MAX_MS) == end - start
            and nullable(r["gap_previous_ms"]) ==
            (None if previous_end is None else start - previous_end)
            and (previous_end is None or start >= previous_end)
            and (kind(r["state"], RX) == "received") == (received > 0)
        )
        since = nullable(r["since_last_tx_ms"])
        require(since is None or since <= start)
        reads.append({**r, "state": r["state"]})
        offset += received
        previous_end = end
    require(offset == rx_bytes <= MAX_BYTES)

    tx = []
    for raw in source["tx"]:
        t = keys(raw, {"category", "started_ms", "ended_ms", "duration_ms"})
        started = integer(t["started_ms"], MAX_MS)
        ended, duration = nullable(t["ended_ms"]), nullable(t["duration_ms"])
        require((ended is None) == (duration is None))
        require(ended is None or (ended >= started and duration == ended - started))
        tx.append({**t, "category": kind(t["category"], TX)})
    completed = [t["ended_ms"] for t in tx if t["ended_ms"] is not None]
    for read in reads:
        past = [v for v in completed if v <= read["started_ms"]]
        require(
            read["since_last_tx_ms"] ==
            (None if not past else read["started_ms"] - max(past))
        )

    candidates = []
    last_ping = None
    for raw in source["h2_candidates"]:
        f = keys(raw, {
            "kind", "confidence", "offset", "length", "completed_ms",
            "first_read", "last_read", "since_last_tx_ms", "ping_interval_ms",
        })
        label = kind(f["kind"], FRAME)
        require(f["confidence"] == "h2_hypothesis_only")
        start, length = integer(f["offset"]), integer(f["length"])
        require(0 < length <= rx_bytes and start + length <= rx_bytes)
        intersections = [
            r["index"] for r in reads
            if r["offset"] < start + length and r["offset"] + r["received"] > start
        ]
        require(bool(intersections))
        require(
            f["first_read"] == intersections[0]
            and f["last_read"] == intersections[-1]
        )
        completed_ms = integer(f["completed_ms"], MAX_MS)
        past = [v for v in completed if v <= completed_ms]
        require(f["since_last_tx_ms"] ==
                (None if not past else completed_ms - max(past)))
        interval = nullable(f["ping_interval_ms"])
        require(
            interval
            == (
                completed_ms - last_ping
                if last_ping is not None and label == "ping_h2"
                else None
            )
        )
        if label == "ping_h2":
            last_ping = completed_ms
        candidates.append({**f, "kind": label, "confidence": "h2_hypothesis_only"})

    unknown = []
    for raw in source["unattributed"]:
        u = keys(raw, {"offset", "length", "basis"})
        start, length = integer(u["offset"]), integer(u["length"])
        require(0 < length <= rx_bytes and start + length <= rx_bytes)
        require(kind(u["basis"], {"h2_unproven_suffix", "unclassified"}))
        unknown.append(dict(u))

    close = keys(source["close"], {
        "state", "started_ms", "ended_ms", "duration_ms",
    })
    state = kind(close["state"], {"not_recorded", "attempted", "closed", "error"})
    start, end, duration = (
        nullable(close["started_ms"]), nullable(close["ended_ms"]),
        nullable(close["duration_ms"]),
    )
    require((state == "not_recorded") == (start is None))
    require((state in {"closed", "error"}) == (end is not None))
    require(end is None or (end >= start and duration == end - start))
    require(end is not None or duration is None)
    fragmented = sum(f["last_read"] > f["first_read"] for f in candidates)
    concatenated = sum(
        sum(f["first_read"] <= r["index"] <= f["last_read"] for f in candidates) >= 2
        for r in reads
    )
    require(
        integer(source["fragmented_candidates"], 256) == fragmented
        and integer(source["concatenated_reads"], 260) == concatenated
    )
    return {
        "basis": "client_monotonic_relative",
        "reads": reads, "tx": tx, "h2_candidates": candidates,
        "unattributed": unknown, "close": dict(close),
        "fragmented_candidates": fragmented,
        "concatenated_reads": concatenated,
    }
