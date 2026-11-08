"""Offline #186-C observer/contract; no connect, read, TX, CLI or live supplier.

Only fixtures construct/drive a session and the explicit transport/clock. This
module observes the real session witness and a bounded scalar transport ledger.
Future manual admission, supervision and publication are deliberately absent.
"""

import json
import math

from custom_components.hoben.exceptions import (
    HobenAuthorizationRequiredError,
    HobenClosedError,
    HobenInternalError,
    HobenProtocolError,
    HobenTimeoutError,
    HobenTlsVerificationError,
    HobenTransportError,
)
from custom_components.hoben.v4_session import SessionState, V4Session, V4SessionMode

LIMITS = {
    "collection_ms": 30000,
    "cleanup_ms": 5000,
    "total_ms": 35000,
    "max_drops": 16,
    "max_events": 128,
    "max_report_bytes": 8192,
}
ERRORS = {
    "none",
    "protocol",
    "transport",
    "authentication",
    "internal",
    "timeout",
    "cancelled",
    "closed",
    "cleanup_unproven",
    "cleanup_timeout",
    "clock",
    "budget",
    "multiple_sessions",
    "evidence_gap",
}
EVENTS = {
    "connect",
    "opening",
    "info_candidate",
    "ping",
    "other",
    "pong",
    "request",
    "request_completed",
    "close_completed",
    "drop",
    "verified",
}
STEPS = {"drop", "ping", "pong", "request", "read"}


class InvalidInfoEvidence(ValueError):
    def __init__(self):
        super().__init__("invalid_offline_info_evidence")


def require(condition):
    if not condition:
        raise InvalidInfoEvidence()


def integer(value, low, high):
    return type(value) is int and low <= value <= high


def error_category(error):
    """Never copy an exception's message, args, payload or traceback."""
    for classes, category in (
        (
            (HobenAuthorizationRequiredError, HobenTlsVerificationError),
            "authentication",
        ),
        ((HobenInternalError,), "internal"),
        ((HobenTimeoutError, TimeoutError), "timeout"),
        ((HobenClosedError,), "closed"),
        ((HobenProtocolError,), "protocol"),
        ((HobenTransportError,), "transport"),
    ):
        if isinstance(error, classes):
            return category
    return "internal"


class OfflineTransportLedger:
    """Scalar fixture instrumentation, bound to one injected transport object.

    No bytes/identity/exception accepted or retained. Read/TX wrappers in the
    fixture record completions; they do not infer frames inside opaque data.
    """

    def __init__(self, transport):
        self.transport = transport
        self.events = []

    def note(self, kind, delivery_bytes=0):
        require(type(kind) is str and kind in EVENTS)
        require(integer(delivery_bytes, 0, 4096))
        require(len(self.events) < LIMITS["max_events"])
        seq = len(self.events) + 1
        self.events.append((seq, kind, delivery_bytes))
        return seq

    def count(self, kind, after=0):
        return sum(k == kind and n > after for n, k, _ in self.events)

    def first(self, kind, after=0):
        return next((n for n, k, _ in self.events if k == kind and n > after), None)


def verdict(report):
    if not report["started"]:
        if report["first_error"] != "none":
            return "FAILURE", report["first_error"]
        return "NOT RUN", "not_started"
    if not report["cleanup_attested"]:
        return "FAILURE", "cleanup_unproven"
    if report["first_error"] != "none":
        return "FAILURE", report["first_error"]
    if not report["same_session"] or report["openings"] != 1 or report["reconnections"]:
        return "FAILURE", "multiple_sessions"
    if not report["info_discarded"]:
        return "INCONCLUSIVE", "info_absent"
    steps = report["steps"]
    ordered = all(integer(n, 1, 128) for n in steps.values()) and (
        steps["drop"] < steps["ping"] < steps["pong"] < steps["request"] < steps["read"]
    )
    if (
        ordered
        and report["reads_after_drop"] == report["requests_after_drop"] == 1
        and report["pings_after_drop"] == report["pongs_after_drop"] >= 1
        and len(report["info_delivery_bytes"]) == report["info_discarded"]
        and report["opened_validated"]
        and report["rx_reaped"]
    ):
        return "SUCCESS", "post_drop_read_verified"
    return "FAILURE", "insufficient_evidence"


