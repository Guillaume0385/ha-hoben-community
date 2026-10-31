"""In-memory session telemetry only; no HA, transport, payload or retry policy."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from .malformed import TEXT_FIELDS

_CATEGORIES = frozenset(
    {
        "malformed_response",
        "timeout",
        "transport_unavailable",
        "server_closed",
        "experimental_close_client",
        "invalid_credentials",
        "authorization_required",
        "invalid_client_inputs",
        "unsupported_profile",
        "cleanup_failed",
        "client_closed",
        "internal_failure",
        "tls_verification_failed",
        "unclassified_opened_client_bytes",
        "modbus_exception",
        "refresh_exhausted",
        "invalid_v4_snapshot",
        "unexpected_error",
        "config_entry_error",
        "authentication_failed",
        "update_failed",
        "client_failed",
        "session_lifecycle_exhausted",
        "session_lifecycle_stopped",
        "data_updated_recovery",
    }
)
_PHASES = TEXT_FIELDS["phase"] | {"post_open", "mbap_header"}


@dataclass(frozen=True, slots=True)
class SessionEvent:
    """Closed metadata; no exception, identity, frame or model reference."""

    kind: str = "changed"
    category: str | None = None
    phase: str | None = None
    generation: int | None = None


def error_event(error):
    try:
        return report_event(error.safe_report())
    except Exception:
        return SessionEvent("error")


def report_event(report, *, recovering=False):
    report = report if type(report) is dict else {}
    category, phase = report.get("error"), report.get("phase")
    return SessionEvent(
        "recovery" if recovering else "error",
        category if type(category) is str and category in _CATEGORIES else None,
        phase if type(phase) is str and phase in _PHASES else None,
    )


def notify_status(callback, event=SessionEvent()):
    """A broken diagnostic subscriber cannot alter session/cleanup behavior."""
    if callback is not None:
        try:
            callback(event)
        except Exception:
            pass


class SessionMonitor:
    """Track events from construction; reads/polls never increment counters.

    recovery_count counts degraded-acquisition episodes, closed by a verified
    recovery, a new accepted generation, or a successful HA model acquisition.
    Uninstrumented clients return unknown counts, rather than invented zeros.
    """

    def __init__(self, *, tracked=False, clock=lambda: datetime.now(UTC)):
        self.tracked, self.clock = tracked, clock
        self.last_error_category = self.last_error_phase = self.last_error_at = None
        self.reconnect_count = self.recovery_count = 0 if tracked else None
        self.recovering = self._closed = False
        self._accepted_generation = 0
        self._listeners: set[Callable[[], None]] = set()

    def __repr__(self):
        return "SessionMonitor()"

    def subscribe(self, listener):
        if self.tracked and not self._closed:
            self._listeners.add(listener)
        return lambda: self._listeners.discard(listener)

    def emit(self, event=SessionEvent()):
        if self._closed or not self.tracked:
            return
        if event.kind in {"error", "recovery"}:
            safe = report_event({"error": event.category, "phase": event.phase})
            self.last_error_category, self.last_error_phase = safe.category, safe.phase
            self.last_error_at = self.clock()
        if event.kind == "recovery" and not self.recovering:
            self.recovery_count += 1
            self.recovering = True
        if event.kind == "accepted":
            generation = event.generation
            if type(generation) is not int or generation < 1:
                self.reconnect_count = None
            elif generation != self._accepted_generation:
                if generation != self._accepted_generation + 1:
                    self.reconnect_count = None  # A missed event cannot imply a zero.
                elif self._accepted_generation and self.reconnect_count is not None:
                    self.reconnect_count += 1
                self._accepted_generation = generation
        if event.kind in {"accepted", "recovered", "read_succeeded", "ended", "stop"}:
            self.recovering = False
        for listener in tuple(self._listeners):
            try:
                listener()
            except Exception:
                pass
        if event.kind == "stop":
            self._closed = True
            self._listeners.clear()
