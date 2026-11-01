"""Actual shared V4 ownership over synthetic streams for the manual campaign."""

import asyncio
import json
from functools import partial

import pytest

from custom_components.hoben.exceptions import HobenProtocolError
from custom_components.hoben.myhoben import DATA_REQUEST_CLIENT, OPEN_CLIENT
from custom_components.hoben.transport import TransportEOF
from custom_components.hoben.v4_lifecycle import V4Lifecycle
from custom_components.hoben.v4_session import V4Session
from scripts.campaign_runtime_contract import observed_status, stage, validate_report
from scripts.protocol_campaign_collect import collect, h1h2
from scripts.run_campaign import identity
from tests.test_campaign_runtime import envelope, node_accepts
from tests.test_session_300_runtime import Stream, response

IDENTITY = {"user_guid": "a" * 32, "device_guid": "D" * 32}


@pytest.mark.parametrize("challenge", [False, True])
def test_user_only_entry_uses_documented_initial_identity_without_association(
    monkeypatch, challenge
):
    from scripts import protocol_campaign_collect as collector

    async def exercise():
        wire = Stream()
        if challenge:
            wire.prefix = b"\x2f"

        def owner(**kwargs):
            kwargs["session_factory"] = partial(
                kwargs["session_factory"], transport_factory=lambda: wire
            )
            return V4Lifecycle(**kwargs)

        monkeypatch.setattr(collector, "V4Lifecycle", owner)
        private = identity({"HOBEN_USER_GUID": "b" * 32})
        metrics, detail = await collect("session-open", private)
        assert metrics["cleanup"] and metrics["completed"] is not challenge
        assert metrics["error"] == ("authorization" if challenge else "none")
        assert len(wire.writes) == 1 and wire.writes[0][0] == OPEN_CLIENT
        assert wire.writes[0][37:69] == b"0" * 32
        assert wire.close_count == 1 and not wire.active_reads
        assert "b" * 32 not in json.dumps([metrics, detail])

    asyncio.run(exercise())


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

        def factory(budget, policy=None):
            life = V4Lifecycle(
                **IDENTITY,
                session_factory=partial(
                    V4Session,
                    transport_factory=lambda: wire,
                    session_300=budget,
                    no_pong_after_120=policy,
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
        if scenario == "session-reconnect":
            assert metrics["pings"] > metrics["pongs"]
            assert detail["recovery_witness"]["suppressed_pongs"] > 0
        else:
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
            assert metrics["useful_ms"] == 240000 and metrics["reads"] <= 10
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
def test_prethreshold_loss_cannot_attest_controlled_reconnection(loss):
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

        def factory(budget, policy=None):
            return V4Lifecycle(
                **IDENTITY,
                retry_delays=(1.0,),
                sleep=backoff,
                clock=lambda: now[0],
                session_factory=partial(
                    V4Session,
                    transport_factory=lambda: next(streams),
                    session_300=budget,
                    no_pong_after_120=policy,
                ),
            )

        metrics, detail = await collect(
            "session-reconnect",
            IDENTITY,
            factory=factory,
            clock=lambda: now[0],
            sleep=sleep,
        )
        assert not metrics["recovered"] and metrics["opens"] == 2 and metrics["cleanup"]
        assert (
            observed_status("protocol", "session-reconnect", metrics) == "INCONCLUSIVE"
        )
        assert detail["recovery_witness"]["suppressed_pongs"] == 0
        assert detail["recovery_witness"]["loss_generation"] is None
        assert detail["recovery_witness"]["read_generation"] is None
        assert metrics["loss_kind"] == (
            "transport" if isinstance(loss, Exception) else "close_client"
        )
        assert metrics["close_client_subcode"] == (
            None if isinstance(loss, Exception) else 3
        )
        assert not first.active_reads and not second.active_reads

    asyncio.run(exercise())


@pytest.mark.parametrize("opening_delay", [0, 37.25])
def test_experimental_reference_keeps_acceptance_origin_and_strict_cleanup(
    opening_delay,
):
    from tests.test_session_suite import Harness

    async def exercise():
        h = Harness()

        def factory(budget, policy):
            life = h.make(budget, policy)
            make_session = life._factory

            def session(**options):
                value = make_session(**options)
                if len(h.streams) == 1:
                    connect = h.streams[0].connect

                    async def delayed():
                        h.now += opening_delay
                        await connect()

                    h.streams[0].connect = delayed
                return value

            life._factory = session
            return life

        metrics, detail = await collect(
            "session-reconnect", IDENTITY, factory=factory, clock=h.clock, sleep=h.sleep
        )
        h.assert_closed()
        r = detail["recovery_witness"]
        assert h.policy.first_opened_at == opening_delay
        assert r["loss_after_ms"] == 160000 and r["reopened_after_ms"] == 161000
        assert r["loss_generation"] == 1 and r["read_generation"] == 2
        assert r["suppressed_pongs"] > 0 and r["recovery_pongs"] > 0
        assert r["stable_ms"] == 120000 and r["boundary_proven"] is False
        assert metrics["recovered"] and metrics["cleanup"]
        assert metrics["useful_ms"] >= int((opening_delay + 161 + 120) * 1000)
        value = stage(
            "protocol",
            "session-reconnect",
            started=True,
            reason="observed",
            elapsed_ms=int(h.now * 1000),
            metrics=metrics,
            detail=detail,
        )
        report = envelope("protocol", "session-reconnect", [value])
        assert validate_report(report) and node_accepts(report)

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
                    "rx_bytes": 50 if i < 6 else 100,
                    "read_calls": 1,
                    "v4_requests": 0 if i < 6 else 2,
                    "correlated_responses": 0 if i < 6 else 2,
                }
                for i in range(12)
            ]
            return {"sessions": sessions, "stopped_early": False}

        metrics, detail = await h1h2(IDENTITY, directory=tmp_path, runner=runner)
        assert observed_status("protocol", "h1h2", metrics) == "SUCCESS"
        assert metrics["h1_sessions"] == metrics["h2_sessions"] == 6
        assert detail["rx_bytes"] == 900 and not captured[0].exists()

        async def fail(directory, **kwargs):
            captured.append(directory)
            (directory / "private").write_text("PRIVATE_PAYLOAD")
            raise HobenProtocolError()

        with pytest.raises(HobenProtocolError):
            await h1h2(IDENTITY, directory=tmp_path, runner=fail)
        assert not captured[-1].exists()

    asyncio.run(exercise())
