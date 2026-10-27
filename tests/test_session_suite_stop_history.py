"""L6bis: historical receipts from real owners, with simulated TLS and time.

No production observer is added. Test wrappers record only after the original
synchronous consumption returns, before teardown can revoke the live origin.
"""

import asyncio
import copy
from typing import NamedTuple

import pytest

from custom_components.hoben.v4_eof_quarantine import State
from custom_components.hoben.v4_no_pong import NoPongAfter120
from custom_components.hoben.v4_session import V4Session
from scripts.session_suite import validate_suite
from tests.test_session_suite_v3 import CORPUS, PROOF, materialize, node
from tests.test_v4_lifecycle_quarantine import (
    clean,
    connected,
    quarantined,
    reached_backoff,
)


class Receipt(NamedTuple):
    generation: int
    eof_at: int
    consumed_at: int


@pytest.mark.parametrize("phase", ["consumption", "acceptance"])
@pytest.mark.parametrize("kind", ["local", "cancel"])
@pytest.mark.parametrize("delta_ms", [0, 1])
def test_owner_receipt_survives_quantized_public_stop_as_failure(
    monkeypatch, phase, kind, delta_ms
):
    async def scenario():
        life, factory, sleep, budget, pong, now, cap = await connected()
        origin = factory.sessions[0]
        t0 = origin._quarantine_time(budget.accepted_at)
        receipt = cleanup_at = inhibition_at = None
        consume = V4Session._consume_quarantine
        cleanup = V4Session._cleanup_quarantine
        suppress = NoPongAfter120.suppress

        def record_consume(session, owner, generation):
            nonlocal receipt
            permit = consume(session, owner, generation)
            assert session is origin and owner is life and receipt is None
            assert session._quarantine_observation.state is State.EOF_CANDIDATE
            receipt = Receipt(
                generation,
                session._quarantine_observation.at_ms,
                session._quarantine_checked_at,
            )
            assert permit is session._quarantine_permit
            return permit

        async def record_cleanup(session, owner, permit):
            nonlocal cleanup_at
            await cleanup(session, owner, permit)
            assert session is origin and cleanup_at is None
            cleanup_at = session._quarantine_now()

        def record_suppression(policy, generation):
            nonlocal inhibition_at
            suppressed = suppress(policy, generation)
            if suppressed and policy is pong and inhibition_at is None:
                inhibition_at = origin._quarantine_now()
            return suppressed

        monkeypatch.setattr(V4Session, "_consume_quarantine", record_consume)
        monkeypatch.setattr(V4Session, "_cleanup_quarantine", record_cleanup)
        monkeypatch.setattr(NoPongAfter120, "suppress", record_suppression)
        try:
            await quarantined(life, factory, pong, now)
            entered = origin._quarantine_observation.at_ms
            causal = budget.failure
            causal_slot = budget.requests
            await reached_backoff(factory, sleep, now)
            assert receipt is not None and cleanup_at is not None
            assert entered < receipt.eof_at <= receipt.consumed_at <= cleanup_at
            assert cap._permit is origin._quarantine_permit
            assert not origin._quarantine_owner_stopped
            accepted = generation = None
            if phase == "acceptance":
                now[0] = 142
                sleep.release.put_nowait(None)
                await life.wait_connected()
                accepted = origin._quarantine_time(budget.accepted_at)
                generation = budget.connected_generation
                assert generation == 2 and receipt.consumed_at < accepted
            # Advance the injected clock only in the separate +1 ms control.
            now[0] += delta_ms / 1000
            stopped_at = origin._quarantine_now()
            assert (
                stopped_at - (receipt.consumed_at if accepted is None else accepted)
                == delta_ms
            )
            if kind == "local":
                await factory.sessions[-1].close()
            else:
                await life.close()
            await life.close()
            assert origin._quarantine_owner_stopped
            assert origin._quarantine_observation.state is State.REFUSED
            assert receipt.generation == 1  # Immutable fact from before revocation.
            assert len(factory.sessions) == (1 if accepted is None else 2)

            # Start from the closed empty shape only. Every non-empty history
            # and counter below comes from the real simulated owner executions.
            second = copy.deepcopy(
                CORPUS["reports"]["not_run"]["session_reconnect_no_pong"]
            )
            second.update(
                result="interrupted",
                terminal="closed" if accepted is None else "stability_lost",
                duration_ms=stopped_at - t0,
                opens=budget.opens,
                reconnections=budget.opens - 1,
                pings=budget.pings,
                pongs=budget.pongs,
                reads=budget.requests,
                responses=budget.responses,
                rx_bytes_total=budget.rx_bytes,
                rx_chunks_total=budget.rx_chunks,
                pongs_suppressed=pong.suppressed,
                peer_eofs=pong.peer_eofs,
                eofs_after_suppression=pong.peer_eofs_after_suppression,
                recovery_generation=generation or 0,
                stable_ms=0 if accepted is None else stopped_at - accepted,
                read_slot=causal_slot,
                failure_phase=causal[0],
                failure_category=causal[1],
                message_category=causal[2],
                causal_ms=entered - t0,
            )
            observation, process, suite = cap._initial._deadlines
            second["timing"].update(
                t0_observed=True,
                functional_end_ms=stopped_at - t0,
                observation_deadline_ms=observation - t0,
                process_deadline_ms=process - t0,
                suite_deadline_ms=suite - t0,
                inhibition_ms=inhibition_at - t0,
            )
            second["quarantine"].update(
                outcome="consumed",
                entered_ms=entered - t0,
                eof_ms=receipt.eof_at - t0,
                consumed_ms=receipt.consumed_at - t0,
                origin_generation=receipt.generation,
                eof_origin="transport_read",
                receipt="valid_at_consumption",
                cleanup_ms=cleanup_at - t0,
                stop=kind + "_after_consumption",
                stop_ms=stopped_at - t0,
                accepted_ms=None if accepted is None else accepted - t0,
                accepted_generation=generation,
            )
            if accepted is not None:
                second["stability"].update(
                    start_ms=accepted - t0,
                    end_ms=stopped_at - t0,
                    generation=generation,
                    interrupted=True,
                )
            # A synthetic first-scenario reference supplies only the unchanged
            # envelope; this test exercises the real second-scenario ownership.
            report = copy.deepcopy(CORPUS["reports"]["success"])
            report.update(
                result="not_successful",
                duration_ms=report["session_300"]["duration_ms"]
                + second["duration_ms"],
                session_reconnect_no_pong=second,
            )
            assert validate_suite(report, PROOF) == report
            actual = node(
                """
const [r,p]=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
const api=require('./.github/scripts/session-suite-report.cjs');
process.stdout.write(JSON.stringify({report:api.validate(r,p),
 completed:api.completed(r,p,'success','success')}));
""",
                [report, PROOF],
            )
            assert actual["report"] == report and actual["completed"] is False
            await clean(life, factory)
        finally:
            await life.close()

    asyncio.run(scenario())


def test_all_stop_fixtures_cannot_complete_even_when_jobs_succeed():
    cases = [c for c in CORPUS["cases"] if c["name"].startswith("stop_")]
    actual = node(
        """
const [reports,p]=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
const api=require('./.github/scripts/session-suite-report.cjs');
process.stdout.write(JSON.stringify(reports.map(r=>{
 try{return api.completed(r,p,'success','success');}catch(_){return false;}
})));
""",
        [[materialize(c) for c in cases], PROOF],
    )
    assert actual and not any(actual)
