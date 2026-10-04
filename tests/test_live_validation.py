"""Offline checks of live-workflow isolation and the actual summary shell steps."""

import json
import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
LIVE_PATH = ROOT / ".github/workflows/live-validation.yml"


@pytest.fixture
def workflow():
    """BaseLoader preserves GitHub's `on` key instead of YAML 1.1 booleans."""
    return yaml.load(LIVE_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def test_live_events_and_dispatch_choices(workflow) -> None:
    """No push, schedule, PR update or privileged pull_request_target runs live."""
    assert set(workflow["on"]) == {"workflow_dispatch", "pull_request"}
    assert workflow["on"]["pull_request"] == {"types": ["labeled"]}
    mode = workflow["on"]["workflow_dispatch"]["inputs"]["mode"]
    assert mode["type"] == "choice"
    assert mode["default"] == "tls-only"
    assert mode["options"] == ["tls-only", "session-open"]


def test_label_path_is_tls_only_without_environment_or_secrets(workflow) -> None:
    """Pin the event boundary: even a same-repo label cannot reach session-open."""
    jobs = workflow["jobs"]
    assert set(jobs) == {"live-validation", "session-open"}
    tls = jobs["live-validation"]
    assert " ".join(tls["if"].split()) == (
        "(github.event_name == 'workflow_dispatch' && inputs.mode == 'tls-only') || "
        "(github.event_name == 'pull_request' && "
        "github.event.action == 'labeled' && "
        "github.event.label.name == 'live-validation')"
    )
    assert tls["env"]["LIVE_MODE"] == "tls-only"
    assert "environment" not in tls
    tls_text = json.dumps(tls)
    assert "secrets." not in tls_text
    assert "--session" not in tls_text
    assert "python scripts/probe_hoben_connection.py --tls-only" in tls_text
    assert jobs["session-open"]["if"] == (
        "github.event_name == 'workflow_dispatch' && inputs.mode == 'session-open'"
    )


def test_environment_and_only_device_secret(workflow) -> None:
    """One environment secret is exposed only to the session probe step."""
    job = workflow["jobs"]["session-open"]
    assert job["environment"] == "hoben-live"
    assert "env" not in job
    secret_steps = [step for step in job["steps"] if "secrets." in json.dumps(step)]
    assert len(secret_steps) == 1
    assert secret_steps[0]["id"] == "probe"
    assert secret_steps[0]["env"] == {
        "HOBEN_DEVICE_GUID": "${{ secrets.HOBEN_DEVICE_GUID }}"
    }
    assert "--session" in secret_steps[0]["run"]
    secret_references = re.findall(r"secrets\.([A-Z_]+)", LIVE_PATH.read_text())
    assert secret_references == ["HOBEN_DEVICE_GUID"]


def test_minimal_permissions_python_and_sanitized_artifact(workflow) -> None:
    """Both jobs use verified probe defaults and retain only its JSON report."""
    assert workflow["permissions"] == {"contents": "read"}
    for job in workflow["jobs"].values():
        assert "permissions" not in job
        assert job["runs-on"] == "ubuntu-latest"
        assert job["timeout-minutes"] == "5"
        assert job["defaults"]["run"]["shell"] == "bash"
        steps = job["steps"]
        checkout = next(
            s for s in steps if s.get("uses", "").startswith("actions/checkout@")
        )
        assert checkout["with"]["persist-credentials"] == "false"
        python = next(
            s for s in steps if s.get("uses", "").startswith("actions/setup-python@")
        )
        assert python["with"]["python-version"] == "3.12"
        uploads = [
            s for s in steps if s.get("uses", "").startswith("actions/upload-artifact@")
        ]
        assert len(uploads) == 1
        assert uploads[0]["if"] == "${{ always() }}"
        assert uploads[0]["with"]["path"] == "${{ runner.temp }}/live-validation.json"


@pytest.mark.parametrize(
    ("job_name", "report", "outcome", "expected"),
    [
        ("live-validation", {"state": "tls_connected"}, "success", "success"),
        (
            "session-open",
            {"state": "opened", "profile": "unknown"},
            "success",
            "success",
        ),
        (
            "session-open",
            {"state": "blocked", "error": "user_guid_unresolved"},
            "failure",
            "BLOCKED",
        ),
        (
            "session-open",
            {"state": "error", "error": "invalid_session_inputs"},
            "failure",
            "failure",
        ),
        ("session-open", None, "skipped", "failure"),
    ],
)
def test_actual_summary_preserves_only_sanitized_probe_json(
    workflow, tmp_path, job_name, report, outcome, expected
) -> None:
    """Run the real summary shell, including the distinct BLOCKED warning."""
    steps = workflow["jobs"][job_name]["steps"]
    summary = next(s for s in steps if s.get("name", "").startswith("Summarize"))
    assert summary["if"] == "${{ always() }}"
    probe_path = tmp_path / "live-validation.json"
    summary_path = tmp_path / "summary.md"
    if report is not None:
        probe_path.write_text(json.dumps(report), encoding="utf-8")
    environment = os.environ | {
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_STEP_SUMMARY": str(summary_path),
        "PROBE_OUTCOME": outcome,
        "LIVE_MODE": "tls-only" if job_name == "live-validation" else "session-open",
        "HOBEN_DEVICE_GUID": "SYNTHETIC-PRIVATE-DEVICE",
        "HOBEN_USER_GUID": "SYNTHETIC-PRIVATE-USER",
    }
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", summary["run"]],
        env=environment,
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )
    rendered = summary_path.read_text(encoding="utf-8")
    assert f"Result: {expected}" in rendered
    assert f"Mode: {environment['LIVE_MODE']}" in rendered
    assert "Endpoint: myhoben.fr:465" in rendered
    if report is not None:
        assert json.dumps(report) in rendered
    if expected == "BLOCKED":
        assert "::warning::BLOCKED: user_guid_unresolved" in result.stdout
    assert "SYNTHETIC-PRIVATE" not in rendered + result.stdout + result.stderr


def test_normal_validate_remains_offline() -> None:
    """Normal PR CI keeps tests/HACS/Hassfest, without live jobs or secret access."""
    source = (ROOT / ".github/workflows/validate.yml").read_text(encoding="utf-8")
    validate = yaml.load(source, Loader=yaml.BaseLoader)
    assert set(validate["jobs"]) == {"tests", "hacs", "hassfest"}
    for job in validate["jobs"].values():
        assert "environment" not in job
    assert "secrets." not in source
    assert "probe_hoben_connection" not in source
    assert "myhoben.fr" not in source
    assert "python -m pytest" in source
