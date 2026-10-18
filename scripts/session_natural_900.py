"""Fail-closed observation of a natural V4 session, without live admission.

V4Lifecycle currently lacks public causal-loss and response-generation evidence.
This collector must never infer a recovered V4 session from a polled state, a
TLS reopening, Ping/Pong, or an otherwise correlated read. The instrumentation
needed to certify recovery belongs to a separately reviewed lifecycle task.
"""

import asyncio
import time

from custom_components.hoben.exceptions import HobenError
from custom_components.hoben.v4_session import SessionState

MAX_SECONDS = 900
RESULTS = frozenset({"reconnected", "failed", "inconclusive", "not_run"})
KEYS = frozenset(
    {
        "scenario",
        "result",
        "duration_ms",
        "initial_continuous",
        "reconnect_attempts",
        "correlated_recovery_reads",
    }
)


def validate_natural(report):
    """Permit only safe scalar evidence; never promote unproven recovery."""
    if type(report) is not dict or set(report) != KEYS:
        raise ValueError("invalid_natural_report")
    if (
        report["scenario"] != "session-natural-900"
        or type(report["result"]) is not str
        or report["result"] not in RESULTS
    ):
        raise ValueError("invalid_natural_report")
    if (
        type(report["duration_ms"]) is not int
        or not 0 <= report["duration_ms"] <= 900000
        or type(report["initial_continuous"]) is not bool
        or type(report["reconnect_attempts"]) is not int
        or report["reconnect_attempts"] not in (0, 1)
        or type(report["correlated_recovery_reads"]) is not int
        or report["correlated_recovery_reads"] != 0
    ):
        raise ValueError("invalid_natural_report")
    # There is not yet a public event timestamp or read-generation witness.
    if report["result"] == "reconnected":
        raise ValueError("invalid_natural_report")
    if report["reconnect_attempts"] and report["initial_continuous"]:
        raise ValueError("invalid_natural_report")
    if report["result"] == "not_run" and (
        report["duration_ms"]
        or report["reconnect_attempts"]
        or report["initial_continuous"]
    ):
        raise ValueError("invalid_natural_report")
    return dict(report)


async def observe_natural(make_lifecycle, *, clock=time.monotonic, sleep=asyncio.sleep):
    """Observe an existing shared lifecycle without manufacturing session loss.

    A caller supplies a real V4Lifecycle configured for at most two openings.
    No live factory or admission path is installed by this module. If public
    evidence cannot distinguish a transient state or time the natural loss,
    stop as inconclusive instead of starting an invented 60-second window.
    """
    started = clock()
    life = None
    result = "failed"
    continuous = False
    attempts = 0
    try:
        # Outer process-style deadline covers initial opening and observation.
        async with asyncio.timeout(MAX_SECONDS):
            life = make_lifecycle()
            if life.snapshot.max_attempts != 2:
                raise ValueError("natural_retry_budget")
            await life.connect()
            # A retry before first acceptance is not an admissible initial
            # opening, even if the lifecycle eventually reports CONNECTED.
            if life.snapshot.attempts != 1 or life.state is not SessionState.CONNECTED:
                result = "failed"
            else:
                continuous = True
                while True:
                    elapsed = clock() - started
                    if elapsed >= MAX_SECONDS:
                        result = "inconclusive"
                        break
                    snapshot = life.snapshot
                    if snapshot.attempts > 2:
                        continuous = False
                        attempts = 1
                        result = "failed"
                        break
                    if snapshot.attempts == 2:
                        # Reopening is not causal proof of natural loss.
                        continuous = False
                        attempts = 1
                        result = "inconclusive"
                        break
                    if life.state is not SessionState.CONNECTED:
                        # Public DISCONNECTED/RECONNECTING cannot attest EOF,
                        # time of loss, or whether another opening is pending.
                        continuous = False
                        result = (
                            "failed"
                            if snapshot.failure
                            and life.state is SessionState.DISCONNECTED
                            else "inconclusive"
                        )
                        break
                    await sleep(min(1.0, MAX_SECONDS - elapsed))
    except asyncio.CancelledError:
        raise
    except TimeoutError:
        result = "inconclusive" if continuous else "failed"
    except (HobenError, ValueError):
        result = "failed"
    finally:
        if life is not None:
            await life.close()
    return validate_natural(
        {
            "scenario": "session-natural-900",
            "result": result,
            "duration_ms": min(900000, max(0, int((clock() - started) * 1000))),
            "initial_continuous": continuous,
            "reconnect_attempts": attempts,
            "correlated_recovery_reads": 0,
        }
    )
