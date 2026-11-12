"""D4-B1: the GitHub evidence adapter is tested only against synthetic REST replies."""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / ".github/scripts/ha-live-gate-evidence-offline.cjs"


def test_github_evidence_node_adversaries_offline():
    run = subprocess.run(
        ["node", "--test", "tests/js/ha-live-gate-evidence-offline.test.cjs"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    assert "PRIVATE_TOKEN" not in run.stdout + run.stderr
    assert "PRIVATE_API_TOKEN" not in run.stdout + run.stderr


@pytest.mark.parametrize("value", ["null", "[]", "{}", '{"execution":"live"}'])
def test_foreign_inputs_fail_with_only_a_closed_refusal(value):
    script = """
const {inspect}=require('./.github/scripts/ha-live-gate-evidence-offline.cjs');
const raw=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
try { inspect(raw, 0); process.exitCode=1; }
catch(error) { process.stdout.write(error.message); }
"""
    run = subprocess.run(
        ["node", "-e", script],
        input=value,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert run.returncode == 0
    assert run.stdout == "ha_live_offline_evidence_refused"
    assert run.stderr == ""


def test_offline_adapter_has_no_network_or_live_gate_entry_point():
    source = MODULE.read_text(encoding="utf-8")
    assert "require(" not in source
    assert "process.env" not in source
    assert "http.request" not in source
    assert "fetch(" not in source
    assert "module.exports=Object.freeze({inspect,requireAttested});" in source
