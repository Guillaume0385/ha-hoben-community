"""Independent Python/Node refusal of incomplete or falsified controlled proof."""

import copy

import pytest

from scripts.campaign_runtime_contract import stage, validate_report
from scripts.ha_campaign_evidence import empty_recovery, project
from scripts.ha_session_supervisor import SourceBundle
from tests.test_campaign_runtime import envelope, ha_detail, node_accepts


def controlled():
    d = ha_detail("session-reconnect", recovered=True)
    e = d["evidence"]
    for sample, at in zip(e["samples"], [0, 60000, 130000, 180000, 240000, 300000]):
        sample["at_ms"] = at
    e["window"]["elapsed_ms"] = 310000
    d["supervisor"]["elapsed_ms"] = 311000
    e["recovery"] = {
        **empty_recovery(),
        "outcome": "verified",
        "accepted_at_ms": 0,
        "suppressed_pongs": 10,
        "loss_generation": 1,
        "loss_after_ms": 130000,
        "reopened_after_ms": 132000,
        "read_generation": 2,
        "read_sequence": 3,
        "recovery_pongs": 10,
        "stable_ms": 120000,
    }
    return d


def report(d):
    s = stage(
        "ha",
        "session-reconnect",
        started=True,
        reason="observed",
        elapsed_ms=d["supervisor"]["elapsed_ms"],
        metrics=project("session-reconnect", d),
        detail=d,
    )
    return envelope("ha", "session-reconnect", [s])


def test_controlled_success_is_bound_to_final_live_generation_and_read():
    r = report(controlled())
    assert r["stages"][0]["status"] == "SUCCESS"
    assert validate_report(r) and node_accepts(r)


@pytest.mark.parametrize(
    "key,value",
    [
        ("mode", "natural"),
        ("boundary_proven", True),
        ("accepted_at_ms", None),
        ("accepted_at_ms", 300000),
        ("suppressed_pongs", 0),
        ("suppressed_pongs", True),
        ("loss_generation", 2),
        ("loss_after_ms", 119999),
        ("loss_after_ms", 133000),
        ("reopened_after_ms", 240000),
        ("read_generation", 1),
        ("read_sequence", 6),
        ("recovery_pongs", 0),
        ("recovery_pongs", 1048577),
        ("stable_ms", 119999),
        ("private", "PRIVATE_PAYLOAD"),
    ],
)
def test_forged_causal_field_cannot_survive_either_validator(key, value):
    r = report(controlled())
    d = r["stages"][0]["detail"]
    d["evidence"]["recovery"][key] = value
    with pytest.raises(ValueError):
        validate_report(r)
    assert not node_accepts(r)


@pytest.mark.parametrize("field,value", [("active", False), ("elapsed_ms", 240000)])
def test_early_or_inactive_final_window_refuses_success(field, value):
    r = report(controlled())
    r["stages"][0]["detail"]["evidence"]["window"][field] = value
    with pytest.raises(ValueError):
        validate_report(r)
    assert not node_accepts(r)


def test_historical_natural_recovery_is_readable_but_no_longer_controlled_success():
    r = report(ha_detail("session-reconnect", recovered=True))
    assert r["stages"][0]["status"] == "INCONCLUSIVE"
    assert validate_report(r) and node_accepts(r)
    bad = copy.deepcopy(r)
    bad["stages"][0]["metrics"]["recovered"] = True
    bad["stages"][0]["status"] = bad["actions_result"] = "SUCCESS"
    with pytest.raises(ValueError):
        validate_report(bad)
    assert not node_accepts(bad)


def test_isolated_campaign_source_has_injector_but_original_baseline_does_not():
    for campaign in (True, False):
        bundle = SourceBundle(live=True, campaign=campaign)
        try:
            for name in ("ha_pong_injection.py", "ha_reconnect_observer.py"):
                path = bundle.folder / "scripts" / name
                assert path.exists() is campaign
                if campaign:
                    assert path.stat().st_mode & 0o777 == 0o444
        finally:
            bundle.close()
