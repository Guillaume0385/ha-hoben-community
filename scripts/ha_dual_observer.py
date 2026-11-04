"""Opt-in two-session observation, real shared owners, no retry/inhibition.

The only injected interfaces in offline tests are the clock and TLS transport.
The worker already confines the actual production transport to verified TLS.
"""

import asyncio
import math
import time

from custom_components.hoben.client import HobenClient
from custom_components.hoben.coordinator import (
    HobenCoordinatorData,
    HobenDataUpdateCoordinator,
)
from custom_components.hoben.error_phases import phase_of
from custom_components.hoben.myhoben import INITIAL_DEVICE_GUID
from custom_components.hoben.session_observation import SessionObservation
from custom_components.hoben.transport import AsyncTlsTransport
from custom_components.hoben.v4_session import SessionState, V4SessionMode
from scripts.campaign_runtime_contract import need
from scripts.ha_dual_evidence import empty, positive
from scripts.ha_dual_instrumentation import (
    ObservationFailed,
    TrackedSession,
    Tracker,
    category,
)


async def observe(
    coordinator, *, evidence=None, clock=None, sleep=None, absolute_end=None
):
    need(
        type(coordinator) is HobenDataUpdateCoordinator
        and type(coordinator.client) is HobenClient
    )
    client = coordinator.client
    need(
        client.session_observation == SessionObservation() and coordinator.data is None
    )
    e = empty() if evidence is None else evidence
    need(e == empty())
    native = clock is None and sleep is None
    clock, sleep = clock or time.monotonic, sleep or asyncio.sleep
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
    end = start + 840  # 60 s for close, HA stop, guardian and reaping.
    if absolute_end is not None:
        need(type(absolute_end) in (float, int) and math.isfinite(absolute_end))
        end = min(end, absolute_end - 60)
    tracker = Tracker(e, stamp, start, end)
    e["clock"] = "monotonic" if native else "synthetic"
    children = []

    def healthy():
        tracker.guard("a")
        if tracker.t0 is not None:
            o = client.session_observation
            if not o.active or o.generation != 1 or o.attempts != 1:
                tracker.fail("a", "closed", "post_open", o.close_client_subcode)
                tracker.guard("a")
        b = tracker.sessions.get("b")
        if (
            e["resources"]["b"]["accepted"]
            and "b" not in tracker.closing
            and b.state is not SessionState.CONNECTED
        ):
            tracker.fail("b", "closed", "post_open", b.snapshot.close_client_subcode)
            tracker.guard("b")

    async def until(at):
        while stamp() < at:
            healthy()
            await sleep(min(1, at - stamp()))
        healthy()

    async def sample(ordinal):
        previous = coordinator.data
        await coordinator.async_refresh()
        o = client.session_observation
        decoded = (
            coordinator.last_update_success
            and type(coordinator.data) is HobenCoordinatorData
            and coordinator.data is not previous
        )
        attempted = tracker.request_times["a"]
        at = attempted[-1] if len(attempted) == ordinal + 1 else tracker.at()
        if tracker.t0 is not None:
            e["reads"].append(
                dict(
                    scheduled_ms=ordinal * 60000,
                    at_ms=at,
                    end_ms=tracker.at(),
                    decoded=decoded,
                    available=coordinator.last_update_success
                    and coordinator.data is not None,
                    state="connected" if o.active else "disconnected",
                    generation=o.read_generation,
                    sequence=o.read_sequence,
                    error="none" if decoded else category(coordinator.last_exception),
                )
            )
        if not decoded or o.read_generation != 1 or o.read_sequence != ordinal + 1:
            tracker.fail(
                "a",
                category(coordinator.last_exception) if not decoded else "protocol",
                phase_of(coordinator.last_exception) or "unknown",
            )
        healthy()

    async def close_role(role):
        tracker.closing.add(role)
        session = tracker.sessions.get(role)
        r = e["resources"][role]
        try:
            if role == "a":
                await client.async_close()
            elif session is not None:
                await session.abort()
            r["cleanup"] = (
                session is None
                and r["opens"] == 0
                or session is not None
                and session.cleanup_succeeded
                and r["close_completed"]
            )
            if not r["cleanup"]:
                tracker.fail(role, "closed", "cleanup")
            elif r["accepted"]:
                tracker.transition(role, "disconnected")
        except (Exception, asyncio.CancelledError) as error:
            tracker.fail(role, category(error), "cleanup")
            raise

    async def session_b():
        await until(tracker.t0 + 180)
        e["b"]["start_ms"] = tracker.at()
        session = TrackedSession(
            tracker=tracker,
            role="b",
            transport_factory=AsyncTlsTransport,
            user_guid=client._user_guid,
            device_guid=INITIAL_DEVICE_GUID,
            mode=V4SessionMode.PERSISTENT,
        )
        try:
            await session.connect()
            if tracker.at() > 185000:
                tracker.fail("b", "timeout", "opening")
                raise ObservationFailed()
            await session.request_v4_data()
            need(session.verified_read_sequence == 1)
            e["b_read_sequence"] = 1
            e["b"]["read_ms"] = tracker.at()
            await until(tracker.t0 + 360)
            e["b_active_at_close"] = session.state is SessionState.CONNECTED
            e["b"]["close_ms"] = tracker.at()
            async with asyncio.timeout(10):
                await close_role("b")
            if e["resources"]["b"]["cleanup"]:
                e["b"]["closed_ms"] = tracker.at()
                if e["b"]["closed_ms"] - e["b"]["close_ms"] > 10000:
                    tracker.fail("b", "timeout", "cleanup")
                    raise ObservationFailed()
        except (Exception, asyncio.CancelledError) as error:
            tracker.fail("b", category(error), phase_of(error) or "unknown")
            raise

    async def schedule_a():
        for ordinal in range(1, 12):
            await until(tracker.t0 + ordinal * 60)
            await sample(ordinal)

    with tracker.install(client):
        try:
            tracker.guard("a")
            async with asyncio.timeout(max(0, end - stamp())):
                await sample(0)
                need(tracker.t0 is not None)
                if end - tracker.t0 < 661:
                    tracker.fail("a", "timeout", "unknown")
                    raise ObservationFailed()
                async with asyncio.TaskGroup() as group:
                    children.extend(
                        (
                            group.create_task(schedule_a(), name="hoben-dual-a"),
                            group.create_task(session_b(), name="hoben-dual-b"),
                        )
                    )
                need(e["b"]["closed_ms"] is not None)
                await until(tracker.t0 + max(660, e["b"]["closed_ms"] / 1000 + 300))
                e["a_end_active"] = client.session_observation.active
        except asyncio.CancelledError:
            tracker.fail("a", "closed", "cleanup")
            raise
        except Exception as error:
            tracker.fail("a", category(error), phase_of(error) or "unknown")
        finally:
            try:
                e["end_ms"] = tracker.at() or 0
            except Exception:
                e["end_ms"] = max(
                    0, int(((last or start) - (tracker.t0 or start)) * 1000)
                )
                tracker.fail("a", "unexpected", "unknown")
            # TaskGroup reaps both schedulers before touching session resources.
            for role in ("b", "a"):
                if role not in tracker.closing:
                    try:
                        async with asyncio.timeout(10):
                            await close_role(role)
                    except (Exception, asyncio.CancelledError):
                        tracker.fail(role, "closed", "cleanup")
            e["completed"] = positive(e)
    return e
