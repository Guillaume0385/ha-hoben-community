"""Read-only protocol scenarios using existing TLS, framing and V4 ownership.

Only the isolated worker calls these functions in a manual run. Unit tests use
in-memory transports/lifecycles and synthetic monotonic clocks exclusively.
"""

import asyncio
import tempfile
import time
from functools import partial
from pathlib import Path

from custom_components.hoben.exceptions import (
    HobenAuthorizationRequiredError,
    HobenClosedError,
    HobenInvalidCredentialsError,
    HobenProtocolError,
    HobenTimeoutError,
    HobenTransportError,
)
from custom_components.hoben.transport import AsyncTlsTransport, TransportError
from custom_components.hoben.v4_experiment import (
    Session300,
    Session300BudgetError,
    SessionReconnect,
)
from custom_components.hoben.v4_lifecycle import V4Lifecycle
from custom_components.hoben.v4_session import SessionState, V4Session
from scripts.campaign_runtime_contract import SECONDS, empty_metrics, need


def category(error):
    if isinstance(error, HobenInvalidCredentialsError):
        return "authentication"
    if isinstance(error, HobenAuthorizationRequiredError):
        return "authorization"
    if isinstance(error, (HobenTimeoutError, TimeoutError)):
        return "timeout"
    if isinstance(error, Session300BudgetError):
        return "budget"
    if isinstance(error, HobenClosedError):
        return "closed"
    if isinstance(error, (HobenTransportError, TransportError)):
        return "transport"
    if isinstance(error, HobenProtocolError):
        return "protocol"
    return "unexpected"


async def h1h2(identity, *, directory=None, runner=None):
    """Keep 12 historical bounded captures private and delete them in finally."""
    from scripts.boundary_capture import run_campaign

    runner = run_campaign if runner is None else runner
    m, detail = empty_metrics("protocol", "h1h2"), {"rx_bytes": 0, "rx_chunks": 0}
    cleanup_failed = False

    def diagnostic(phase, failed=False):
        nonlocal cleanup_failed
        cleanup_failed |= phase == "cleanup" and failed

    with tempfile.TemporaryDirectory(
        prefix="hoben-campaign-private-", dir=directory
    ) as folder:
        Path(folder).chmod(0o700)
        raw = await runner(
            Path(folder), mode="both", seconds=90, **identity, diagnostic=diagnostic
        )
        need(
            type(raw) is dict
            and type(raw["sessions"]) is list
            and len(raw["sessions"]) <= 12
        )
        for i, s in enumerate(raw["sessions"]):
            mode = "H1" if i < 6 else "H2"
            need(s["mode"] == mode and s["boundary_proven"] is False)
            for key, cap in (
                ("rx_bytes", 1048576),
                ("read_calls", 1048576),
                ("v4_requests", 0 if mode == "H1" else 2),
                ("correlated_responses", 2),
            ):
                need(type(s[key]) is int and 0 <= s[key] <= cap)
            need(s["correlated_responses"] <= s["v4_requests"])
            m["h1_sessions" if mode == "H1" else "h2_sessions"] += 1
            m["opens"] += 1
            m["reads"] += s["v4_requests"]
            m["reads_ok"] += s["correlated_responses"]
            detail["rx_bytes"] += s["rx_bytes"]
            detail["rx_chunks"] += s["read_calls"]
        m["completed"] = len(raw["sessions"]) == 12 and not raw["stopped_early"]
    m["cleanup"] = not cleanup_failed
    return m, detail