class InfoDeliveryScenario:
    """Read-only observation of one real session; the fixture owns all actions."""

    def __init__(self, session, ledger, *, clock):
        require(
            type(session) is V4Session and session._mode is V4SessionMode.PERSISTENT
        )
        require(type(ledger) is OfflineTransportLedger and callable(clock))
        self.session, self.ledger, self.clock = session, ledger, clock
        self.start = self._time()
        self.last_time = self.start
        self.elapsed = self.cleanup_start = 0
        self.first_error = "none"
        self.opened = self.same_session = False
        self.rx = None
        self.verified = session.verified_read_sequence
        self.drops = 0
        self.sizes = []
        self.steps = dict.fromkeys(STEPS)
        self.reads = 0

    def _time(self):
        value = self.clock()
        require(type(value) in (int, float) and math.isfinite(value) and value >= 0)
        return value

    def fail(self, category):
        require(type(category) is str and category in ERRORS - {"none"})
        if self.first_error == "none":
            self.first_error = category

    def _elapsed(self):
        try:
            now = self._time()
            require(now >= self.last_time)
            elapsed = int((now - self.start) * 1000)
            require(elapsed >= self.elapsed and elapsed <= LIMITS["total_ms"])
        except InvalidInfoEvidence:
            self.fail("clock")
        else:
            self.elapsed = elapsed
            self.last_time = now

    def sample(self):
        """Called after fixture scheduling turns, never a socket read or poll TX."""
        self._elapsed()
        session, ledger = self.session, self.ledger
        if self.elapsed >= LIMITS["collection_ms"]:
            self.fail("budget")
        if ledger.count("connect") > 1:
            self.same_session = False
            self.fail("multiple_sessions")
        if session.state is SessionState.CONNECTED:
            if not self.opened:
                self.opened = session.snapshot.opening is not None
                self.rx = session._rx_task
                self.same_session = session._transport is ledger.transport
            elif (
                session._transport is not ledger.transport
                or session._rx_task is not self.rx
            ):
                self.same_session = False
                self.fail("multiple_sessions")
        cap = session._info_delivery_drop
        count = cap._count if cap is not None else 0
        require(integer(count, 0, LIMITS["max_drops"]))
        if count != self.drops:
            candidates = [
                (n, size)
                for n, k, size in ledger.events
                if k == "info_candidate" and n > (self.steps["drop"] or 0)
            ]
            if count != self.drops + 1 or len(candidates) != 1:
                self.fail("evidence_gap")
            else:
                self.sizes.append(candidates[0][1])
            self.drops = count
            seq = ledger.note("drop")
            # Require the complete proof after the LAST observed drop. A good
            # sample or Pong from before another discard is never reusable.
            self.steps = dict.fromkeys(STEPS)
            self.steps["drop"] = seq
            self.reads = 0
        sequence = session.verified_read_sequence
        if sequence != self.verified:
            if sequence != self.verified + 1:
                self.fail("evidence_gap")
            drop = self.steps["drop"]
            if drop is not None and ledger.first("request", drop) is not None:
                if ledger.first("request_completed", drop) is None:
                    self.fail("evidence_gap")
                self.reads += 1
                self.steps["read"] = ledger.note("verified")
            self.verified = sequence
        if self.steps["drop"] is not None:
            for key, kind in (
                ("ping", "ping"),
                ("pong", "pong"),
                ("request", "request"),
            ):
                self.steps[key] = ledger.first(kind, self.steps["drop"])
        if session._rx_error is not None:
            self.fail(error_category(session._rx_error))

    def begin_cleanup(self):
        self._elapsed()
        self.cleanup_start = self.elapsed

    def finish(self):
        """Project only closed scalars; never export a session/dataclass wholesale."""
        self._elapsed()
        s, ledger = self.session, self.ledger
        cleanup_ms = self.elapsed - self.cleanup_start
        if cleanup_ms > LIMITS["cleanup_ms"]:
            self.fail("cleanup_timeout")
        reaped = s._rx_task is not None and s._rx_task.done()
        clean = (
            s.cleanup_succeeded
            and s.state is SessionState.CLOSED
            and reaped
            and (
                not s._tx_operations
                and ledger.count("close_completed") == 1
                and ledger.transport.active_reads == ledger.transport.active_tx == 0
            )
        )
        drop = self.steps["drop"] or len(ledger.events) + 1
        report = {
            "schema": 1,
            "scenario": "info-delivery-0x0C",
            "mode": "offline",
            "experimental_hypothesis": True,
            "boundary_proven": False,
            "info_framing": "INCONCLUSIVE",
            "limits": dict(LIMITS),
            "started": ledger.count("connect") > 0,
            "opened_validated": self.opened,
            "same_session": self.same_session,
            "openings": ledger.count("connect"),
            "reconnections": max(0, ledger.count("connect") - 1),
            "info_discarded": self.drops,
            "info_delivery_bytes": list(self.sizes),
            "pings_after_drop": ledger.count("ping", drop),
            "pongs_after_drop": ledger.count("pong", drop),
            "requests_after_drop": ledger.count("request", drop),
            "reads_after_drop": self.reads,
            "steps": dict(self.steps),
            "rx_reaped": reaped,
            "cleanup_attested": bool(clean),
            "first_error": self.first_error,
            "elapsed_ms": self.elapsed,
            "collection_ms": self.cleanup_start,
            "cleanup_ms": cleanup_ms,
        }
        report["result"], report["reason"] = verdict(report)
        return validate_report(report)


