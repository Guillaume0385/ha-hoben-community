"""Run the installed phase-one script with offline GitHub API doubles."""

import copy
import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
FILE = ".github/workflows/hoben-manual.yml"
REPOSITORY = "Guillaume0385/ha-hoben-community"
SHA = "a" * 40
SCENARIOS = ["h1h2", "session-300", "session-reconnect"]


def workflow():
    return yaml.load((ROOT / FILE).read_text(), Loader=yaml.BaseLoader)


def fixture(scenario="all", branch="experimental"):
    context = {
        "eventName": "workflow_dispatch",
        "repo": {"owner": "Guillaume0385", "repo": "ha-hoben-community"},
        "actor": "Guillaume0385",
        "ref": f"refs/heads/{branch}",
        "sha": SHA,
        "runId": 123,
        "payload": {
            "repository": {"id": 1401398724, "full_name": REPOSITORY},
            "sender": {"login": "Guillaume0385", "id": 18246624, "type": "User"},
            "inputs": {"scenario": scenario},
        },
    }
    env = {
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_ACTOR": "Guillaume0385",
        "GITHUB_TRIGGERING_ACTOR": "Guillaume0385",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_REPOSITORY": REPOSITORY,
        "GITHUB_REF": context["ref"],
        "GITHUB_SHA": SHA,
        "GITHUB_WORKFLOW_SHA": SHA,
        "GITHUB_WORKFLOW_REF": f"{REPOSITORY}/{FILE}@{context['ref']}",
        "GITHUB_RUN_ID": "123",
    }
    return {
        "context": context,
        "env": env,
        "branch": {"protected": True, "commit": {"sha": SHA}},
        "run": {
            "id": 123,
            "event": "workflow_dispatch",
            "run_attempt": 1,
            "head_sha": SHA,
            "head_branch": branch,
            "path": FILE,
            "repository": copy.deepcopy(context["payload"]["repository"]),
            "actor": {"login": "Guillaume0385", "id": 18246624},
            "triggering_actor": {"login": "Guillaume0385", "id": 18246624},
        },
    }


def execute(case):
    payload = copy.deepcopy(case)
    payload["script"] = workflow()["jobs"]["preflight"]["steps"][0]["with"]["script"]
    result = subprocess.run(
        [
            "node",
            "-e",
            """
const p=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
Object.assign(process.env,p.env);
const errors=[],tables=[],messages=[],calls=[];
const summary={addHeading:()=>summary,addRaw:s=>{messages.push(s);return summary;},
  addTable:t=>{tables.push(t);return summary;},write:async()=>{}};
const core={summary,setFailed:s=>errors.push(s),
  setOutput:()=>{throw Error('unexpected_output');}};
const github={rest:{repos:{getBranch:async q=>{
  calls.push(['branch',q]);if(p.apiError)throw Error('PRIVATE_API_EXCEPTION');
  return {data:p.branch};
}},actions:{getWorkflowRun:async q=>{calls.push(['run',q]);return {data:p.run};}}}};
(async()=>{await new (Object.getPrototypeOf(async function(){}).constructor)(
  'github','context','core',p.script)(github,p.context,core);
  process.stdout.write(JSON.stringify({errors,tables,messages,calls}));
})().catch(()=>process.exit(1));
""",
        ],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        timeout=5,
        check=True,
        env={
            key: value
            for key, value in os.environ.items()
            if key not in fixture()["env"]
        },
    )
    assert result.stderr == "" and "PRIVATE" not in result.stdout
    return json.loads(result.stdout)


def test_only_manual_hoben_entry_remains_and_ci_release_are_preserved():
    paths = {p.name for p in (ROOT / ".github/workflows").glob("*.yml")}
    assert paths == {"hoben-manual.yml", "validate.yml", "publish-release.yml"}
    config = workflow()
    assert set(config["on"]) == {"workflow_dispatch"}
    assert set(config["on"]["workflow_dispatch"]["inputs"]) == {"scenario"}
    choice = config["on"]["workflow_dispatch"]["inputs"]["scenario"]
    assert choice["type"] == "choice" and choice["required"] == "true"
    assert choice["options"] == SCENARIOS + ["all"]
    assert config["permissions"] == {}
    assert config["concurrency"] == {
        "group": "hoben-read-only-observation",
        "cancel-in-progress": "false",
        "queue": "max",
    }
    assert set(config["jobs"]) == {"preflight"}
    job = config["jobs"]["preflight"]
    assert job["timeout-minutes"] == "5"
    assert job["permissions"] == {"contents": "read", "actions": "read"}
    assert "environment" not in job and "outputs" not in job
    assert len(job["steps"]) == 1
    assert (
        job["steps"][0]["uses"]
        == "actions/github-script@ed597411d8f924073f98dfc5c65a23a2325f34cd"
    )
    assert not {"run", "env"} & job["steps"][0].keys()
    assert "secrets." not in (ROOT / FILE).read_text()
    ci = yaml.load(
        (ROOT / ".github/workflows/validate.yml").read_text(), Loader=yaml.BaseLoader
    )
    assert "pull_request" in ci["on"]
    assert set(ci["jobs"]) == {"tests", "ha-tests", "hacs", "hassfest"}
    for path in (ROOT / "tests/fixtures/retired_workflows").glob("*.yml"):
        assert path.parent != ROOT / ".github/workflows"