async def collect(
    scenario,
    identity,
    *,
    factory=None,
    transport_factory=AsyncTlsTransport,
    clock=time.monotonic,
    sleep=asyncio.sleep,
):
    need(scenario in SECONDS["protocol"] and scenario not in {"h1h2", "all"})
    m, detail = empty_metrics(), {"rx_bytes": 0, "rx_chunks": 0}
    budget = (
        SessionReconnect(clock=clock)
        if scenario == "session-reconnect"
        else Session300(clock=clock)
    )
    owner = None
    stable_ms = 0
    start = clock()
    try:
        # The parent arms its independent absolute deadline BEFORE the worker
        # receives ACK. This timeout leaves a bounded close/kill/reap reserve.
        reserve = 3 if scenario == "tls-only" else 10
        async with asyncio.timeout(SECONDS["protocol"][scenario] - reserve):
            if scenario == "tls-only":
                owner = transport_factory(connect_timeout=10, close_timeout=2)
                await owner.connect()
                m.update(opens=1, completed=True)
            else:
                if factory is None:
                    retry_delays = (
                        (1.0, 2.0)
                        if scenario in {"session-300", "session-reconnect"}
                        else ()
                    )
                    owner = V4Lifecycle(
                        **identity,
                        retry_delays=retry_delays,
                        session_factory=partial(V4Session, session_300=budget),
                    )
                else:
                    owner = factory(budget)
                if scenario == "session-300":
                    from scripts.run_session_300 import observe

                    raw = await observe(
                        owner,
                        budget,
                        {},
                        clock=clock,
                        sleep=sleep,
                        _project=lambda data, _: data,
                    )
                    m.update(
                        completed=raw["result"] in {"continuous_300s", "reconnected"},
                        reads_ok=raw["reads_ok"],
                        useful_ms=raw["duration_ms"],
                    )
                    if not m["completed"]:
                        m["error"] = {
                            "budget": "budget",
                            "authorization": "authorization",
                            "transport": "transport",
                            "timeout": "timeout",
                            "closed": "closed",
                        }.get(raw["terminal"], "protocol")
                else:
                    await owner.connect()
                    if scenario == "session-open":
                        m["completed"] = True
                    elif scenario == "read-v4-state":
                        await owner.request_v4_data(
                            timeout=min(
                                25,
                                SECONDS["protocol"][scenario]
                                - (clock() - start)
                                - reserve,
                            )
                        )
                        m.update(reads_ok=1, completed=True)
                    else:
                        stable_ms = await observe_natural(
                            owner, budget, m, clock=clock, sleep=sleep
                        )
    except asyncio.CancelledError:
        raise
    except Exception as error:
        m["error"] = category(error)
    finally:
        if owner is not None:
            try:
                async with asyncio.timeout(3 if scenario == "tls-only" else 10):
                    await owner.close()
                m["cleanup"] = True
                if scenario != "tls-only":
                    o = owner.session_observation
                    m["cleanup"] = (
                        o.stopped
                        and not o.cleanup_failed
                        and o.cleaned_generation == o.generation
                    )
                    m["loss_kind"] = (
                        o.loss_kind.value if o.loss_kind is not None else "none"
                    )
                    m["close_client_subcode"] = o.close_client_subcode
            except Exception:
                m["cleanup"] = False
        if scenario != "tls-only":
            m.update(
                opens=budget.opens,
                reads=budget.requests,
                pings=budget.pings,
                pongs=budget.pongs,
            )
        detail.update(
            rx_bytes=min(1048576, budget.rx_bytes),
            rx_chunks=min(1048576, budget.rx_chunks),
        )
        detail.update(budget.ignored_diagnostic())
        if scenario == "session-reconnect" and owner is not None:
            witness = owner.witness
            detail["recovery_witness"] = {
                "loss_generation": witness.lost_generation,
                "read_generation": witness.verified_read_generation,
                "read_sequence": witness.verified_read_sequence,
                "stable_ms": stable_ms,
            }
    return m, detail


async def observe_natural(owner, budget, m, *, clock, sleep):
    """No injected loss. Require a fresh correlated read and 120 s stability."""
    start = clock()
    end = start + 440  # connection + cleanup still consume the 480 s parent
    last_read_generation = None
    while clock() < end:
        due = max(clock(), budget.next_read_at)
        if due >= end or budget.requests >= 10:
            await sleep(max(0, end - clock()))
            break
        await sleep(max(0, due - clock()))
        await owner.wait_connected()
        try:
            await owner.request_v4_data(timeout=min(30, end - clock()))
            m["reads_ok"] += 1
            last_read_generation = owner.snapshot.attempts
        except (HobenTransportError, HobenClosedError):
            # Never replay a failed read. Only the next bounded cadence slot
            # can establish recovery after the shared manager has cleaned up.
            pass
        if (
            budget.last_lost_generation is not None
            and last_read_generation is not None
            and last_read_generation > budget.last_lost_generation
            and budget.accepted_at is not None
            and clock() - budget.accepted_at >= 120
            and owner.state is SessionState.CONNECTED
            and budget.usable
        ):
            m["recovered"] = True
            break
    m.update(completed=True, useful_ms=max(0, int((clock() - start) * 1000)))
    return (
        0
        if budget.accepted_at is None
        else max(0, int((clock() - budget.accepted_at) * 1000))
    )
