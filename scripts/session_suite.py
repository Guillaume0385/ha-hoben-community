"""Shared suite engine. No CLI, credential lookup or live authorization.

An admitted caller provides the shared V4Lifecycle/V4Session factory.
The suite preserves its sequential gate; the #119 manual entry may also call
the bounded reconnect collector alone. These APIs grant no live authorization.
"""

import asyncio
import time

from custom_components.hoben.exceptions import (
    HobenError,
    HobenTimeoutError,
    HobenTransportError,
)
from custom_components.hoben.v4_experiment import (
    RECONNECT_DIAGNOSTIC_MESSAGES,
    Session300,
    Session300BudgetError,
    SessionReconnect,
)
from custom_components.hoben.v4_lifecycle import LifecycleExhaustedError
from custom_components.hoben.v4_no_pong import NoPongAfter120
from custom_components.hoben.v4_session import SessionState
from scripts.run_session_300 import observe as observe_300
from scripts.run_session_300 import valid_ignored_messages
from scripts.run_session_300 import validate_report as validate_300
from scripts.session_suite_v3 import validate_v3

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
SECOND_DIAGNOSTIC_KEYS = {
    "read_slot",
    "failure_phase",
    "failure_category",
    "message_category",
}
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
        "schema": 2,
        "scenario": "session-reconnect-no-pong",
        "boundary_proven": False,
        "result": "not_run",
        "terminal": "first_not_admissible",
        "eof_after_threshold_ms": None,
        "read_slot": 0,
        "failure_phase": "none",
        "failure_category": "first_not_admissible",
        "message_category": "unclassified",
    }


def validate_second(r, proof):
    """Closed scalar projection, independent from the engine's mutable state."""
    if type(r) is dict and type(r.get("schema")) is int and r["schema"] == 3:
        return validate_v3(
            r, proof, PROVENANCE, COUNTERS, TERMINALS, RECONNECT_DIAGNOSTIC_MESSAGES
        )
    need(type(r) is dict and type(r.get("schema")) is int and r["schema"] in {1, 2})
    keys = SECOND_KEYS | (SECOND_DIAGNOSTIC_KEYS if r["schema"] == 2 else set())
    if "ignored_messages" in r:
        keys |= {"ignored_messages"}
    need(set(r) == keys)
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
    if "ignored_messages" in r:
        need(valid_ignored_messages(r["ignored_messages"], r["rx_bytes_total"]))
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
    if r["schema"] == 2:
        phase, category, message = (
            r["failure_phase"],
            r["failure_category"],
            r["message_category"],
        )
        need(type(phase) is str and phase in RECONNECT_DIAGNOSTIC_MESSAGES)
        need(type(category) is str and category in TERMINALS)
        need(type(message) is str and message in RECONNECT_DIAGNOSTIC_MESSAGES[phase])
        need(type(r["read_slot"]) is int and r["read_slot"] == r["reads"])
        need((phase == "none") == (category in {"verified", "first_not_admissible"}))
        if phase == "none" or r["terminal"] in {"verified", "first_not_admissible"}:
            need(category == r["terminal"])
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
    return {k: r[k] for k in sorted(keys)}


