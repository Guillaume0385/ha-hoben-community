"""Offline contract for the experimental-only, secretless push preflight."""

import shutil
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github/workflows/experimental-manager-preflight.yml"
GATE_PATH = ROOT / ".github/scripts/experimental-push-preflight.cjs"


def test_preflight_is_push_only_without_any_secret_or_live_job():
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    config = yaml.safe_load(text)
    events = config.get("on", config.get(True))
    assert set(events) == {"push"}
    assert events["push"] == {"branches": ["experimental"]}
    assert set(config["jobs"]) == {"dry-run"}
    assert config["permissions"] == {}
    job = config["jobs"]["dry-run"]
    assert job["strategy"]["matrix"]["scenario"] == [
        "hoben-live",
        "hoben-experimental",
    ]
    assert job["permissions"] == {"contents": "read", "pull-requests": "read"}
    assert config["concurrency"]["cancel-in-progress"] is False
    assert "github.run_attempt == 1" in job["if"]
    assert "github.actor == 'Guillaume0385'" in job["if"]
    assert "github.sha" in text
    for forbidden in (
        "secrets.",
        "environment:",
        "HOBEN_USER_GUID",
        "HOBEN_DEVICE_GUID",
        "upload-artifact",
        "curl ",
        "probe_hoben_",
        "run_experimental_boundary",
        "workflow_dispatch",
        "pull_request_target",
        "issues:",
    ):
        assert forbidden not in text
    assert GATE_PATH.is_file()
    assert "module.exports" in GATE_PATH.read_text(encoding="utf-8")


def test_preflight_node_regressions():
    assert shutil.which("node"), "Node.js is required for the GitHub-script gate"
    result = subprocess.run(
        ["node", "--test", "tests/js/experimental-push-preflight.test.cjs"],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout[-2500:] + result.stderr[-2500:]
