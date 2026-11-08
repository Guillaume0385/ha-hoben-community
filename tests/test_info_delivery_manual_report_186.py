"""Run the pure Node contract in ordinary CI and compare real #186-C evidence."""

import asyncio
import copy
import json
import subprocess
from pathlib import Path

import pytest

from custom_components.hoben.transport import TransportEOF, TransportTlsError
from scripts.info_delivery_scenario import InvalidInfoEvidence, validate_report
from tests.info_delivery_fixture_186 import run_case
from tests.tls_read_candidate_186 import PING, RESPONSE

ROOT = Path(__file__).resolve().parents[1]
DRIVER = """
const api=require('./.github/scripts/info-delivery-manual-report.cjs');
const reports=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
const results=reports.map(text=>{
  try {return {accepted:true,report:api.parseOffline(text)};}
  catch(error) {
    if(error.message!=='invalid_offline_info_report')process.exit(2);
    return {accepted:false};
  }
});
process.stdout.write(JSON.stringify(results));
"""


def node_reports(reports):
    result = subprocess.run(
        ["node", "-e", DRIVER],
        input=json.dumps(
            [json.dumps(r, separators=(",", ":"), sort_keys=True) for r in reports]
        ),
        text=True,
        capture_output=True,
        cwd=ROOT,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, "offline_node_contract_driver_failed"
    return json.loads(result.stdout)


def test_node_info_contract_suite_runs_in_existing_pytest_ci():
    # node:test also runs standalone and propagates failed assertions via exit.
    result = subprocess.run(
        ["node", "tests/js/info-delivery-manual-report.test.cjs"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "case",
    [
        "success",
        "absent",
        "fragment",
        "lost-ping",
        "lost-response",
        "eof",
        "tls",
        "auth",
        "timeout",
        "cancel",
        "cleanup",
        "cleanup-timeout",
        "collection-timeout",
        "cached",
        "duplicate-open",
        "limit",
        "exhausted",
        "default-off",
        "opening-suffix",
        "fragmented-response",
    ],
)
def test_node_accepts_actual_real_session_fixture_reports(monkeypatch, case):
    options = {
        "success": {},
        "absent": {"deliveries": ()},
        "fragment": {"deliveries": (b"\x0c", b"\x02", PING)},
        "lost-ping": {"deliveries": (b"\x0c" + PING,)},
        "lost-response": {"replies": (b"\x0c" + RESPONSE,)},
        "eof": {"replies": (TransportEOF(),)},
        "tls": {"replies": (TransportTlsError("PRIVATE_D1"),)},
        "auth": {"replies": (b"\x2f",)},
        "timeout": {"replies": ()},
        "cancel": {"replies": (), "cancel": True},
        "cleanup": {"close_error": TransportTlsError("PRIVATE_D1")},
        "cleanup-timeout": {"close_delay": 6},
        "collection-timeout": {"delivery_delay": 31},
        "cached": {"before_drop_read": True},
        "duplicate-open": {"duplicate_open": True},
        "limit": {"deliveries": (b"\x0c",) * 16 + (PING,), "limit": 16},
        "exhausted": {"deliveries": (b"\x0c", b"\x0c", PING), "limit": 1},
        "default-off": {"enabled": False},
        "opening-suffix": {"suffix": b"\x0c"},
        "fragmented-response": {"replies": (RESPONSE[:7], RESPONSE[7:])},
    }[case]
    report = asyncio.run(run_case(monkeypatch, **options)).report
    assert validate_report(report) == report
    observed = node_reports([report])
    assert observed == [{"accepted": True, "report": report}]
    assert "PRIVATE_D1" not in json.dumps(observed)
    assert report["mode"] == "offline" and not report["boundary_proven"]


def test_python_node_agree_on_closed_schema_and_counter_tampering(monkeypatch):
    report = asyncio.run(run_case(monkeypatch)).report
    variants = [report]
    for key in report:
        missing = copy.deepcopy(report)
        del missing[key]
        variants.append(missing)
    for key in (
        "openings",
        "reconnections",
        "info_discarded",
        "pings_after_drop",
        "pongs_after_drop",
        "requests_after_drop",
        "reads_after_drop",
        "elapsed_ms",
        "collection_ms",
        "cleanup_ms",
    ):
        for value in (-1, 35001, True, "PRIVATE_D1", None, 0.5):
            changed = copy.deepcopy(report)
            changed[key] = value
            variants.append(changed)
    for key, value in (
        ("mode", "live"),
        ("boundary_proven", True),
        ("first_error", "PRIVATE_D1"),
        ("cleanup_attested", False),
        ("same_session", False),
        ("reads_after_drop", 0),
    ):
        changed = copy.deepcopy(report)
        changed[key] = value
        variants.append(changed)
    for key in ("drop", "ping", "pong", "request", "read"):
        for value in (None, 0, True, 129):
            changed = copy.deepcopy(report)
            changed["steps"][key] = value
            variants.append(changed)
    variants.append({**report, "private": "PRIVATE_D1"})
    expected = []
    for changed in variants:
        try:
            validate_report(changed)
        except InvalidInfoEvidence:
            expected.append(False)
        else:
            expected.append(True)
    assert [result["accepted"] for result in node_reports(variants)] == expected
