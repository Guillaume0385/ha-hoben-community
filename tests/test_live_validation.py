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


def _and_condition_matches(condition: str, context: dict[str, str]) -> bool:
    """Evaluate the equality/AND subset used by the two session job gates.

    Reject other grammar rather than ignoring new alternatives. GitHub string
    equality is case-insensitive. This does not validate remote environment policy.
    """
    clauses = []
    for term in condition.split("&&"):
        match = re.fullmatch(r"([a-z_.]+)\s*==\s*'([^']+)'", term.strip())
        assert match is not None, f"Unsupported condition term: {term}"
        key, expected = match.groups()
        clauses.append(context[key].casefold() == expected.casefold())
    return all(clauses)


def test_live_events_and_dispatch_choices(workflow) -> None:
    """No push, schedule, PR update or privileged pull_request_target runs live."""
    assert set(workflow["on"]) == {"workflow_dispatch", "pull_request"}
    assert workflow["on"]["pull_request"] == {"types": ["labeled"]}
    mode = workflow["on"]["workflow_dispatch"]["inputs"]["mode"]
    assert mode["type"] == "choice"
    assert mode["default"] == "tls-only"
    assert mode["options"] == ["tls-only", "session-open", "read-v4-state"]


def test_label_path_is_tls_only_without_environment_or_secrets(workflow) -> None:
    """Pin the event boundary: even a same-repo label cannot reach session-open."""
    jobs = workflow["jobs"]
    assert set(jobs) == {
        "live-validation",
        "live-session-negative",
        "session-open",
        "read-v4-state",
    }
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
    assert "--read-v4-state" not in tls_text
    assert "python scripts/probe_hoben_connection.py --tls-only" in tls_text


@pytest.mark.parametrize(
    ("event_name", "mode", "ref", "allowed"),
    [
        ("workflow_dispatch", "session-open", "refs/heads/main", True),
        ("workflow_dispatch", "session-open", "refs/heads/unreviewed", False),
        ("workflow_dispatch", "session-open", "refs/tags/main", False),
        ("pull_request", "session-open", "refs/pull/15/merge", False),
        ("pull_request", "session-open", "refs/heads/main", False),
        ("workflow_dispatch", "tls-only", "refs/heads/main", False),
        ("push", "session-open", "refs/heads/main", False),
    ],
    ids=[
        "manual-main",
        "manual-other-branch",
        "manual-tag-named-main",
        "pr-label",
        "pr-label-even-with-main-ref",
        "manual-tls-only",
        "push-main",
    ],
)
@pytest.mark.parametrize("job_mode", ["session-open", "read-v4-state"])
def test_session_open_requires_manual_main(
    workflow, event_name, mode, ref, allowed, job_mode
) -> None:
    """Both real modes reject labels, tags, other branches and automatic events."""
    mode = job_mode if mode == "session-open" else mode
    context = {
        "github.event_name": event_name,
        "inputs.mode": mode,
        "github.ref": ref,
    }
    assert _and_condition_matches(workflow["jobs"][job_mode]["if"], context) is allowed


@pytest.mark.parametrize(
    ("event_name", "action", "label", "allowed"),
    [
        ("pull_request", "labeled", "live-session-negative", True),
        ("pull_request", "labeled", "live-validation", False),
        ("pull_request", "labeled", "other", False),
        ("pull_request", "labeled", "live-session-negative-extra", False),
        ("pull_request", "synchronize", "live-session-negative", False),
        ("pull_request", "opened", "live-session-negative", False),
        ("pull_request", "unlabeled", "live-session-negative", False),
        ("workflow_dispatch", "labeled", "live-session-negative", False),
        ("push", "labeled", "live-session-negative", False),
    ],
)
def test_negative_requires_its_newly_added_label(
    workflow, event_name, action, label, allowed
) -> None:
    """Existing labels, commits, other labels and manual runs never opt in."""
    context = {
        "github.event_name": event_name,
        "github.event.action": action,
        "github.event.label.name": label,
    }
    condition = workflow["jobs"]["live-session-negative"]["if"]
    assert _and_condition_matches(condition, context) is allowed


