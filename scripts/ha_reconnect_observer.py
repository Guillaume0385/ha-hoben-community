"""Owner-authorized Pong inhibition, only for the isolated HA campaign worker."""

import asyncio
import math
import time

from custom_components.hoben.client import HobenClient
from custom_components.hoben.coordinator import HobenDataUpdateCoordinator
from custom_components.hoben.session_observation import SessionObservation
from scripts.campaign_runtime_contract import need
from scripts.ha_campaign_evidence import empty, empty_recovery
from scripts.ha_pong_injection import PongInjection
from scripts.ha_session_evidence import project_observation


async def observe(
    coordinator, *, evidence=None, clock=None, sleep=None, absolute_end=None
):
    from scripts.ha_campaign_observer import take_sample

    need(
        type(coordinator) is HobenDataUpdateCoordinator
        and type(coordinator.client) is HobenClient
        and coordinator.client.session_observation == SessionObservation()
        and coordinator.data is None
    )
    if evidence is None:
        evidence = empty("session-reconnect")
    else:
        need(evidence == empty("hoben-live"))
        evidence.update(terminal="none", recovery=empty_recovery())
    native = clock is None and sleep is None
    clock = time.monotonic if clock is None else clock
    sleep = asyncio.sleep if sleep is None else sleep
    last = None

    def stamp():
        nonlocal last
        now = clock()
        need(
            type(now) in (int, float)
            and math.isfinite(now)
            and (last is None or now >= last)
        )
        last = now
        return now

    start = stamp()
    end = start + 570  # original 600 s process cap, 30 s teardown reserve
    if absolute_end is not None:
        need(type(absolute_end) in (int, float) and math.isfinite(absolute_end))
        end = min(end, absolute_end - 40)
    need(end > start)
    evidence["window"]["clock"] = "monotonic" if native else "synthetic"
    probe = PongInjection(stamp, end, multi=True, start=start)
    witness = evidence["recovery"]
    witness.update(schema=2, generations=probe.generations)
    next_read = start
    recovery_read = None
    reads = {}
    outcome = "internal"

    with probe.install(coordinator.client):
        try:
            async with asyncio.timeout(end - start):
                while True:
                    now = stamp()
                    if now >= end:
                        raise TimeoutError
                    policy = probe.policy
                    first, loss = (
                        policy.first_opened_at,
                        policy.first_loss_after_suppression_at,
                    )
                    o = coordinator.client.session_observation
                    owner = coordinator.client._lifecycle
                    interruption = probe.diagnostic["interruption"]
                    if interruption is not None:
                        evidence["terminal"] = "closed"
                        outcome = (
                            "not_exercised"
                            if interruption["generation"] == 1
                            else "reopen_failed"
                            if probe.reopened_at is None
                            else "stability_lost"
                        )
                        break
                    if owner is not None and owner._task.done() and not o.active:
                        evidence["terminal"], outcome = "closed", "closed"
                        break
                    if first is not None:
                        if now >= first + 240 and loss is None:
                            outcome = (
                                "no_disconnect"
                                if policy.suppressed
                                else "not_exercised"
                            )
                            break
                        controlled_open = (
                            probe.generations[policy.first_generation]["opened_ms"]
                            if policy.first_generation < len(probe.generations)
                            else None
                        )
                        if loss is not None and (
                            loss >= first + 240
                            or controlled_open is None
                            and now >= first + 240
                            or controlled_open is not None
                            and probe.start + controlled_open / 1000 >= first + 240
                        ):
                            outcome = "reopen_failed"
                            break
                        if (
                            recovery_read is not None
                            and loss is not None
                            and all(
                                g in reads for g in range(2, len(probe.generations) + 1)
                            )
                            and probe.generations[-1]["loss_ms"] is None
                            and o.active
                            and o.generation == recovery_read[0]
                            and probe.reopened_at is not None
                            and now >= probe.reopened_at + 120
                            and probe.recovery_pongs > 0
                            and not o.cleanup_failed
                        ):
                            outcome = "verified"
                            break
                    if (
                        now >= next_read
                        and len(evidence["samples"]) < 6
                        and (owner is None or o.active)
                    ):
                        # The true coordinator owns decoding/error/availability.
                        # No application read is replayed after a failed attempt.
                        await take_sample(
                            coordinator,
                            evidence,
                            stamp,
                            start,
                            require_fresh=True,
                            max_attempts=3,
                        )
                        next_read = stamp() + 60
                        s = evidence["samples"][-1]
                        o = coordinator.client.session_observation
                        if (
                            s["decoded"]
                            and o.read_generation is not None
                            and o.loss_generation is not None
                            and o.read_generation > o.loss_generation
                            and o.cleaned_generation is not None
                            and o.cleaned_generation >= o.loss_generation
                            and not o.cleanup_failed
                        ):
                            recovery_read = (o.read_generation, o.read_sequence)
                            reads[o.read_generation] = recovery_read
                    await sleep(min(1, max(0, end - stamp())))
                evidence["completed"] = evidence["terminal"] == "none"
        except asyncio.CancelledError:
            evidence["terminal"], outcome = "closed", "closed"
            raise
        except TimeoutError:
            evidence["terminal"], outcome = "timeout", "timeout"
        except Exception:
            evidence["terminal"], outcome = "unexpected", "internal"
        finally:
            try:
                try:
                    now = stamp()
                except Exception:
                    now = start if last is None else last
                    evidence.update(completed=False, terminal="unexpected")
                    outcome = "internal"
                first = probe.policy.first_opened_at
                loss = probe.policy.first_loss_after_suppression_at

                accepted_ms = (
                    None if first is None else probe.generations[0]["opened_ms"]
                )
                reopened_ms = (
                    probe.generations[1]["opened_ms"]
                    if len(probe.generations) > 1
                    else None
                )
                loss_ms = probe.generations[0]["loss_ms"] if loss is not None else None

                witness.update(
                    outcome=outcome,
                    accepted_at_ms=accepted_ms,
                    suppressed_pongs=probe.policy.suppressed,
                    loss_after_ms=None if loss_ms is None else loss_ms - accepted_ms,
                    reopened_after_ms=None
                    if reopened_ms is None
                    else reopened_ms - accepted_ms,
                    loss_generation=probe.policy.first_generation
                    if loss is not None
                    else None,
                    read_generation=None if recovery_read is None else recovery_read[0],
                    read_sequence=None if recovery_read is None else recovery_read[1],
                    recovery_pongs=probe.recovery_pongs,
                    stable_ms=0
                    if recovery_read is None or probe.reopened_at is None
                    else min(120000, max(0, int((now - probe.reopened_at) * 1000))),
                )
                evidence["window"].update(
                    elapsed_ms=max(0, int((now - start) * 1000)),
                    observation=project_observation(
                        coordinator.client.session_observation, max_attempts=3
                    ),
                    active=coordinator.client.session_observation.active,
                )
            finally:
                probe.tearing_down = True
                try:
                    async with asyncio.timeout(10):
                        await coordinator.client.async_close()
                    need(all(probe.cleaned(s) for s in probe.sessions))
                    evidence["cleanup"]["completed"] = True
                except Exception as error:
                    # Preserve the bounded failure report for the worker. A
                    # later idempotent close cannot certify this failed close.
                    evidence.update(
                        completed=False,
                        terminal="timeout"
                        if isinstance(error, TimeoutError)
                        else "unexpected",
                    )
                    if probe.attempts:
                        probe.note("cleanup", error, "observer_cleanup", probe.attempts)
                except asyncio.CancelledError:
                    evidence.update(completed=False, terminal="closed")
                    raise
                finally:
                    evidence["cleanup"]["observation"] = project_observation(
                        coordinator.client.session_observation, max_attempts=3
                    )
                    # Copy only bounded scalar diagnostics, never an exception.
                    witness["diagnostic"] = probe.diagnostic.copy()
    return evidence
