"""#186-D2 synthetic supervision policy, never a process/network supervisor.

All time and lifecycle evidence is explicitly injected. Requests below are
scalar intentions, not proof of a signal, close, waitpid or authenticated worker.
"""

import copy
import json

from scripts.info_delivery_scenario import validate_report as validate_observation

LIMITS = {
    "observation_ms": 3_540_000,
    "cleanup_reserve_ms": 60_000,
    "total_ms": 3_600_000,
    "max_events": 64,
    "max_report_bytes": 8192,
}
MAX_TIME = 2**53 - 1
ERRORS = {
    "none",
    "clock",
    "invalid_evidence",
    "evidence_time",
    "evidence_missing",
    "duplicate_evidence",
    "late_evidence",
    "observation_failed",
    "observation_incomplete",
    "cancelled",
    "worker_failed",
    "cleanup_failed",
    "cleanup_unproven",
    "cleanup_timeout",
    "global_timeout",
    "unexpected_event",
    "event_budget",
}
EVENTS = {
    "start",
    "observation",
    "tick",
    "cancel",
    "worker_failed",
    "cleanup_failed",
    "transport_closed",
    "rx_reaped",
    "worker_reaped",
    "finish",
    "event_budget",
}
ACKS = {"transport_closed", "rx_reaped", "worker_reaped"}
CONSTANTS = {
    "schema": 1,
    "scenario": "info-observation-supervisor",
    "mode": "offline",
    "proof_scope": "synthetic_events",
    "live_provenance": "not_proven",
    "boundary_proven": False,
    "info_framing": "INCONCLUSIVE",
}


class InvalidSupervision(ValueError):
    def __init__(self):
        super().__init__("invalid_offline_info_supervision")


def need(condition):
    if not condition:
        raise InvalidSupervision()


def time_value(value):
    return type(value) is int and 0 <= value <= MAX_TIME


