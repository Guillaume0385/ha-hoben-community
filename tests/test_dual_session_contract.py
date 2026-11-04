"""#126/032: optional selection, dedicated budget and closed evidence, offline."""

import copy

import pytest

from scripts.campaign_runtime_contract import (
    CampaignLimits,
    ha_limits,
    plan,
    stage,
    validate_report,
)
from scripts.ha_dual_evidence import empty, owner_record, phase, project
from scripts.run_campaign import run
from tests.test_campaign_runtime import PROVENANCE, envelope, node_accepts
from tests.test_ha_live_proof import receipt

DUAL = "dual-session-observation"
HISTORICAL = (
    "hoben-live",
    "open-errors",
    "refresh-v4",
    "session-reuse",
    "session-reconnect",
    "cleanup",
    "availability",
)


def test_optional_dual_choice_never_expands_historical_all():
    assert plan("ha", DUAL) == (DUAL,)
    assert plan("ha", "all") == HISTORICAL
    with pytest.raises(ValueError):
        plan("protocol", DUAL)


def test_900_seconds_is_a_named_profile_not_a_general_budget_extension():
    limits = ha_limits(DUAL)
    assert limits.process_ms == 900000 and limits.useful_ms is None
    assert limits.memory_bytes == 1024**3 and limits.pids == 128
    with pytest.raises(ValueError):
        CampaignLimits(1024**3, 128, None, 900000)
    assert [ha_limits(s).process_ms for s in HISTORICAL] == [
        360000,
        90000,
        120000,
        180000,
        600000,
        60000,
        120000,
    ]


def proof():
    """Invented scalar receipt, never an attestation of a real collection."""
    e = empty()
    e.update(
        clock="monotonic",
        completed=True,
        t0_ms=1000,
        end_ms=660000,
        a_end_active=True,
        b_read_sequence=1,
        b_active_at_close=True,
    )
    e["b"] = dict(
        start_ms=180000,
        accepted_ms=180000,
        read_ms=180000,
        close_ms=360000,
        closed_ms=360000,
    )
    e["resources"] = {
        role: dict(
            opens=1, accepted=True, close_calls=1, close_completed=True, cleanup=True
        )
        for role in ("a", "b")
    }
    e["owners"] = [
        {
            **owner_record(role, 1),
            **e["resources"][role],
            "open_ms": None if role == "a" else 180000,
            "accepted_ms": 0 if role == "a" else 180000,
            "closed_ms": 660000 if role == "a" else 360000,
            "cleaned_ms": 660000 if role == "a" else 360000,
        }
        for role in ("a", "b")
    ]
    e["reads"] = [
        dict(
            scheduled_ms=n * 60000,
            at_ms=n * 60000,
            end_ms=n * 60000,
            decoded=True,
            available=True,
            state="connected",
            generation=1,
            sequence=n + 1,
            error="none",
            attempted=True,
            held=False,
            last_success_ms=n * 60000,
            age_ms=0,
        )
        for n in range(12)
    ]
    for s in e["reads"]:
        e["phases"][phase(s["at_ms"])]["a"]["requests"] += 1
        e["phases"][phase(s["at_ms"])]["a"]["types"][4] += 1
    e["phases"][1]["b"]["requests"] = 1
    e["phases"][0]["a"]["types"][1] = 1
    e["phases"][1]["b"]["types"][1] = 1
    e["phases"][1]["b"]["types"][4] = 1
    e["transitions"] = [
        dict(role=r, at_ms=t, state=s)
        for r, t, s in (
            ("a", 0, "connected"),
            ("b", 180000, "connected"),
            ("b", 360000, "disconnected"),
            ("a", 660000, "disconnected"),
        )
    ]
    return dict(
        supervisor=receipt(
            process_ms=900000, useful_ms=None, elapsed_ms=662000, network="fixed_tls"
        ),
        evidence=e,
    )


def report(d):
    v = stage(
        "ha",
        DUAL,
        started=True,
        elapsed_ms=d["supervisor"]["elapsed_ms"],
        reason="observed",
        detail=d,
        metrics=project(d),
    )
    return envelope("ha", DUAL, [v])


def test_python_and_node_accept_only_positive_native_proof():
    r = report(proof())
    assert validate_report(r) and node_accepts(r)
    assert r["stages"][0]["status"] == "SUCCESS"
    for k, v in (("clock", "synthetic"), ("completed", False)):
        d = proof()
        d["evidence"][k] = v
        r = report(d)
        assert r["stages"][0]["status"] == "FAILURE" and node_accepts(r)


@pytest.mark.parametrize(
    "path,value",
    [
        (("evidence", "boundary_proven"), True),
        (("evidence", "b", "start_ms"), 179999),
        (("evidence", "b", "closed_ms"), 360001),  # less than 300 s afterward
        (("evidence", "b_read_sequence"), 0),
        (("evidence", "resources", "b", "cleanup"), False),
        (("evidence", "resources", "a", "close_completed"), False),
        (("evidence", "resources", "a", "opens"), 2),
        (("evidence", "reads", 4, "decoded"), False),
        (("evidence", "reads", 4, "sequence"), 3),
        (("evidence", "reads", 4, "at_ms"), 246000),
        (("evidence", "reads", 4, "generation"), 2),
        (("evidence", "a_end_active"), False),
        (("evidence", "phases", 1, "b", "requests"), 2),
        (("evidence", "phases", 1, "a", "invalid"), 1),
        (("evidence", "phases", 1, "a", "eof"), 1),
        (("evidence", "transitions", 1, "at_ms"), 180001),
        (("evidence", "overflow"), True),
        (("evidence", "raw"), "PRIVATE_PAYLOAD"),
        (("supervisor", "process_ms"), 600000),
        (("supervisor", "elapsed_ms"), 660000),
        (("supervisor", "pids"), 129),
    ],
)
def test_missing_contradictory_or_private_proof_is_refused_by_both(path, value):
    d = proof()
    r = report(copy.deepcopy(d))
    node = r["stages"][0]["detail"]
    for key in path[:-1]:
        d, node = d[key], node[key]
    d[path[-1]] = node[path[-1]] = value
    assert not node_accepts(r)
    with pytest.raises((ValueError, TypeError)):
        validate_report(r)


