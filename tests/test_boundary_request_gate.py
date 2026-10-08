"""Exercise the real trusted label gate against paginated offline GitHub APIs."""

import copy
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
REPO = "Guillaume0385/ha-hoben-community"
WORKFLOW = ".github/workflows/hoben-boundary-request.yml"
MAIN = "a" * 40
POLICY = json.loads((ROOT / ".github/config/hoben-boundary.json").read_text())
SHA = POLICY["candidate_sha"]
DRIVER = r"""
const input=JSON.parse(require('fs').readFileSync(0,'utf8'));
const actualNow=Date.now;
Date.now=()=> input.now ?? Date.parse('2026-10-09T00:00:00Z');
const calls=[], writes=[], claims=input.claims || {};
const invoke=async(name,args,data)=>{
 calls.push({name,args});
 if(input.error_at===name)throw Error('PRIVATE_TOKEN PRIVATE_PACKET');
 return {data};
};
const page=(array,args)=>array.slice(((args.page||1)-1)*100,(args.page||1)*100);
const github={rest:{
 repos:{get:a=>invoke('repository',a,input.repository),
  getBranch:a=>invoke('branch',a,input.branch),
  getEnvironment:a=>invoke('environment',a,input.environment),
  listDeploymentBranchPolicies:a=>invoke('policies',a,page(input.policies,a)),
  createCommitStatus:a=>{writes.push({name:'status',args:a});
   return invoke('status',a,{})}},
 pulls:{get:a=>invoke('pr',a,input.pr),
  listReviews:a=>invoke('reviews',a,page(input.reviews,a))},
 issues:{get:a=>invoke('issue',a,input.issue),
  createComment:a=>{writes.push({name:'comment',args:a});
   return invoke('comment',a,{})}},
 checks:{listForRef:a=>invoke('checks',a,page(input.checks,a))},
 actions:{getWorkflowRun:a=>invoke('run',a,input.runs[String(a.run_id)]),
  listWorkflowRunsForRepo:a=>invoke('active',a,page(input.active.filter(r=>r.status===a.status),a)),
  listJobsForWorkflowRun:a=>invoke('jobs',a,page(input.jobs,a))},
 git:{getRef:a=>{
   const value=claims[a.ref.replace(/^tags\//,'')];
   if(!value)throw Error('PRIVATE_NOT_FOUND');
   return invoke('getRef',a,{object:{type:'tag',sha:JSON.stringify(value)}})},
  getTag:a=>invoke('getTag',a,JSON.parse(a.tag_sha)),
  createTag:a=>{writes.push({name:'tag',args:a});
   const tag={object:{type:a.type,sha:a.object},message:a.message};
   return invoke('tag',a,{sha:JSON.stringify(tag)})},
  createRef:a=>{const name=a.ref.replace(/^refs\/tags\//,'');
   if(claims[name])throw Error('PRIVATE_DUPLICATE');
   return invoke('ref',a,{}).then(r=>{claims[name]=JSON.parse(a.sha);
    writes.push({name:'ref',args:a});return r})}}
},paginate:async(method,args)=>{
 const all=[];for(let p=1;p<=20;p++){const result=await method({...args,page:p});
 all.push(...result.data);if(result.data.length<100)return all;}
 throw Error('PRIVATE_PAGINATION');
},graphql:async(query,args)=>{
 const p=args.cursor===null?0:Number(args.cursor);const data=input.threads[p];
  await invoke('threads',args,data);
  return {repository:{pullRequest:{reviewThreads:data}}};
}};
const gate=require(input.gate);
(async()=>{
 const results=[];
 for(const op of input.operations||[{name:'verify'}]){
  const output={failed:[],outputs:{},logs:[]};
  const core={setFailed:x=>output.failed.push(x),
   setOutput:(k,v)=>output.outputs[k]=v,info:x=>output.logs.push(x)};
  const context=structuredClone(input.context);
  if(op.phase){context.payload.label.name=`manager-hoben-boundary-${op.phase}`;
   input.pr.labels=[{name:context.payload.label.name}];}
  if(op.id)context.runId=op.id;
  if(op.reviews)input.reviews=op.reviews;
  if(op.report)require('fs').writeFileSync(
   `${process.env.GITHUB_WORKSPACE}/public-report/report.json`,
   JSON.stringify(op.report));
  if(op.name==='publish')await gate.publish({github,context,core});
  else await gate.verify({github,context,core,recheck:op.name==='recheck'});
  results.push(output);
 }
 process.stdout.write(JSON.stringify({results,calls,writes,claims}));
})().catch(()=>process.exit(1));
"""


