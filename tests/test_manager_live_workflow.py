"""Execute the trusted workflow gates/status scripts with offline GitHub doubles."""

import copy
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github/workflows/manager-live-hoben.yml"
REPOSITORY = "Guillaume0385/ha-hoben-community"
SHA = "a" * 40
NEW_SHA = "b" * 40
LABEL = "manager-live-hoben"

# Execute the actual inline JavaScript, not a Python copy of its decisions.
# No network client, action dependency, candidate code or credential is loaded.
NODE_DRIVER = r"""
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const output = {statuses: [], failed: [], outputs: {}, logs: [], reads: 0};
const core = {
  setFailed: value => output.failed.push(value),
  setOutput: (key, value) => output.outputs[key] = value,
  info: value => output.logs.push(value)
};
const github = {rest: {
  pulls: {get: async args => {
    output.reads++;
    if (input.get_error) throw new Error('PRIVATE-API-ERROR');
    return {data: input.current};
  }},
  repos: {createCommitStatus: async args => {
    if (input.status_error) throw new Error('PRIVATE-API-ERROR');
    output.statuses.push(args);
  }}
}};
const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;
const run = new AsyncFunction('github', 'context', 'core', input.script);
run(github, input.context, core)
  .then(() => process.stdout.write(JSON.stringify(output)))
  .catch(() => {
    process.stderr.write('Unhandled workflow script failure'); process.exit(1);
  });
"""


@pytest.fixture
def workflow():
    """BaseLoader preserves `on`, boolean expressions and action inputs as text."""
    return yaml.load(WORKFLOW_PATH.read_text(), Loader=yaml.BaseLoader)


@pytest.fixture
def context():
    """A single owner label event on a reviewed, same-repository main PR."""
    pr = {
        "number": 19,
        "state": "open",
        "draft": False,
        "base": {"ref": "main", "repo": {"full_name": REPOSITORY}},
        "head": {"sha": SHA, "repo": {"full_name": REPOSITORY}},
        "labels": [{"name": LABEL}],
    }
    return {
        "eventName": "pull_request_target",
        "actor": "Guillaume0385",
        "ref": "refs/heads/main",
        "repo": {"owner": "Guillaume0385", "repo": "ha-hoben-community"},
        "serverUrl": "https://github.com",
        "runId": 123,
        "payload": {
            "action": "labeled",
            "label": {"name": LABEL},
            "sender": {"login": "Guillaume0385"},
            "pull_request": pr,
        },
    }


def execute_script(workflow, context, job, *, current=None, env=None, **failures):
    """Run a real workflow script with only synthetic inputs and stub REST calls."""
    node = shutil.which("node")
    assert node is not None, "Node.js is required for offline workflow security tests"
    step = next(
        s for s in workflow["jobs"][job]["steps"] if "script" in s.get("with", {})
    )
    result = subprocess.run(
        [node, "-e", NODE_DRIVER],
        input=json.dumps(
            {
                "script": step["with"]["script"],
                "context": context,
                "current": current or context["payload"]["pull_request"],
                **failures,
            }
        ),
        env={
            "GITHUB_TRIGGERING_ACTOR": "Guillaume0385",
            "GITHUB_RUN_ATTEMPT": "1",
            **(env or {}),
        },
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert "PRIVATE" not in result.stdout + result.stderr
    return json.loads(result.stdout)


def change(value, path, replacement):
    """Change a nested synthetic event field without reimplementing the gate."""
    for key in path.split(".")[:-1]:
        value = value[key]
    value[path.split(".")[-1]] = replacement


def test_only_trusted_labeled_event_and_all_job_guards(workflow):
    """No creation, commit, schedule, dispatch or fork automatically runs live."""
    assert workflow["on"] == {"pull_request_target": {"types": ["labeled"]}}
    gate = workflow["jobs"]["manager-approval"]
    assert " ".join(gate["if"].split()) == (
        "github.event_name == 'pull_request_target' && "
        "github.event.action == 'labeled' && "
        "github.event.pull_request.base.ref == 'main' && "
        "github.event.pull_request.draft == false && "
        "github.event.pull_request.head.repo.full_name == "
        "'Guillaume0385/ha-hoben-community' && "
        "github.event.label.name == 'manager-live-hoben' && "
        "github.actor == 'Guillaume0385'"
    )
    assert gate["outputs"] == {"approved": "${{ steps.gate.outputs.approved }}"}
    live = workflow["jobs"]["live-probe"]
    assert live["needs"] == "manager-approval"
    assert live["if"] == "needs.manager-approval.outputs.approved == 'true'"
    assert workflow["concurrency"]["cancel-in-progress"] == "false"


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        *[
            ("eventName", event)
            for event in ("pull_request", "push", "schedule", "workflow_dispatch")
        ],
        *[
            ("payload.action", action)
            for action in ("opened", "synchronize", "reopened", "unlabeled")
        ],
        ("payload.label.name", "other"),
        ("payload.label.name", "manager-live-hoben-extra"),
        ("payload.label.name", "MANAGER-LIVE-HOBEN"),
        ("actor", "someone-else"),
        ("actor", "guillaume0385"),
        ("payload.sender.login", "someone-else"),
        ("ref", "refs/heads/unreviewed"),
        ("ref", "refs/tags/main"),
        ("payload.pull_request.base.ref", "other"),
        ("payload.pull_request.base.ref", "MAIN"),
        ("payload.pull_request.base.repo.full_name", "fork/ha-hoben-community"),
        ("payload.pull_request.draft", True),
        ("payload.pull_request.state", "closed"),
        ("payload.pull_request.head.repo.full_name", "fork/ha-hoben-community"),
        ("payload.pull_request.head.repo.full_name", REPOSITORY.lower()),
        ("payload.pull_request.head.repo", None),
        ("payload.pull_request.head.sha", "main"),
        ("repo.owner", "fork"),
    ],
)
def test_gate_rejects_every_non_manager_event(workflow, context, path, replacement):
    """Strict checks also reject case variants that GitHub's == would accept."""
    change(context, path, replacement)
    result = execute_script(workflow, context, "manager-approval")
    assert result["failed"]
    assert result["outputs"] == {}
    assert result["statuses"] == []
    assert result["reads"] == 0


