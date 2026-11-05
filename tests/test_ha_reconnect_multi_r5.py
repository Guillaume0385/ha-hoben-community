"""Independent Python/Node R5 contracts. Every receipt here is synthetic."""

import copy

import pytest

from scripts.campaign_runtime_contract import validate_report
from scripts.ha_campaign_evidence import empty_recovery
from tests.test_campaign_runtime import ha_detail, node_accepts
from tests.test_ha_controlled_evidence import report


def detail():
    d = ha_detail("session-reconnect", recovered=True)
    e = d["evidence"]
    template = e["samples"][0]["observation"]
    observations = []
    for g, seq in [(1, 1), (1, 2), (1, 3), (2, 1), (3, 1), (3, 2)]:
        observations.append(
            dict(
                template,
                attempts=g,
                generation=g,
                read_generation=g,
                read_sequence=seq,
                loss_generation=g - 1 or None,
                loss_kind=None if g == 1 else "close_client" if g == 2 else "transport",
                close_client_subcode=3 if g == 2 else None,
                cleaned_generation=g - 1 or None,
                stopped=False,
                cleanup_failed=False,
            )
        )
    for i, (s, o) in enumerate(zip(e["samples"], observations, strict=True)):
        s.update(
            at_ms=i * 60000, observation=o, decoded=True, available=True, error="none"
        )
    e["window"].update(
        elapsed_ms=342000, active=True, observation=copy.deepcopy(observations[-1])
    )
    e["cleanup"] = dict(
        completed=True,
        observation=dict(observations[-1], stopped=True, cleaned_generation=3),
    )
    generations = []
    owners = []
    for g, connect, loss, cleanup, cat, code, pongs, seq, read in [
        (1, 0, 130000, 130000, "close_client", 3, 119, 3, 120000),
        (2, 132000, 220000, 220000, "eof", None, 87, 1, 180000),
        (3, 222000, None, 342000, None, None, 120, 2, 300000),
    ]:
        generations.append(
            dict(
                generation=g,
                connect_ms=connect,
                opened_ms=connect,
                loss_ms=loss,
                category=cat,
                subcode=code,
                cleanup_ms=cleanup,
                pongs=pongs,
            )
        )
        owners.append(
            dict(
                role="a",
                generation=g,
                accepted=True,
                accepted_generation=g,
                close_client_subcode=code,
                close=[cleanup] * 4,
                stage="reaped",
                pending=0,
                last_read=[seq, read, 342000 - read],
            )
        )
    e["recovery"] = dict(
        empty_recovery(),
        schema=2,
        generations=generations,
        diagnostic=dict(interruption=None, cleanup=None),
        outcome="verified",
        accepted_at_ms=0,
        suppressed_pongs=10,
        loss_generation=1,
        loss_after_ms=130000,
        reopened_after_ms=132000,
        read_generation=3,
        read_sequence=2,
        recovery_pongs=120,
        stable_ms=120000,
    )
    e.update(
        diagnostic_schema=1,
        diagnostic=dict(
            end_ms=342000,
            invalid=False,
            owners=owners,
            first=["a", 1, 130000, "close_client", "post_open", "session", 3],
            terminal=None,
            cleanup=None,
        ),
    )
    d["supervisor"]["elapsed_ms"] = 343000
    return d


def test_two_individually_proven_recoveries_are_accepted_by_both_validators():
    r = report(detail())
    assert r["stages"][0]["status"] == "SUCCESS"
    assert validate_report(r) and node_accepts(r)


@pytest.mark.parametrize(
    "field,value",
    [
        ("connect_ms", 129999),
        ("connect_ms", None),
        ("opened_ms", None),
        ("opened_ms", 180001),
        ("generation", 1),
        ("loss_ms", None),
        ("loss_ms", 131999),
        ("category", "internal"),
        ("category", "PRIVATE"),
        ("subcode", 3),
        ("cleanup_ms", None),
        ("cleanup_ms", 222001),
        ("pongs", True),
        ("private", "PRIVATE"),
    ],
)
def test_each_transition_is_required_and_closed(field, value):
    r = report(detail())
    r["stages"][0]["detail"]["evidence"]["recovery"]["generations"][1][field] = value
    with pytest.raises(ValueError):
        validate_report(r)
    assert not node_accepts(r)


@pytest.mark.parametrize(
    "case",
    [
        "last_stability",
        "last_pong",
        "stale",
        "missing_read",
        "hidden_loss",
        "owner_pending",
        "owner_unreaped",
        "cleanup",
        "terminal",
        "permanent_first",
        "extra_generation",
        "missing_generation",
        "unknown_boundary",
        "clock",
        "missing_f1",
        "replay",
        "late_read",
        "early_inhibition",
    ],
)
def test_missing_or_falsified_evidence_never_succeeds(case):
    r = report(detail())
    e = r["stages"][0]["detail"]["evidence"]
    g, f = e["recovery"]["generations"], e["diagnostic"]
    if case == "last_stability":
        e["window"]["elapsed_ms"] = 341999
    elif case == "last_pong":
        g[-1]["pongs"] = 0
    elif case == "stale":
        e["samples"][-1]["decoded"] = False
    elif case == "missing_read":
        e["samples"][3]["decoded"] = False
    elif case == "hidden_loss":
        g[-1].update(loss_ms=320000, category="eof")
    elif case == "owner_pending":
        f["owners"][1]["pending"] = 1
    elif case == "owner_unreaped":
        f["owners"][1]["close"][3] = None
    elif case == "cleanup":
        f["cleanup"] = f["first"]
    elif case == "terminal":
        f["terminal"] = f["first"]
    elif case == "permanent_first":
        f["first"][3], f["first"][6] = "authentication", None
    elif case == "extra_generation":
        g.append(copy.deepcopy(g[-1]))
    elif case == "missing_generation":
        g.pop(1)
    elif case == "unknown_boundary":
        e["recovery"]["boundary_proven"] = True
    elif case == "clock":
        g[1]["opened_ms"] = 130001
    elif case == "missing_f1":
        del e["diagnostic"]
        del e["diagnostic_schema"]
    elif case == "replay":
        e["samples"][-1]["observation"]["read_sequence"] = 1
    elif case == "late_read":
        e["samples"][3]["at_ms"] = 221000
    elif case == "early_inhibition":
        e["recovery"]["loss_after_ms"] = 119999
    with pytest.raises(ValueError):
        validate_report(r)
    assert not node_accepts(r)