@pytest.fixture
def event(tmp_path):
    scripts, config = tmp_path / "scripts", tmp_path / "config"
    scripts.mkdir()
    config.mkdir()
    shutil.copy(ROOT / ".github/scripts/hoben-boundary-request.cjs", scripts)
    shutil.copy(ROOT / ".github/config/hoben-capture-recipient.pem", config)
    policy = copy.deepcopy(POLICY)
    policy["review"]["body_sha256"] = hashlib.sha256(
        b"Synthetic independent review"
    ).hexdigest()
    (config / "hoben-boundary.json").write_text(json.dumps(policy))
    (tmp_path / "public-report").mkdir()
    write_report(tmp_path, "dry-run")
    pr = {
        "number": 49,
        "state": "open",
        "draft": True,
        "head": {"sha": SHA, "ref": "codex/issue-48", "repo": {"full_name": REPO}},
        "base": {"ref": "main", "repo": {"full_name": REPO}},
        "labels": [{"name": "manager-hoben-boundary-dry-run"}],
    }
    return {
        "gate": str(scripts / "hoben-boundary-request.cjs"),
        "workspace": str(tmp_path),
        "context": {
            "eventName": "pull_request_target",
            "actor": "Guillaume0385",
            "ref": "refs/heads/main",
            "sha": MAIN,
            "runId": 123,
            "repo": {"owner": "Guillaume0385", "repo": "ha-hoben-community"},
            "payload": {
                "action": "labeled",
                "label": {"name": pr["labels"][0]["name"]},
                "sender": {"login": "Guillaume0385", "id": 18246624, "type": "User"},
                "repository": {
                    "full_name": REPO,
                    "id": 1401398724,
                    "default_branch": "main",
                },
                "pull_request": copy.deepcopy(pr),
            },
        },
        "repository": {"default_branch": "main"},
        "branch": {"protected": True, "commit": {"sha": MAIN}},
        "pr": pr,
        "issue": {"state": "open", "labels": [{"name": "state:blocked"}]},
        "reviews": [
            {
                "id": policy["review"]["id"],
                "commit_id": SHA,
                "state": "COMMENTED",
                "body": "Synthetic independent review",
                "user": {"login": "Guillaume0385", "id": 18246624},
            }
        ],
        "threads": [
            {
                "nodes": [{"isResolved": True}],
                "pageInfo": {"hasNextPage": False, "endCursor": None},
            }
        ],
        "checks": [
            {
                "name": n,
                "head_sha": SHA,
                "app": {"slug": "github-actions"},
                "status": "completed",
                "conclusion": "success",
                "details_url": f"https://github.com/{REPO}/actions/runs/10/job/{i}",
            }
            for i, n in enumerate(("tests", "ha-tests", "hacs", "hassfest"), 1)
        ],
        "environment": {
            "name": "hoben-live",
            "deployment_branch_policy": {
                "custom_branch_policies": True,
                "protected_branches": False,
            },
        },
        "policies": [{"name": "main", "type": "branch"}],
        "active": [],
        "runs": {
            "10": {
                "path": ".github/workflows/validate.yml",
                "event": "pull_request",
                "head_sha": SHA,
                "status": "completed",
                "conclusion": "success",
            }
        },
        "jobs": [],
    }


def execute(event, **env):
    process = subprocess.run(
        ["node", "-e", DRIVER],
        input=json.dumps(event),
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
        env={
            **os.environ,
            "GITHUB_TRIGGERING_ACTOR": "Guillaume0385",
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_WORKFLOW_REF": f"{REPO}/{WORKFLOW}@refs/heads/main",
            "GITHUB_WORKFLOW_SHA": MAIN,
            "GITHUB_WORKSPACE": event["workspace"],
            **env,
        },
    )
    assert "PRIVATE" not in process.stdout + process.stderr
    return json.loads(process.stdout)


