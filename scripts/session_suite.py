"""Offline suite engine. No CLI, credential lookup, launcher or live activation.

An admitted future caller must provide the shared V4Lifecycle/V4Session factory.
Only this sequential entry point schedules the second collector. The installed
suite-installation barrier is deliberately unchanged; these APIs grant no access.
"""

import asyncio
import time

from custom_components.hoben.exceptions import (
    HobenError,
    HobenTimeoutError,
    HobenTransportError,
)
from custom_components.hoben.v4_experiment import (
    Session300,
    Session300BudgetError,
    SessionReconnect,
)
from custom_components.hoben.v4_lifecycle import LifecycleExhaustedError
from custom_components.hoben.v4_no_pong import NoPongAfter120
from custom_components.hoben.v4_session import SessionState
from scripts.run_session_300 import observe as observe_300
from scripts.run_session_300 import validate_report as validate_300

PROVENANCE = {"merge_sha", "candidate_sha", "run_id", "run_attempt", "pr_number"}
COUNTERS = {
    "duration_ms": 600000,
    "opens": 3,
    "reconnections": 2,
    "pings": 1048576,
    "pongs": 1048576,
    "reads": 10,
    "reads_ok": 10,
    "reads_failed": 10,
    "responses": 10,
    "rx_bytes_total": 1048576,
    "rx_chunks_total": 1048576,
    "pongs_suppressed": 1048576,
    "peer_eofs": 3,
    "eofs_after_suppression": 1,
    "stable_ms": 120000,
    "recovery_generation": 3,
    "recovery_reads_ok": 10,
    "recovery_pongs": 1048576,
}
TERMINALS = {
    "verified",
    "not_exercised",
    "no_disconnect",
    "reopen_failed",
    "stability_lost",
    "timeout",
    "budget",
    "transport",
    "protocol",
    "internal",
    "closed",
    "first_not_admissible",
}
SECOND_KEYS = (
    PROVENANCE
    | set(COUNTERS)
    | {
        "schema",
        "scenario",
        "boundary_proven",
        "result",
        "terminal",
        "eof_after_threshold_ms",
    }
)
SUITE_KEYS = PROVENANCE | {
    "schema",
    "scenario",
    "boundary_proven",
    "result",
    "duration_ms",
    "session_300",
    "session_reconnect_no_pong",
}


def need(ok):
    if not ok:
        raise ValueError("invalid_session_suite_report")


def second_empty(proof):
    """An explicit skipped scenario, never an inferred successful observation."""
    return {
        **proof,
        **dict.fromkeys(COUNTERS, 0),
        "schema": 1,
        "scenario": "session-reconnect-no-pong",
        "boundary_proven": False,
        "result": "not_run",
        "terminal": "first_not_admissible",
        "eof_after_threshold_ms": None,
    }


def validate_second(r, proof):
    """Closed scalar projection, independent from the engine's mutable state."""
    need(type(r) is dict and set(r) == SECOND_KEYS)
    need(type(r["schema"]) is int and r["schema"] == 1)
    need(r["scenario"] == "session-reconnect-no-pong")
    need(r["boundary_proven"] is False)
    for k in PROVENANCE:
        need(type(r[k]) is type(proof[k]) and r[k] == proof[k])
    for k, maximum in COUNTERS.items():
        need(type(r[k]) is int and 0 <= r[k] <= maximum)
    need(type(r["terminal"]) is str and r["terminal"] in TERMINALS)
    need(type(r["result"]) is str)
    need(r["result"] in {"recovered_120s", "inconclusive", "interrupted", "not_run"})
    need(r["reconnections"] == max(0, r["opens"] - 1))
    need(r["pongs"] + r["pongs_suppressed"] <= r["pings"])
    need(r["reads_ok"] + r["reads_failed"] == r["reads"])
    need(r["reads_ok"] <= r["responses"] <= r["reads"])
    need(r["rx_chunks_total"] <= r["rx_bytes_total"])
    need(r["eofs_after_suppression"] <= r["peer_eofs"] <= r["opens"])
    need(r["recovery_generation"] <= r["opens"])
    need(r["recovery_reads_ok"] <= r["reads_ok"])
    need(r["recovery_pongs"] <= r["pongs"])
    eof = r["eof_after_threshold_ms"]
    need(eof is None or (type(eof) is int and 0 <= eof <= 480000))
    need((eof is not None) == (r["eofs_after_suppression"] == 1))
    if eof is not None:
        need(r["pongs_suppressed"] > 0)
    need((r["result"] == "recovered_120s") == (r["terminal"] == "verified"))
    need((r["result"] == "not_run") == (r["terminal"] == "first_not_admissible"))
    if r["result"] == "not_run":
        need(all(r[k] == 0 for k in COUNTERS) and eof is None)
    if r["result"] == "recovered_120s":
        need(eof is not None and eof <= 180000)
        need(r["opens"] >= 2 and r["recovery_generation"] >= 2)
        need(r["stable_ms"] == 120000 and r["duration_ms"] >= 240000)
        need(r["recovery_reads_ok"] > 0 and r["recovery_pongs"] > 0)
    if r["terminal"] == "not_exercised":
        need(r["pongs_suppressed"] == 0 and eof is None)
    if r["terminal"] == "no_disconnect":
        need(r["pongs_suppressed"] > 0 and (eof is None or eof > 180000))
    return {k: r[k] for k in sorted(SECOND_KEYS)}


