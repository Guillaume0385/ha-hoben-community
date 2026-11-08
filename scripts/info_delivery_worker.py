"""#186-D4 offline adapter. No executable entry point, process or live routing.

The fixture alone constructs/opts in V4Session and installs virtual loop time.
Only exact memory ports are accepted, before any connect. No default supplier.
"""

import asyncio

from custom_components.hoben.v4_session import SessionState, V4Session, V4SessionMode
from scripts.info_delivery_memory import MemoryFactory, MemoryTransport, OfflineClock
from scripts.info_delivery_scenario import error_category, require
from scripts.info_delivery_supervisor import (
    LIMITS,
    InfoSupervisor,
    validate_supervision_report,
)


async def _wait_progress(wire, clock, deadline, rx):
    """Own/reap every helper; observing RX completion never becomes an RX owner."""
    changed = asyncio.create_task(wire.changed.wait())
    timer = asyncio.create_task(clock.until(deadline))
    try:
        await asyncio.wait((changed, timer, rx), return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in (changed, timer):
            task.cancel()
        await asyncio.gather(changed, timer, return_exceptions=True)


def _check_ports(session, clock):
    require(type(session) is V4Session and type(clock) is OfflineClock)
    require(session._mode is V4SessionMode.PERSISTENT)
    require(session.state is SessionState.DISCONNECTED)
    require(session.verified_read_sequence == 0)
    factory = session._transport_factory
    require(type(factory) is MemoryFactory and factory.calls == 0)
    wire = factory.transport
    require(type(wire) is MemoryTransport and wire.session is None)
    require(asyncio.get_running_loop().time is clock.loop_time)
    wire.session, wire.clock = session, clock
    return wire


async def run_offline_worker(*, session, clock):
    """Drive/reap one async memory worker; never attests a real process/TLS close.

    Cancel before start: no connection. Cancel in flight: signal the owned task
    once, shield its bounded cleanup against repeat cancellation, reap, FAILURE.
    The synchronous return is a validated synthetic report, never live evidence.
    """
    wire = _check_ports(session, clock)
    policy = InfoSupervisor(clock_ms=lambda: clock.now_ms)
    origin = clock.now_ms
    deadline = origin + LIMITS["observation_ms"]
    require(deadline + LIMITS["cleanup_reserve_ms"] <= 4_000_000)
    policy.start()

    async def work():
        first = "none"
        try:
            async with asyncio.timeout(5):
                await session.connect()
            while clock.now_ms < deadline:
                wire.changed.clear()
                wire.sample()
                if session._rx_task.done():
                    if session._rx_error is not None:
                        raise session._rx_error
                    first = "closed"
                    break
                child = wire.scenario
                if child is not None:
                    # C's short proof window starts at candidate delivery, not
                    # at the beginning of the one-hour parent observation.
                    if child.first_error != "none":
                        first = child.first_error
                        break
                    local_end = int(child.start * 1000) + 29999
                    if clock.now_ms >= local_end:
                        first = "timeout"
                        break
                    if child.drops and child.steps["pong"] is not None:
                        remaining = min(
                            5, (min(deadline, local_end) - clock.now_ms) / 1000
                        )
                        await session.request_v4_data(timeout=remaining)
                        wire.sample()
                        break
                else:
                    local_end = deadline
                await _wait_progress(
                    wire, clock, min(deadline, local_end), session._rx_task
                )
        except asyncio.CancelledError:
            first = "cancelled"
            if policy.state != "STOPPED":
                policy.event("cancel")
        except Exception as error:
            first = error_category(error)
        finally:
            wire._begin_evidence()
            child = wire.scenario
            if first != "none":
                child.fail(first)
            wire.sample()
            child.begin_cleanup()
            pending = child.finish()
            wire.frozen = True
            if pending["cleanup_attested"]:
                # The real read error path may already have closed/reaped RX.
                # Preserve its final FAILURE, never pretend cleanup is pending
                # or replace it with a provisional successful observation.
                final = pending
            else:
                if policy.state != "STOPPED":
                    policy.prepare_observation(pending)
                try:
                    # C's tighter cap remains inside the immutable D2 reserve.
                    async with asyncio.timeout(5):
                        await session.abort()
                except asyncio.CancelledError:
                    child.fail("cancelled")
                except Exception:
                    child.fail("cleanup_unproven")
                final = child.finish()
            if policy.state != "STOPPED":
                policy.observe(final)
                if wire.closed and session.cleanup_succeeded:
                    policy.event("transport_closed")
                if session._rx_task is not None and session._rx_task.done():
                    if policy.state != "STOPPED":
                        policy.event("rx_reaped")
            return final

    task = asyncio.create_task(work(), name="hoben-info-offline-worker")
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            if not cancelled:
                cancelled = True
                if policy.state != "STOPPED":
                    policy.event("cancel")
                task.cancel()
        except Exception:
            if policy.state != "STOPPED":
                policy.event("worker_failed")
            break
    # Retrieve the terminal outcome; no acknowledgment from a callback/signal.
    try:
        final = task.result()
    except (Exception, asyncio.CancelledError):
        final = None
    if policy.state != "STOPPED":
        if isinstance(final, dict) and final["cleanup_attested"] and wire.closed:
            policy.event("worker_reaped")
        else:
            policy.event("cleanup_failed")
    report = policy.finish()
    return validate_supervision_report(report)
