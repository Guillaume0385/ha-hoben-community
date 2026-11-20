"""Retired HA-parity fixture security and non-reactivation regressions (#189 B1)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "tests/fixtures/retired_workflows/hoben-live-experimental.yml"


def test_retired_ha_parity_cannot_be_reactivated_by_an_installed_entry_point():
    """Keep the security fixture, but never reinstall its removed live worker."""
    assert WORKFLOW.is_file()
    assert not (ROOT / ".github/workflows" / WORKFLOW.name).exists()
    removed = ("launch_live_ha_parity", "run_live_ha_parity")
    for name in removed:
        assert not (ROOT / "scripts" / f"{name}.py").exists()
    for folder in (
        ".github/workflows",
        ".github/scripts",
        "scripts",
        "custom_components",
    ):
        for path in (ROOT / folder).rglob("*"):
            if path.suffix in {".py", ".cjs", ".yml", ".yaml"}:
                assert not any(name in path.read_text() for name in removed), path


def test_exact_live_workflow_permissions_and_secret_lifecycle():
    workflow = yaml.safe_load(WORKFLOW.read_text())
    assert workflow.get("on", workflow.get(True)) == {
        "push": {"branches": ["experimental"]}
    }
    assert workflow["permissions"] == {}
    assert workflow["concurrency"] == {
        "group": "hoben-read-only-observation",
        "cancel-in-progress": False,
        "queue": "max",
    }
    jobs = workflow["jobs"]
    assert set(jobs) == {"dry-run", "admission", "collect", "publish", "result"}
    assert jobs["publish"]["needs"] == ["admission", "collect"]
    assert jobs["result"]["needs"] == ["admission", "collect", "publish"]
    assert jobs["collect"]["outputs"]["report_b64"] == (
        "${{ steps.exports.outputs.report_b64 }}"
    )
    assert "environment" not in jobs["publish"]
    assert jobs["publish"]["permissions"] == {"contents": "read"}
    assert jobs["admission"]["needs"] == "dry-run"
    assert jobs["collect"]["needs"] == "admission"
    assert jobs["collect"]["environment"] == "hoben-live"
    assert jobs["collect"]["if"] == "needs.admission.outputs.approved == 'true'"
    assert "environment" not in jobs["admission"]
    assert "environment" not in jobs["dry-run"]
    for name, job in jobs.items():
        writes = {key for key, value in job["permissions"].items() if value == "write"}
        assert writes == (
            {"contents"}
            if name == "admission"
            else {"statuses"}
            if name == "result"
            else set()
        )
        assert job["permissions"].get("id-token") != "write"
        assert all(
            step["with"]["persist-credentials"] is False
            for step in job["steps"]
            if "checkout@" in step.get("uses", "")
        )

    secret_steps = [
        (name, step)
        for name, job in jobs.items()
        for step in job["steps"]
        if "${{ secrets." in json.dumps(step)
    ]
    assert len(secret_steps) == 1
    name, secret = secret_steps[0]
    assert name == "collect"
    assert secret["id"] == "capture"
    assert secret["if"] == "steps.recheck.outputs.approved == 'true'"
    assert set(secret["env"]) == {
        "LIVE_APPROVED_SHA",
        "LIVE_APPROVED_PR",
        "HOBEN_USER_GUID",
        "HOBEN_DEVICE_GUID",
    }
    assert secret["run"] == "python trusted/scripts/launch_live_ha_parity.py"

    assert not any(
        "upload-artifact@" in step.get("uses", "") for step in jobs["collect"]["steps"]
    )
    uploads = [
        step
        for step in jobs["publish"]["steps"]
        if "upload-artifact@" in step.get("uses", "")
    ]
    assert len(uploads) == 1
    assert uploads[0]["with"]["retention-days"] <= 7
    assert uploads[0]["with"]["path"] == (
        "${{ runner.temp }}/hoben-live-public/report.json"
    )
    assert "steps.publish.outputs.report" in uploads[0]["if"]
    assert jobs["publish"]["steps"][1]["env"]["PUBLIC_REPORT_B64"] == (
        "${{ needs.collect.outputs.report_b64 }}"
    )
    script = next(s for s in jobs["admission"]["steps"] if s.get("id") == "gate")
    assert "gate.refusalCategory(error)" in script["with"]["script"]
    assert (
        "core.setOutput('approved', 'true')"
        not in (script["with"]["script"].split("catch (error)", 1)[1])
    )
    assert "-a${{ github.run_attempt }}" in WORKFLOW.read_text()
    assert "github.triggering_actor" in jobs["dry-run"]["if"]
    assert "pr" in jobs["admission"]["outputs"]
    assert "workflow_dispatch" not in workflow.get("on", workflow.get(True))


@pytest.mark.parametrize(
    "suite", ["experimental-live-gate", "experimental-live-report"]
)
def test_node_live_offline_security_regressions(suite):
    assert shutil.which("node"), "Node required to test the Actions security gates"
    result = subprocess.run(
        ["node", "--test", f"tests/js/{suite}.test.cjs"],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-3000:]
