"""Offline admission matrix; never connects the future HA Live gate."""

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_ha_live_admission_synthetic_github_matrix():
    result = subprocess.run(
        ["node", "tests/js/ha-live-gate-contract.test.cjs"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PRIVATE_API_TOKEN" not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {"execution": "live", "admission": "APPROVED"},
        {"status": "approved", "private": "PRIVATE_API_TOKEN"},
        {"execution": "offline", "observed_at": "PRIVATE_API_TOKEN"},
        {"__proto__": {"execution": "offline"}},
    ],
)
def test_foreign_or_private_input_has_only_closed_refusal(payload):
    result = subprocess.run(
        [
            "node",
            "-e",
            """
const {OfflineClaims}=require('./.github/scripts/ha-live-gate-contract.cjs');
const payload=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
try {new OfflineClaims().reserve(payload,1000);process.exitCode=1;}
catch(error){process.stdout.write(error.message);}
""",
        ],
        input=json.dumps(payload),
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout == "ha_live_offline_contract_refused"
    assert result.stderr == ""