def validate_suite(r, proof):
    """Validate both scenarios and derive a global result that cannot hide a KO."""
    need(type(r) is dict and set(r) == SUITE_KEYS)
    need(type(r["schema"]) is int and r["schema"] == 1)
    need(r["scenario"] == "session-suite" and r["boundary_proven"] is False)
    for k in PROVENANCE:
        need(type(r[k]) is type(proof[k]) and r[k] == proof[k])
    need(type(r["duration_ms"]) is int and 0 <= r["duration_ms"] <= 1020000)
    first = validate_300(r["session_300"], proof)
    second = validate_second(r["session_reconnect_no_pong"], proof)
    admissible = first["result"] in {"continuous_300s", "reconnected"}
    need(admissible or second["result"] == "not_run")
    need(
        r["result"]
        == (
            "success"
            if admissible and second["result"] == "recovered_120s"
            else "not_successful"
        )
    )
    need(r["duration_ms"] >= first["duration_ms"] + second["duration_ms"])
    return {
        **{k: r[k] for k in sorted(SUITE_KEYS)},
        "session_300": first,
        "session_reconnect_no_pong": second,
    }


async def _observe_reconnect(life, budget, policy, proof, *, clock, sleep):
    """Schedule reads only; the shared lifecycle owns TLS, RX, TX and backoff.

    Real monotonic callbacks attest EOF/acceptance even between collector ticks.
    No timer closes a transport to manufacture an EOF. Teardown starts only
    after the result decision, cancellation, or a fixed deadline is reached.
    """
    started = clock()
    stop = None
    terminal, result = "internal", "interrupted"
    reads_ok = recovery_reads = stable_ms = recovery_generation = 0
    recovery_pongs = 0
    try:
        # Leave ten seconds of the fixed 600 s cap for shared-owner teardown.
        async with asyncio.timeout(590):
            await life.connect()
            stop = asyncio.create_task(life.wait_stopped())
            while True:
                now = clock()
                first_at = policy.first_opened_at
                eof_at = policy.first_eof_after_suppression_at
                first_generation = policy.first_generation
                if budget.last_lost_generation not in {None, first_generation}:
                    result, terminal = "inconclusive", "stability_lost"
                    break
                if first_at is not None and (
                    (eof_at is None and now >= first_at + 300)
                    or (eof_at is not None and eof_at > first_at + 300)
                ):
                    result = "inconclusive"
                    terminal = (
                        "not_exercised" if not policy.suppressed else "no_disconnect"
                    )
                    break
                if stop.done():
                    stop.result()
                if now - started >= 590:
                    result, terminal = "interrupted", "timeout"
                    break
                if (
                    eof_at is not None
                    and budget.usable
                    and budget.connected_generation != first_generation
                    and life.state is SessionState.CONNECTED
                ):
                    recovery_generation = budget.connected_generation
                    stable_ms = min(120000, int((now - budget.accepted_at) * 1000))
                    recovery_pongs = budget.pongs - budget.generation_pongs
                    if stable_ms == 120000 and recovery_reads and recovery_pongs:
                        result, terminal = "recovered_120s", "verified"
                        break
                if (
                    budget.usable
                    and life.state is SessionState.CONNECTED
                    and budget.requests < 10
                    and now >= budget.next_read_at
                ):
                    generation = budget.connected_generation
                    deadline = started + 590
                    if eof_at is None and first_at is not None:
                        deadline = min(deadline, first_at + 300)
                    read = asyncio.create_task(
                        life.request_v4_data(timeout=min(30, deadline - now))
                    )
                    try:
                        await asyncio.wait(
                            {read, stop}, return_when=asyncio.FIRST_COMPLETED
                        )
                        if stop.done():
                            stop.result()
                        await read  # Returned registers are deliberately discarded.
                        reads_ok += 1
                        if (
                            eof_at is not None
                            and generation != first_generation
                            and budget.connected_generation == generation
                        ):
                            recovery_reads += 1
                    except HobenTransportError:
                        pass  # No replay; only the next >=60 s slot can read again.
                    finally:
                        if not read.done():
                            read.cancel()
                        await asyncio.gather(read, return_exceptions=True)
                # Poll observation state, never poll the transport. Cap each wait
                # at the already fixed process deadline, including recovery.
                await sleep(min(1, max(0, 590 - (clock() - started))))
    except asyncio.CancelledError:
        raise
    except (TimeoutError, HobenTimeoutError):
        result, terminal = "interrupted", "timeout"
        if (
            policy.first_opened_at is not None
            and clock() >= policy.first_opened_at + 300
            and policy.first_eof_after_suppression_at is None
        ):
            result = "inconclusive"
            terminal = "not_exercised" if not policy.suppressed else "no_disconnect"
    except Session300BudgetError:
        result, terminal = "inconclusive", "budget"
    except LifecycleExhaustedError:
        result, terminal = "inconclusive", "reopen_failed"
    except HobenTransportError:
        result, terminal = "interrupted", "transport"
    except HobenError:
        result, terminal = "inconclusive", "protocol"
    except Exception:
        result, terminal = "interrupted", "internal"
    finally:
        if stop is not None:
            stop.cancel()
            await asyncio.gather(stop, return_exceptions=True)
        try:
            async with asyncio.timeout(10):
                await life.close()
        except Exception:
            result, terminal = "interrupted", "closed"
    eof_at, first_at = policy.first_eof_after_suppression_at, policy.first_opened_at
    return validate_second(
        {
            **second_empty(proof),
            "result": result,
            "terminal": terminal,
            "duration_ms": min(600000, max(0, int((clock() - started) * 1000))),
            "opens": budget.opens,
            "reconnections": max(0, budget.opens - 1),
            "pings": budget.pings,
            "pongs": budget.pongs,
            "reads": budget.requests,
            "reads_ok": reads_ok,
            "reads_failed": budget.requests - reads_ok,
            "responses": budget.responses,
            "rx_bytes_total": min(1048576, budget.rx_bytes),
            "rx_chunks_total": min(1048576, budget.rx_chunks),
            "pongs_suppressed": policy.suppressed,
            "peer_eofs": policy.peer_eofs,
            "eofs_after_suppression": policy.peer_eofs_after_suppression,
            "eof_after_threshold_ms": None
            if eof_at is None
            else max(0, int((eof_at - first_at - 120) * 1000)),
            "stable_ms": stable_ms,
            "recovery_generation": recovery_generation,
            "recovery_reads_ok": recovery_reads,
            "recovery_pongs": recovery_pongs,
        },
        proof,
    )


