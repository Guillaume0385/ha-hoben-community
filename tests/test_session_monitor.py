"""Session telemetry has no HA, network, identity or register dependency."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.hoben.session_monitor import (
    SessionEvent,
    SessionMonitor,
    error_event,
    notify_status,
    report_event,
)


def test_uninstrumented_counts_are_unknown_and_no_listener_is_registered():
    monitor = SessionMonitor()
    monitor.subscribe(lambda: pytest.fail("untracked source"))
    monitor.emit(SessionEvent("accepted", generation=1))
    assert monitor.reconnect_count is monitor.recovery_count is None
    assert not monitor._listeners


def test_counters_follow_distinct_generations_and_episodes_not_notifications():
    monitor = SessionMonitor(tracked=True)
    assert monitor.reconnect_count == monitor.recovery_count == 0
    for g, expected in [(1, 0), (1, 0), (2, 1), (2, 1), (3, 2)]:
        monitor.emit(SessionEvent("accepted", generation=g))
        assert monitor.reconnect_count == expected
    monitor.emit(SessionEvent("recovery", "malformed_response", "mbap_header"))
    monitor.emit(SessionEvent("recovery", "malformed_response", "mbap_header"))
    for _ in range(10):
        monitor.emit()
    assert monitor.recovery_count == 1
    monitor.emit(SessionEvent("recovered"))
    monitor.emit(SessionEvent("recovery", "invalid_v4_snapshot"))
    assert monitor.recovery_count == 2
    monitor.emit(SessionEvent("read_succeeded"))
    assert not monitor.recovering


@pytest.mark.parametrize("generation", [None, True, -1, 3])
def test_missing_generation_evidence_cannot_invent_a_counter(generation):
    monitor = SessionMonitor(tracked=True)
    monitor.emit(SessionEvent("accepted", generation=generation))
    assert monitor.reconnect_count is None


@pytest.mark.parametrize(
    "private", ["PRIVATE_PAYLOAD", 17, True, [], {"private": "PRIVATE_PAYLOAD"}]
)
def test_untrusted_error_metadata_is_dropped_before_any_public_event(private):
    monitor = SessionMonitor(tracked=True)
    monitor.emit(report_event({"error": private, "phase": private, "raw": private}))
    assert monitor.last_error_category is monitor.last_error_phase is None
    assert monitor.last_error_at.tzinfo is UTC
    assert "PRIVATE_PAYLOAD" not in repr(monitor)


def test_unchanged_signals_do_not_advance_last_error_date_and_close_seals_callbacks():
    now = [datetime(2026, 10, 31, tzinfo=UTC)]
    monitor = SessionMonitor(tracked=True, clock=lambda: now[0])
    calls = []
    remove = monitor.subscribe(lambda: calls.append(True))
    monitor.emit(SessionEvent("error", "transport_unavailable"))
    first = monitor.last_error_at
    now[0] += timedelta(seconds=60)
    monitor.emit()
    assert monitor.last_error_at == first
    monitor.emit(SessionEvent("stop"))
    before = len(calls)
    monitor.emit(SessionEvent("recovery", "malformed_response"))
    assert len(calls) == before and not monitor._listeners
    assert monitor.recovery_count == 0
    remove()


def test_failed_callbacks_and_reports_cannot_change_the_source_owner():
    def broken(*_):
        raise RuntimeError("PRIVATE_PAYLOAD")

    monitor = SessionMonitor(tracked=True)
    monitor.subscribe(broken)
    notify_status(monitor.emit, SessionEvent("accepted", generation=1))
    notify_status(broken)
    assert monitor.reconnect_count == 0

    class Failure:
        safe_report = broken

    assert error_event(Failure()) == SessionEvent("error")
