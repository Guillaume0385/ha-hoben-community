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
    assert set(jobs) == {"dry-run", "admission", "collect", "publish", "result"}
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
