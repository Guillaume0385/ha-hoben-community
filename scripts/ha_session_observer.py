"""Actual HA coordinator observation, without transport injection or live CLI."""

import asyncio
import math
import time

from custom_components.hoben.client import HobenClient
from custom_components.hoben.coordinator import (
    HobenCoordinatorData,
    HobenDataUpdateCoordinator,
)
from custom_components.hoben.session_observation import SessionObservation
from scripts.ha_live_proof import (
    COLLECTION_MS,
    REFRESH_AT_MS,
    USEFUL_MS,
    empty_evidence,
)
from scripts.ha_session_evidence import project_observation


async def observe(coordinator, *, clock=None, sleep=None, evidence=None):
    """Six bounded refreshes over the real HA path; cleanup owns cancellation."""
    if (
        type(coordinator) is not HobenDataUpdateCoordinator
        or type(coordinator.client) is not HobenClient
        or coordinator.client.session_observation != SessionObservation()
        or coordinator.data is not None
    ):
        raise ValueError("fresh isolated HA coordinator required")
    if evidence is None:
        evidence = empty_evidence()
    if evidence != empty_evidence():
        raise ValueError("fresh evidence required")
    # Injecting either timing primitive always marks the evidence synthetic.
    evidence["window"]["clock"] = (
        "monotonic" if clock is None and sleep is None else "synthetic"
    )
    native_clock = clock is None
    clock = time.monotonic_ns if native_clock else clock
    sleep = asyncio.sleep if sleep is None else sleep
    anchor, last = None, None

    def stamp():
        nonlocal last
        current = clock()
        if (
            type(current) not in (int, float)
            or not math.isfinite(current)
            or last is not None
            and current < last
        ):
            raise ValueError("invalid observation clock")
        last = current
        return current if native_clock else round(current * 1_000_000_000)

    async def until(target):
        # Early/spurious wakeups cannot manufacture elapsed monotonic time.
        while (remaining := target - stamp()) > 0:
            await sleep(remaining / 1_000_000_000)
        await asyncio.sleep(0)  # let the persistent RX owner publish pending loss

    try:
        # Startup gets at most 30 s, collection 300 s. The independent guardian
        # reserves cleanup/kill/reaping within the ORIGINAL 360 s deadline.
        async with asyncio.timeout(COLLECTION_MS / 1000):
            for ordinal, at_ms in enumerate(REFRESH_AT_MS, 1):
                if anchor is not None:
                    await until(anchor + at_ms * 1_000_000)
                    if stamp() - anchor >= USEFUL_MS * 1_000_000:
                        raise TimeoutError
                previous = coordinator.data
                try:
                    await coordinator.async_refresh()
                finally:
                    current = stamp()
                    if anchor is None:
                        anchor = current
                    elapsed_ms = (current - anchor) // 1_000_000
                    if elapsed_ms >= USEFUL_MS:
                        raise TimeoutError
                    evidence["samples"].append(
                        {
                            "ordinal": ordinal,
                            "at_ms": elapsed_ms,
                            "decoded": coordinator.last_update_success
                            and type(coordinator.data) is HobenCoordinatorData
                            and coordinator.data is not previous,
                            "observation": project_observation(
                                coordinator.client.session_observation
                            ),
                        }
                    )
            # Keep the actual persistent reader/lifecycle alive for the whole
            # tail. A sticky loss witness at this bound invalidates continuity;
            # this wait alone never attests a new correlated read/reconnection.
            await until(anchor + USEFUL_MS * 1_000_000)
            if stamp() - anchor >= COLLECTION_MS * 1_000_000:
                raise TimeoutError
            evidence["window"].update(
                elapsed_ms=(stamp() - anchor) // 1_000_000,
                observation=project_observation(coordinator.client.session_observation),
                active=coordinator.client.session_observation.active,
            )
            evidence["completed"] = evidence["window"]["elapsed_ms"] >= USEFUL_MS
    except asyncio.CancelledError:
        raise
    except Exception:
        pass
    finally:
        if evidence["window"]["observation"] is None:
            evidence["window"]["elapsed_ms"] = (
                0
                if anchor is None or last is None
                else ((last if native_clock else round(last * 1_000_000_000)) - anchor)
                // 1_000_000
            )
            evidence["window"]["observation"] = project_observation(
                coordinator.client.session_observation
            )
            evidence["window"]["active"] = coordinator.client.session_observation.active
        try:
            async with asyncio.timeout(10):
                await coordinator.client.async_close()
            evidence["cleanup"]["completed"] = True
        finally:
            evidence["cleanup"]["observation"] = project_observation(
                coordinator.client.session_observation
            )
    return evidence