def validate_report(report):
    """Refuse unknown keys/types, false proof, excess output or forged verdicts."""
    constants = {
        "schema": 1,
        "scenario": "info-delivery-0x0C",
        "mode": "offline",
        "experimental_hypothesis": True,
        "boundary_proven": False,
        "info_framing": "INCONCLUSIVE",
        "limits": LIMITS,
    }
    booleans = {
        "started",
        "opened_validated",
        "same_session",
        "rx_reaped",
        "cleanup_attested",
    }
    counters = {
        "openings": 2,
        "reconnections": 1,
        "info_discarded": 16,
        "pings_after_drop": 64,
        "pongs_after_drop": 64,
        "requests_after_drop": 1,
        "reads_after_drop": 1,
        "elapsed_ms": 35000,
        "collection_ms": 35000,
        "cleanup_ms": 35000,
    }
    keys = (
        set(constants)
        | booleans
        | set(counters)
        | {
            "info_delivery_bytes",
            "steps",
            "first_error",
            "result",
            "reason",
        }
    )
    require(type(report) is dict and report.keys() == keys)
    for k, v in constants.items():
        require(type(report[k]) is type(v) and report[k] == v)
    require(all(type(value) is int for value in report["limits"].values()))
    require(all(type(report[k]) is bool for k in booleans))
    require(all(integer(report[k], 0, maximum) for k, maximum in counters.items()))
    require(type(report["first_error"]) is str and report["first_error"] in ERRORS)
    sizes, steps = report["info_delivery_bytes"], report["steps"]
    require(type(sizes) is list and len(sizes) <= report["info_discarded"])
    require(all(integer(size, 1, 4096) for size in sizes))
    require(type(steps) is dict and steps.keys() == STEPS)
    require(all(n is None or integer(n, 1, 128) for n in steps.values()))
    for step, counter in (
        ("drop", "info_discarded"),
        ("ping", "pings_after_drop"),
        ("pong", "pongs_after_drop"),
        ("request", "requests_after_drop"),
        ("read", "reads_after_drop"),
    ):
        require((steps[step] is None) == (report[counter] == 0))
    if not report["info_discarded"]:
        require(all(n is None for n in steps.values()))
    require(report["reads_after_drop"] <= report["requests_after_drop"])
    require(report["reconnections"] == max(0, report["openings"] - 1))
    require(report["started"] == (report["openings"] > 0))
    require(not report["opened_validated"] or report["started"])
    require(not report["same_session"] or report["opened_validated"])
    require(report["elapsed_ms"] == report["collection_ms"] + report["cleanup_ms"])
    require(not report["cleanup_attested"] or report["rx_reaped"])
    if report["collection_ms"] >= LIMITS["collection_ms"]:
        require(report["first_error"] != "none")
    if report["cleanup_ms"] > LIMITS["cleanup_ms"]:
        require(report["first_error"] != "none")
    require(type(report["result"]) is str and type(report["reason"]) is str)
    require((report["result"], report["reason"]) == verdict(report))
    require(len(json.dumps(report, separators=(",", ":")).encode()) <= 8192)
    return report


def encode_report(report):
    validate_report(report)
    return json.dumps(report, separators=(",", ":"), sort_keys=True)
