"""Unconnected, pure offline policy: no TX freeze, transport EOF or retry proof.

Only tests instantiate this foundation. Integer monotonic milliseconds are
injected, never read from a clock. An EOF candidate is provisional and may be
revoked by stop, expiry or ambiguous ordering. A refusal is absorbing.
"""

from dataclasses import dataclass
from enum import StrEnum

MAX_TIME_MS = (1 << 53) - 1


class State(StrEnum):
    READY = "ready"
    WAITING = "waiting"
    EOF_CANDIDATE = "eof_candidate"
    REFUSED = "refused"


class Reason(StrEnum):
    NONE = "none"
    INELIGIBLE = "ineligible"
    INVALID = "invalid"
    STALE = "stale_generation"
    AMBIGUOUS = "ambiguous_order"
    EXPIRED = "expired"
    LOCAL_STOP = "local_stop"
    CANCELLED = "cancelled"
    TX_IN_FLIGHT = "tx_in_flight"
    NON_EOF = "non_eof"
    EOF_CANDIDATE = "eof_candidate"


class Scenario(StrEnum):
    SESSION_300 = "session-300"
    RECONNECT = "session-reconnect-no-pong"


class Rejection(StrEnum):
    CLOSE_CLIENT = "close_client"
    DATA_UPDATED = "data_updated"
    OTHER_KNOWN = "other_known"
    UNKNOWN = "unknown"
    AMBIGUOUS = "ambiguous"


class Event(StrEnum):
    REQUEST = "request"
    TICK = "tick"
    EOF = "eof"
    TLS_FAILURE = "tls_failure"
    LOCAL_CLOSE = "local_close"
    CANCEL = "cancel"
    TX_IN_FLIGHT = "tx_in_flight"


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Closed scalars only; never evidence of effects performed elsewhere."""

    state: State
    reason: Reason
    block_tx: bool
    generation: int | None
    deadline_ms: int | None
    candidate_at_ms: int | None


def _time(value):
    return type(value) is int and 0 <= value <= MAX_TIME_MS


class EofQuarantinePolicy:
    """One first-generation policy, with no reset, I/O, clock or callback.

    request() latches block_tx even on refusal. It does not acquire a lock or
    attest any actual TX cutoff. advance() consumes declared events only; EOF
    cannot attest its transport origin. The future RX bridge must verify that.
    Refused policies cannot rearm; provisional EOF candidates confer no rights.
    """

    __slots__ = ("_snapshot", "_accepted", "_last", "_last_event")

    def __init__(
        self,
        *,
        accepted_generation,
        accepted_at_ms,
        observation_deadline_ms,
        process_deadline_ms,
        suite_deadline_ms,
    ):
        self._accepted = self._last = self._last_event = None
        self._snapshot = Snapshot(State.REFUSED, Reason.INVALID, True, None, None, None)
        times = (
            accepted_at_ms,
            observation_deadline_ms,
            process_deadline_ms,
            suite_deadline_ms,
        )
        if (
            type(accepted_generation) is not int
            or accepted_generation != 1
            or not all(_time(t) for t in times)
            or accepted_at_ms > MAX_TIME_MS - 300000
        ):
            return  # Never retain invalid objects, text, bytes or non-finite time.
        deadline = min(accepted_at_ms + 300000, *times[1:])
        if deadline <= accepted_at_ms:
            return
        self._accepted = accepted_at_ms
        self._snapshot = Snapshot(State.READY, Reason.NONE, False, 1, deadline, None)

    def __repr__(self):
        return "EofQuarantinePolicy()"

    @property
    def snapshot(self):
        return self._snapshot

    def _refuse(self, reason):
        if self._snapshot.state is not State.REFUSED:
            s = self._snapshot
            self._snapshot = Snapshot(
                State.REFUSED, reason, True, s.generation, s.deadline_ms, None
            )
        return self._snapshot

    def _observe(self, now_ms, generation, event):
        if (
            not _time(now_ms)
            or now_ms < self._accepted
            or (self._last is not None and now_ms < self._last)
        ):
            self._refuse(Reason.INVALID)
        elif type(generation) is not int or generation != self._snapshot.generation:
            self._refuse(Reason.STALE)
        elif (
            now_ms == self._last
            and event is not self._last_event
            and event not in {Event.LOCAL_CLOSE, Event.CANCEL, Event.TX_IN_FLIGHT}
        ):
            self._refuse(Reason.AMBIGUOUS)
        else:
            self._last, self._last_event = now_ms, event
            return True
        return False

    def request(
        self,
        *,
        now_ms,
        generation,
        scenario,
        rejection,
        suppressed_pongs,
        tx_in_flight,
        local_stop,
    ):
        """Latch a request at fixed 120/300 s bounds; flags are declarations."""
        s = self._snapshot
        if s.state is State.REFUSED:
            return s
        self._snapshot = Snapshot(
            s.state, s.reason, True, s.generation, s.deadline_ms, s.candidate_at_ms
        )
        if (
            type(scenario) is not Scenario
            or type(rejection) is not Rejection
            or type(suppressed_pongs) is not int
            or not 0 <= suppressed_pongs <= 1048576
            or type(tx_in_flight) is not bool
            or type(local_stop) is not bool
        ):
            return self._refuse(Reason.INVALID)
        if not self._observe(now_ms, generation, Event.REQUEST):
            return self._snapshot
        if local_stop:
            return self._refuse(Reason.LOCAL_STOP)
        if tx_in_flight:
            return self._refuse(Reason.TX_IN_FLIGHT)
        if now_ms >= s.deadline_ms:
            return self._refuse(Reason.EXPIRED)
        if (
            scenario is not Scenario.RECONNECT
            or rejection is not Rejection.CLOSE_CLIENT
            or suppressed_pongs == 0
            or now_ms < self._accepted + 120000
        ):
            return self._refuse(Reason.INELIGIBLE)
        if s.state is State.READY:
            self._snapshot = Snapshot(
                State.WAITING, Reason.NONE, True, s.generation, s.deadline_ms, None
            )
        return self._snapshot

    def advance(self, event, *, now_ms, generation):
        """Apply a simulated event; a tie between distinct events is ambiguous.

        Stop/cancel/TX-in-flight take priority even at an equal timestamp.
        Expiry, including EOF exactly at the deadline, fails closed. No timer
        enforces it: the future owner would have to supply timely observations.
        """
        s = self._snapshot
        if s.state is State.REFUSED:
            return s
        if type(event) is not Event or event is Event.REQUEST:
            return self._refuse(Reason.INVALID)
        if not self._observe(now_ms, generation, event):
            return self._snapshot
        stops = {
            Event.LOCAL_CLOSE: Reason.LOCAL_STOP,
            Event.CANCEL: Reason.CANCELLED,
            Event.TX_IN_FLIGHT: Reason.TX_IN_FLIGHT,
            Event.TLS_FAILURE: Reason.NON_EOF,
        }
        if event in stops:
            return self._refuse(stops[event])
        if s.state is State.READY:
            return self._refuse(Reason.INELIGIBLE)
        if now_ms >= s.deadline_ms:
            return self._refuse(Reason.EXPIRED)
        if event is Event.EOF and s.state is State.WAITING:
            self._snapshot = Snapshot(
                State.EOF_CANDIDATE,
                Reason.EOF_CANDIDATE,
                True,
                s.generation,
                s.deadline_ms,
                now_ms,
            )
        return self._snapshot
