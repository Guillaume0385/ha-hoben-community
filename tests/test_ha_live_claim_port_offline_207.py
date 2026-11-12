"""#207 D4-C2: simulated atomic claim port, no GitHub/HA network."""

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ".github/scripts/ha-live-claim-port-offline.cjs"


def _node(script: str, value: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        input=json.dumps(value),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def test_simulated_atomic_race_and_adversarial_matrix():
    result = subprocess.run(
        ["node", "--test", "--test-reporter=tap", "tests/js/ha-live-claim-port-offline.test.cjs"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "# pass 11" in result.stdout
    assert "PRIVATE_TOKEN" not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {"contract": "live", "private_token": "PRIVATE_TOKEN"},
        {"repository": "Guillaume0385/ha-hoben-community", "attempt": 2},
        {"sha": "a" * 40, "ref": "refs/heads/main"},
        {"execution": "offline", "complete": True, "live_ready": True},
    ],
)
def test_foreign_or_private_metadata_yields_redacted_refusal(payload):
    script = f"""
const fs=require('node:fs');
const {{OfflineClaimPort,SharedMockClaimStore}}=require('./{MODULE}');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
(async()=>{{
  try {{await new OfflineClaimPort(new SharedMockClaimStore()).reserve(input);process.exitCode=1;}}
  catch(e) {{process.stdout.write(e.message);}}
}})();
"""
    result = _node(script, payload)
    assert result.returncode == 0
    assert result.stdout == "ha_live_claim_port_offline_refused"
    assert result.stderr == ""


def test_offline_port_has_no_live_entrypoint_or_git_mutation():
    source = (ROOT / MODULE).read_text(encoding="utf-8")
    assert "require(" not in source
    assert "fetch(" not in source
    assert "github.com/" not in source
    assert "refs/tags/" not in source
    assert "deleteRef" not in source
    assert "secrets_allowed: false" in source
    assert "live_ready: false" in source
    assert "complete: false" in source
    assert "admission: 'NOT RUN'" in source
