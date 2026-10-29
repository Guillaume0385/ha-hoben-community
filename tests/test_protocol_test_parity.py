"""#126 experimental parity: real shared owners, synthetic peers and clocks."""

import asyncio
import json

import pytest

from scripts.campaign_runtime_contract import SECONDS, stage, validate_report
from scripts.protocol_campaign_collect import collect
from tests.test_campaign_runtime import envelope, node_accepts
from tests.test_protocol_campaign_collect import IDENTITY
from tests.test_session_suite import Harness


def test_owner_decided_protocol_ceilings_preserve_ha_and_h1h2():
    assert SECONDS["protocol"]["session-reconnect"] == 600
    assert SECONDS["protocol"]["all"] == 3000
    assert sum(v for k, v in SECONDS["protocol"].items() if k != "all") == 2850
    assert SECONDS["protocol"]["h1h2"] == 1800
    assert SECONDS["protocol"]["session-300"] == 360
    assert list(SECONDS["ha"].values()) == [360, 90, 120, 180, 600, 60, 120, 1800]


def test_reconnect_uses_existing_pong_policy_and_collector_with_real_sessions():
    async def scenario():
        harness = Harness("recovered")
        metrics, detail = await collect(
            "session-reconnect",
            IDENTITY,
            factory=lambda budget, policy=None: harness.make(budget, policy),
            clock=harness.clock,
            sleep=harness.sleep,
        )
        harness.assert_closed()
        assert harness.policy is not None and harness.policy.suppressed > 0
        assert metrics["recovered"] and metrics["cleanup"]
        witness = detail["recovery_witness"]
        assert witness["mode"] == "pong_inhibition_after_120s"
        assert (
            120000 <= witness["loss_after_ms"] < witness["reopened_after_ms"] < 240000
        )
        assert witness["stable_ms"] == 120000 and witness["recovery_pongs"] > 0
        value = stage(
            "protocol",
            "session-reconnect",
            started=True,
            reason="observed",
            elapsed_ms=int(harness.now * 1000),
            metrics=metrics,
            detail=detail,
        )
        report = envelope("protocol", "session-reconnect", [value])
        assert value["status"] == "SUCCESS"
        assert validate_report(report) and node_accepts(report)
        assert "private" not in json.dumps(report) and "a" * 32 not in json.dumps(
            [metrics, detail]
        )

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "mode, outcome, status",
    [
        ("no_ping", "not_exercised", "INCONCLUSIVE"),
        ("no_disconnect", "no_disconnect", "INCONCLUSIVE"),
        ("tls", "no_disconnect", "INCONCLUSIVE"),
        ("stability_loss", "stability_lost", "INCONCLUSIVE"),
        ("reopen_failed", "reopen_failed", "INCONCLUSIVE"),
        ("no_recovery_pong", "timeout", "FAILURE"),
    ],
)
def test_unattested_recovery_never_succeeds(mode, outcome, status):
    async def scenario():
        harness = Harness(mode)
        metrics, detail = await collect(
            "session-reconnect",
            IDENTITY,
            factory=lambda budget, policy: harness.make(budget, policy),
            clock=harness.clock,
            sleep=harness.sleep,
        )
        harness.assert_closed()
        assert not metrics["recovered"]
        assert detail["recovery_witness"]["outcome"] == outcome
        value = stage(
            "protocol",
            "session-reconnect",
            started=True,
            reason="observed",
            elapsed_ms=int(harness.now * 1000),
            metrics=metrics,
            detail=detail,
        )
        report = envelope("protocol", "session-reconnect", [value])
        assert value["status"] == status
        assert validate_report(report) and node_accepts(report)

    asyncio.run(scenario())


def controlled_receipt():
    """Independently specified successful experiment for the two validators."""
    from scripts.campaign_runtime_contract import empty_metrics

    metrics = empty_metrics()
    metrics.update(
        opens=2,
        reads=5,
        reads_ok=5,
        pings=10,
        pongs=8,
        useful_ms=281000,
        completed=True,
        cleanup=True,
        recovered=True,
        loss_kind="transport",
    )
    detail = {
        "rx_bytes": 1000,
        "rx_chunks": 10,
        "recovery_witness": {
            "mode": "pong_inhibition_after_120s",
            "boundary_proven": False,
            "outcome": "verified",
            "loss_generation": 1,
            "read_generation": 2,
            "read_sequence": 2,
            "stable_ms": 120000,
            "suppressed_pongs": 2,
            "loss_after_ms": 160000,
            "reopened_after_ms": 161000,
            "recovery_pongs": 4,
        },
    }
    value = stage(
        "protocol",
        "session-reconnect",
        started=True,
        reason="observed",
        elapsed_ms=281000,
        metrics=metrics,
        detail=detail,
    )
    return envelope("protocol", "session-reconnect", [value])


