"""Offline contract diagnostic for the causal/quarantine clock gap.

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
        (1, 10000, False),
        (-1, 10000, False),
        (0, 0, False),
        (0, -1, False),
        (0, 1, True),
    ],
)
def test_published_v3_contract_causal_entry_and_eof(
    entry_delta, eof_delta, accepted
):
    """A real 1 ms owner gap is rejected by both installed validators."""
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
    """Changing the entry time cannot fabricate a valid EOF/recovery."""
    report = _report(entry_delta=1, eof_delta=10000)
    second = report["session_reconnect_no_pong"]
    assert second["quarantine"]["entered_ms"] == second["causal_ms"] + 1
    assert second["quarantine"]["eof_ms"] > second["quarantine"]["entered_ms"]
    assert second["quarantine"]["accepted_ms"] > second["quarantine"]["eof_ms"]
    with pytest.raises((ValueError, TypeError)):
        validate_suite(report, PROOF)
    assert not _node_accepts(report)