def test_negative_job_has_no_secret_or_environment(workflow) -> None:
    """Execute PR-head code with no Hoben secret or protected environment binding."""
    job = workflow["jobs"]["live-session-negative"]
    assert "environment" not in job
    assert "env" not in workflow
    assert "env" not in job
    source = json.dumps(job)
    assert "secrets" not in source
    assert "hoben-live" not in source
    assert "HOBEN_DEVICE_GUID" not in source
    assert "HOBEN_USER_GUID" not in source
    assert "--read-v4-state" not in source
    steps = job["steps"]
    checkout = next(
        s for s in steps if s.get("uses", "").startswith("actions/checkout@")
    )
    assert checkout["with"]["ref"] == "${{ github.event.pull_request.head.sha }}"
    probe = next(s for s in steps if s.get("id") == "probe")
    assert "env" not in probe
    assert (
        "python scripts/probe_hoben_connection.py --session-negative | tee"
        in probe["run"]
    )


@pytest.mark.parametrize(
    ("job_mode", "cli_mode"),
    [("session-open", "--session"), ("read-v4-state", "--read-v4-state")],
)
def test_environment_and_only_user_secret(workflow, job_mode, cli_mode) -> None:
    """One environment secret is exposed only to the session probe step."""
    job = workflow["jobs"][job_mode]
    assert job["environment"] == "hoben-live"
    assert "env" not in job
    secret_steps = [step for step in job["steps"] if "secrets." in json.dumps(step)]
    assert len(secret_steps) == 1
    assert secret_steps[0]["id"] == "probe"
    assert secret_steps[0]["env"] == {
        "HOBEN_USER_GUID": "${{ secrets.HOBEN_USER_GUID }}"
    }
    assert cli_mode in secret_steps[0]["run"]
    secret_references = re.findall(r"secrets\.([A-Z_]+)", LIVE_PATH.read_text())
    assert secret_references == ["HOBEN_USER_GUID", "HOBEN_USER_GUID"]
    assert "HOBEN_DEVICE_GUID" not in LIVE_PATH.read_text()
    # The workflow only injects the secret as an environment input to Python.
    # No shell command/summary creates or interpolates the identifier.
    for step in job["steps"]:
        assert "HOBEN_USER_GUID" not in step.get("run", "")


@pytest.mark.parametrize("job_mode", ["session-open", "read-v4-state"])
def test_real_modes_cannot_select_each_other_or_any_pr_label(workflow, job_mode):
    """Only the exact manual input selects a real job, regardless of PR labels."""
    condition = workflow["jobs"][job_mode]["if"]
    for mode in ("tls-only", "session-open", "read-v4-state"):
        context = {
            "github.event_name": "workflow_dispatch",
            "inputs.mode": mode,
            "github.ref": "refs/heads/main",
        }
        assert _and_condition_matches(condition, context) is (mode == job_mode)
        for label in ("live-validation", "live-session-negative", "read-v4-state"):
            context.update(
                {
                    "github.event_name": "pull_request",
                    "github.event.action": "labeled",
                    "github.event.label.name": label,
                }
            )
            assert not _and_condition_matches(condition, context)


def test_minimal_permissions_python_and_sanitized_artifact(workflow) -> None:
    """All jobs use verified probe defaults and retain only their JSON report."""
    assert workflow["permissions"] == {"contents": "read"}
    for name, job in workflow["jobs"].items():
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
        filename = (
            "live-session-negative.json"
            if name == "live-session-negative"
            else "live-validation.json"
        )
        assert uploads[0]["with"]["path"] == "${{ runner.temp }}/" + filename


