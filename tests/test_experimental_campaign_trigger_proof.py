"""Offline evidence for a *non-secret* GitHub branch-creation trigger only.

This must never be mistaken for an authorized Hoben campaign.
"""

import shutil
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
FLOW = ROOT / ".github/workflows/experimental-campaign-trigger-proof.yml"
GATE = ROOT / ".github/scripts/experimental-campaign-trigger-proof.cjs"


def test_campaign_proof_is_push_ref_only_and_has_no_secrets():
    text = FLOW.read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    event = workflow.get("on", workflow.get(True))
    assert event == {"push": {"branches": ["hoben-campaign-proof/**"]}}
    assert workflow["permissions"] == {}
    assert list(workflow["jobs"]) == ["proof"]
    proof = workflow["jobs"]["proof"]
    assert proof["permissions"] == {"contents": "read"}
    assert "environment" not in proof
    assert "github.run_attempt == 1" in proof["if"]
    assert "github.actor == 'Guillaume0385'" in proof["if"]
    assert proof["timeout-minutes"] <= 5
    assert workflow["concurrency"]["cancel-in-progress"] is False
    assert "checkout@v7" in text
    assert "persist-credentials: false" in text
    assert GATE.is_file()
    gate_text = GATE.read_text(encoding="utf-8")
    assert "module.exports" in gate_text
    assert "protected === true" in gate_text
    assert "payload.created === true" in gate_text
    for forbidden in (
        "secrets.",
        "HOBEN_USER_GUID",
        "HOBEN_DEVICE_GUID",
        "hoben-live:",
        "hoben-experimental:",
        "upload-artifact",
        "workflow_dispatch",
        "repository_dispatch",
        "pull_request_target",
        "issues:",
        "schedule:",
        "id-token: write",
        "contents: write",
        "createRef(",
        "createTag(",
        "run_experimental_boundary.py",
    ):
        assert forbidden not in text
    for forbidden in ("secrets.", "createRef(", "createTag(", "HOBEN_USER_GUID"):
        assert forbidden not in gate_text


def test_campaign_branch_trigger_offline_node_refusals():
    assert shutil.which("node")
    result = subprocess.run(
        ["node", "--test", "tests/js/experimental-campaign-trigger-proof.test.cjs"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout[-2500:] + result.stderr[-2500:]
