"""Closed v3 report projection only; no observer, clock, credentials or I/O RX.

The receipt fields describe evidence a FUTURE producer must receive from the
origin owner at consumption, with stop history. A final revoked snapshot cannot
be upgraded into this receipt. This structural validator authenticates no event.
"""

import copy
import json
import re
from pathlib import Path

CONTRACT = json.loads(
    Path(__file__).with_name("session_suite_v3_contract.json").read_text()
)


def need(ok):
    if not ok:
        raise ValueError("invalid_session_suite_report")


def validate_v3(r, proof, provenance, counters, terminals, messages):
    """Validate independent origin, timing, stability and bounded RX evidence."""
    expected = (
        provenance
        | set(counters)
        | set(CONTRACT)
        | {
            "schema",
            "scenario",
            "boundary_proven",
            "result",
            "terminal",
            "read_slot",
            "failure_phase",
            "failure_category",
            "message_category",
            "causal_ms",
        }
    )
    need(type(r) is dict and set(r) == expected)
    need(type(r["schema"]) is int and r["schema"] == 3)
    need(r["scenario"] == "session-reconnect-no-pong" and r["boundary_proven"] is False)
    for k in provenance:
        need(type(r[k]) is type(proof[k]) and r[k] == proof[k])
    for k in ("merge_sha", "candidate_sha"):
        need(type(r[k]) is str and re.fullmatch(r"[0-9a-f]{40}", r[k]))
    need(type(r["run_attempt"]) is int and r["run_attempt"] == 1)
    for k in ("run_id", "pr_number"):
        need(type(r[k]) is int and 1 <= r[k] <= 2**53 - 1)
    for k, maximum in counters.items():
        need(type(r[k]) is int and 0 <= r[k] <= maximum)
    need(type(r["terminal"]) is str and r["terminal"] in terminals)
    need(
        type(r["result"]) is str
        and r["result"] in {"recovered_120s", "inconclusive", "interrupted", "not_run"}
    )
    for group, fields in CONTRACT.items():
        values = r[group]
        need(type(values) is dict and set(values) == set(fields))
        for k, spec in fields.items():
            v = values[k]
            if spec[0] == "nullable_int":
                need(v is None or (type(v) is int and 0 <= v <= spec[1]))
            elif spec[0] == "bool":
                need(type(v) is bool)
            else:
                need(type(v) is str and v in spec[1])
    need(r["reconnections"] == max(0, r["opens"] - 1))
    need(r["pongs"] + r["pongs_suppressed"] <= r["pings"])
    need(r["reads_ok"] + r["reads_failed"] == r["reads"])
    need(r["reads_ok"] <= r["responses"] <= r["reads"])
    need(r["rx_chunks_total"] <= r["rx_bytes_total"])
    need(r["eofs_after_suppression"] <= r["peer_eofs"] <= r["opens"])
    need(r["recovery_reads_ok"] <= r["reads_ok"] and r["recovery_pongs"] <= r["pongs"])
    phase, category, message = (
        r["failure_phase"],
        r["failure_category"],
        r["message_category"],
    )
    need(type(phase) is str and phase in messages)
    need(type(category) is str and category in terminals)
    need(type(message) is str and message in messages[phase])
    need(type(r["read_slot"]) is int and 0 <= r["read_slot"] <= r["reads"])
    causal = r["causal_ms"]
    need(causal is None or (type(causal) is int and 0 <= causal <= 360000))
    has_t0 = r["timing"]["t0_observed"]
    need((phase == "none" or not has_t0) == (causal is None))
    need((phase == "none") == (category in {"verified", "first_not_admissible"}))
    if phase == "none":
        need(r["read_slot"] == 0 and category == r["terminal"])
    if phase in {
        "frame_boundary",
        "message_classification",
        "request_correlation",
        "response_validation",
    }:
        need(category == "protocol")
    if phase == "tls_read":
        need(category in {"transport", "budget"})
    if phase == "pong_tx":
        need(category in {"transport", "protocol"})
    if phase == "teardown":
        need(category == r["terminal"] == "closed")
    if phase == "scheduled_read":
        need(r["read_slot"] > 0)
    t, q, s, d = (r[k] for k in ("timing", "quarantine", "stability", "rx_diagnostic"))
    end = t["functional_end_ms"]
    success, skipped = r["result"] == "recovered_120s", r["result"] == "not_run"
    need(success == (r["terminal"] == "verified"))
    need(skipped == (r["terminal"] == "first_not_admissible"))
    if skipped:
        need(all(r[k] == 0 for k in counters) and not has_t0)
        need(
            all(
                t[k] is None
                for k, spec in CONTRACT["timing"].items()
                if spec[0] == "nullable_int"
            )
        )
        need(phase == "none")
    elif not has_t0:
        need(
            all(
                t[k] is None
                for k, spec in CONTRACT["timing"].items()
                if spec[0] == "nullable_int"
            )
        )
        need(phase == "opening" and category == r["terminal"] and r["read_slot"] == 0)
        need(r["opens"] >= 1 and not success)
        need(
            r["terminal"]
            in {"timeout", "budget", "transport", "protocol", "internal", "closed"}
        )
        need(
            all(
                r[k] == 0
                for k in counters
                if k
                not in {
                    "duration_ms",
                    "opens",
                    "reconnections",
                    "rx_bytes_total",
                    "rx_chunks_total",
                }
            )
        )
    else:
        need(end is not None and r["opens"] >= 1 and r["duration_ms"] >= end)
        need(
            all(
                t[k] is not None and end <= t[k] for k in t if k.endswith("deadline_ms")
            )
        )
        need(causal is None or causal <= end)
        need(r["reads"] <= end // 60000 + 1)
        if causal is not None:
            need(r["read_slot"] <= causal // 60000 + 1)
    inhibition = t["inhibition_ms"]
    need((inhibition is not None) == (r["pongs_suppressed"] > 0))
    if inhibition is not None:
        need(120000 <= inhibition <= end)
    entered, eof, consumed, accepted = (
        q[k] for k in ("entered_ms", "eof_ms", "consumed_ms", "accepted_ms")
    )
    need((q["outcome"] == "not_entered") == (entered is None))
    if entered is None:
        need(
            all(
                q[k] is None
                for k in (
                    "eof_ms",
                    "consumed_ms",
                    "origin_generation",
                    "cleanup_ms",
                    "stop_ms",
                    "accepted_ms",
                    "accepted_generation",
                )
            )
        )
        need(q["eof_origin"] == q["receipt"] == q["stop"] == "none")
    else:
        need(inhibition is not None and inhibition <= entered <= end)
        need(entered < min(240000, *(t[k] for k in t if k.endswith("deadline_ms"))))
        need(q["origin_generation"] == 1)
        need(
            (phase, category, message)
            == ("message_classification", "protocol", "close_client")
        )
        need(causal is not None and causal <= entered)
    need((eof is None) == (q["eof_origin"] == "none"))
    if eof is not None:
        need(entered is not None and entered <= eof <= end)
    transport_eof = eof is not None and q["eof_origin"] == "transport_read"
    if r["eofs_after_suppression"]:
        need(inhibition is not None)
    if transport_eof:
        need(r["eofs_after_suppression"] == 1)
    need((consumed is not None) == (q["receipt"] == "valid_at_consumption"))
    need((consumed is not None) == (q["outcome"] == "consumed"))
    if consumed is not None:
        need(
            transport_eof
            and entered
            < eof
            <= consumed
            < min(240000, *(t[k] for k in t if k.endswith("deadline_ms")))
        )
        need(consumed <= end)
    if q["outcome"] in {"waiting", "no_eof"}:
        need(eof is None and q["receipt"] == "none" and q["stop"] == "none")
        need(r["eofs_after_suppression"] == 0)
    if q["outcome"] == "revoked":
        need(q["receipt"] == "revoked_before_consumption")
        need(q["stop"] in {"local_before_consumption", "cancel_before_consumption"})
    if q["receipt"] == "revoked_before_consumption":
        need(q["outcome"] == "revoked")
    if q["receipt"] == "invalid":
        need(q["outcome"] == "refused")
    if q["outcome"] == "expired":
        need(end >= min(240000, *(t[k] for k in t if k.endswith("deadline_ms"))))
    if q["outcome"] == "waiting":
        need(end < min(240000, *(t[k] for k in t if k.endswith("deadline_ms"))))
    need((q["stop"] == "none") == (q["stop_ms"] is None))
    if q["stop_ms"] is not None:
        need(entered is not None and entered <= q["stop_ms"] <= end)
        if q["stop"] in {"local_after_consumption", "cancel_after_consumption"}:
            # A historical owner receipt attests execution order; equal
            # quantized times confer no current recovery permission.
            need(consumed is not None and consumed <= q["stop_ms"])
        else:
            need(consumed is None)
    if q["cleanup_ms"] is not None:
        need(consumed is not None and consumed <= q["cleanup_ms"] <= end)
    need((accepted is None) == (q["accepted_generation"] is None))
    need(r["recovery_generation"] == (q["accepted_generation"] or 0))
    if accepted is not None:
        need(
            consumed is not None
            and consumed
            < accepted
            < min(240000, *(t[k] for k in t if k.endswith("deadline_ms")))
        )
        need(2 <= q["accepted_generation"] <= r["opens"])
        need(q["accepted_generation"] == r["opens"])
        need(
            accepted + 120000
            <= min(360000, *(t[k] for k in t if k.endswith("deadline_ms")))
        )
        need(q["cleanup_ms"] is not None and q["cleanup_ms"] <= accepted)
        need(q["stop_ms"] is None or accepted <= q["stop_ms"])
        need(s["start_ms"] == accepted and s["generation"] == q["accepted_generation"])
    else:
        need(
            all(s[k] is None for k in s if k != "interrupted")
            and s["interrupted"] is False
        )
    if q["stop"] != "none":
        need(r["result"] == "interrupted")
        if accepted is None:
            need(r["terminal"] == "closed")
        else:
            need(r["terminal"] == "stability_lost")
            need(s["interrupted"] and s["end_ms"] is not None)
    if s["start_ms"] is not None:
        need(accepted is not None and accepted <= end)
        if s["end_ms"] is not None:
            need(accepted <= s["end_ms"] <= end)
            if q["stop_ms"] is not None:
                need(s["interrupted"] and s["end_ms"] <= q["stop_ms"])
        need(r["stable_ms"] == (0 if s["end_ms"] is None else s["end_ms"] - accepted))
        for key, count in (
            ("first_pong_ms", "recovery_pongs"),
            ("first_read_ok_ms", "recovery_reads_ok"),
        ):
            need((s[key] is not None) == (r[count] > 0))
            if s[key] is not None:
                need(
                    accepted
                    <= s[key]
                    <= (s["end_ms"] if s["end_ms"] is not None else end)
                )
    else:
        need(r["stable_ms"] == r["recovery_reads_ok"] == r["recovery_pongs"] == 0)
    if success:
        need(
            consumed is not None and accepted is not None and s["interrupted"] is False
        )
        need(s["end_ms"] == accepted + 120000 and s["end_ms"] <= end)
        need(s["end_ms"] < min(t[k] for k in t if k.endswith("deadline_ms")))
        need(
            r["stable_ms"] == 120000
            and r["recovery_pongs"] > 0
            and r["recovery_reads_ok"] > 0
        )
        need(r["peer_eofs"] == 1 and r["opens"] == q["accepted_generation"])
        need(d["observed"] and d["end_ms"] == end)
        need(q["stop"] == "none")
    if r["terminal"] == "stability_lost":
        need(accepted is not None and s["interrupted"])
    if r["terminal"] == "not_exercised":
        need(inhibition is None and entered is None)
    if r["terminal"] == "no_disconnect":
        need(inhibition is not None and not transport_eof and consumed is None)
    # Fixed-size aggregate: offsets count whole RX deliveries once, opening
    # included. They never claim a frame boundary or contain payload bytes.
    if not d["observed"]:
        need(
            all(
                d[k] is None
                for k, spec in CONTRACT["rx_diagnostic"].items()
                if spec[0] == "nullable_int"
            )
        )
        need(
            (d["framer"], d["phase"], d["category"], d["message"])
            == ("not_observed", "none", "none", "unclassified")
        )
    else:
        need(
            end is not None
            and d["start_ms"] == 150000
            and d["end_ms"] is not None
            and 150000 <= d["end_ms"] <= end
        )
        need(
            all(
                d[k] is not None
                for k in ("bytes", "chunks", "start_offset", "end_offset")
            )
        )
        need(d["start_offset"] <= d["end_offset"] <= r["rx_bytes_total"])
        need(d["end_offset"] - d["start_offset"] == d["bytes"])
        need(d["chunks"] <= d["bytes"] and d["chunks"] <= r["rx_chunks_total"])
        need((d["bytes"] == 0) == (d["chunks"] == 0))
        need((d["first_rx_ms"] is None) == (d["bytes"] == 0))
        need((d["last_rx_ms"] is None) == (d["bytes"] == 0))
        if d["bytes"]:
            need(150000 <= d["first_rx_ms"] <= d["last_rx_ms"] <= d["end_ms"])
        rejection = d["rejection_ms"]
        need(
            (rejection is None)
            == (d["rejection_offset"] is None)
            == (d["rejection_size"] is None)
        )
        if rejection is None:
            prior_refusal = (
                causal is not None
                and causal < 150000
                and phase
                in {
                    "frame_boundary",
                    "message_classification",
                    "request_correlation",
                    "response_validation",
                }
                and category == "protocol"
            )
            need(
                d["framer"] in {"empty", "prefix", "ambiguous"}
                or d["framer"] == "refused"
                and prior_refusal
            )
            need(
                (d["phase"], d["category"], d["message"])
                == ("none", "none", "unclassified")
            )
        else:
            # Delivery and the existing parser's decision are separate events.
            # Retained pre-window bytes may be rejected with zero new RX.
            need(150000 <= rejection <= d["end_ms"])
            need(
                d["framer"] == "refused"
                and d["category"] == "protocol"
                and d["phase"] != "none"
            )
            need(d["message"] in messages[d["phase"]])
            need(d["rejection_offset"] < d["end_offset"])
            need(0 < d["rejection_size"] <= d["end_offset"] - d["rejection_offset"])
            if d["rejection_offset"] + d["rejection_size"] > d["start_offset"]:
                need(d["first_rx_ms"] is not None and d["first_rx_ms"] <= rejection)
        if d["eof_ms"] is not None:
            need(150000 <= d["eof_ms"] <= d["end_ms"])
            need(r["peer_eofs"] > 0)
            if transport_eof and r["peer_eofs"] == 1:
                need(d["eof_ms"] == eof)
        if transport_eof and 150000 <= eof <= d["end_ms"]:
            need(d["eof_ms"] == eof)
        if (
            phase
            in {
                "frame_boundary",
                "message_classification",
                "request_correlation",
                "response_validation",
            }
            and 150000 <= causal <= d["end_ms"]
        ):
            need(
                (d["rejection_ms"], d["phase"], d["category"], d["message"])
                == (causal, phase, category, message)
            )
    if s["first_read_ok_ms"] is not None:
        # >=60 s separates requests, not response-validation times. Bound the
        # count by the recovery phase; do not invent a last read/delivery time.
        stable_end = s["end_ms"] if s["end_ms"] is not None else end
        need(r["recovery_reads_ok"] <= (stable_end - accepted) // 60000 + 1)
        if (
            d["observed"]
            and 150000 <= s["first_read_ok_ms"] <= d["end_ms"]
            and (accepted >= 150000 or d["start_offset"] == 0)
        ):
            need(d["bytes"] > 0 and d["first_rx_ms"] <= s["first_read_ok_ms"])
    return copy.deepcopy({k: r[k] for k in sorted(expected)})
