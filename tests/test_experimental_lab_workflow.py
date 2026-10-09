"""Offline lane contracts: approval, isolation, lifecycle and export refusal."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from scripts import launch_experimental_boundary as launcher

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/hoben-experimental.yml"


def test_workflow_separates_admission_collection_and_publication():
    text = WORKFLOW.read_text()
    workflow = yaml.safe_load(text)
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
    assert set(jobs) == {"dry-run", "admission", "collect", "result"}
    assert jobs["admission"]["needs"] == "dry-run"
    assert jobs["collect"]["needs"] == "admission"
    assert jobs["collect"]["environment"] == "hoben-experimental"
    # REST environment and deployment branch policy reads require Actions:read.
    # This is a static permission contract, not proof the runner API responded.
    assert jobs["admission"]["permissions"]["actions"] == "read"
    assert jobs["collect"]["permissions"]["actions"] == "read"
    assert "environment" not in jobs["admission"]
    assert "needs.admission.outputs.approved == 'true'" in jobs["collect"]["if"]
    assert "environment" not in jobs["dry-run"]
    for name, job in jobs.items():
        permissions = job["permissions"]
        assert permissions.get("id-token") != "write"
        writes = {k for k, value in permissions.items() if value == "write"}
        assert writes == (
            {"contents"}
            if name == "admission"
            else {"statuses"}
            if name == "result"
            else set()
        )
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
    name, step = secret_steps[0]
    assert name == "collect" and step["id"] == "capture"
    assert step["if"] == "steps.recheck.outputs.approved == 'true'"
    assert set(step["env"]) == {
        "HOBEN_USER_GUID",
        "HOBEN_DEVICE_GUID",
        "EXPERIMENTAL_APPROVED_SHA",
    }
    assert step["run"] == "python trusted/scripts/launch_experimental_boundary.py"
    uploads = [
        s for s in jobs["collect"]["steps"] if "upload-artifact@" in s.get("uses", "")
    ]
    assert len(uploads) == 2
    for upload in uploads:
        assert upload["with"]["retention-days"] <= 7
        assert "always()" in upload["if"] and "steps.exports.outputs." in upload["if"]
        assert upload["with"]["path"] in {
            "${{ runner.temp }}/hoben-experimental-ciphertext/captures.cms",
            "${{ runner.temp }}/hoben-experimental-public/report.json",
        }
        assert "*" not in upload["with"]["path"]
    assert "candidate/scripts/probe" not in text
    assert "workflow_dispatch" not in workflow.get("on", workflow.get(True))
    assert "issues" not in workflow.get("on", workflow.get(True))


def test_admission_summary_uses_only_fixed_categorical_refusal():
    """A real API failure may contain private headers or URLs: never print it."""
    text = WORKFLOW.read_text()
    workflow = yaml.safe_load(text)
    steps = workflow["jobs"]["admission"]["steps"]
    gate = next(step for step in steps if step.get("id") == "gate")
    script = gate["with"]["script"]
    assert "gate.refusalCategory(error)" in script
    assert "category=" in script
    assert "core.setFailed" in script and "core.summary.addRaw" in script
    assert "core.setOutput('approved', 'true')" in script
    assert "error.message" not in script
    assert "error.stack" not in script
    assert "JSON.stringify(error)" not in script
    assert "core.info(error)" not in script
    # Refusal must not set approved=true in the catch path.
    refused = script.split("catch (error)", 1)[1]
    assert "core.setOutput('approved', 'true')" not in refused
    collect_condition = workflow["jobs"]["collect"]["if"]
    assert "needs.admission.outputs.approved == 'true'" in collect_condition


def test_actual_subprocess_cannot_inherit_tokens_or_output_commands(
    tmp_path, monkeypatch, capsys
):
    trusted, candidate = tmp_path / "trusted", tmp_path / "candidate"
    trusted.mkdir()
    scripts = candidate / "scripts"
    scripts.mkdir(parents=True)
    # This subprocess is an offline observer, never a network client.
    (scripts / "run_experimental_boundary.py").write_text(
        "import json, os, sys\n"
        "open('keys.json','w').write(json.dumps(sorted(os.environ)))\n"
        "print('SYNTHETIC_PRIVATE_OUTPUT')\n"
        "assert sys.argv[1:] == ['live']\n"
    )
    monkeypatch.setattr(launcher, "ROOT", trusted)
    for name in (
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "ACTIONS_RUNTIME_TOKEN",
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
        "ACTIONS_ID_TOKEN_REQUEST_URL",
        "GITHUB_OUTPUT",
        "GITHUB_ENV",
        "GITHUB_STEP_SUMMARY",
        "PYTHONPATH",
        "UNEXPECTED_SECRET",
    ):
        monkeypatch.setenv(name, "SYNTHETIC_PRIVATE_VALUE")
    monkeypatch.setenv("HOBEN_USER_GUID", "SYNTHETIC_PRIVATE_IDENTITY")
    assert launcher.main() == 0
    keys = set(json.loads((candidate / "keys.json").read_text()))
    assert keys <= set(launcher.ALLOWED) | {"PATH", "EXPERIMENTAL_PHASE", "LC_CTYPE"}
    assert "HOBEN_USER_GUID" in keys
    assert not capsys.readouterr().out
    assert os.environ["GITHUB_TOKEN"] == "SYNTHETIC_PRIVATE_VALUE"


@pytest.mark.parametrize("outcome", [1, "timeout", "cancel"])
def test_launcher_failure_never_becomes_success(monkeypatch, outcome):
    def run(*args, **kwargs):
        if outcome == "timeout":
            raise subprocess.TimeoutExpired("fixed", 1800)
        if outcome == "cancel":
            raise KeyboardInterrupt
        return subprocess.CompletedProcess(args[0], outcome)

    monkeypatch.setattr(launcher.subprocess, "run", run)
    assert launcher.main() == 1


def test_research_instrumentation_is_not_imported_into_the_runtime():
    for source in (ROOT / "custom_components/hoben").glob("*.py"):
        text = source.read_text()
        assert "scripts." not in text
        assert (
            "boundary_capture" not in text and "run_experimental_boundary" not in text
        )


@pytest.mark.parametrize(
    "suite", ["experimental-lab-gate", "experimental-exports", "experimental-handoff-check"]
)
def test_node_security_regressions(suite):
    assert shutil.which("node"), "Node.js is required for the GitHub gates"
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