async def observe_suite(
    make_lifecycle, proof, *, clock=time.monotonic, sleep=asyncio.sleep
):
    """Indivisible ordering, fixed budgets, and a 1020 s hard in-process deadline.

    The factory takes (fixed_budget, optional_pong_policy); it must instantiate
    the existing shared lifecycle/session, with its bounded retry policy. This
    offline API is intentionally not wired into any secret-bearing entry point.
    Cancellation propagates after each collector has cleaned up its owner.
    A hard deadline refuses a report rather than inventing a completed scenario.
    """
    started = clock()
    async with asyncio.timeout(1020):
        budget = Session300(clock=clock)
        first = await observe_300(
            make_lifecycle(budget, None), budget, proof, clock=clock, sleep=sleep
        )
        second = second_empty(proof)
        if first["result"] in {"continuous_300s", "reconnected"}:
            budget = SessionReconnect(clock=clock)
            policy = NoPongAfter120(clock=clock)
            second = await _observe_reconnect(
                make_lifecycle(budget, policy),
                budget,
                policy,
                proof,
                clock=clock,
                sleep=sleep,
            )
        return validate_suite(
            {
                **proof,
                "schema": 1,
                "scenario": "session-suite",
                "boundary_proven": False,
                "session_300": first,
                "session_reconnect_no_pong": second,
                "result": "success"
                if second["result"] == "recovered_120s"
                else "not_successful",
                "duration_ms": max(0, int((clock() - started) * 1000)),
            },
            proof,
        )