@pytest.mark.parametrize("scenario", SCENARIOS + ["all"])
@pytest.mark.parametrize("branch", ["main", "experimental"])
def test_every_choice_is_explicitly_not_run_until_phase_two(scenario, branch):
    result = execute(fixture(scenario, branch))
    reason = (
        "branch_not_activated"
        if branch == "main"
        else "experimental_runtime_not_installed"
    )
    assert result["errors"] == [f"NOT RUN: {reason}"]
    assert len(result["calls"]) == (0 if branch == "main" else 2)
    rows = result["tables"][0][1:]
    assert [row[0] for row in rows] == SCENARIOS
    assert all(row[1] == "NOT RUN" for row in rows)
    assert [row[0] for row in rows if row[2] == "demandé"] == (
        SCENARIOS if scenario == "all" else [scenario]
    )


@pytest.mark.parametrize(
    "event", ["push", "pull_request", "pull_request_target", "workflow_run", "schedule"]
)
def test_non_manual_context_never_reaches_any_api(event):
    case = fixture()
    case["context"]["eventName"] = event
    case["env"]["GITHUB_EVENT_NAME"] = event
    result = execute(case)
    assert result["errors"] == ["NOT RUN: invalid_dispatch"] and not result["calls"]


@pytest.mark.parametrize("key", list(fixture()["env"]))
def test_missing_or_forged_environment_provenance_refuses_before_any_api(key):
    for replacement in (None, "PRIVATE_UNTRUSTED"):
        case = fixture()
        if replacement is None:
            del case["env"][key]
        else:
            case["env"][key] = replacement
        result = execute(case)
        assert result["errors"][0].startswith("NOT RUN: ") and not result["calls"]


@pytest.mark.parametrize("attempt", ["2", "50", "01", "0"])
def test_rerun_always_requires_a_new_manual_dispatch(attempt):
    case = fixture()
    case["env"]["GITHUB_RUN_ATTEMPT"] = attempt
    result = execute(case)
    assert result["errors"] == ["NOT RUN: invalid_dispatch"] and not result["calls"]


@pytest.mark.parametrize(
    "inputs", [{}, {"scenario": "PRIVATE"}, {"scenario": "all", "ref": "main"}]
)
def test_unknown_input_or_arbitrary_ref_is_not_a_branch_selector(inputs):
    case = fixture()
    case["context"]["payload"]["inputs"] = inputs
    result = execute(case)
    assert result["errors"] == ["NOT RUN: invalid_dispatch"] and not result["calls"]


@pytest.mark.parametrize(
    "mutation",
    [
        "actor_id",
        "triggering_actor",
        "head_sha",
        "event",
        "path",
        "repository",
        "attempt",
        "branch",
        "unprotected",
        "moved",
        "api",
    ],
)
def test_current_run_and_protected_head_proof_cannot_activate_the_placeholder(mutation):
    case = fixture()
    if mutation == "actor_id":
        case["run"]["actor"]["id"] = 1
    elif mutation == "triggering_actor":
        case["run"]["triggering_actor"]["login"] = "other"
    elif mutation == "head_sha":
        case["run"]["head_sha"] = "b" * 40
    elif mutation == "event":
        case["run"]["event"] = "push"
    elif mutation == "path":
        case["run"]["path"] = ".github/workflows/other.yml"
    elif mutation == "repository":
        case["run"]["repository"]["id"] = 1
    elif mutation == "attempt":
        case["run"]["run_attempt"] = 2
    elif mutation == "branch":
        case["run"]["head_branch"] = "main"
    elif mutation == "unprotected":
        case["branch"]["protected"] = False
    elif mutation == "moved":
        case["branch"]["commit"]["sha"] = "b" * 40
    else:
        case["apiError"] = True
    result = execute(case)
    reason = "provenance_unavailable" if mutation == "api" else "provenance_unverified"
    assert result["errors"] == [f"NOT RUN: {reason}"]
    assert all(row[1] == "NOT RUN" for row in result["tables"][0][1:])


@pytest.mark.parametrize(
    "ref", ["refs/tags/experimental", "refs/heads/other", "refs/pull/119/merge"]
)
def test_native_selector_cannot_activate_another_branch_or_tag(ref):
    case = fixture()
    case["context"]["ref"] = case["env"]["GITHUB_REF"] = ref
    case["env"]["GITHUB_WORKFLOW_REF"] = f"{REPOSITORY}/{FILE}@{ref}"
    result = execute(case)
    assert result["errors"] == ["NOT RUN: branch_not_activated"] and not result["calls"]


@pytest.mark.parametrize(
    "mutation",
    [
        "actor",
        "sender_id",
        "sender_login",
        "sender_type",
        "repository",
        "run_id",
        "sha",
    ],
)
def test_immutable_dispatch_identity_must_match(mutation):
    case = fixture()
    context = case["context"]
    if mutation == "actor":
        context["actor"] = "other"
    elif mutation == "sender_id":
        context["payload"]["sender"]["id"] = 1
    elif mutation == "sender_login":
        context["payload"]["sender"]["login"] = "other"
    elif mutation == "sender_type":
        context["payload"]["sender"]["type"] = "Bot"
    elif mutation == "repository":
        context["payload"]["repository"]["id"] = 1
    elif mutation == "run_id":
        context["runId"] = 0
    else:
        context["sha"] = "PRIVATE"
    result = execute(case)
    assert result["errors"] == ["NOT RUN: invalid_dispatch"] and not result["calls"]
