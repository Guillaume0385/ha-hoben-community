"""Actual HA coordinator observation, without transport injection or live CLI."""

import asyncio
import time

from custom_components.hoben.client import HobenClient
from custom_components.hoben.coordinator import (
    HobenCoordinatorData,
    HobenDataUpdateCoordinator,
)
from custom_components.hoben.session_observation import SessionObservation
from scripts.ha_live_proof import REFRESH_AT_MS, empty_evidence
from scripts.ha_session_evidence import project_observation


async def observe(
    coordinator, *, clock=time.monotonic, sleep=asyncio.sleep, evidence=None
):
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
    start = clock()
    try:
        async with asyncio.timeout(300):
            for ordinal, at_ms in enumerate(REFRESH_AT_MS, 1):
                await sleep(max(0, start + at_ms / 1000 - clock()))
                if clock() - start >= 300:
                    raise TimeoutError
                previous = coordinator.data
                try:
                    await coordinator.async_refresh()
                finally:
                    evidence["samples"].append(
                        {
                            "ordinal": ordinal,
                            "decoded": coordinator.last_update_success
                            and type(coordinator.data) is HobenCoordinatorData
                            and coordinator.data is not previous,
                            "observation": project_observation(
                                coordinator.client.session_observation
                            ),
                        }
                    )
                if clock() - start >= 300:
                    raise TimeoutError
            evidence["completed"] = True
    except asyncio.CancelledError:
        raise
    except Exception:
        pass
    finally:
        try:
            async with asyncio.timeout(10):
                await coordinator.client.async_close()
            evidence["cleanup"]["completed"] = True
        finally:
            evidence["cleanup"]["observation"] = project_observation(
                coordinator.client.session_observation
            )
    return evidence