def claim(event, phase, run_id=123):
    event.setdefault("claims", {})[f"hoben-boundary-{phase}-{MAIN}-{SHA}"] = {
        "object": {"type": "commit", "sha": MAIN},
        "message": json.dumps(
            {
                "schema": 1,
                "scenario": "h1h2",
                "phase": phase,
                "main_sha": MAIN,
                "candidate_sha": SHA,
                "run_id": run_id,
            }
        ),
    }


def live(event):
    event["context"]["payload"]["label"]["name"] = "manager-hoben-boundary-live"
    event["pr"]["labels"] = [{"name": "manager-hoben-boundary-live"}]
    claim(event, "dry-run", 120)
    event["runs"]["120"] = {
        "path": WORKFLOW,
        "event": "pull_request_target",
        "head_sha": MAIN,
        "run_attempt": 1,
        "actor": {"login": "Guillaume0385"},
        "triggering_actor": {"login": "Guillaume0385"},
        "status": "completed",
        "conclusion": "success",
    }
    event["jobs"] = [
        {"name": n, "status": "completed", "conclusion": "success"}
        for n in ("request", "dry-run", "publish")
    ]
    event["jobs"].append({"name": "observations", "conclusion": "skipped"})
    write_report(Path(event["workspace"]), "live")
    return event


def write_report(workspace, phase, run_id=123):
    report = {
        "schema": 1,
        "scenario": "h1h2",
        "phase": phase,
        "main_sha": MAIN,
        "candidate_sha": SHA,
        "run_id": run_id,
        "boundary_proven": False,
        "result": "dry_run_pass" if phase == "dry-run" else "inconclusive",
        "reason": "no_hoben_connection"
        if phase == "dry-run"
        else "hypotheses_unproven",
        "executed_sessions": 0,
    }
    if phase == "live":
        report.update(
            observation_seconds=90,
            planned_sessions=12,
            eligible_sessions=0,
            sessions=[],
        )
    (workspace / "public-report/report.json").write_text(json.dumps(report))
    return report


def test_authenticated_dry_run_records_atomic_claim_on_main_and_pending_status(event):
    result = execute(event)
    assert not result["results"][0]["failed"]
    assert result["results"][0]["outputs"]["approved"] == "true"
    tag = next(w["args"] for w in result["writes"] if w["name"] == "tag")
    assert tag["object"] == MAIN and json.loads(tag["message"])["candidate_sha"] == SHA
    status = next(w["args"] for w in result["writes"] if w["name"] == "status")
    assert status["sha"] == SHA and status["state"] == "pending"
    assert status["target_url"].endswith("/123")


@pytest.mark.parametrize(
    "path,value",
    [
        ("context.actor", "other"),
        ("context.eventName", "issue_comment"),
        ("context.eventName", "schedule"),
        ("context.eventName", "push"),
        ("context.ref", "refs/heads/codex/issue-48"),
        ("context.repo.owner", "fork"),
        ("context.payload.action", "edited"),
        ("context.payload.sender.login", "other"),
        ("context.payload.sender.id", 1),
        ("context.payload.sender.type", "Bot"),
        ("context.payload.repository.id", 1),
        ("context.payload.repository.full_name", "fork/repo"),
        ("context.payload.label.name", "manager-live-hoben"),
        ("context.payload.pull_request.number", 51),
        ("context.payload.pull_request.head.sha", "b" * 40),
        ("context.payload.pull_request.head.repo.full_name", "fork/repo"),
        ("branch.protected", False),
        ("branch.commit.sha", "b" * 40),
        ("repository.default_branch", "candidate"),
        ("pr.state", "closed"),
        ("pr.draft", False),
        ("pr.head.sha", "b" * 40),
        ("pr.head.repo.full_name", "fork/repo"),
        ("pr.head.ref", "different-branch"),
        ("pr.base.ref", "other"),
        ("pr.labels", []),
        (
            "pr.labels",
            [
                {"name": "manager-hoben-boundary-live"},
                {"name": "manager-hoben-boundary-dry-run"},
            ],
        ),
        ("issue.state", "closed"),
        ("issue.pull_request", {}),
        ("issue.labels", [{"name": "state:in-progress"}]),
        ("issue.labels", [{"name": "state:blocked"}, {"name": "state:ready"}]),
        ("reviews", []),
        ("checks", []),
        ("policies", []),
        ("policies", [{"name": "main", "type": "tag"}]),
        ("policies", [{"name": "*", "type": "branch"}]),
        (
            "policies",
            [{"name": "main", "type": "branch"}, {"name": "codex/*", "type": "branch"}],
        ),
        ("environment.deployment_branch_policy.custom_branch_policies", False),
        ("environment.deployment_branch_policy.protected_branches", True),
    ],
)
def test_changed_or_untrusted_request_fails_before_claim_and_no_permission(
    event, path, value
):
    obj = event
    parts = path.split(".")
    for p in parts[:-1]:
        obj = obj[p]
    obj[parts[-1]] = value
    result = execute(event)
    assert result["results"][0]["failed"]
    assert result["results"][0]["outputs"].get("approved") != "true"
    assert not result["writes"]