@pytest.mark.parametrize(
    ("job_name", "report", "outcome", "expected"),
    [
        ("live-validation", {"state": "tls_connected"}, "success", "success"),
        (
            "session-open",
            {"state": "opened", "profile": "unknown"},
            "success",
            "observed",
        ),
        (
            "session-open",
            {"state": "authorization_required", "message_type": 47},
            "success",
            "observed",
        ),
        (
            "session-open",
            {"state": "closed", "message_type": 5, "reason": "invalid_identifier"},
            "success",
            "observed",
        ),
        (
            "session-open",
            {"state": "error", "error": "invalid_session_inputs"},
            "failure",
            "failure",
        ),
        ("session-open", None, "skipped", "failure"),
        (
            "read-v4-state",
            {"state": "read", "profile": "v4", "registers": [65535] * 20},
            "success",
            "read",
        ),
        (
            "read-v4-state",
            {"state": "modbus_exception", "exception_code": 255},
            "failure",
            "failure",
        ),
        (
            "read-v4-state",
            {"state": "read_not_attempted", "error": "unsupported_profile"},
            "failure",
            "failure",
        ),
        ("read-v4-state", None, "skipped", "failure"),
        (
            "live-session-negative",
            {"state": "opened", "observation": "informative"},
            "success",
            "informative",
        ),
        (
            "live-session-negative",
            {
                "state": "error",
                "error": "unexpected_message_type",
                "message_type": 255,
                "observation": "informative",
            },
            "success",
            "informative",
        ),
        (
            "live-session-negative",
            {
                "state": "authorization_required",
                "message_type": 47,
                "observation": "informative",
            },
            "success",
            "informative",
        ),
        (
            "live-session-negative",
            {
                "state": "closed",
                "message_type": 5,
                "reason": "invalid_identifier",
                "observation": "informative",
            },
            "success",
            "informative",
        ),
        (
            "live-session-negative",
            {"state": "error", "error": "eof", "observation": "informative"},
            "success",
            "informative",
        ),
        (
            "live-session-negative",
            {"state": "error", "error": "timeout", "observation": "inconclusive"},
            "failure",
            "inconclusive",
        ),
        ("live-session-negative", None, "skipped", "inconclusive"),
    ],
)
def test_actual_summary_preserves_only_sanitized_probe_json(
    workflow, tmp_path, job_name, report, outcome, expected
) -> None:
    """Run the actual summary shell for observations, errors and missing output."""
    steps = workflow["jobs"][job_name]["steps"]
    summary = next(s for s in steps if s.get("name", "").startswith("Summarize"))
    assert summary["if"] == "${{ always() }}"
    negative = job_name == "live-session-negative"
    probe_path = tmp_path / (
        "live-session-negative.json" if negative else "live-validation.json"
    )
    summary_path = tmp_path / "summary.md"
    if report is not None:
        probe_path.write_text(json.dumps(report), encoding="utf-8")
    environment = os.environ | {
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_STEP_SUMMARY": str(summary_path),
        "PROBE_OUTCOME": outcome,
        "LIVE_MODE": {
            "live-validation": "tls-only",
            "session-open": "session-open",
            "live-session-negative": "session-negative",
            "read-v4-state": "read-v4-state",
        }[job_name],
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
    if job_name == "session-open":
        assert "no authentication code requested or sent" in rendered
    if job_name == "read-v4-state":
        assert "raw UInt16 registers without semantic interpretation" in rendered
    assert "SYNTHETIC-PRIVATE" not in rendered + result.stdout + result.stderr


def test_normal_validate_remains_offline() -> None:
    """Protocol/HA/HACS/Hassfest CI stays separate from live/secret validation."""
    source = (ROOT / ".github/workflows/validate.yml").read_text(encoding="utf-8")
    validate = yaml.load(source, Loader=yaml.BaseLoader)
    assert set(validate["jobs"]) == {"tests", "ha-tests", "hacs", "hassfest"}
    for job in validate["jobs"].values():
        assert "environment" not in job
    assert "secrets." not in source
    assert "probe_hoben_connection" not in source
    assert "myhoben.fr" not in source
    assert "python -m pytest" in source
    protocol_steps = validate["jobs"]["tests"]["steps"]
    ha_steps = validate["jobs"]["ha-tests"]["steps"]
    assert any(
        step.get("run") == "python -m pip install --group dev"
        for step in protocol_steps
    )
    assert any(
        step.get("run") == "python -m pip install --group ha-test" for step in ha_steps
    )
    assert any(
        step.get("run") == "python -m pytest -c ha_tests/pytest.ini ha_tests"
        for step in ha_steps
    )
    assert any(
        step.get("with", {}).get("python-version") == "3.14" for step in ha_steps
    )
