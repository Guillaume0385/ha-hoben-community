"""#207 D4-D: real gate design, offline/negative proof tests only.

No GitHub, appliance, TLS or Home Assistant network is contacted.
"""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
D4 = ROOT / ".github/scripts/ha-live-d4-security.cjs"
NODE_TEST = "tests/js/ha-live-d4-security.test.cjs"


def test_offline_d4_security_node_matrix():
    result = subprocess.run(
        ["node", "--test", NODE_TEST],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "synthetic-private-credential" not in result.stdout + result.stderr


def test_offline_d4_rest_read_node_matrix():
    result = subprocess.run(
        ["node", "--test", "tests/js/ha-live-d4-rest-read.test.cjs"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "synthetic-test-token" not in result.stdout + result.stderr


def test_offline_300_second_verdict_node_matrix():
    result = subprocess.run(
        ["node", "--test", "tests/js/ha-live-d4-observation.test.cjs"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "SENSITIVE_IDENTIFIER" not in result.stdout + result.stderr


def test_preflight_cli_rejects_invalid_context_without_secret(tmp_path):
    import json
    import os

    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps({"inputs": {"scenario": "hoben-live"}}))
    env = {
        "PATH": os.environ.get("PATH", ""),
        "GITHUB_REPOSITORY": "Guillaume0385/ha-hoben-community",
        "GITHUB_ACTOR": "Guillaume0385",
        "GITHUB_TRIGGERING_ACTOR": "Guillaume0385",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": "a" * 40,
        "GITHUB_RUN_ID": "12",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_EVENT_PATH": str(event_path),
    }
    p = subprocess.run(
        ["node", "scripts/ha_live_d4_preflight.cjs"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert p.returncode != 0
    assert "ha_live_d4_preflight_NOT_RUN" in p.stderr
    assert "Bearer" not in p.stdout + p.stderr


def test_fail_closed_no_automatic_claim_or_runtime_secrets():
    source = D4.read_text(encoding="utf8")
    assert "ha_live_d4_security_refused" in source
    assert "protected:true alone" in source or "protected:true" in source
    assert "deny();" in source
    assert "method:'GET'" in source
    assert "redirect:'manual'" in source
    for forbidden in (
        "workflow_dispatch(",
        "secrets.HOBEN_USER_GUID",
        "secrets.HOBEN_DEVICE_GUID",
        "POST",
        "DELETE",
        "force:true",
    ):
        assert forbidden not in source


def test_protected_ha_and_experimental_info_workflows_still_exist():
    ha = (ROOT / ".github/workflows/hoben-ha-manual.yml").read_text()
    info = (ROOT / ".github/workflows/hoben-manual.yml").read_text()
    assert "hoben-read-only-observation" in ha
    assert "cancel-in-progress: false" in ha
    assert "environment: hoben-live" in ha
    assert "workflow_dispatch" in ha
    assert "info" in info.lower() or "collect-info" in info
    # The old collector is never used for the D4 selection or the all alias.
    assert "!['hoben-live', 'all'].includes(scenario)" in ha
    assert "d4_preflight:" in ha
    assert "node scripts/ha_live_d4_preflight.cjs" in ha
    assert "GITHUB_TOKEN: ${{ github.token }}" in ha