def test_parent_uses_original_start_including_preparation_never_rearms():
    seen = []
    now = [200.0]

    def execute(c, s, p, deadline, **kwargs):
        seen.append(deadline)
        now[0] = 862
        return report(proof())["stages"][0]

    r = run(
        "ha",
        DUAL,
        PROVENANCE,
        b"synthetic",
        executor=execute,
        clock=lambda: now[0],
        absolute_start=100,
    )
    assert seen == [1000] and r["elapsed_ms"] == 762000
    with pytest.raises(ValueError):
        run("ha", "cleanup", PROVENANCE, b"synthetic", absolute_start=100)


def test_budget_exhausted_during_preparation_never_enters_worker():
    def forbidden(*args, **kwargs):
        raise AssertionError("worker entered after global deadline")

    r = run(
        "ha",
        DUAL,
        PROVENANCE,
        b"synthetic",
        executor=forbidden,
        clock=lambda: 1001,
        absolute_start=100,
    )
    assert r["stages"][0]["status"] == "NOT RUN"
    assert r["stages"][0]["reason"] == "timeout" and node_accepts(r)


def diagnostic_proof():
    d = proof()
    e = d["evidence"]
    e.update(
        completed=False,
        error="protocol",
        failure=dict(
            role="a",
            at_ms=240000,
            category="protocol",
            phase="frame_boundary",
            subcode=None,
        ),
    )
    e["phases"][1]["a"]["last_frame"] = dict(
        event="error",
        generation=1,
        message_type="data_response_client",
        expected_total_bytes=50,
        received_bytes=7,
        length_scope="frame",
        provenance="validated_header",
        phase="frame_boundary",
        category="protocol",
        status="partial",
        at_ms=240000,
    )
    return d


def test_b3_partial_lengths_survive_only_as_closed_metadata():
    d = diagnostic_proof()
    r = report(d)
    assert node_accepts(r) and r["stages"][0]["status"] == "FAILURE"
    assert (
        r["stages"][0]["detail"]["evidence"]["phases"][1]["a"]["last_frame"][
            "received_bytes"
        ]
        == 7
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("expected_total_bytes", 48),
        ("received_bytes", 4097),
        ("received_bytes", "PRIVATE_PAYLOAD"),
        ("phase", "PRIVATE_PAYLOAD"),
        ("header", "PRIVATE_PAYLOAD"),
    ],
)
def test_openedclient_total_oversized_or_private_frame_metadata_are_never_attested(
    field, value
):
    r = report(diagnostic_proof())
    f = r["stages"][0]["detail"]["evidence"]["phases"][1]["a"]["last_frame"]
    if field == "expected_total_bytes":
        f["message_type"] = "opened_client"
    f[field] = value
    assert not node_accepts(r)
    with pytest.raises((ValueError, TypeError)):
        validate_report(r)


@pytest.mark.parametrize("accept,read", [(200000, 200000), (180000, 220000)])
def test_late_b_open_or_unbounded_read_does_not_prove_required_overlap(accept, read):
    r = report(proof())
    e = r["stages"][0]["detail"]["evidence"]
    e["b"].update(accepted_ms=accept, read_ms=read)
    e["transitions"][1]["at_ms"] = accept
    assert not node_accepts(r)
    with pytest.raises(ValueError):
        validate_report(r)


@pytest.mark.parametrize(
    "role,slot,index", [("a", 0, 1), ("b", 1, 1), ("a", 2, 4), ("b", 1, 4)]
)
def test_missing_b3_header_proof_never_credits_success(role, slot, index):
    r = report(proof())
    r["stages"][0]["detail"]["evidence"]["phases"][slot][role]["types"][index] = 0
    assert not node_accepts(r)
    with pytest.raises(ValueError):
        validate_report(r)


def test_counter_overflow_keeps_budget_diagnostic_when_observer_stops():
    from scripts.ha_dual_evidence import validate
    from scripts.ha_dual_instrumentation import ObservationFailed, Tracker

    e = empty()
    tracker = Tracker(e, lambda: 1000, 1000, 1900)
    tracker.increment("a", "rx_bytes", 1048577)
    with pytest.raises(ObservationFailed):
        tracker.guard("a")
    tracker.fail("a", "unexpected", "unknown")
    assert e["error"] == e["failure"]["category"] == "budget"
    assert validate(e)


@pytest.mark.parametrize("host,port", [("other.invalid", 465), ("myhoben.fr", 433)])
def test_metadata_wrapper_preserves_fixed_destination_before_any_connection(host, port):
    import asyncio
    from unittest.mock import AsyncMock

    from custom_components.hoben.transport import AsyncTlsTransport
    from scripts.ha_dual_instrumentation import TrackedTransport, Tracker

    wire = AsyncTlsTransport(host, port)
    wire.connect = AsyncMock()
    tracker = Tracker(empty(), lambda: 1000, 1000, 1900)

    async def scenario():
        with pytest.raises(ValueError):
            await TrackedTransport(wire, None, tracker, "a").connect()

    asyncio.run(scenario())
    wire.connect.assert_not_awaited()