@pytest.mark.parametrize(
    "env",
    [
        {"GITHUB_RUN_ATTEMPT": "2"},
        {"GITHUB_TRIGGERING_ACTOR": "other"},
        {"GITHUB_WORKFLOW_REF": "candidate-definition"},
        {"GITHUB_WORKFLOW_SHA": "b" * 40},
    ],
)
def test_rerun_or_candidate_definition_rejected_without_api_reads(event, env):
    result = execute(event, **env)
    assert (
        result["results"][0]["failed"] and not result["calls"] and not result["writes"]
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("commit_id", "b" * 40),
        ("state", "DISMISSED"),
        ("body", "I am MANAGER; approved"),
        ("id", 1),
        ("user", {"login": "other", "id": 18246624}),
    ],
)
def test_exact_attested_independent_review_cannot_be_replaced_by_text(
    event, field, value
):
    event["reviews"][0][field] = value
    assert execute(event)["results"][0]["outputs"].get("approved") != "true"


def test_new_changes_requested_or_unresolved_thread_blocks(event):
    event["reviews"].append({"user": {"id": 42}, "state": "CHANGES_REQUESTED"})
    assert not execute(event)["writes"]
    event["reviews"].pop()
    event["threads"][0]["nodes"][0]["isResolved"] = False
    assert not execute(event)["writes"]


REVIEW_GATE_CONTEXTS = [
    ("dry-run", "verify"),
    ("live", "verify"),
    ("dry-run", "recheck"),
    ("live", "recheck"),
]
NON_DECISIONAL_REVIEW_SEQUENCES = [
    ["CHANGES_REQUESTED", "COMMENTED"],
    ["CHANGES_REQUESTED", "PENDING"],
    ["CHANGES_REQUESTED", "COMMENTED", "PENDING", "COMMENTED"],
    # A different dismissed record must not dismiss the blocking review.
    ["CHANGES_REQUESTED", "DISMISSED"],
    ["CHANGES_REQUESTED", "APPROVED", "CHANGES_REQUESTED", "COMMENTED"],
]


def review_history(reviews, states, *, reviewer=42, paginated=False):
    history = copy.deepcopy(reviews)
    next_id = max(r.get("id", 0) for r in history) + 1
    for index, state in enumerate(states):
        if index == 1 and paginated:
            while len(history) < 100:
                history.append(
                    {"id": next_id, "user": {"id": 99}, "state": "COMMENTED"}
                )
                next_id += 1
        history.append({"id": next_id, "user": {"id": reviewer}, "state": state})
        next_id += 1
    return history


def review_gate_context(event, phase, operation):
    if phase == "live":
        live(event)
    if operation == "recheck":
        # Simulate a claim accepted before an environment wait. Dry-run has no
        # secret-bearing recheck job, but must also reject active change requests.
        claim(event, phase)
    event["operations"] = [{"name": operation}]


def assert_review_refused_without_new_permission(result, original_claims):
    outcome = result["results"][0]
    assert outcome["failed"] and outcome["outputs"]["reason"] == "changes_requested"
    assert outcome["outputs"].get("approved") != "true"
    assert outcome["outputs"].get("claimed") != "true"
    assert not result["writes"] and result["claims"] == original_claims


