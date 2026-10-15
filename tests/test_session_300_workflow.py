"""Offline structural contracts of the new lane, plus Node gate regressions."""

import json
import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_dedicated_lane_has_exact_scope_and_one_secret_step():
    file = ROOT / ".github/workflows/hoben-session-300.yml"
    workflow = yaml.load(file.read_text(), Loader=yaml.BaseLoader)
    assert workflow["on"] == {"push": {"branches": ["experimental"]}}
    assert workflow["permissions"] == {}
    assert workflow["concurrency"]["group"] == "hoben-read-only-observation"
    assert workflow["concurrency"]["cancel-in-progress"] == "false"
    jobs = workflow["jobs"]
    assert set(jobs) == {
        "suite-installation",
        "dry-run",
        "admission",
        "collect",
        "publish",
        "result",
    }
    assert jobs["dry-run"]["needs"] == "suite-installation"
    assert jobs["admission"]["needs"] == "dry-run"
    assert jobs["collect"]["needs"] == "admission"
    assert jobs["collect"]["environment"] == "hoben-experimental"
    assert "github.run_attempt == 1" in jobs["dry-run"]["if"]
    secret_steps = []
    for name, job in jobs.items():
        assert job["permissions"].get("id-token") != "write"
        writes = {k for k, v in job["permissions"].items() if v == "write"}
        assert writes == (
            {"contents"}
            if name == "admission"
            else {"statuses"}
            if name == "result"
            else set()
        )
        if name != "collect":
            assert "environment" not in job
        for step in job["steps"]:
            if "uses" in step:
                assert re.search(r"@[0-9a-f]{40}$", step["uses"])
            if "checkout@" in step.get("uses", ""):
                assert step["with"]["persist-credentials"] == "false"
            if "${{ secrets." in json.dumps(step):
                secret_steps.append((name, step))
    assert len(secret_steps) == 1
    name, step = secret_steps[0]
    assert name == "collect"
    assert step["if"] == "steps.recheck.outputs.approved == 'true'"
    assert step["run"] == "python trusted/scripts/launch_session_300.py"
    assert set(k for k in step["env"] if k.startswith("HOBEN_")) == {
        "HOBEN_USER_GUID",
        "HOBEN_DEVICE_GUID",
    }
    assert not any(
        "upload-artifact" in s.get("uses", "") for s in jobs["collect"]["steps"]
    )
    assert jobs["publish"]["needs"] == ["admission", "collect"]
    assert "session-300-report.cjs" in json.dumps(jobs["publish"])
    assert "['continuous_300s','reconnected'].includes(report.result)" in json.dumps(
        jobs["result"]
    )


def test_uninstalled_suite_barrier_reports_both_not_run_before_all_live_jobs(tmp_path):
    workflow = yaml.load(
        (ROOT / ".github/workflows/hoben-session-300.yml").read_text(),
        Loader=yaml.BaseLoader,
    )
    job = workflow["jobs"]["suite-installation"]
    assert job["permissions"] == {} and "environment" not in job and "if" not in job
    assert len(job["steps"]) == 1 and "uses" not in job["steps"][0]
    summary = tmp_path / "summary"
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-c", job["steps"][0]["run"]],
        env={"GITHUB_STEP_SUMMARY": str(summary), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )
    assert result.returncode == 1
    assert summary.read_text().splitlines() == [
        "session-300: NOT RUN (suite_not_installed)",
        "session-reconnect-no-pong: NOT RUN (suite_not_installed)",
    ]
    # No always()/continue-on-error may bypass the failed prerequisite.
    assert "always(" not in workflow["jobs"]["dry-run"]["if"]
    assert "continue-on-error" not in json.dumps(job)


@pytest.mark.parametrize("suite", ["session-300-gate", "session-300-report"])
def test_node_safety_contracts(suite):
    result = subprocess.run(
        ["node", "--test", f"tests/js/{suite}.test.cjs"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-3000:]