class InfoSupervisor:
    """Deterministic, bounded reducer. No implicit clock, timer, callback or I/O."""

    def __init__(self, *, clock_ms):
        need(callable(clock_ms))
        self._clock = clock_ms
        self._origin = None
        self._elapsed = None
        self._phase = "NEW"
        self._events = []
        self._observation = None
        self._started = False
        self._clock_valid = True
        self._first_error = self._stop_reason = "none"
        self._cleanup_start = self._cleanup_deadline = None
        self._stop_requested = self._abort_requested = self._reap_requested = False
        self._cleanup_failed = False
        self._acks = dict.fromkeys(ACKS, False)

    @property
    def state(self):
        return self._phase

    def _latch(self, error):
        if self._first_error == "none":
            self._first_error = error

    def _cleanup(self, reason, *, at=None):
        self._phase = "CLEANING"
        self._stop_requested = self._reap_requested = True
        self._stop_reason = reason
        if self._cleanup_start is None:
            self._cleanup_start = self._elapsed if at is None else at
            self._cleanup_deadline = min(
                self._cleanup_start + LIMITS["cleanup_reserve_ms"], LIMITS["total_ms"]
            )

    def _stop_failure(self, reason):
        self._latch(reason)
        self._stop_reason = reason
        self._phase = "STOPPED"
        if self._started:
            self._stop_requested = self._abort_requested = self._reap_requested = True

    def _stamp(self, kind):
        try:
            value = self._clock()
            need(time_value(value))
            if kind == "start" and self._origin is None:
                self._origin = value
            need(self._origin is not None)
            elapsed = value - self._origin
            need(time_value(elapsed))
            need(self._elapsed is None or elapsed >= self._elapsed)
        except Exception:
            return None
        self._elapsed = elapsed
        return elapsed

    def _advance(self):
        if self._phase == "OBSERVING" and self._elapsed >= LIMITS["observation_ms"]:
            # Late polling never moves the fixed observation/global boundaries.
            self._cleanup("window_elapsed", at=LIMITS["observation_ms"])
            if self._observation is None:
                self._latch("evidence_missing")
        if self._phase == "CLEANING" and self._elapsed >= self._cleanup_deadline:
            self._cleanup_failed = True
            self._stop_failure(
                "global_timeout"
                if self._elapsed >= LIMITS["total_ms"]
                else "cleanup_timeout"
            )

    def _accept(self, report):
        if self._phase != "OBSERVING":
            self._latch("late_evidence")
            return
        if self._observation is not None:
            self._latch("duplicate_evidence")
            self._cleanup("duplicate_evidence")
            return
        try:
            validate_observation(report)
            need(
                all(
                    type(key) is str
                    for part in (report, report["limits"], report["steps"])
                    for key in part
                )
            )
            need(report["started"] and report["result"] != "NOT RUN")
            self._observation = copy.deepcopy(report)
        except Exception:
            self._latch("invalid_evidence")
            self._cleanup("invalid_evidence")
            return
        if report["elapsed_ms"] > self._elapsed:
            self._latch("evidence_time")
            self._cleanup("evidence_time")
        elif report["result"] == "SUCCESS":
            self._cleanup("observed")
        elif report["result"] != "INCONCLUSIVE":
            self._latch("observation_failed")
            self._cleanup("observation_failed")
        # No Info: stay in OBSERVING until the fixed window ends.

    def _step(self, kind, report=None):
        need(self._phase != "STOPPED" and kind in EVENTS - {"event_budget"})
        need(self._phase != "NEW" or kind in {"start", "cancel"})
        at = None if self._phase == "NEW" and kind == "cancel" else self._stamp(kind)
        if len(self._events) == LIMITS["max_events"] - 1:
            self._events.append({"event": "event_budget", "at_ms": at})
            if at is None:
                self._clock_valid = False
            self._stop_failure("event_budget")
            return
        self._events.append({"event": kind, "at_ms": at})
        if self._phase == "NEW":
            if kind == "cancel":
                self._stop_failure("cancelled")
            elif at is None:
                self._clock_valid = False
                self._stop_failure("clock")
            else:
                self._started, self._phase = True, "OBSERVING"
            return
        if at is None:
            self._clock_valid = False
            self._latch("clock")
            self._abort_requested = True
            self._cleanup("clock")
        if self._clock_valid:
            self._advance()
        if self._phase == "STOPPED":
            return
        if kind == "tick":
            return
        if kind == "observation":
            if self._clock_valid:
                self._accept(report)
            return
        if kind in {"cancel", "worker_failed", "cleanup_failed"}:
            reason = "cancelled" if kind == "cancel" else kind
            self._latch(reason)
            self._abort_requested = True
            self._cleanup_failed |= kind == "cleanup_failed"
            self._cleanup(reason)
        elif kind in ACKS:
            if self._phase != "CLEANING" or not self._clock_valid:
                self._stop_failure("unexpected_event")
            elif self._acks[kind] or (
                kind == "worker_reaped"
                and not (self._acks["transport_closed"] and self._acks["rx_reaped"])
            ):
                self._stop_failure("cleanup_unproven")
            else:
                self._acks[kind] = True
                if all(self._acks.values()):
                    self._phase = "STOPPED"
        elif kind == "finish":
            self._stop_failure(
                "observation_incomplete"
                if self._phase == "OBSERVING"
                else "cleanup_unproven"
            )
        else:
            self._stop_failure("unexpected_event")

    def start(self):
        self._step("start")

    def observe(self, report):
        self._step("observation", report)

    def tick(self):
        self._step("tick")

    def event(self, kind):
        need(
            type(kind) is str
            and kind in ACKS | {"cancel", "worker_failed", "cleanup_failed"}
        )
        self._step(kind)

    def finish(self):
        if self._phase == "NEW":
            self._phase = "STOPPED"
        elif self._phase != "STOPPED":
            self._step("finish")
        clean = bool(
            self._observation
            and self._observation["cleanup_attested"]
            and all(self._acks.values())
            and self._clock_valid
            and not self._cleanup_failed
        )
        if self._first_error != "none":
            result, reason = "FAILURE", self._first_error
        elif not self._started:
            result, reason = "NOT RUN", "not_started"
        elif not clean:
            result, reason = "FAILURE", "cleanup_unproven"
        elif self._observation["result"] == "SUCCESS":
            result, reason = "SUCCESS", "post_drop_read_verified"
        elif self._stop_reason == "window_elapsed":
            result, reason = "INCONCLUSIVE", "info_absent"
        else:
            result, reason = "FAILURE", "evidence_missing"
        output = {
            **CONSTANTS,
            "limits": dict(LIMITS),
            "phase": self._phase,
            "events": self._events,
            "observation": self._observation,
            "started": self._started,
            "clock_valid": self._clock_valid,
            "elapsed_ms": self._elapsed,
            "cleanup_started_ms": self._cleanup_start,
            "cleanup_deadline_ms": self._cleanup_deadline,
            "first_error": self._first_error,
            "stop_reason": self._stop_reason,
            "stop_requested": self._stop_requested,
            "abort_requested": self._abort_requested,
            "reap_requested": self._reap_requested,
            **self._acks,
            "cleanup_attested": clean,
            "result": result,
            "reason": reason,
        }
        need(
            len(json.dumps(output, separators=(",", ":")).encode())
            <= LIMITS["max_report_bytes"]
        )
        return copy.deepcopy(output)