@pytest.mark.parametrize("phase,operation", REVIEW_GATE_CONTEXTS)
@pytest.mark.parametrize("states", NON_DECISIONAL_REVIEW_SEQUENCES)
@pytest.mark.parametrize("paginated", [False, True])
def test_non_decisional_reviews_preserve_active_change_requests(
    event, phase, operation, states, paginated
):
    review_gate_context(event, phase, operation)
    event["reviews"] = review_history(event["reviews"], states, paginated=paginated)
    original_claims = copy.deepcopy(event.get("claims", {}))
    result = execute(event)
    assert_review_refused_without_new_permission(result, original_claims)
    if paginated:
        assert any(
            c["name"] == "reviews" and c["args"]["page"] == 2 for c in result["calls"]
        )


@pytest.mark.parametrize("phase,operation", REVIEW_GATE_CONTEXTS)
def test_other_reviewer_approval_does_not_clear_remaining_change_request(
    event, phase, operation
):
    review_gate_context(event, phase, operation)
    event["reviews"] = review_history(
        event["reviews"], ["CHANGES_REQUESTED", "COMMENTED"]
    )
    event["reviews"] = review_history(
        event["reviews"], ["CHANGES_REQUESTED", "APPROVED", "COMMENTED"], reviewer=43
    )
    original_claims = copy.deepcopy(event.get("claims", {}))
    assert_review_refused_without_new_permission(execute(event), original_claims)


@pytest.mark.parametrize("phase,operation", REVIEW_GATE_CONTEXTS)
def test_pinned_commented_attestation_does_not_clear_its_author_change_request(
    event, phase, operation
):
    review_gate_context(event, phase, operation)
    event["reviews"].insert(
        0,
        {
            "id": POLICY["review"]["id"] - 1,
            "user": copy.deepcopy(event["reviews"][0]["user"]),
            "state": "CHANGES_REQUESTED",
        },
    )
    original_claims = copy.deepcopy(event.get("claims", {}))
    assert_review_refused_without_new_permission(execute(event), original_claims)


@pytest.mark.parametrize("states", NON_DECISIONAL_REVIEW_SEQUENCES)
@pytest.mark.parametrize("paginated", [False, True])
def test_new_review_during_environment_wait_refuses_secret_recheck(
    event, states, paginated
):
    live(event)
    event["operations"] = [
        {"name": "verify"},
        {
            "name": "recheck",
            "reviews": review_history(event["reviews"], states, paginated=paginated),
        },
    ]
    result = execute(event)
    admitted, rechecked = result["results"]
    assert admitted["outputs"]["approved"] == "true" and not admitted["failed"]
    assert rechecked["failed"]
    assert rechecked["outputs"]["reason"] == "changes_requested"
    assert rechecked["outputs"].get("approved") != "true"
    assert rechecked["outputs"].get("claimed") != "true"
    # Only the original admission may write. Recheck adds no claim or status.
    assert [w["name"] for w in result["writes"]] == ["tag", "ref", "status"]
    assert result["writes"][-1]["args"]["state"] == "pending"
    assert len(result["claims"]) == 2


@pytest.mark.parametrize(
    "phase,operation", [c for c in REVIEW_GATE_CONTEXTS if c != ("dry-run", "recheck")]
)
@pytest.mark.parametrize("paginated", [False, True])
@pytest.mark.parametrize(
    "states",
    [
        ["CHANGES_REQUESTED", "COMMENTED", "APPROVED", "PENDING"],
        ["CHANGES_REQUESTED", "APPROVED", "COMMENTED", "DISMISSED"],
        # The API changes the original blocking record's state to DISMISSED;
        # it does not append a dismissal that clears other active records.
        ["DISMISSED", "COMMENTED"],
    ],
)
def test_actual_approval_or_dismissal_allows_correctly_reviewed_request(
    event, phase, operation, paginated, states
):
    review_gate_context(event, phase, operation)
    event["reviews"] = review_history(event["reviews"], states, paginated=paginated)
    result = execute(event)
    assert not result["results"][0]["failed"]
    assert result["results"][0]["outputs"]["approved"] == "true"
    assert [w["name"] for w in result["writes"]] == (
        [] if operation == "recheck" else ["tag", "ref", "status"]
    )


