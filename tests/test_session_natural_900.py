"""Offline acceptance for the fail-closed natural-session collector."""

import asyncio
from copy import deepcopy

import pytest

from custom_components.hoben.exceptions import HobenProtocolError
from custom_components.hoben.transport import TransportEOF
from custom_components.hoben.v4_lifecycle import V4Lifecycle
from scripts.session_natural_900 import observe_natural, validate_natural
from tests.test_v4_lifecycle import Backoff, Factory, assert_clean


def report(**changes):
    return {
        "scenario": "session-natural-900",
        "result": "not_run",
        "duration_ms": 0,
        "initial_continuous": False,
        "reconnect_attempts": 0,
        "correlated_recovery_reads": 0,
    } | changes


@pytest.mark.parametrize(
    "outcome",
    [
        report(),
        report(result="inconclusive", duration_ms=900000, initial_continuous=True),
        report(result="inconclusive", duration_ms=1500, reconnect_attempts=1),
        report(result="failed", duration_ms=10),
    ],
)
def test_allowlisted_outcomes(outcome):
    assert validate_natural(outcome) == outcome


@pytest.mark.parametrize(
    "changes",
    [
        {"duration_ms": 900001},
        {"duration_ms": -1},
        {"reconnect_attempts": 2},
        {"reconnect_attempts": True},
        {"correlated_recovery_reads": 2},
        {"correlated_recovery_reads": True},
        {"correlated_recovery_reads": 1},
        {"result": "reconnected", "reconnect_attempts": 1},
        {"result": "reconnected", "initial_continuous": True},
        {"result": "not_run", "duration_ms": 1},
        {"result": "not_run", "initial_continuous": True},
        {"result": "not_run", "reconnect_attempts": 1},
        {"initial_continuous": True, "reconnect_attempts": 1},
    ],
)
def test_unproved_evidence_is_rejected(changes):
    with pytest.raises(ValueError, match="invalid_natural_report"):
        validate_natural(report(**changes))


def test_no_private_fields_in_report():
    private = deepcopy(report())
    private["device_guid"] = "synthetic-placeholder"
    with pytest.raises(ValueError, match="invalid_natural_report"):
        validate_natural(private)


def test_quiet_actual_lifecycle_reaches_900_without_fake_reconnect():
    async def scenario():
        now = 0.0
        factory = Factory()
        life = V4Lifecycle(
            user_guid="b" * 32,
            retry_delays=(1.0,),
            session_factory=factory,
        )

        async def tick(delay):
            nonlocal now
            now += delay
            await asyncio.sleep(0)

        result = await observe_natural(
            lambda: life, clock=lambda: now, sleep=tick
        )
        assert result == report(
            result="inconclusive",
            duration_ms=900000,
            initial_continuous=True,
        )
        assert len(factory.sessions) == 1
        assert_clean(factory)

    asyncio.run(scenario())


def test_actual_lifecycle_natural_loss_in_backoff_is_inconclusive():
    async def scenario():
        now = 0.0
        factory, backoff = Factory(), Backoff()
        life = V4Lifecycle(
            user_guid="b" * 32,
            retry_delays=(1.0,),
            session_factory=factory,
            sleep=backoff,
        )
        emitted = False

        async def tick(delay):
            nonlocal now, emitted
            now += delay
            if not emitted:
                emitted = True
                factory.transports[0].rx.set_exception(
                    TransportEOF("synthetic")
                )
            for _ in range(40):
                await asyncio.sleep(0)

        result = await observe_natural(
            lambda: life, clock=lambda: now, sleep=tick
        )
        assert result["result"] == "inconclusive"
        assert result["initial_continuous"] is False
        assert result["correlated_recovery_reads"] == 0
        assert len(factory.sessions) == 1
        assert backoff.delays == [1.0]
        assert_clean(factory)

    asyncio.run(scenario())


def test_actual_lifecycle_reopened_transport_is_not_generation_proof():
    async def scenario():
        now = 0.0
        factory = Factory()
        life = V4Lifecycle(
            user_guid="b" * 32,
            retry_delays=(1.0,),
            session_factory=factory,
            sleep=lambda _: asyncio.sleep(0),
        )
        emitted = False

        async def tick(delay):
            nonlocal now, emitted
            now += delay
            if not emitted:
                emitted = True
                factory.transports[0].rx.set_exception(
                    TransportEOF("synthetic")
                )
            for _ in range(100):
                await asyncio.sleep(0)

        result = await observe_natural(
            lambda: life, clock=lambda: now, sleep=tick
        )
        assert result["result"] == "inconclusive"
        assert result["reconnect_attempts"] == 1
        assert result["initial_continuous"] is False
        assert result["correlated_recovery_reads"] == 0
        assert len(factory.sessions) == 2
        assert_clean(factory)

    asyncio.run(scenario())


def test_initial_protocol_failure_stops_and_cleans_up():
    async def scenario():
        factory = Factory(failures=(HobenProtocolError(),))
        life = V4Lifecycle(
            user_guid="b" * 32,
            retry_delays=(1.0,),
            session_factory=factory,
        )
        result = await observe_natural(lambda: life)
        assert result["result"] == "failed"
        assert result["reconnect_attempts"] == 0
        assert result["initial_continuous"] is False
        assert len(factory.sessions) == 1
        assert_clean(factory)

    asyncio.run(scenario())


def test_cancellation_propagates_after_closing_real_lifecycle():
    async def scenario():
        factory = Factory()
        life = V4Lifecycle(
            user_guid="b" * 32,
            retry_delays=(1.0,),
            session_factory=factory,
        )
        waiting = asyncio.Event()
        gate = asyncio.Event()

        async def blocked_sleep(_):
            waiting.set()
            await gate.wait()

        task = asyncio.create_task(
            observe_natural(lambda: life, sleep=blocked_sleep)
        )
        await waiting.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert_clean(factory)

    asyncio.run(scenario())


def test_wrong_factory_budget_fails_closed_before_connect():
    async def scenario():
        factory = Factory()
        life = V4Lifecycle(
            user_guid="b" * 32,
            retry_delays=(1.0, 2.0),
            session_factory=factory,
        )
        result = await observe_natural(lambda: life)
        assert result["result"] == "failed"
        assert factory.sessions == []

    asyncio.run(scenario())
