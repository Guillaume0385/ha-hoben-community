"""Two-phase C evidence never credits a still-connected session as clean."""

import asyncio
import copy

import pytest

from scripts.info_delivery_scenario import validate_report
from scripts.info_delivery_supervisor import (
    InfoSupervisor,
    InvalidSupervision,
    validate_supervision_report,
)
from tests.info_delivery_fixture_186 import run_case


def pending(report):
    result = copy.deepcopy(report)
    result.update(
        cleanup_attested=False,
        rx_reaped=False,
        result="FAILURE",
        reason="cleanup_unproven",
    )
    return validate_report(result)


@pytest.mark.parametrize("absent", [False, True])
def test_final_evidence_after_real_cleanup_not_before(monkeypatch, absent):
    final = asyncio.run(
        run_case(monkeypatch, deliveries=() if absent else (b"\x0c", b"\x0a"))
    ).report
    now = [0]
    policy = InfoSupervisor(clock_ms=lambda: now[0])
    policy.start()
    now[0] = 3_540_000 if absent else 1000
    policy.prepare_observation(pending(final))
    assert policy.state == "CLEANING"
    now[0] += 10
    final["elapsed_ms"] += 10
    final["cleanup_ms"] += 10
    policy.observe(final)
    for event in ("transport_closed", "rx_reaped", "worker_reaped"):
        policy.event(event)
    result = policy.finish()
    assert result["schema"] == 2
    assert result["result"] == ("INCONCLUSIVE" if absent else "SUCCESS")
    assert validate_supervision_report(result) == result
    forged = copy.deepcopy(result)
    forged["pending_observation"]["info_discarded"] += 1
    with pytest.raises(InvalidSupervision):
        validate_supervision_report(forged)


@pytest.mark.parametrize(
    "attack",
    [
        "new-read",
        "session",
        "erase-error",
        "early-absent",
        "duration",
        "late",
        "duplicate",
        "no-final",
    ],
)
def test_provisional_evidence_cannot_be_replaced_or_claim_cleanup(monkeypatch, attack):
    final = asyncio.run(run_case(monkeypatch)).report
    provisional = pending(final)
    now = [0]
    policy = InfoSupervisor(clock_ms=lambda: now[0])
    policy.start()
    now[0] = 1000
    if attack == "early-absent":
        final = asyncio.run(run_case(monkeypatch, deliveries=())).report
        provisional = pending(final)
    if attack == "erase-error":
        provisional["first_error"] = "timeout"
    policy.prepare_observation(provisional)
    now[0] = 1010
    final["elapsed_ms"] += 10
    final["cleanup_ms"] += 10
    if attack == "new-read":
        final["steps"]["read"] += 1
    elif attack == "session":
        final["same_session"] = False
        final.update(result="FAILURE", reason="multiple_sessions")
    elif attack == "duration":
        final["elapsed_ms"] -= 10
        final["cleanup_ms"] -= 10
    elif attack == "late":
        now[0] = 61000  # Exact immutable cleanup deadline, not a retry.
    elif attack == "duplicate":
        policy.prepare_observation(provisional)
    if attack != "no-final" and policy.state != "STOPPED":
        policy.observe(final)
    for event in ("transport_closed", "rx_reaped", "worker_reaped"):
        if policy.state != "STOPPED":
            policy.event(event)
    result = policy.finish()
    assert result["result"] == "FAILURE"
    assert validate_supervision_report(result) == result


@pytest.mark.parametrize("at", [3_599_999, 3_600_000, 3_600_001])
def test_schema2_absolute_global_deadline(monkeypatch, at):
    final = asyncio.run(run_case(monkeypatch, deliveries=())).report
    now = [0]
    policy = InfoSupervisor(clock_ms=lambda: now[0])
    policy.start()
    now[0] = 3_540_000
    policy.prepare_observation(pending(final))
    now[0] = at
    # C's stricter 5 s budget independently refuses this late child. Nothing
    # extends the parent reserve to accept it as a valid C cleanup.
    policy.tick()
    result = policy.finish()
    assert result["result"] == "FAILURE"
    assert result["cleanup_deadline_ms"] == 3_600_000
    assert result["elapsed_ms"] == at
    assert validate_supervision_report(result) == result