def test_review_and_thread_pagination_inspects_later_pages(event):
    filler = {"user": {"id": 42}, "state": "COMMENTED", "id": 1}
    event["reviews"] = [filler] * 100 + event["reviews"]
    result = execute(event)
    assert result["results"][0]["outputs"]["approved"] == "true"
    assert any(
        c["name"] == "reviews" and c["args"]["page"] == 2 for c in result["calls"]
    )
    event["threads"] = [
        {
            "nodes": [{"isResolved": True}] * 100,
            "pageInfo": {"hasNextPage": True, "endCursor": "1"},
        },
        {
            "nodes": [{"isResolved": False}],
            "pageInfo": {"hasNextPage": False, "endCursor": None},
        },
    ]
    assert not execute(event)["writes"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("conclusion", "failure"),
        ("status", "in_progress"),
        ("head_sha", "b" * 40),
        ("app", {"slug": "other"}),
        ("details_url", "https://example.invalid/10"),
    ],
)
def test_ci_check_must_be_exact_successful_trusted_run(event, field, value):
    event["checks"][0][field] = value
    assert not execute(event)["writes"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("path", "candidate.yml"),
        ("event", "push"),
        ("head_sha", "b" * 40),
        ("conclusion", "failure"),
    ],
)
def test_ci_workflow_origin_verified(event, field, value):
    event["runs"]["10"][field] = value
    assert not execute(event)["writes"]


@pytest.mark.parametrize(
    "file",
    [
        "manager-live-hoben.yml",
        "live-validation.yml",
        "opened-client-boundary.yml",
        "hoben-boundary-request.yml",
    ],
)
def test_other_active_privileged_workflow_refuses_parallel_collection(event, file):
    event["active"] = [
        {"id": 999, "path": f".github/workflows/{file}", "status": "waiting"}
    ]
    assert not execute(event)["writes"]


@pytest.mark.parametrize(
    "api",
    [
        "repository",
        "environment",
        "policies",
        "reviews",
        "threads",
        "checks",
        "active",
        "ref",
    ],
)
def test_unavailable_api_or_failed_atomic_claim_is_private_and_fail_closed(event, api):
    event["error_at"] = api
    result = execute(event)
    assert result["results"][0]["failed"]
    assert result["results"][0]["outputs"].get("approved") != "true"
    assert not any(w["name"] == "status" for w in result["writes"])


@pytest.mark.parametrize("now", ["2026-10-08T07:00:00Z", "2027-10-08T07:00:00Z"])
def test_certificate_not_yet_valid_or_less_than_hour_remaining(event, now):
    from datetime import datetime

    event["now"] = int(datetime.fromisoformat(now).timestamp() * 1000)
    assert not execute(event)["writes"]


@pytest.mark.parametrize(
    "change", ["missing", "wrong_pin", "private_key", "symlink", "scenario"]
)
def test_missing_unsafe_recipient_or_non_allowlisted_scenario_refuses(event, change):
    config = Path(event["gate"]).parent.parent / "config"
    pem = config / "hoben-capture-recipient.pem"
    if change == "missing":
        pem.unlink()
    elif change == "private_key":
        pem.write_text("-----BEGIN PRIVATE KEY-----\nPRIVATE\n")
    elif change == "symlink":
        pem.unlink()
        pem.symlink_to(ROOT / ".github/config/hoben-capture-recipient.pem")
    else:
        policy = json.loads((config / "hoben-boundary.json").read_text())
        policy["recipient_sha256" if change == "wrong_pin" else "scenario"] = (
            "b" * 64 if change == "wrong_pin" else "arbitrary-script"
        )
        (config / "hoben-boundary.json").write_text(json.dumps(policy))
    assert not execute(event)["writes"]