@pytest.mark.parametrize(
    "key, value",
    [
        ("mode", "natural"),
        ("boundary_proven", True),
        ("outcome", "no_disconnect"),
        ("outcome", []),
        ("loss_generation", None),
        ("read_generation", 1),
        ("read_sequence", None),
        ("read_sequence", 6),
        ("stable_ms", 119999),
        ("suppressed_pongs", 0),
        ("suppressed_pongs", True),
        ("suppressed_pongs", 3),
        ("loss_after_ms", 119999),
        ("loss_after_ms", True),
        ("loss_after_ms", 240000),
        ("reopened_after_ms", 240000),
        ("reopened_after_ms", 159999),
        ("recovery_pongs", 0),
        ("recovery_pongs", 9),
        ("raw", "PRIVATE_PAYLOAD"),
    ],
)
def test_python_and_node_refuse_incomplete_or_forged_recovery_receipts(key, value):
    report = controlled_receipt()
    assert validate_report(report) and node_accepts(report)
    report["stages"][0]["detail"]["recovery_witness"][key] = value
    with pytest.raises(ValueError):
        validate_report(report)
    assert not node_accepts(report)


def test_old_receipt_without_inhibition_cannot_claim_current_scenario_success():
    report = controlled_receipt()
    witness = report["stages"][0]["detail"]["recovery_witness"]
    for key in list(witness):
        if key not in {
            "loss_generation",
            "read_generation",
            "read_sequence",
            "stable_ms",
        }:
            del witness[key]
    with pytest.raises(ValueError):
        validate_report(report)
    assert not node_accepts(report)


def test_global_all_executes_six_stages_within_3000_seconds():
    from scripts.run_campaign import run
    from tests.test_campaign_runtime import PROVENANCE, observed

    now, calls = [0.0], []

    def execute(campaign, scenario, payload, deadline, **kwargs):
        duration = SECONDS[campaign][scenario]
        assert deadline == now[0] + duration
        calls.append(scenario)
        value = observed(campaign, scenario)
        value["elapsed_ms"] = duration * 1000
        now[0] += duration
        return value

    report = run(
        "protocol",
        "all",
        PROVENANCE,
        b"synthetic",
        executor=execute,
        clock=lambda: now[0],
    )
    assert calls == [
        "tls-only",
        "session-open",
        "read-v4-state",
        "h1h2",
        "session-300",
        "session-reconnect",
    ]
    assert report["elapsed_ms"] == 2850000
    assert validate_report(report) and node_accepts(report)


def test_global_deadline_prevents_any_further_ack():
    from scripts.run_campaign import run
    from tests.test_campaign_runtime import PROVENANCE, observed

    now, calls = [0.0], []

    def execute(campaign, scenario, payload, deadline, **kwargs):
        calls.append(scenario)
        now[0] = 3000  # Parent delay/cleanup has consumed the global envelope.
        return observed(campaign, scenario)

    report = run(
        "protocol",
        "all",
        PROVENANCE,
        b"synthetic",
        executor=execute,
        clock=lambda: now[0],
    )
    assert calls == ["tls-only"]
    assert all(s["status"] == "NOT RUN" for s in report["stages"][1:])
    assert validate_report(report) and node_accepts(report)


@pytest.mark.parametrize("scenario", ["session-300", "session-reconnect"])
def test_default_binding_supplies_the_real_budget_and_only_experimental_pong_policy(
    monkeypatch, scenario
):
    from custom_components.hoben.v4_experiment import Session300, SessionReconnect
    from custom_components.hoben.v4_no_pong import NoPongAfter120
    from scripts import protocol_campaign_collect as collector

    async def exercise():
        harness = Harness()
        bound = []

        def make_owner(**kwargs):
            options = kwargs["session_factory"].keywords
            budget, policy = options["session_300"], options["no_pong_after_120"]
            assert kwargs["retry_delays"] == (1.0, 2.0)
            assert type(budget) is (
                SessionReconnect if scenario == "session-reconnect" else Session300
            )
            assert (
                (type(policy) is NoPongAfter120)
                if scenario == "session-reconnect"
                else policy is None
            )
            bound.append((budget, policy))
            return harness.make(budget, policy)

        monkeypatch.setattr(collector, "V4Lifecycle", make_owner)
        metrics, _ = await collector.collect(
            scenario, IDENTITY, clock=harness.clock, sleep=harness.sleep
        )
        assert metrics["completed"] and metrics["cleanup"] and len(bound) == 1
        harness.assert_closed()

    asyncio.run(exercise())


@pytest.mark.parametrize("scenario", ["session-300", "session-reconnect"])
def test_historical_collector_owns_exactly_one_cleanup_timeout(monkeypatch, scenario):
    from custom_components.hoben.v4_lifecycle import V4Lifecycle

    async def exercise():
        harness, closes = Harness(), []
        original = V4Lifecycle.close

        async def close(owner):
            closes.append(owner)
            await original(owner)

        monkeypatch.setattr(V4Lifecycle, "close", close)
        metrics, _ = await collect(
            scenario,
            IDENTITY,
            factory=lambda budget, policy=None: harness.make(budget, policy),
            clock=harness.clock,
            sleep=harness.sleep,
        )
        assert metrics["cleanup"] and closes == harness.lives
        harness.assert_closed()

    asyncio.run(exercise())


def test_cancellation_during_pong_inhibition_reaps_the_shared_owner():
    async def exercise():
        harness, entered = Harness("no_disconnect"), asyncio.Event()

        async def sleep(delay):
            await harness.sleep(delay)
            if harness.policy.suppressed:
                entered.set()
                await asyncio.Future()

        task = asyncio.create_task(
            collect(
                "session-reconnect",
                IDENTITY,
                factory=lambda budget, policy: harness.make(budget, policy),
                clock=harness.clock,
                sleep=sleep,
            )
        )
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        harness.assert_closed()

    asyncio.run(exercise())
