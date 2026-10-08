"""Execute the real main-only dispatch gate with offline GitHub API doubles."""

import copy
import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "Guillaume0385/ha-hoben-community"
SHA = "a" * 40
MAIN_SHA = "b" * 40
WORKFLOW_REF = (
    f"{REPOSITORY}/.github/workflows/opened-client-boundary.yml@refs/heads/main"
)
GATE = ROOT / ".github/scripts/opened-client-boundary-gate.cjs"
DRIVER = """
const input=JSON.parse(require('fs').readFileSync(0, 'utf8'));
const output={failed:[], outputs:{}, reads:0, logs:[]};
const core={setFailed:x=>output.failed.push(x),
 setOutput:(k,v)=>output.outputs[k]=v, info:x=>output.logs.push(x)};
const call=async data=>{output.reads++;if(input.api_error)throw Error('PRIVATE');
 return {data};};
const github={rest:{repos:{getBranch:()=>call(input.branch)},
 pulls:{get:()=>call(input.pr)}}};
require(input.gate)({github, context:input.context, core})
 .then(()=>process.stdout.write(JSON.stringify(output)))
 .catch(()=>process.exit(1));
"""


@pytest.fixture
def event():
    return {
        "context": {
            "eventName": "workflow_dispatch",
            "actor": "Guillaume0385",
            "ref": "refs/heads/main",
            "sha": MAIN_SHA,
            "repo": {"owner": "Guillaume0385", "repo": "ha-hoben-community"},
            "payload": {
                "sender": {"login": "Guillaume0385"},
                "inputs": {
                    "reviewed_sha": SHA,
                    "mode": "both",
                    "observation_seconds": "90",
                    "recipient_sha256": "c" * 64,
                },
            },
        },
        "branch": {"protected": True, "commit": {"sha": MAIN_SHA}},
        "pr": {
            "state": "open",
            "draft": True,
            "head": {
                "sha": SHA,
                "ref": "codex/issue-48",
                "repo": {"full_name": REPOSITORY},
            },
            "base": {"ref": "main", "repo": {"full_name": REPOSITORY}},
        },
    }


def execute(event, **env):
    result = subprocess.run(
        ["node", "-e", DRIVER],
        input=json.dumps({"gate": str(GATE), **event}),
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
        env={
            **os.environ,
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_TRIGGERING_ACTOR": "Guillaume0385",
            "GITHUB_WORKFLOW_REF": WORKFLOW_REF,
            **env,
        },
    )
    assert "PRIVATE" not in result.stdout + result.stderr
    return json.loads(result.stdout)


def test_exact_manager_dispatch_accepts_only_current_protected_main_and_pr(event):
    result = execute(event)
    assert not result["failed"] and result["reads"] == 2
    assert result["outputs"] == {
        "approved": "true",
        "sha": SHA,
        "mode": "both",
        "seconds": "90",
        "recipient": "c" * 64,
    }


@pytest.mark.parametrize(
    "path,value",
    [
        ("context.eventName", "pull_request"),
        ("context.eventName", "schedule"),
        ("context.ref", "refs/heads/unreviewed"),
        ("context.actor", "guillaume0385"),
        ("context.payload.sender.login", "other"),
        ("context.repo.owner", "fork"),
        ("context.payload.inputs.reviewed_sha", "main"),
        ("context.payload.inputs.reviewed_sha", "A" * 40),
        ("context.payload.inputs.mode", "H1; dump-secret"),
        ("context.payload.inputs.observation_seconds", "91"),
        ("context.payload.inputs.observation_seconds", "29"),
        ("context.payload.inputs.observation_seconds", "90junk"),
        ("context.payload.inputs.recipient_sha256", "private-input"),
        ("branch.protected", False),
        ("branch.commit.sha", "d" * 40),
        ("pr.head.sha", "d" * 40),
        ("pr.head.ref", "other"),
        ("pr.head.repo.full_name", "fork/repo"),
        ("pr.state", "closed"),
        ("pr.base.ref", "MAIN"),
        ("pr.base.repo.full_name", "fork/repo"),
    ],
)
def test_gate_rejects_stale_unsafe_or_unbounded_dispatch(event, path, value):
    changed = copy.deepcopy(event)
    item = changed
    keys = path.split(".")
    for key in keys[:-1]:
        item = item[key]
    item[keys[-1]] = value
    result = execute(changed)
    assert result["failed"] and not result["outputs"]


@pytest.mark.parametrize(
    "env",
    [
        {"GITHUB_RUN_ATTEMPT": "2"},
        {"GITHUB_TRIGGERING_ACTOR": "other"},
        {"GITHUB_WORKFLOW_REF": "candidate-workflow"},
    ],
)
def test_rerun_or_candidate_definition_cannot_authorize(event, env):
    result = execute(event, **env)
    assert result["reads"] == 0 and result["failed"]


def test_api_error_is_sanitized_and_fail_closed(event):
    result = execute({**event, "api_error": True})
    assert result["failed"] and not result["outputs"]


def test_workflow_has_manual_only_trigger_separate_gate_and_exact_exports():
    workflow = yaml.load(
        (ROOT / ".github/workflows/opened-client-boundary.yml").read_text(),
        Loader=yaml.BaseLoader,
    )
    assert set(workflow["on"]) == {"workflow_dispatch"}
    assert workflow["concurrency"]["cancel-in-progress"] == "false"
    jobs = workflow["jobs"]
    assert set(jobs) == {"manager-dispatch", "observations"}
    assert "environment" not in jobs["manager-dispatch"]
    assert jobs["observations"]["environment"] == "hoben-live"
    assert jobs["observations"]["needs"] == "manager-dispatch"
    assert all(
        permission == "read"
        for job in jobs.values()
        for permission in job["permissions"].values()
    )
    steps = jobs["observations"]["steps"]
    checkouts = [s for s in steps if s.get("uses", "").startswith("actions/checkout")]
    assert all(s["with"]["persist-credentials"] == "false" for s in checkouts)
    assert checkouts[0]["with"]["ref"] == "${{ github.sha }}"
    assert checkouts[1]["with"]["ref"] == "${{ needs.manager-dispatch.outputs.sha }}"
    probe = next(s for s in steps if "HOBEN_USER_GUID" in s.get("env", {}))
    assert "HOBEN_USER_GUID" not in jobs["observations"].get("env", {})
    assert "GITHUB_TOKEN" not in probe["env"]
    assert ">/dev/null 2>/dev/null" in probe["run"]
    assert "pip" not in probe["run"] and "tee" not in probe["run"]
    uploads = [
        s for s in steps if s.get("uses", "").startswith("actions/upload-artifact")
    ]
    assert [s["with"]["path"] for s in uploads] == [
        "${{ runner.temp }}/hoben-boundary-exports/captures.cms",
        "${{ runner.temp }}/hoben-boundary-exports/report.json",
    ]
    assert all(s["with"]["retention-days"] == "7" for s in uploads)
    assert not any("manager-live-hoben" in str(s) for s in steps)
