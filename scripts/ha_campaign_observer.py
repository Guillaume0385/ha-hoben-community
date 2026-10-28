"""Actual coordinator observations for the additional #126 manual scenarios.

No credentials are modified, no disconnect is injected and no client is copied.
The #112 hoben-live observer remains the sole implementation of its 300 s proof.
"""

import asyncio
import math
import time

from custom_components.hoben.client import HobenClient
from custom_components.hoben.coordinator import (
    HobenCoordinatorData,
    HobenDataUpdateCoordinator,
)
from custom_components.hoben.safe_reports import safe_error_report
from custom_components.hoben.session_observation import SessionObservation
from scripts.campaign_runtime_contract import SECONDS, need
from scripts.ha_campaign_evidence import empty
from scripts.ha_session_evidence import project_observation

SCHEDULES = {
    "open-errors": (0,),
    "refresh-v4": (0, 60),
    "session-reuse": (0, 60, 120),
    "session-reconnect": (0, 100, 200, 300, 400, 500),
    "cleanup": (0,),
    "availability": (0, 60),
}
ERROR_CATEGORIES = {
    "invalid_credentials": "authentication",
    "authentication_failed": "authentication",
    "authorization_required": "authorization",
    "transport_unavailable": "transport",
    "update_failed": "transport",
    "timeout": "timeout",
    "server_closed": "closed",
    "experimental_close_client": "closed",
    "refresh_exhausted": "closed",
    "client_closed": "closed",
    "unsupported_profile": "protocol",
    "malformed_response": "protocol",
    "unclassified_opened_client_bytes": "protocol",
    "modbus_exception": "protocol",
    "config_entry_error": "protocol",
}


async def observe(
    coordinator, scenario, *, evidence=None, clock=None, sleep=None, absolute_end=None
):
    if scenario == "hoben-live":
        from scripts.ha_session_observer import observe as baseline

        return await baseline(coordinator, evidence=evidence, clock=clock, sleep=sleep)
    need(scenario in SCHEDULES)
    need(
        type(coordinator) is HobenDataUpdateCoordinator
        and type(coordinator.client) is HobenClient
    )
    need(
        coordinator.client.session_observation == SessionObservation()
        and coordinator.data is None
    )
    expected = empty(scenario)
    if evidence is None:
        evidence = expected
    else:
        # collect() creates exactly the existing #112 empty evidence object.
        need(evidence == empty("hoben-live"))
        evidence.update(terminal="none")
    native = clock is None and sleep is None
    clock = time.monotonic if clock is None else clock
    sleep = asyncio.sleep if sleep is None else sleep
    last = None

    def stamp():
        nonlocal last
        now = clock()
        need(
            type(now) in (float, int)
            and math.isfinite(now)
            and (last is None or now >= last)
        )
        last = now
        return now

    start = stamp()
    evidence["window"]["clock"] = "monotonic" if native else "synthetic"
    # Thirty seconds remain for async_close, HA shutdown, guardian and reaping.
    collection_end = start + SECONDS["ha"][scenario] - 30
    if absolute_end is not None:
        need(type(absolute_end) in (int, float) and math.isfinite(absolute_end))
        collection_end = min(collection_end, absolute_end - 40)
        need(collection_end > start)

    async def until(at):
        while (remaining := at - stamp()) > 0:
            await sleep(remaining)
        await asyncio.sleep(0)

    try:
        recovered = False
        async with asyncio.timeout(SECONDS["ha"][scenario] - 30):
            for ordinal, offset in enumerate(SCHEDULES[scenario], 1):
                await until(start + offset)
                need(stamp() < collection_end)
                previous = coordinator.data
                try:
                    await coordinator.async_refresh()
                finally:
                    decoded = (
                        coordinator.last_update_success
                        and type(coordinator.data) is HobenCoordinatorData
                        and coordinator.data is not previous
                    )
                    safe = safe_error_report(coordinator.last_exception)
                    category = (
                        "none"
                        if decoded
                        else ERROR_CATEGORIES.get(
                            (safe or {}).get("error"), "unexpected"
                        )
                    )
                    evidence["samples"].append(
                        {
                            "ordinal": ordinal,
                            "at_ms": max(0, int((stamp() - start) * 1000)),
                            "decoded": decoded,
                            "available": coordinator.last_update_success
                            and coordinator.data is not None,
                            "error": category,
                            "observation": project_observation(
                                coordinator.client.session_observation
                            ),
                        }
                    )
                o = coordinator.client.session_observation
                if (
                    scenario == "session-reconnect"
                    and decoded
                    and o.loss_generation is not None
                    and o.read_generation is not None
                    and o.read_generation > o.loss_generation
                    and o.cleaned_generation is not None
                    and o.cleaned_generation >= o.loss_generation
                    and not o.cleanup_failed
                ):
                    recovered = True
                    break
            if scenario == "session-reconnect" and not recovered:
                # Keep the real RX owner alive until the natural-observation
                # bound. A late loss without a subsequent read is NOT recovery.
                await until(collection_end - 1)
            evidence["completed"] = True
    except asyncio.CancelledError:
        evidence["terminal"] = "closed"
        raise
    except TimeoutError:
        evidence["terminal"] = "timeout"
    except Exception:
        evidence["terminal"] = "unexpected"
    finally:
        evidence["window"].update(
            elapsed_ms=max(0, int((stamp() - start) * 1000)),
            observation=project_observation(coordinator.client.session_observation),
            active=coordinator.client.session_observation.active,
        )
        try:
            async with asyncio.timeout(10):
                await coordinator.client.async_close()
            evidence["cleanup"]["completed"] = True
        finally:
            evidence["cleanup"]["observation"] = project_observation(
                coordinator.client.session_observation
            )
    return evidence
