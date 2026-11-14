"""#212 report-size regression over real HA/session owners, offline only."""

import json
from copy import deepcopy

import pytest
from conftest import assert_private_values_absent

from ha_tests.test_dual_session_033 import exercise033
from ha_tests.test_persistent_client import peers as peers  # noqa: F401
from scripts.ha_dual_evidence import recovered, validate_detail
from scripts.ha_dual_observer import _compact_stale_report
from tests.test_ha_live_proof import receipt


@pytest.mark.parametrize("b_offset", [0, 1])
async def test_stale_timeout_report_keeps_generations_and_fits_original_limit(
    hass, entry, peers, freezer, monkeypatch, b_offset
):
    originals = []

    def capture(e):
        originals.append(deepcopy(e))
        _compact_stale_report(e)

    monkeypatch.setattr("scripts.ha_dual_observer._compact_stale_report", capture)
    evidence, first, _, _ = await exercise033(
        hass, entry, peers, freezer, monkeypatch, kind="stale", b_offset=b_offset
    )
    detail = {
        "supervisor": receipt(
            process_ms=900000, useful_ms=None, elapsed_ms=900000, network="fixed_tls"
        ),
        "evidence": evidence,
    }
    validate_detail(detail)
    assert len(json.dumps(detail, separators=(",", ":")).encode()) <= 8192
    assert not evidence["completed"] and not recovered(evidence)
    assert evidence["incident"]["category"] == "timeout"
    assert evidence["incident"]["generation"] == 1
    assert (
        sum(row["decoded"] for row in evidence["reads"] if row["generation"] == 1) == 6
    )
    assert [
        row["sequence"]
        for row in evidence["reads"]
        if row["decoded"] and row["generation"] == 2
    ] == [1, 2, 3]
    original = originals[0]
    assert (
        len(
            json.dumps({**detail, "evidence": original}, separators=(",", ":")).encode()
        )
        > 8192
    )
    expected = deepcopy(original)
    for phase in expected["phases"][:2]:
        assert phase["a"]["last_frame"] is not None
        phase["a"]["last_frame"] = None
    assert evidence == expected  # Every event, read, owner and diagnostic survives.
    assert_private_values_absent(json.dumps(detail))
    assert all(owner["cleanup"] for owner in evidence["owners"])
    assert [o["generation"] for o in evidence["owners"] if o["role"] == "a"] == [1, 2]
    # Other incidents and non-routine frames must retain their complete report.
    for field, value in (("kind", "eof"), ("late_frame", None)):
        other = deepcopy(original)
        other["incident"][field] = value
        before = deepcopy(other)
        _compact_stale_report(other)
        assert other == before
    abnormal = deepcopy(original)
    for phase in abnormal["phases"][:2]:
        phase["a"]["last_frame"]["category"] = "protocol"
    before = deepcopy(abnormal)
    _compact_stale_report(abnormal)
    assert abnormal == before
    again = deepcopy(evidence)
    _compact_stale_report(again)
    assert again == evidence
    assert evidence["resources"]["a"]["opens"] == 2
    first.close.assert_awaited_once_with()


@pytest.mark.parametrize("kind", ["late", "eof", "silence"])
async def test_other_observation_scenarios_keep_their_complete_report(
    hass, entry, peers, freezer, monkeypatch, kind
):
    seen = []

    def check_unchanged(e):
        before = deepcopy(e)
        _compact_stale_report(e)
        assert e == before
        seen.append(True)

    monkeypatch.setattr(
        "scripts.ha_dual_observer._compact_stale_report", check_unchanged
    )
    await exercise033(hass, entry, peers, freezer, monkeypatch, kind=kind)
    assert seen == [True]
