"""Strictly bounded, payload-free timing projections from private H1/H2 journals.

Client read() completions are not wire frames. Candidate frame positions are
explicitly H2 hypotheses; all byte values and stove data stay private.
"""
from __future__ import annotations

import math
from collections.abc import Mapping

from scripts.boundary_analysis import RxRead

MAX_MS = 180_000
MAX_RX = 1024 * 1024
MAX_READS = 260
MAX_TX = 100
MAX_FRAMES = 256
TX_KINDS = frozenset({"open_client", "pong_before_open", "read_v4_h2", "pong_h2"})
FRAME_KINDS = frozenset({"ping_h2", "response_h2", "notification_h2"})
READ_STATES = frozenset({"received", "eof", "cancelled_read", "read_error"})


class TimelineInvalid(ValueError):
    """No source details or potentially private values appear in this error."""


def insist(condition: bool) -> None:
    if not condition:
        raise TimelineInvalid("invalid_timeline")


def milliseconds(value: object, zero: float) -> int:
    insist(type(value) in (int, float) and math.isfinite(value))
    elapsed = (value - zero) * 1000
    insist(-0.001 <= elapsed <= MAX_MS)
    return max(0, round(elapsed))


def metadata_timeline(
    events: list[dict],
    reads: list[RxRead],
    *,
    rx_bytes: int,
    opening_offset: int | None,
    h2: Mapping[str, object],
) -> dict:
    """Emit fixed fields only; discard data/payload even if journal is tainted."""
    insist(type(events) is list and type(reads) is list)
    insist(type(rx_bytes) is int and 0 <= rx_bytes <= MAX_RX)
    insist(len(reads) <= MAX_READS and len(events) <= MAX_READS * 5 + MAX_TX * 3)
    beginnings = [
        entry["started"]
        for entry in events
        if type(entry) is dict and entry.get("kind") == "tx_attempt"
    ]
    # A TLS connect refusal legitimately has no read or TX. Still record
    # its close attempt without inventing a network timestamp or frame.
    closing = [
        entry["at"] for entry in events
        if type(entry) is dict and entry.get("kind") == "close_attempt"
    ]
    insist(bool(beginnings) or bool(reads) or bool(closing))
    baseline = (
        beginnings[0] if beginnings else reads[0].started if reads else closing[0]
    )
    insist(type(baseline) in (int, float) and math.isfinite(baseline))
    rx_events = [e for e in events if e.get("kind") == "rx"]
    insist(len(rx_events) == len(reads))

    tx = []
    pending = None
    for event in events:
        kind = event.get("kind")
        if kind == "tx_attempt":
            insist(pending is None and len(tx) < MAX_TX)
            category = event.get("category")
            insist(type(category) is str and category in TX_KINDS)
            pending = {
                "category": category,
                "started_ms": milliseconds(event.get("started"), baseline),
                "ended_ms": None,
                "duration_ms": None,
            }
            tx.append(pending)
        elif kind == "tx_complete":
            insist(pending is not None and event.get("category") == pending["category"])
            started = milliseconds(event.get("started"), baseline)
            ended = milliseconds(event.get("ended"), baseline)
            insist(started == pending["started_ms"] and ended >= started)
            pending["ended_ms"] = ended
            pending["duration_ms"] = ended - started
            pending = None
    data_offset = 0
    timeline_reads = []
    for index, (event, record) in enumerate(zip(rx_events, reads, strict=True)):
        state = event.get("status")
        insist(type(state) is str and state in READ_STATES)
        insist(record.index == index and record.offset == data_offset)
        insist(
            type(record.requested) is int
            and 0 < record.requested <= 4096
            and type(record.returned) is int
            and 0 <= record.returned <= record.requested
        )
        insist((state == "received") == (record.returned > 0))
        started = milliseconds(record.started, baseline)
        ended = milliseconds(record.ended, baseline)
        insist(ended >= started)
        completed_tx = [
            t["ended_ms"] for t in tx
            if t["ended_ms"] is not None and t["ended_ms"] <= started
        ]
        previous_end = timeline_reads[-1]["ended_ms"] if timeline_reads else None
        insist(previous_end is None or started >= previous_end)
        timeline_reads.append({
            "index": index,
            "offset": data_offset,
            "requested": record.requested,
            "received": record.returned,
            "started_ms": started,
            "ended_ms": ended,
            "duration_ms": ended - started,
            "gap_previous_ms": None if previous_end is None else started - previous_end,
            "since_last_tx_ms": (
                None if not completed_tx else started - max(completed_tx)
            ),
            "state": state,
        })
        data_offset += record.returned
    insist(data_offset == rx_bytes)

    frames = []
    previous_ping = None
    for event in events:
        if event.get("kind") != "candidate_frame":
            continue
        insist(len(frames) < MAX_FRAMES)
        category, offset, length = (
            event.get("category"), event.get("offset"), event.get("length")
        )
        insist(type(category) is str and category in FRAME_KINDS)
        insist(type(offset) is int and type(length) is int)
        insist(0 <= offset < rx_bytes and 1 <= length <= rx_bytes - offset)
        ended = milliseconds(event.get("received_at"), baseline)
        intersects = [
            r["index"] for r in timeline_reads
            if r["offset"] < offset + length
            and r["offset"] + r["received"] > offset
        ]
        insist(bool(intersects))
        prior_tx = [
            t["ended_ms"] for t in tx
            if t["ended_ms"] is not None and t["ended_ms"] <= ended
        ]
        frames.append({
            "kind": category,
            "confidence": "h2_hypothesis_only",
            "offset": offset,
            "length": length,
            "completed_ms": ended,
            "first_read": intersects[0],
            "last_read": intersects[-1],
            "since_last_tx_ms": None if not prior_tx else ended - max(prior_tx),
            "ping_interval_ms": (
                None if category != "ping_h2" or previous_ping is None
                else ended - previous_ping
            ),
        })
        if category == "ping_h2":
            previous_ping = ended

    unknown = []
    if opening_offset is not None and h2.get("covered_bytes") is not None:
        covered = h2["covered_bytes"]
        remaining = h2.get("unattributed_bytes")
        insist(type(opening_offset) is int and 0 <= opening_offset <= rx_bytes)
        insist(type(covered) is int and type(remaining) is int)
        start = opening_offset + 48 + covered
        insist(0 <= start <= rx_bytes and remaining == rx_bytes - start)
        if remaining:
            unknown.append({
                "offset": start, "length": remaining, "basis": "h2_unproven_suffix"
            })
    elif rx_bytes:
        unknown.append({"offset": 0, "length": rx_bytes, "basis": "unclassified"})

    close_start, close_end, close_state = None, None, "not_recorded"
    for event in events:
        if event.get("kind") == "close_attempt":
            insist(close_start is None)
            close_start = milliseconds(event.get("at"), baseline)
            close_state = "attempted"
        elif event.get("kind") in ("close_complete", "close_error"):
            insist(close_start is not None and close_end is None)
            close_end = milliseconds(event.get("at"), baseline)
            insist(close_end >= close_start)
            close_state = "closed" if event["kind"] == "close_complete" else "error"
    return {
        "basis": "client_monotonic_relative",
        "reads": timeline_reads,
        "tx": tx,
        "h2_candidates": frames,
        "unattributed": unknown,
        "close": {
            "state": close_state,
            "started_ms": close_start,
            "ended_ms": close_end,
            "duration_ms": None if close_end is None else close_end - close_start,
        },
        "fragmented_candidates": sum(
            f["last_read"] > f["first_read"] for f in frames
        ),
        "concatenated_reads": sum(
            sum(
                f["first_read"] <= r["index"] <= f["last_read"]
                for f in frames
            ) >= 2
            for r in timeline_reads
        ),
    }