def test_live_requires_current_installed_channel_dry_run(event):
    live(event)
    result = execute(event)
    assert result["results"][0]["outputs"]["approved"] == "true"
    event["claims"] = {}
    assert not execute(event)["writes"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("head_sha", "b" * 40),
        ("event", "workflow_dispatch"),
        ("path", "existing-manual.yml"),
        ("run_attempt", 2),
        ("conclusion", "failure"),
        ("status", "in_progress"),
        ("actor", {"login": "other"}),
        ("triggering_actor", {"login": "other"}),
    ],
)
def test_old_or_unrelated_dry_run_is_not_proof(event, field, value):
    live(event)["runs"]["120"][field] = value
    assert not execute(event)["writes"]


def test_failed_or_executed_live_job_cannot_be_dry_run_proof(event):
    live(event)["jobs"][0]["conclusion"] = "failure"
    assert not execute(event)["writes"]
    event["jobs"][0]["conclusion"] = "success"
    event["jobs"][-1]["conclusion"] = "success"
    assert not execute(event)["writes"]


def test_existing_label_and_repeated_new_label_cannot_reset_atomic_claim(event):
    event["operations"] = [{"name": "verify"}, {"name": "verify", "id": 124}]
    result = execute(event)
    assert result["results"][0]["outputs"]["approved"] == "true"
    assert result["results"][1]["outputs"].get("approved") != "true"
    assert len([w for w in result["writes"] if w["name"] == "ref"]) == 1
    assert len([w for w in result["writes"] if w["name"] == "status"]) == 1


def test_recheck_reuses_same_live_claim_with_no_write(event):
    live(event)
    claim(event, "live")
    event["operations"] = [{"name": "recheck"}]
    result = execute(event)
    assert (
        result["results"][0]["outputs"]["approved"] == "true" and not result["writes"]
    )
    claim(event, "live", 999)
    assert execute(event)["results"][0]["outputs"].get("approved") != "true"


def test_publish_metadata_only_does_not_overwrite_result_of_duplicate(event):
    event["operations"] = [{"name": "publish"}]
    claim(event, "dry-run", 100)
    result = execute(
        event,
        BOUNDARY_APPROVED="false",
        BOUNDARY_CLAIMED="false",
        BOUNDARY_JOB_RESULT="skipped",
    )
    assert [w["name"] for w in result["writes"]] == ["comment"]
    assert "result: refused" in result["writes"][0]["args"]["body"]
    assert "Boundary remains unproven" in result["writes"][0]["args"]["body"]


@pytest.mark.parametrize(
    "phase,result,expected",
    [
        ("dry-run", "success", "dry_run_pass"),
        ("live", "success", "inconclusive"),
        ("live", "failure", "failure"),
    ],
)
def test_publish_exact_claim_status_is_never_boundary_approval(
    event, phase, result, expected
):
    if phase == "live":
        live(event)
    event["context"]["payload"]["label"]["name"] = f"manager-hoben-boundary-{phase}"
    claim(event, phase)
    event["operations"] = [{"name": "publish"}]
    output = execute(
        event,
        BOUNDARY_APPROVED="true",
        BOUNDARY_CLAIMED="true",
        BOUNDARY_JOB_RESULT=result,
    )
    assert expected in output["writes"][0]["args"]["description"]
    assert output["writes"][0]["args"]["target_url"].endswith("/123")


@pytest.mark.parametrize(
    "change", ["missing", "sha", "run", "text", "proof", "symlink"]
)
def test_publisher_rejects_unverified_public_artifact_without_echoing_its_data(
    event, change
):
    live(event)
    claim(event, "live")
    event["operations"] = [{"name": "publish"}]
    file = Path(event["workspace"]) / "public-report/report.json"
    report = json.loads(file.read_text())
    if change == "missing":
        file.unlink()
    elif change == "symlink":
        file.unlink()
        file.symlink_to(Path(event["gate"]))
    else:
        report[
            {
                "sha": "main_sha",
                "run": "run_id",
                "text": "reason",
                "proof": "boundary_proven",
            }[change]
        ] = {
            "sha": "b" * 40,
            "run": 999,
            "text": "PRIVATE_TOKEN",
            "proof": True,
        }[change]
        file.write_text(json.dumps(report))
    result = execute(
        event,
        BOUNDARY_APPROVED="true",
        BOUNDARY_CLAIMED="true",
        BOUNDARY_JOB_RESULT="success",
    )
    assert result["results"][0]["failed"]
    assert result["writes"][0]["args"]["state"] == "failure"