def validate_suite(r, proof):
    """Validate both scenarios and derive a global result that cannot hide a KO."""
    need(type(r) is dict and set(r) == SUITE_KEYS)
    need(type(r["schema"]) is int and r["schema"] in {1, 2, 3})
    need(r["scenario"] == "session-suite" and r["boundary_proven"] is False)
    for k in PROVENANCE:
        need(type(r[k]) is type(proof[k]) and r[k] == proof[k])
    need(type(r["duration_ms"]) is int and 0 <= r["duration_ms"] <= 1020000)
    first = validate_300(r["session_300"], proof)
    second = validate_second(r["session_reconnect_no_pong"], proof)
    need(second["schema"] == r["schema"])
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
    phase = "opening"
    try:
        # Leave ten seconds of the fixed 600 s cap for shared-owner teardown.
        async with asyncio.timeout(590) as observation:
            await life.connect()
            first_at = policy.first_opened_at
            deadline = started + 590
            if first_at is not None:
                # Functional time starts at strict acceptance. Keep the existing
                # process/cleanup caps; this narrower scenario cannot extend them.
                deadline = min(deadline, first_at + 360)
                observation.reschedule(
                    asyncio.get_running_loop().time() + max(0, deadline - clock())
                )
            phase = "lifecycle_transition"
            stop = asyncio.create_task(life.wait_stopped())
            while True:
                now = clock()
                first_at = policy.first_opened_at
                eof_at = policy.first_eof_after_suppression_at
                first_generation = policy.first_generation
                recovered = (
                    eof_at is not None
                    and budget.usable
                    and budget.connected_generation != first_generation
                    and budget.accepted_at is not None
                    and life.state is SessionState.CONNECTED
                )
                if budget.last_lost_generation not in {None, first_generation}:
                    result, terminal = "inconclusive", "stability_lost"
                    break
                if first_at is not None and eof_at is None and now >= first_at + 240:
                    result = "inconclusive"
                    terminal = (
                        "not_exercised" if not policy.suppressed else "no_disconnect"
                    )
                    break
                if stop.done():
                    stop.result()
                if (
                    first_at is not None
                    and eof_at is not None
                    and (
                        eof_at >= first_at + 240
                        or (not recovered and now >= first_at + 240)
                        or (recovered and budget.accepted_at >= first_at + 240)
                    )
                ):
                    result, terminal = "inconclusive", "reopen_failed"
                    break
                if now >= deadline:
                    result, terminal = "interrupted", "timeout"
                    break
                if recovered:
                    recovery_generation = budget.connected_generation
                    stable_ms = (
                        120000
                        if now >= budget.accepted_at + 120
                        else int((now - budget.accepted_at) * 1000)
                    )
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
                    read_deadline = deadline
                    if not recovered and first_at is not None:
                        read_deadline = min(read_deadline, first_at + 240)
                    read = asyncio.create_task(
                        life.request_v4_data(timeout=min(30, read_deadline - now))
                    )
                    phase = "scheduled_read"
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
                            and budget.usable
                            and life.state is SessionState.CONNECTED
                        ):
                            recovery_reads += 1
                    except HobenTransportError:
                        pass  # No replay; only the next >=60 s slot can read again.
                    finally:
                        if not read.done():
                            read.cancel()
                        await asyncio.gather(read, return_exceptions=True)
                    phase = "lifecycle_transition"
                # Observe owner callbacks, never poll TLS. Wake at the exact
                # functional boundary or stability end, including fractional T0.
                wake_at = deadline
                if first_at is not None and not recovered:
                    wake_at = min(wake_at, first_at + 240)
                if recovered and stable_ms < 120000 and budget.accepted_at is not None:
                    wake_at = min(wake_at, budget.accepted_at + 120)
                await sleep(min(1, max(0, wake_at - clock())))
    except asyncio.CancelledError:
        raise
    except (TimeoutError, HobenTimeoutError):
        result, terminal = "interrupted", "timeout"
        if (
            policy.first_opened_at is not None
            and clock() >= policy.first_opened_at + 240
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
        # Snapshot the causal diagnostic before teardown. A secondary close
        # failure still changes the existing terminal, but cannot erase it.
        diagnostic = (
            ("none", terminal, "unclassified")
            if terminal == "verified"
            else budget.failure or (phase, terminal, "unclassified")
        )
        if stop is not None:
            stop.cancel()
            await asyncio.gather(stop, return_exceptions=True)
        try:
            async with asyncio.timeout(10):
                await life.close()
        except Exception:
            result, terminal = "interrupted", "closed"
            if diagnostic[0] == "none":
                diagnostic = ("teardown", "closed", "unclassified")
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
            "read_slot": budget.requests,
            "failure_phase": diagnostic[0],
            "failure_category": diagnostic[1],
            "message_category": diagnostic[2],
            **budget.ignored_diagnostic(),
        },
        proof,
    )


async def observe_suite(
    make_lifecycle, proof, *, clock=time.monotonic, sleep=asyncio.sleep
):
    """Indivisible ordering, fixed budgets, and a 1020 s hard in-process deadline.

    The factory takes (fixed_budget, optional_pong_policy); it must instantiate
    the existing shared lifecycle/session, with its bounded retry policy. This
    runner entry point remains subject to the installed admission gates.
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
                "schema": 2,
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