@pytest.mark.parametrize(
    "env", [{"GITHUB_RUN_ATTEMPT": "2"}, {"GITHUB_TRIGGERING_ACTOR": "other"}]
)
def test_reruns_need_a_fresh_manager_label_event(workflow, context, env):
    """GitHub's rerun UI cannot reuse the old label event to release a secret."""
    result = execute_script(workflow, context, "manager-approval", env=env)
    assert result["failed"] and not result["outputs"] and not result["statuses"]


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        ("head.sha", NEW_SHA),
        ("head.repo.full_name", "fork/ha-hoben-community"),
        ("base.ref", "other"),
        ("base.repo.full_name", "fork/ha-hoben-community"),
        ("draft", True),
        ("state", "closed"),
        ("labels", []),
        ("labels", [{"name": "MANAGER-LIVE-HOBEN"}]),
    ],
)
def test_queued_approval_cannot_authorize_changed_pr(
    workflow, context, path, replacement
):
    """Re-fetch the PR before pending or secret release; never switch to its new SHA."""
    current = copy.deepcopy(context["payload"]["pull_request"])
    change(current, path, replacement)
    result = execute_script(workflow, context, "manager-approval", current=current)
    assert result["reads"] == 1
    assert result["failed"] and not result["outputs"] and not result["statuses"]


def test_approved_event_publishes_pending_on_exact_sha(workflow, context):
    result = execute_script(workflow, context, "manager-approval")
    assert result["failed"] == []
    assert result["outputs"] == {"approved": "true"}
    assert result["statuses"] == [
        {
            "owner": "Guillaume0385",
            "repo": "ha-hoben-community",
            "sha": SHA,
            "state": "pending",
            "context": "live-hoben-authenticated",
            "description": (
                "MANAGER-approved authenticated read-only validation started"
            ),
            "target_url": f"https://github.com/{REPOSITORY}/actions/runs/123",
        }
    ]
    assert SHA in " ".join(result["logs"])


@pytest.mark.parametrize("failure", ["get_error", "status_error"])
def test_api_failure_never_releases_live_job(workflow, context, failure):
    result = execute_script(workflow, context, "manager-approval", **{failure: True})
    assert result["failed"] and not result["outputs"] and not result["statuses"]


