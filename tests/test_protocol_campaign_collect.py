"""Actual shared V4 ownership over synthetic streams for the manual campaign."""

import asyncio
from functools import partial

import pytest

from custom_components.hoben.exceptions import HobenProtocolError
from custom_components.hoben.myhoben import DATA_REQUEST_CLIENT, OPEN_CLIENT
from custom_components.hoben.transport import TransportEOF
from custom_components.hoben.v4_lifecycle import V4Lifecycle
from custom_components.hoben.v4_session import V4Session
from scripts.campaign_runtime_contract import observed_status, stage, validate_report
from scripts.protocol_campaign_collect import collect, h1h2
from tests.test_campaign_runtime import envelope, node_accepts
from tests.test_session_300_runtime import Stream, response

IDENTITY = {"user_guid": "a" * 32, "device_guid": "D" * 32}


@pytest.mark.parametrize(
    "scenario", ["session-open", "read-v4-state", "session-300", "session-reconnect"]
)
@pytest.mark.parametrize("split", [1, 10, 49])
def test_real_framer_and_lifecycle_without_live_network(scenario, split):
    async def exercise():
        now = [0.0]
        wire = Stream([b"\x0a" + response()[:split], response()[split:] + b"\x0a"])
        lifecycles = []

        async def sleep(delay):
            now[0] += delay
            for _ in range(5):
                await asyncio.sleep(0)

        def factory(budget):
            life = V4Lifecycle(
                **IDENTITY,
                session_factory=partial(
                    V4Session, transport_factory=lambda: wire, session_300=budget
                ),
                retry_delays=(),
                clock=lambda: now[0],
            )
            lifecycles.append(life)
            return life

        metrics, detail = await collect(
            scenario, IDENTITY, factory=factory, clock=lambda: now[0], sleep=sleep
        )
        assert (
            metrics["cleanup"] and metrics["completed"] and metrics["error"] == "none"
        )
        assert metrics["opens"] == 1 and detail["rx_bytes"] <= 1048576
        assert observed_status("protocol", scenario, metrics) == (
            "INCONCLUSIVE" if scenario == "session-reconnect" else "SUCCESS"
        )
        assert metrics["pings"] == metrics["pongs"]
        assert all(
            payload[0] in {OPEN_CLIENT, 11, DATA_REQUEST_CLIENT}
            for payload in wire.writes
        )
        assert all(
            payload[0] != DATA_REQUEST_CLIENT or payload[8] == 4
            for payload in wire.writes
        )
        assert not wire.active_reads and lifecycles[0].session_observation.stopped
        if scenario == "session-300":
            assert metrics["useful_ms"] == 300000 and metrics["reads"] == 5
        if scenario == "session-reconnect":
            assert metrics["useful_ms"] == 440000 and metrics["reads"] <= 10
        value = stage(
            "protocol",
            scenario,
            started=True,
            reason="observed",
            elapsed_ms=max(1000, int(now[0] * 1000)),
            metrics=metrics,
            detail=detail,
        )
        report = envelope("protocol", scenario, [value])
        assert validate_report(report) and node_accepts(report)

    asyncio.run(exercise())


@pytest.mark.parametrize("loss", [TransportEOF("PRIVATE_PAYLOAD"), b"\x05\x03"])
def test_natural_recovery_requires_real_new_generation_and_correlated_read(loss):
    async def exercise():
        now = [0.0]
        first, second = Stream([response()]), Stream([response()])
        streams = iter([first, second])
        injected = False

        async def sleep(delay):
            nonlocal injected
            now[0] += delay
            if now[0] >= 60 and not injected:
                injected = True
                first.queue.put_nowait(loss)
            for _ in range(20):
                await asyncio.sleep(0)

        async def backoff(_):
            await asyncio.sleep(0)

        def factory(budget):
            return V4Lifecycle(
                **IDENTITY,
                retry_delays=(1.0,),
                sleep=backoff,
                clock=lambda: now[0],
                session_factory=partial(
                    V4Session,
                    transport_factory=lambda: next(streams),
                    session_300=budget,
                ),
            )

        metrics, detail = await collect(
            "session-reconnect",
            IDENTITY,
            factory=factory,
            clock=lambda: now[0],
            sleep=sleep,
        )
        assert metrics["recovered"] and metrics["opens"] == 2 and metrics["cleanup"]
        assert observed_status("protocol", "session-reconnect", metrics) == "SUCCESS"
        assert detail["recovery_witness"]["stable_ms"] >= 120000
        assert detail["recovery_witness"]["read_generation"] == 2
        assert metrics["loss_kind"] == (
            "transport" if isinstance(loss, Exception) else "close_client"
        )
        assert metrics["close_client_subcode"] == (
            None if isinstance(loss, Exception) else 3
        )
        assert not first.active_reads and not second.active_reads

    asyncio.run(exercise())


def test_tls_only_has_no_protocol_write_and_closes_on_failure():
    async def exercise():
        closed = []

        class TLS:
            def __init__(self, **kwargs):
                assert kwargs == {"connect_timeout": 10, "close_timeout": 2}

            async def connect(self):
                raise TransportEOF("PRIVATE_PAYLOAD")

            async def close(self):
                closed.append(True)

        metrics, _ = await collect("tls-only", {}, transport_factory=TLS)
        assert closed and metrics["cleanup"] and metrics["error"] == "transport"
        assert observed_status("protocol", "tls-only", metrics) == "FAILURE"

    asyncio.run(exercise())


def test_h1h2_reuses_exact_historical_schedule_and_removes_private_capture(tmp_path):
    async def exercise():
        captured = []

        async def runner(directory, **kwargs):
            captured.append(directory)
            assert kwargs["mode"] == "both" and kwargs["seconds"] == 90
            (directory / "private").write_text("PRIVATE_PAYLOAD")
            sessions = [
                {
                    "mode": "H1" if i < 6 else "H2",
                    "boundary_proven": False,
                    "rx_bytes": 50,
                    "read_calls": 1,
                    "v4_requests": 0 if i < 6 else 1,
                    "correlated_responses": 0 if i < 6 else 1,
                }
                for i in range(12)
            ]
            return {"sessions": sessions, "stopped_early": False}

        metrics, detail = await h1h2(IDENTITY, directory=tmp_path, runner=runner)
        assert observed_status("protocol", "h1h2", metrics) == "INCONCLUSIVE"
        assert metrics["h1_sessions"] == metrics["h2_sessions"] == 6
        assert detail["rx_bytes"] == 600 and not captured[0].exists()

        async def fail(directory, **kwargs):
            captured.append(directory)
            (directory / "private").write_text("PRIVATE_PAYLOAD")
            raise HobenProtocolError()

        with pytest.raises(HobenProtocolError):
            await h1h2(IDENTITY, directory=tmp_path, runner=fail)
        assert not captured[-1].exists()

    asyncio.run(exercise())
