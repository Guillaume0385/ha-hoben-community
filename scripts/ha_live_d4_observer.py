"""#207 D4-D: inert HA coordinator observer for a future gated Live run.

The caller must supply the real persistent HA coordinator; this module never
creates a client, obtains credentials, dispatches Actions, or opens a socket.
The observer uses only D3 allowlisted counters and closes the owner in finally.
Its result is component evidence, never a live admission or public run report.
"""

from __future__ import annotations

import asyncio
import math
import time
from typing import Any

DURATION = 300
MAX_OBSERVATION = 900
POLL = 5
CAP = 65535
LIMIT_GENERATION = 2147483647
COUNTERS = (
    "unsupported_deliveries",
    "info_candidate_deliveries",
    "v4_responses_correlated",
    "responses_after_drop",
    "responses_after_info_candidate",
    "pings",
    "pongs",
)
FLAGS = (
    "tls_connected",
    "v4_accepted",
    "acquisition_uncertain",
    "eof_received",
    "terminal_error",
    "transport_close_requested",
    "transport_close_failed",
    "cleanup_failed",
    "cleanup_succeeded",
)


def _snapshot(raw: Any) -> dict[str, int | bool] | None:
    """Only copy the narrow closed scalar subset; never return arbitrary data."""
    if type(raw) is not dict:
        return None
    generation = raw.get("tls_generation")
    if (
        raw.get("schema") != 1
        or raw.get("scope") != "tls_attempt"
        or raw.get("length_scope") != "tls_delivery"
        or raw.get("info_framing") != "INCONCLUSIVE"
        or raw.get("counters_capped") is not False
        or type(generation) is not int
        or not 1 <= generation <= LIMIT_GENERATION
        or any(type(raw.get(k)) is not int or not 0 <= raw[k] <= CAP for k in COUNTERS)
        or any(type(raw.get(k)) is not bool for k in FLAGS)
        or raw.get("boundary_proven") is not False
    ):
        return None
    return {
        "generation": generation,
        **{name: raw[name] for name in COUNTERS},
        **{name: raw[name] for name in FLAGS},
    }


def _result(*, observation: str, elapsed: int, drop: int, recovery: int,
            generation: int | None, final: dict | None, cleaned: bool) -> dict:
    """Never include raw bytes, home values, credentials or exception strings."""
    return {
        "schema": 1,
        "scenario": "hoben-live",
        "execution": "component_only",
        "admission": "NOT RUN",
        "live_ready": False,
        "secrets_allowed": False,
        "boundary_proven": False,
        "observation": observation,
        "elapsed_ms": min(MAX_OBSERVATION * 1000, max(0, elapsed)),
        "drop_at_ms": drop,
        "correlated_at_ms": recovery,
        "tls_generation": generation,
        "unknown_drops": final["unsupported_deliveries"] if final else 0,
        "info_candidates": final["info_candidate_deliveries"] if final else 0,
        "correlated_after_drop": final["responses_after_drop"] if final else 0,
        "pings": final["pings"] if final else 0,
        "pongs": final["pongs"] if final else 0,
        "cleanup_attested": cleaned,
    }


async def observe(coordinator, *, clock=None, sleep=None):
    """Observe 300 s AFTER a fresh V4 correlation following an unknown drop.

    Counter changes in one polling interval cannot prove event order and do
    not establish recovery. Any new TLS generation, EOF, local close or D2
    uncertainty prevents success. A 900 s upper budget includes observation;
    coordinator/client cleanup gets a separate bounded 10 s finally budget.
    """
    clock = time.monotonic if clock is None else clock
    sleep = asyncio.sleep if sleep is None else sleep
    client = getattr(coordinator, "client", None)
    if client is None or not callable(getattr(coordinator, "async_refresh", None)):
        raise ValueError("ha_live_d4_observer_refused")
    last_clock = None

    def stamp():
        nonlocal last_clock
        value = clock()
        if (
            type(value) not in (int, float)
            or not math.isfinite(value)
            or last_clock is not None and value < last_clock
        ):
            raise ValueError("ha_live_d4_observer_refused")
        last_clock = value
        return value

    start = stamp()
    generation = None
    drop = recovery = -1
    failed = False
    provisional_success = False
    final = None
    cleaned = False
    try:
        while stamp() - start < MAX_OBSERVATION:
            before = _snapshot(getattr(client, "session_diagnostics", None))
            try:
                # The real coordinator uses the real HobenClient and verified V4
                # codec. This call must never mutate the appliance.
                await asyncio.wait_for(coordinator.async_refresh(), timeout=35)
            except asyncio.CancelledError:
                raise
            except Exception:
                # No exception text is retained. Only owner diagnostics may
                # attest whether this was an actual EOF/TLS failure.
                pass
            current = _snapshot(getattr(client, "session_diagnostics", None))
            now_ms = int((stamp() - start) * 1000)
            if current is None:
                await sleep(POLL)
                continue
            if (
                current["eof_received"]
                or current["terminal_error"]
                or current["transport_close_requested"]
                or current["transport_close_failed"]
                or current["cleanup_failed"]
            ):
                failed = True
                break
            if generation is not None and current["generation"] != generation:
                break
            if not current["tls_connected"] or not current["v4_accepted"]:
                await sleep(POLL)
                continue
            old = before if before and before["generation"] == current["generation"] else None
            if drop < 0 and (
                (old and current["unsupported_deliveries"] > old["unsupported_deliveries"])
                or (old is None and current["unsupported_deliveries"] > 0)
            ):
                generation, drop = current["generation"], now_ms
            # Never credit a drop and read delivered in the SAME observed
            # interval: order cannot be established from aggregate counters.
            elif (
                drop >= 0
                and recovery < 0
                and old is not None
                and old["generation"] == generation
                and current["generation"] == generation
                and current["responses_after_drop"] > old["responses_after_drop"]
                and current["v4_responses_correlated"] > old["v4_responses_correlated"]
                and not current["acquisition_uncertain"]
            ):
                recovery = now_ms
            if (
                recovery >= 0
                and now_ms - recovery >= DURATION * 1000
                and current["generation"] == generation
                and not current["acquisition_uncertain"]
            ):
                provisional_success = True
                break
            await sleep(POLL)
    except asyncio.CancelledError:
        failed = True
        raise
    except Exception:
        failed = True
    finally:
        try:
            await asyncio.wait_for(client.async_close(), timeout=10)
        except BaseException:
            failed = True
        final = _snapshot(getattr(client, "session_diagnostics", None))
        cleaned = bool(final and final["cleanup_succeeded"] and not final["cleanup_failed"])
    elapsed = int((stamp() - start) * 1000)
    status = (
        "FAILED"
        if failed or not cleaned
        else "SUCCESS"
        if provisional_success and recovery >= 0 and drop >= 0
        else "INCONCLUSIVE"
    )
    return _result(
        observation=status,
        elapsed=elapsed,
        drop=drop,
        recovery=recovery,
        generation=generation,
        final=final,
        cleaned=cleaned,
    )


__all__ = ("observe",)