def test_candidate_has_only_one_secret_step_and_no_status_token(workflow):
    """Fresh runners separate trusted status tokens from candidate execution."""
    assert workflow["permissions"] == {"contents": "read"}
    assert "env" not in workflow
    jobs = workflow["jobs"]
    live = jobs["live-probe"]
    assert live["environment"] == "hoben-live"
    assert live["permissions"] == {"contents": "read"}
    assert "env" not in live
    checkout = live["steps"][0]
    assert checkout["uses"].startswith("actions/checkout@")
    assert checkout["with"] == {
        "repository": REPOSITORY,
        "ref": "${{ github.event.pull_request.head.sha }}",
        "persist-credentials": "false",
    }
    secret_steps = [s for s in live["steps"] if "secrets." in json.dumps(s)]
    assert len(secret_steps) == 1
    probe = secret_steps[0]
    assert probe["id"] == "probe"
    assert probe["env"] == {"HOBEN_USER_GUID": "${{ secrets.HOBEN_USER_GUID }}"}
    commands = [
        line.strip()
        for line in probe["run"].splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert commands == [
        "python scripts/probe_hoben_connection.py --live-premerge | tee "
        '"$RUNNER_TEMP/live-hoben-authenticated.json"'
    ]
    assert re.findall(r"secrets\.([A-Z_]+)", WORKFLOW_PATH.read_text()) == [
        "HOBEN_USER_GUID"
    ]
    live_source = json.dumps(live)
    for forbidden in (
        "github.token",
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "pip install",
        "--host",
        "--function",
        "--register",
        "inputs.",
    ):
        assert forbidden not in live_source
    for job in ("manager-approval", "candidate-status"):
        source = json.dumps(jobs[job])
        assert "statuses" in jobs[job]["permissions"]
        assert "environment" not in jobs[job]
        assert "secrets." not in source
        assert "checkout@" not in source
    assert jobs["manager-approval"]["permissions"] == {
        "contents": "read",
        "pull-requests": "read",
        "statuses": "write",
    }
    assert jobs["candidate-status"]["permissions"] == {
        "contents": "read",
        "statuses": "write",
    }


@pytest.mark.parametrize(
    ("job_result", "probe_outcome", "expected"),
    [
        ("success", "success", "success"),
        ("failure", "success", "failure"),
        ("success", "failure", "failure"),
        ("failure", "failure", "failure"),
        ("cancelled", "success", "failure"),
        ("skipped", "", "failure"),
        ("success", "skipped", "failure"),
    ],
)
@pytest.mark.parametrize("sha", [SHA, NEW_SHA])
def test_final_status_never_applies_to_base_or_another_commit(
    workflow, context, job_result, probe_outcome, expected, sha
):
    """Status state derives from the job and actual step, always on event HEAD."""
    context["payload"]["pull_request"]["head"]["sha"] = sha
    result = execute_script(
        workflow,
        context,
        "candidate-status",
        env={"LIVE_RESULT": job_result, "PROBE_OUTCOME": probe_outcome},
    )
    assert result["failed"] == []
    assert len(result["statuses"]) == 1
    status = result["statuses"][0]
    assert (status["sha"], status["state"], status["context"]) == (
        sha,
        expected,
        "live-hoben-authenticated",
    )
    assert sha in " ".join(result["logs"])


def test_final_api_failure_is_not_reported_as_success(workflow, context):
    result = execute_script(
        workflow,
        context,
        "candidate-status",
        status_error=True,
        env={"LIVE_RESULT": "success", "PROBE_OUTCOME": "success"},
    )
    assert result["failed"] and not result["statuses"]


def test_always_publish_failure_after_approved_probe_failure(workflow):
    job = workflow["jobs"]["candidate-status"]
    assert job["needs"] == ["manager-approval", "live-probe"]
    assert (
        job["if"]
        == "${{ always() && needs.manager-approval.outputs.approved == 'true' }}"
    )
    step = job["steps"][0]
    assert step["env"] == {
        "LIVE_RESULT": "${{ needs.live-probe.result }}",
        "PROBE_OUTCOME": "${{ needs.live-probe.outputs.probe-outcome }}",
    }


@pytest.mark.parametrize("outcome", ["success", "failure", "skipped"])
def test_actual_summary_records_candidate_sha_and_sanitized_json(
    workflow, tmp_path, outcome
):
    """Exercise the actual trusted shell summary without identifiers or tokens."""
    summary = next(
        s
        for s in workflow["jobs"]["live-probe"]["steps"]
        if s.get("name", "").startswith("Summarize")
    )
    report = {
        "state": "client_refresh_validated",
        "profile": "v4",
        "register_count": 20,
        "refresh_count": 2,
        "device_guid_reuse": "validated",
    }
    (tmp_path / "live-hoben-authenticated.json").write_text(json.dumps(report))
    summary_path = tmp_path / "summary.md"
    result = subprocess.run(
        ["bash", "-eo", "pipefail", "-c", summary["run"]],
        env=os.environ
        | {
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_STEP_SUMMARY": str(summary_path),
            "CANDIDATE_SHA": SHA,
            "PROBE_OUTCOME": outcome,
            "HOBEN_USER_GUID": "PRIVATE-USER",
            "GITHUB_TOKEN": "PRIVATE-TOKEN",
        },
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    rendered = summary_path.read_text()
    assert SHA in rendered and json.dumps(report) in rendered
    assert "Two HobenClient refreshes with assigned DeviceGuid reuse" in rendered
    assert f"Result: {'success' if outcome == 'success' else 'failure'}" in rendered
    assert "PRIVATE" not in rendered + result.stdout + result.stderr
