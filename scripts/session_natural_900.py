"""Natural V4 observation, offline-testable and never an admission grant.

The owner is the existing V4Lifecycle/V4Session. No Pong suppression, forced
disconnection or fabricated opening/EOF event is part of this scenario.
"""

import asyncio
import time

from custom_components.hoben.exceptions import HobenError
from custom_components.hoben.v4_session import SessionState

MAX_SECONDS = 900
RECOVERY_SECONDS = 60
RESULTS = frozenset({"reconnected", "failed", "inconclusive", "not_run"})


def validate_natural(report):
    """Closed allowlist; no identity, frames, or domestic register values."""
    if type(report) is not dict or set(report) != {
        "scenario",
        "result",
        "duration_ms",
        "initial_continuous",
        "reconnect_attempts",
        "correlated_recovery_reads",
    }:
        raise ValueError("invalid_natural_report")
    if report["scenario"] != "session-natural-900" or report["result"] not in RESULTS:
        raise ValueError("invalid_natural_report")
    if (
        type(report["duration_ms"]) is not int
        or not 0 <= report["duration_ms"] <= 900000
    ):
        raise ValueError("invalid_natural_report")
    if type(report["initial_continuous"]) is not bool:
        raise ValueError("invalid_natural_report")
    if type(report["reconnect_attempts"]) is not int or report[
        "reconnect_attempts"
    ] not in (0, 1):
        raise ValueError("invalid_natural_report")
    if type(report["correlated_recovery_reads"]) is not int or report[
        "correlated_recovery_reads"
    ] not in (0, 1):
        raise ValueError("invalid_natural_report")
    if report["correlated_recovery_reads"] and (
        report["result"] != "reconnected" or report["reconnect_attempts"] != 1
    ):
        raise ValueError("invalid_natural_report")
    if (report["result"] == "reconnected") != (
        report["correlated_recovery_reads"] == 1
    ):
        raise ValueError("invalid_natural_report")
    if report["result"] == "not_run" and (
        report["duration_ms"]
        or report["reconnect_attempts"]
        or report["correlated_recovery_reads"]
    ):
        raise ValueError("invalid_natural_report")
    return dict(report)


async def observe_natural(make_lifecycle, *, clock=time.monotonic, sleep=asyncio.sleep):
    """One initial opening and at most one natural-loss recovery.

    A bounded lifecycle's first opening is never retried. The shared parser
    alone attests a correlated V4 read; Ping/Pong or TLS cannot count as proof.
    Cancellation is propagated and ownership is always closed.
    """
    started = clock()
    life = None
    result = "failed"
    continuous = False
    recovery_reads = 0
    attempts = 0
    try:
        async with asyncio.timeout(MAX_SECONDS):
            life = make_lifecycle()
            # The factory must configure retry_delays=(0.0,) or another single
            # strictly bounded delay and use the genuine shared V4 lifecycle.
            if life.snapshot.max_attempts != 2:
                raise ValueError("natural_retry_budget")
            # Initial failure must never spend a recovery attempt.
            async with asyncio.timeout(60):
                opening = asyncio.create_task(life.connect())
                done, _ = await asyncio.wait({opening}, timeout=60)
                if not done:
                    opening.cancel()
                    await asyncio.gather(opening, return_exceptions=True)
                    raise TimeoutError()
                await opening
            continuous = True
            while True:
                if life.snapshot.attempts > 1:
                    continuous = False
                    attempts = 1
                    if life.snapshot.attempts > 2:
                        result = "failed"
                        break
                    # Recovery must finish within 60 seconds from first loss.
                    async with asyncio.timeout(RECOVERY_SECONDS):
                        await life.wait_connected()
                        if (
                            life.snapshot.attempts != 2
                            or life.state is not SessionState.CONNECTED
                        ):
                            result = "failed"
                            break
                        # Verified parser and transaction correlation are inside
                        # request_v4_data; discarded values never leave the owner.
                        await life.request_v4_data(timeout=min(30.0, RECOVERY_SECONDS))
                        recovery_reads = 1
                        result = "reconnected"
                        break
                if life.state is not SessionState.CONNECTED:
                    result = "failed"
                    break
                if clock() - started >= MAX_SECONDS:
                    result = "inconclusive"
                    break
                await sleep(min(1.0, max(0.0, MAX_SECONDS - (clock() - started))))
    except asyncio.CancelledError:
        raise
    except TimeoutError:
        result = "failed" if attempts else "inconclusive" if continuous else "failed"
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
            "correlated_recovery_reads": recovery_reads,
        }
    )
