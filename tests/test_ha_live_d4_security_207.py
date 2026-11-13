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