def validate_supervision_report(report):
    """Closed schema plus deterministic replay; never authenticates the events."""
    try:
        empty = InfoSupervisor(clock_ms=lambda: 0).finish()
        need(type(report) is dict and report.keys() == empty.keys())
        for key, value in CONSTANTS.items():
            need(type(report[key]) is type(value) and report[key] == value)
        need(type(report["limits"]) is dict and report["limits"] == LIMITS)
        need(all(type(value) is int for value in report["limits"].values()))
        for key in (
            "started",
            "clock_valid",
            "stop_requested",
            "abort_requested",
            "reap_requested",
            *ACKS,
            "cleanup_attested",
        ):
            need(type(report[key]) is bool)
        for key in ("elapsed_ms", "cleanup_started_ms", "cleanup_deadline_ms"):
            need(report[key] is None or time_value(report[key]))
        need(type(report["phase"]) is str and report["phase"] == "STOPPED")
        need(type(report["first_error"]) is str and report["first_error"] in ERRORS)
        need(
            type(report["stop_reason"]) is str
            and report["stop_reason"] in ERRORS | {"observed", "window_elapsed"}
        )
        need(type(report["result"]) is str and type(report["reason"]) is str)
        if report["observation"] is not None:
            validate_observation(report["observation"])
        events = report["events"]
        need(type(events) is list and len(events) <= LIMITS["max_events"])
        now = [0]
        replay = InfoSupervisor(clock_ms=lambda: now[0])
        for entry in events:
            need(type(entry) is dict and entry.keys() == {"event", "at_ms"})
            kind, now[0] = entry["event"], entry["at_ms"]
            need(type(kind) is str and kind in EVENTS)
            need(now[0] is None or time_value(now[0]))
            if kind == "observation":
                replay.observe(report["observation"])
            elif kind == "event_budget":
                need(len(replay._events) == LIMITS["max_events"] - 1)
                replay.tick()
            else:
                if kind == "finish":
                    replay.finish()
                else:
                    replay._step(kind)
        need(replay.finish() == report)
        need(
            len(json.dumps(report, separators=(",", ":")).encode())
            <= LIMITS["max_report_bytes"]
        )
        return copy.deepcopy(report)
    except Exception:
        raise InvalidSupervision() from None


def encode_supervision_report(report):
    return json.dumps(
        validate_supervision_report(report), separators=(",", ":"), sort_keys=True
    )
