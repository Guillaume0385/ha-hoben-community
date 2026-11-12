"""#207 D4-B2: only deterministic, injected transport fixtures are exercised."""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / ".github/scripts/ha-live-gate-evidence-transport-offline.cjs"


def test_node_mock_transport_adversaries():
    result = subprocess.run(
        ["node", "--test", "tests/js/ha-live-gate-evidence-transport-offline.test.cjs"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=25,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "VERY_PRIVATE_TOKEN" not in result.stdout + result.stderr
    assert "TOKEN_SECRET_PRIVATE" not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "value", ["null", "{}", '{"now":0}', '{"context":{"run_id":1}}']
)
def test_missing_injected_transport_refuses_without_leaking(value):
    script = """
const {collect}=require('./.github/scripts/' +
  'ha-live-gate-evidence-transport-offline.cjs');
const value=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
collect(value).then(()=>{process.exitCode=1},e=>process.stdout.write(e.message));
"""
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        input=value,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout == "ha_live_offline_transport_refused"
    assert result.stderr == ""


def test_transport_source_has_no_live_or_secret_entrypoint():
    source = MODULE.read_text(encoding="utf-8")
    assert "process.env" not in source
    assert "fetch(" not in source
    assert "http.request" not in source
    assert "https.request" not in source
    assert "child_process" not in source
    assert "workflow_dispatch" in source  # a checked fixture field, not a call
    assert "module.exports = Object.freeze({collect});" in source