def test_dry_request_status_then_live_request_recheck_and_inconclusive_report(event):
    live(event)
    event["claims"] = {}
    event["runs"]["123"] = event["runs"]["120"]
    workspace = Path(event["workspace"])
    event["operations"] = [
        {"name": "verify", "phase": "dry-run", "id": 123},
        {
            "name": "publish",
            "phase": "dry-run",
            "id": 123,
            "report": write_report(workspace, "dry-run", 123),
        },
        {"name": "verify", "phase": "live", "id": 124},
        {"name": "recheck", "phase": "live", "id": 124},
        {
            "name": "publish",
            "phase": "live",
            "id": 124,
            "report": write_report(workspace, "live", 124),
        },
    ]
    result = execute(
        event,
        BOUNDARY_APPROVED="true",
        BOUNDARY_CLAIMED="true",
        BOUNDARY_JOB_RESULT="success",
    )
    assert not any(r["failed"] for r in result["results"])
    statuses = [w["args"] for w in result["writes"] if w["name"] == "status"]
    assert [s["state"] for s in statuses] == [
        "pending",
        "success",
        "pending",
        "success",
    ]
    assert "inconclusive" in statuses[-1]["description"]
    assert len(result["claims"]) == 2
    assert statuses[-1]["target_url"].endswith("/124")


def test_workflow_is_label_only_main_trusted_token_and_secret_separation():
    w = yaml.load((ROOT / WORKFLOW).read_text(), Loader=yaml.BaseLoader)
    assert w["on"] == {"pull_request_target": {"types": ["labeled"]}}
    assert w["permissions"] == {} and w["concurrency"] == {
        "group": "hoben-boundary-campaign",
        "cancel-in-progress": "false",
    }
    jobs = w["jobs"]
    assert set(jobs) == {"request", "dry-run", "observations", "publish"}
    assert jobs["observations"]["environment"] == "hoben-live"
    for name, job in jobs.items():
        if name != "observations":
            assert "environment" not in job
        assert "HOBEN_USER_GUID" not in job.get("env", {})
        checkouts = [
            s for s in job["steps"] if s.get("uses", "").startswith("actions/checkout")
        ]
        assert checkouts[0]["with"]["ref"] == "${{ github.sha }}"
        assert all(s["with"]["persist-credentials"] == "false" for s in checkouts)
        if name != "observations":
            assert len(checkouts) == 1
            assert "secrets." not in json.dumps(job)
    live_job = jobs["observations"]
    assert all(v == "read" for v in live_job["permissions"].values())
    assert jobs["request"]["permissions"]["contents"] == "write"
    assert jobs["publish"]["permissions"]["contents"] == "read"
    assert (
        "recheck: true"
        in next(s for s in live_job["steps"] if s.get("id") == "recheck")["with"][
            "script"
        ]
    )
    probe = next(s for s in live_job["steps"] if "HOBEN_USER_GUID" in s.get("env", {}))
    assert probe["if"] == "steps.recheck.outputs.approved == 'true'"
    assert "GITHUB_TOKEN" not in probe["env"] and "GH_TOKEN" not in probe["env"]
    assert (
        probe["run"]
        == "python trusted/scripts/run_boundary_request.py live >/dev/null 2>/dev/null"
    )
    assert not any("pip " in s.get("run", "") for s in live_job["steps"])
    uploads = [
        s["with"]
        for s in live_job["steps"]
        if s.get("uses", "").startswith("actions/upload-artifact")
    ]
    assert [u["path"] for u in uploads] == [
        "${{ runner.temp }}/hoben-boundary-request-exports/captures.cms",
        "${{ runner.temp }}/hoben-boundary-request-exports/report.json",
    ]
    assert all(
        u["retention-days"] == "7" and u["if-no-files-found"] == "error"
        for u in uploads
    )
    downloads = [
        s["with"]
        for s in jobs["publish"]["steps"]
        if s.get("uses", "").startswith("actions/download-artifact")
    ]
    assert len(downloads) == 2 and all(d["path"] == "public-report" for d in downloads)
    assert all("ciphertext" not in d["name"] for d in downloads)
