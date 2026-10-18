"""Offline regression for the causal/quarantine clock contract.

These tests do not pretend to execute the unpublished L7 v3 producer.
"""

import copy
import json
import subprocess
from pathlib import Path

import pytest

from scripts.session_suite import validate_suite

ROOT = Path(__file__).resolve().parents[1]
CORPUS = json.loads((ROOT / "tests/fixtures/session_suite_v3_cases.json").read_text())
PROOF = CORPUS["proof"]


def _report(*, entry_delta=0, eof_delta=10000):
    report = copy.deepcopy(CORPUS["reports"]["success"])
    second = report["session_reconnect_no_pong"]
    second["quarantine"]["entered_ms"] = second["causal_ms"] + entry_delta
    second["quarantine"]["eof_ms"] = second["causal_ms"] + eof_delta
    second["rx_diagnostic"]["eof_ms"] = second["causal_ms"] + eof_delta
    return report


def _node_accepts(report):
    code = """
const [r,p]=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
const api=require('./.github/scripts/session-suite-report.cjs');
let ok=true;
try { api.validate(r,p); } catch (_) { ok=false; }
process.stdout.write(JSON.stringify(ok));
"""
    result = subprocess.run(
        ["node", "-e", code],
        input=json.dumps([report, PROOF]),
        text=True,
        capture_output=True,
        cwd=ROOT,
        check=True,
        timeout=20,
    )
    assert not result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize(
    ("entry_delta", "eof_delta", "accepted"),
    [
        (0, 10000, True),
        (1, 10000, True),
        (-1, 10000, False),
        (0, 0, False),
        (0, -1, False),
        (0, 1, True),
    ],
)
def test_published_v3_contract_causal_entry_and_eof(entry_delta, eof_delta, accepted):
    """Both validators preserve owner ordering, strict EOF and old success proof."""
    report = _report(entry_delta=entry_delta, eof_delta=eof_delta)
    try:
        validated = validate_suite(report, PROOF)
    except (ValueError, TypeError):
        python_accepted = False
    else:
        python_accepted = validated == report
    assert python_accepted is accepted
    assert _node_accepts(report) is accepted


def test_reconnection_requires_real_post_entry_eof():
    """Moving the entry cannot itself fabricate an EOF/recovery proof."""
    report = _report(entry_delta=1, eof_delta=10000)
    second = report["session_reconnect_no_pong"]
    assert second["quarantine"]["entered_ms"] == second["causal_ms"] + 1
    assert second["quarantine"]["eof_ms"] > second["quarantine"]["entered_ms"]
    assert second["quarantine"]["accepted_ms"] > second["quarantine"]["eof_ms"]
    assert validate_suite(report, PROOF) == report
    assert _node_accepts(report)
    second["rx_diagnostic"]["eof_ms"] = None
    with pytest.raises((ValueError, TypeError)):
        validate_suite(report, PROOF)
    assert not _node_accepts(report)


@pytest.mark.parametrize(
    ("change", "accepted"),
    [
        ({"causal_ms": 159999}, False),
        ({"rx_diagnostic.rejection_ms": 159999}, False),
        ({"quarantine.entered_ms": 159999}, False),
        ({"quarantine.entered_ms": 160000}, True),
        ({"quarantine.entered_ms": 160001}, True),
        ({"quarantine.entered_ms": 169999}, True),
        ({"quarantine.entered_ms": 170000}, False),
        ({"quarantine.entered_ms": 240000}, False),
        ({"quarantine.entered_ms": 300001}, False),
        ({"quarantine.eof_origin": "none"}, False),
        ({"quarantine.receipt": "none"}, False),
        ({"quarantine.accepted_ms": None}, False),
        ({"stability.end_ms": None}, False),
    ],
)
def test_clock_ordering_cannot_weaken_other_evidence(change, accepted):
    """Changing an owner field is not permission to create a causal/EOF event."""
    report = _report()
    second = report["session_reconnect_no_pong"]
    for path, value in change.items():
        target = second
        keys = path.split(".")
        for key in keys[:-1]:
            target = target[key]
        target[keys[-1]] = value
    try:
        python_accepted = validate_suite(report, PROOF) == report
    except (ValueError, TypeError):
        python_accepted = False
    assert python_accepted is accepted
    assert _node_accepts(report) is accepted


@pytest.mark.parametrize(
    "name", ["no_eof", "stopped_after_consumption", "stopped_after_acceptance"]
)
def test_clock_gap_never_upgrades_inconclusive_or_interrupted(name):
    report = copy.deepcopy(CORPUS["reports"][name])
    second = report["session_reconnect_no_pong"]
    second["quarantine"]["entered_ms"] += 1
    assert validate_suite(report, PROOF) == report
    assert _node_accepts(report)
    assert second["result"] != "recovered_120s"
