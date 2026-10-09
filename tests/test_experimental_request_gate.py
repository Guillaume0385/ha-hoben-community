"""Run the actual trusted gate against paginated, entirely offline GitHub APIs."""

import copy
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
REPO = "Guillaume0385/ha-hoben-community"
WORKFLOW = ".github/workflows/hoben-experimental-request.yml"
MAIN, SHA, HEAD = "a" * 40, "b" * 40, "c" * 40
POLICY = json.loads((ROOT / ".github/config/hoben-experimental.json").read_text())
OWNER = {"login": "Guillaume0385", "id": 18246624, "type": "User"}
REVIEWER = {"login": "independent-synthetic", "id": 12345, "type": "User"}
MARKER = "<!-- hoben-experimental-decision:v1 -->\n"
DRIVER = r"""
const fs=require('node:fs');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
Date.now=()=>Date.parse('2026-10-09T00:00:00Z');
for(const [module,methods] of [['node:net',['connect','createConnection']],
 ['node:tls',['connect']],['node:dns',['lookup','resolve']]]){
 for(const method of methods)require(module)[method]=()=>{
  throw Error('NETWORK_FORBIDDEN')
 };
}
const calls=[], writes=[], claims=input.claims||{};
const invoke=async(name,args,data)=>{
 calls.push({name,args});
 if(input.error_at===name)throw Error('SYNTHETIC_PRIVATE_TOKEN_PACKET');
 return {data};
};
const page=(a,args)=>a.slice(((args.page||1)-1)*100,(args.page||1)*100);
const github={rest:{
 repos:{get:a=>invoke('repository',a,input.repository),
  getBranch:a=>invoke('branch',a,input.branches[a.branch]),
  getEnvironment:a=>invoke('environment',a,input.environment),
  listDeploymentBranchPolicies:a=>invoke('policies',a,{branch_policies:page(input.policies,a)}),
  getDeploymentBranchPolicy:a=>invoke('policy-detail',a,input.policy_detail),
  getCombinedStatusForRef:a=>invoke('combined',a,input.combined),
  createCommitStatus:a=>invoke('status',a,{}).then(r=>{
   writes.push({name:'status',args:a});input.combined.statuses.unshift(a);return r})},
 issues:{get:a=>invoke('issue',a,input.issue),
  listComments:a=>invoke('comments',a,page(input.comments,a)),
  listEvents:a=>invoke('events',a,page(input.events,a)),
  createComment:a=>invoke('comment',a,{}).then(r=>{
   writes.push({name:'comment',args:a});input.comments.push({id:9000+input.comments.length,
    body:a.body,user:{login:'github-actions[bot]',type:'Bot'}});return r})},
 pulls:{get:a=>invoke('pr',a,input.pr),
  listReviews:a=>invoke('reviews',a,page(input.reviews,a))},
 checks:{listForRef:a=>invoke('checks',a,{check_runs:page(input.checks,a)})},
 actions:{getWorkflowRun:a=>invoke('run',a,input.runs[String(a.run_id)]),
  listWorkflowRunsForRepo:a=>invoke('active',a,{workflow_runs:page(input.active.filter(r=>r.status===a.status),a)}),
  listJobsForWorkflowRun:a=>invoke('jobs',a,{jobs:page(input.jobs[String(a.run_id)]||[],a)}),
  listWorkflowRunArtifacts:a=>invoke('artifacts',a,{artifacts:page(input.artifacts[String(a.run_id)]||[],a)})},
 git:{getRef:a=>{const tag=claims[a.ref.replace(/^tags\//,'')];
   if(!tag)throw Error('SYNTHETIC_NOT_FOUND');
   return invoke('get-ref',a,{object:{type:'tag',sha:JSON.stringify(tag)}})},
  getTag:a=>invoke('get-tag',a,JSON.parse(a.tag_sha)),
  createTag:a=>invoke('tag',a,{sha:JSON.stringify({object:{type:a.type,sha:a.object},message:a.message})})
   .then(r=>{writes.push({name:'tag',args:a});return r}),
  createRef:a=>{const key=a.ref.replace(/^refs\/tags\//,'');
   if(claims[key])throw Error('SYNTHETIC_DUPLICATE');
   return invoke('ref',a,{}).then(r=>{claims[key]=JSON.parse(a.sha);
    writes.push({name:'ref',args:a});return r})}}
},request:async(route,args)=>{
 if(route!=='GET /repos/{owner}/{repo}/actions/runs/{run_id}/approvals')
  throw Error('UNEXPECTED_ROUTE');
 return invoke('approvals',args,input.approvals);
},paginate:async(method,args)=>{
 const all=[];for(let p=1;p<=20;p++){
  const {data}=await method({...args,page:p});
  const entries=Array.isArray(data)?data: Object.values(data).find(Array.isArray);
  all.push(...entries);if(entries.length<100)return all;
 }throw Error('SYNTHETIC_PAGINATION');
},graphql:async(query,args)=>{
 const p=args.cursor===null?0:Number(args.cursor);
 const threads=input.threads[p];await invoke('threads',args,threads);
 return {repository:{pullRequest:{reviewThreads:threads}}};
}};
const gate=require(input.gate);
(async()=>{
 const results=[];
 for(const op of input.operations||[{name:'verify'}]){
  if(op.now)Date.now=()=>Date.parse(op.now);
  if(op.patch)Object.assign(input,op.patch);
  if(op.env)Object.assign(process.env,op.env);
  const output={failed:[],outputs:{},logs:[]};
  const core={setFailed:s=>output.failed.push(s),setOutput:(k,v)=>output.outputs[k]=v,
   info:s=>output.logs.push(s),summary:{addRaw:s=>({write:async()=>{output.summary=s}})}};
  try {
   if(op.name==='verify')await gate.verify({
    github,context:input.context,core,recheck:!!op.recheck});
   else if(op.name==='publish')await gate.publish({github,context:input.context,core});
   else if(op.name==='dry')gate.dryReport(input.context);
   else if(op.name==='prepare-public')gate.preparePublicReport({
    context:input.context,core});
   else if(op.name==='prepare-ciphertext')gate.prepareCiphertext({
    context:input.context,core});
   else if(op.name==='discover')output.result=await gate.discover({github,
    repo:input.context.repo,phase:input.phase,candidate:input.candidate});
   else throw Error('UNEXPECTED_OPERATION');
  }catch{output.failed.push('REFUSED')}
  results.push(output);
 }
 process.stdout.write(JSON.stringify({results,calls,writes,claims}));
})().catch(()=>process.exit(1));
"""


def decision(phase="dry-run"):
    return {
        "schema": 1,
        "phase": phase,
        "scenario": "h1h2",
        "main_sha": MAIN,
        "experimental_sha": SHA,
        "pull_request": 55,
        "decision": "reviewed-read-only",
        "recipient_sha256": POLICY["recipient_sha256"],
    }


def run_record(id=123, *, completed=False):
    return {
        "id": id,
        "path": WORKFLOW,
        "event": "issues",
        "head_branch": "main",
        "head_sha": MAIN,
        "run_attempt": 1,
        "actor": OWNER,
        "triggering_actor": OWNER,
        "created_at": "2026-10-09T00:00:05Z",
        "status": "completed" if completed else "in_progress",
        "conclusion": "success" if completed else None,
    }


def artifact(id=120):
    return {
        "id": 777,
        "name": f"experimental-report-{SHA}-{id}",
        "expired": False,
        "workflow_run": {"id": id, "head_sha": MAIN},
    }


def claim_tag(phase="dry-run", id=120):
    stamp = {
        "schema": 1,
        "phase": phase,
        "scenario": "h1h2",
        "candidate_sha": SHA,
        "main_sha": MAIN,
        "pull_request": 55,
        "run_id": id,
        "comment_id": 101,
        "label_event_id": 102,
        "comment_digest": "d" * 64,
        "environment_digest": None,
    }
    return {"object": {"type": "commit", "sha": MAIN}, "message": json.dumps(stamp)}


def associated_pr():
    # The REST associations use reduced repo objects, not necessarily full_name.
    repo = {"id": 1401398724, "url": f"https://api.github.com/repos/{REPO}"}
    return {
        "number": 55,
        "url": f"https://api.github.com/repos/{REPO}/pulls/55",
        "head": {"sha": HEAD, "ref": "codex/issue-54", "repo": repo.copy()},
        "base": {"ref": "experimental", "repo": repo.copy()},
    }


@pytest.fixture
def api():
    label = "manager-hoben-experimental-dry-run"
    current = run_record()
    data = {
        "context": {
            "eventName": "issues",
            "ref": "refs/heads/main",
            "actor": OWNER["login"],
            "repo": {"owner": OWNER["login"], "repo": "ha-hoben-community"},
            "sha": MAIN,
            "runId": 123,
            "payload": {
                "action": "labeled",
                "label": {"name": label},
                "sender": OWNER,
                "repository": {
                    "full_name": REPO,
                    "id": 1401398724,
                    "default_branch": "main",
                },
                "issue": {
                    "number": 54,
                    "id": POLICY["tracking_issue_id"],
                    "state": "open",
                    "updated_at": "2026-10-09T00:00:01Z",
                },
            },
        },
        "repository": {"full_name": REPO, "id": 1401398724, "default_branch": "main"},
        "branches": {
            "main": {"protected": True, "commit": {"sha": MAIN}},
            "experimental": {"protected": False, "commit": {"sha": SHA}},
        },
        "issue": {
            "id": POLICY["tracking_issue_id"],
            "state": "open",
            "labels": [{"name": "state:review"}, {"name": label}],
        },
        "comments": [
            {
                "id": 101,
                "user": OWNER,
                "created_at": "2026-10-09T00:00:00Z",
                "updated_at": "2026-10-09T00:00:00Z",
                "body": MARKER + json.dumps(decision()),
            }
        ],
        "events": [
            {
                "id": 102,
                "event": "labeled",
                "label": {"name": label},
                "actor": OWNER,
                "created_at": "2026-10-09T00:00:01Z",
            }
        ],
        "pr": {
            "number": 55,
            "state": "closed",
            "merged": True,
            "draft": False,
            "merge_commit_sha": SHA,
            "merged_by": OWNER,
            "merged_at": "2026-10-08T23:00:00Z",
            "base": {"ref": "experimental", "repo": {"full_name": REPO}},
            "head": {
                "sha": HEAD,
                "ref": "codex/issue-54",
                "repo": {"full_name": REPO},
            },
        },
        "reviews": [],
        "threads": [
            {"nodes": [], "pageInfo": {"hasNextPage": False, "endCursor": None}}
        ],
        "checks": [
            {
                "name": "tests",
                "head_sha": HEAD,
                "status": "completed",
                "conclusion": "success",
                "app": {"slug": "github-actions"},
                "details_url": f"https://github.com/{REPO}/actions/runs/98/job/99",
                "pull_requests": [associated_pr()],
            }
        ],
        "runs": {
            "123": current,
            "120": run_record(120, completed=True),
            "98": {
                "id": 98,
                "path": ".github/workflows/validate.yml",
                "event": "pull_request",
                "head_branch": "codex/issue-54",
                "head_sha": HEAD,
                "status": "completed",
                "conclusion": "success",
                "repository": {"id": 1401398724, "full_name": REPO},
                "head_repository": {"id": 1401398724, "full_name": REPO},
                "pull_requests": [associated_pr()],
            },
        },
        "active": [],
        "claims": {},
        "environment": {
            "id": 50,
            "name": "hoben-experimental",
            "updated_at": "2026-10-08T20:00:00Z",
            "deployment_branch_policy": {
                "custom_branch_policies": True,
                "protected_branches": False,
            },
            "protection_rules": [
                {
                    "id": 51,
                    "type": "required_reviewers",
                    "prevent_self_review": True,
                    "reviewers": [{"type": "User", "reviewer": REVIEWER}],
                },
                {"id": 52, "type": "branch_policy"},
            ],
        },
        "policies": [
            {
                "id": 53,
                "node_id": "SYNTHETIC_BRANCH_NODE",
                "name": "main",
                "type": "branch",
            }
        ],
        "policy_detail": {
            "id": 53,
            "node_id": "SYNTHETIC_BRANCH_NODE",
            "name": "main",
            "type": "branch",
        },
        "approvals": [
            {
                "state": "approved",
                "user": REVIEWER,
                "environments": [{"id": 50, "name": "hoben-experimental"}],
            }
        ],
        "jobs": {
            "120": [
                {"name": name, "status": "completed", "conclusion": "success"}
                for name in ("request", "dry-run", "publish")
            ]
        },
        "artifacts": {"120": [artifact()]},
        "combined": {
            "statuses": [
                {
                    "context": "hoben-experimental/h1h2/dry-run",
                    "state": "success",
                    "target_url": f"https://github.com/{REPO}/actions/runs/120",
                }
            ]
        },
        "phase": "dry-run",
        "candidate": SHA,
    }
    return copy.deepcopy(data)


def live(api):
    label = "manager-hoben-experimental-live"
    api["phase"] = "live"
    api["context"]["payload"]["label"]["name"] = label
    api["issue"]["labels"][1]["name"] = label
    api["comments"][0]["body"] = MARKER + json.dumps(decision("live"))
    api["events"][0]["label"]["name"] = label
    api["claims"][f"hoben-experimental-dry-run-h1h2-{SHA}"] = claim_tag()


def execute(
    api, tmp_path, *, operations=None, env=None, report=None, candidate_report=None
):
    node = shutil.which("node")
    assert node, "Node is required to test the actual GitHub gate"
    api = copy.deepcopy(api)
    api["gate"] = str(ROOT / ".github/scripts/hoben-experimental-request.cjs")
    if operations:
        api["operations"] = operations
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    if report is not None:
        public = work / "public-report"
        public.mkdir(exist_ok=True)
        (public / "report.json").write_text(json.dumps(report))
    if candidate_report is not None:
        source = work / "hoben-experimental-exports"
        source.mkdir(exist_ok=True)
        (source / "report.json").write_text(json.dumps(candidate_report))
    variables = {
        "PATH": os.environ["PATH"],
        "GITHUB_TRIGGERING_ACTOR": OWNER["login"],
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_WORKFLOW_REF": f"{REPO}/{WORKFLOW}@refs/heads/main",
        "GITHUB_WORKFLOW_SHA": MAIN,
        "GITHUB_WORKSPACE": str(work),
        "RUNNER_TEMP": str(work),
        "EXPERIMENTAL_APPROVED_SHA": SHA,
    }
    variables.update(env or {})
    result = subprocess.run(
        [node, "-e", DRIVER],
        input=json.dumps(api),
        env=variables,
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    )
    assert not result.stderr and "SYNTHETIC_PRIVATE_TOKEN_PACKET" not in result.stdout
    return json.loads(result.stdout)


def refused(result, reason=None):
    last = result["results"][-1]
    assert last["failed"] and last["outputs"].get("approved") != "true"
    if reason:
        assert last["outputs"]["reason"] == reason


def test_dry_admission_is_offline_does_not_read_environment_and_claims_once(
    api, tmp_path
):
    result = execute(api, tmp_path, operations=[{"name": "verify"}, {"name": "verify"}])
    assert result["results"][0]["outputs"]["approved"] == "true"
    refused(result, "duplicate_or_unrecordable_request")
    assert len([w for w in result["writes"] if w["name"] == "ref"]) == 1
    assert all(c["name"] not in {"environment", "approvals"} for c in result["calls"])
    status = [w for w in result["writes"] if w["name"] == "status"]
    assert len(status) == 1 and status[0]["args"]["state"] == "pending"
    assert status[0]["args"]["sha"] == SHA


@pytest.mark.parametrize(
    "key,value",
    [
        ("GITHUB_RUN_ATTEMPT", "2"),
        ("GITHUB_TRIGGERING_ACTOR", "other"),
        ("GITHUB_WORKFLOW_REF", f"{REPO}/{WORKFLOW}@refs/heads/experimental"),
        ("GITHUB_WORKFLOW_SHA", SHA),
    ],
)
def test_wrong_runner_context_never_creates_claim(api, tmp_path, key, value):
    result = execute(api, tmp_path, env={key: value})
    refused(result, "unauthenticated_request")
    assert not result["writes"]


@pytest.mark.parametrize(
    "change",
    [
        "sender",
        "actor",
        "ref",
        "event",
        "issue",
        "issue-id",
        "pr",
        "repository",
        "label",
        "attempt",
    ],
)
def test_forged_or_wrong_issue_request_refuses(api, tmp_path, change):
    context, payload = api["context"], api["context"]["payload"]
    if change == "sender":
        payload["sender"]["id"] = 123
    elif change == "actor":
        context["actor"] = "other"
    elif change == "ref":
        context["ref"] = "refs/heads/experimental"
    elif change == "event":
        context["eventName"] = "workflow_dispatch"
    elif change == "issue":
        payload["issue"]["number"] = 55
    elif change == "issue-id":
        payload["issue"]["id"] = 1
    elif change == "pr":
        payload["issue"]["pull_request"] = {}
    elif change == "repository":
        payload["repository"]["id"] = 1
    elif change == "label":
        payload["label"]["name"] = "manager-live-hoben"
    else:
        api["runs"]["123"]["run_attempt"] = 2
    result = execute(api, tmp_path)
    refused(result, "unauthenticated_request")
    assert not result["writes"]


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "edited",
        "other-user",
        "main",
        "sha",
        "phase",
        "scenario",
        "command",
        "recipient",
        "label-event",
        "label-actor",
        "stale",
        "future",
        "latest-invalid",
    ],
)
def test_decision_must_be_exact_fresh_owner_data_not_instructions(
    api, tmp_path, change
):
    record = decision()
    if change == "missing":
        api["comments"] = []
    elif change == "edited":
        api["comments"][0]["updated_at"] = "2026-10-09T00:00:02Z"
    elif change == "other-user":
        api["comments"][0]["user"] = REVIEWER
    elif change in {"main", "sha", "phase", "scenario", "command", "recipient"}:
        key, value = {
            "main": ("main_sha", HEAD),
            "sha": ("experimental_sha", "short"),
            "phase": ("phase", "live"),
            "scenario": ("scenario", "arbitrary"),
            "command": ("execute", "SYNTHETIC_SHELL"),
            "recipient": ("recipient_sha256", "0" * 64),
        }[change]
        record[key] = value
        api["comments"][0]["body"] = MARKER + json.dumps(record)
    elif change == "label-event":
        api["events"][0]["event"] = "unlabeled"
    elif change == "label-actor":
        api["events"][0]["actor"] = REVIEWER
    elif change == "stale":
        api["runs"]["123"]["created_at"] = "2026-10-09T02:00:00Z"
    elif change == "future":
        api["comments"][0].update(
            created_at="2026-10-10T00:00:00Z", updated_at="2026-10-10T00:00:00Z"
        )
    else:
        api["comments"].append(
            {**api["comments"][0], "id": 103, "body": MARKER + "arbitrary"}
        )
    result = execute(api, tmp_path)
    refused(result)
    assert not result["writes"]


@pytest.mark.parametrize(
    "change",
    [
        "main",
        "unprotected",
        "candidate",
        "wrong-base",
        "fork",
        "not-merged",
        "wrong-merger",
        "closed-issue",
        "waiting",
        "multi-state",
        "both-labels",
        "ci-head",
        "ci-app",
        "ci-failed",
        "wrong-ci-event",
        "changes-requested",
        "unresolved",
    ],
)
def test_heads_issue_merge_and_ci_must_still_match(api, tmp_path, change):
    if change == "main":
        api["branches"]["main"]["commit"]["sha"] = HEAD
    elif change == "unprotected":
        api["branches"]["main"]["protected"] = False
    elif change == "candidate":
        api["branches"]["experimental"]["commit"]["sha"] = HEAD
    elif change == "wrong-base":
        api["pr"]["base"]["ref"] = "main"
    elif change == "fork":
        api["pr"]["head"]["repo"]["full_name"] = "fork/repo"
    elif change == "not-merged":
        api["pr"]["merged"] = False
    elif change == "wrong-merger":
        api["pr"]["merged_by"] = REVIEWER
    elif change == "closed-issue":
        api["issue"]["state"] = "closed"
    elif change == "waiting":
        api["issue"]["labels"][0]["name"] = "state:waiting"
    elif change == "multi-state":
        api["issue"]["labels"].append({"name": "state:in-progress"})
    elif change == "both-labels":
        api["issue"]["labels"].append({"name": "manager-hoben-experimental-live"})
    elif change == "ci-head":
        api["checks"][0]["head_sha"] = SHA
    elif change == "ci-app":
        api["checks"][0]["app"]["slug"] = "other"
    elif change == "ci-failed":
        api["runs"]["98"]["conclusion"] = "failure"
    elif change == "wrong-ci-event":
        api["runs"]["98"]["event"] = "workflow_dispatch"
    elif change == "changes-requested":
        api["reviews"] = [
            {"user": REVIEWER, "state": "CHANGES_REQUESTED"},
            {"user": REVIEWER, "state": "COMMENTED"},
        ]
    else:
        api["threads"][0]["nodes"] = [{"isResolved": False}]
    result = execute(api, tmp_path)
    refused(result)
    assert not result["writes"]


def test_all_api_collections_and_review_threads_are_paginated(api, tmp_path):
    api["comments"] = [
        {"id": i, "user": REVIEWER, "body": "ignored"} for i in range(100)
    ] + api["comments"]
    api["events"] = [{"id": i, "event": "mentioned"} for i in range(100)] + api[
        "events"
    ]
    api["checks"] = [{"name": "unrelated"} for _ in range(100)] + api["checks"]
    api["reviews"] = [{"user": REVIEWER, "state": "COMMENTED"} for _ in range(101)]
    api["threads"] = [
        {
            "nodes": [{"isResolved": True}] * 100,
            "pageInfo": {"hasNextPage": True, "endCursor": "1"},
        },
        {
            "nodes": [{"isResolved": True}],
            "pageInfo": {"hasNextPage": False, "endCursor": None},
        },
    ]
    result = execute(api, tmp_path)
    assert result["results"][0]["outputs"]["approved"] == "true"
    for name in ("comments", "events", "checks", "reviews"):
        assert any(
            c["name"] == name and c["args"].get("page") == 2 for c in result["calls"]
        )
    assert any(
        c["name"] == "threads" and c["args"]["cursor"] == "1" for c in result["calls"]
    )


@pytest.mark.parametrize(
    "change",
    [
        "no-policy",
        "experimental",
        "wildcard",
        "tag",
        "both-missing-type",
        "wrong-detail",
        "no-reviewer",
        "self-review",
        "team",
        "only-owner",
        "environment-api-denied",
    ],
)
def test_live_requires_verified_main_only_environment_and_independent_reviewer(
    api, tmp_path, change
):
    live(api)
    if change == "no-policy":
        api["policies"] = []
    elif change in {"experimental", "wildcard"}:
        api["policies"][0]["name"] = "experimental" if change == "experimental" else "*"
    elif change == "tag":
        api["policies"][0]["type"] = "tag"
    elif change in {"both-missing-type", "wrong-detail"}:
        del api["policies"][0]["type"]
        if change == "both-missing-type":
            del api["policy_detail"]["type"]
        else:
            api["policy_detail"]["node_id"] = "different"
    elif change == "no-reviewer":
        api["environment"]["protection_rules"] = []
    elif change == "self-review":
        api["environment"]["protection_rules"][0]["prevent_self_review"] = False
    elif change == "team":
        api["environment"]["protection_rules"][0]["reviewers"][0]["type"] = "Team"
    elif change == "only-owner":
        api["environment"]["protection_rules"][0]["reviewers"][0]["reviewer"] = OWNER
    else:
        api["error_at"] = "environment"
    result = execute(api, tmp_path)
    refused(result)
    assert not result["writes"]


def test_missing_list_type_uses_same_detail_explicit_branch_proof(api, tmp_path):
    live(api)
    del api["policies"][0]["type"]
    result = execute(
        api,
        tmp_path,
        operations=[{"name": "verify"}, {"name": "verify", "recheck": True}],
    )
    assert all(r["outputs"]["approved"] == "true" for r in result["results"])
    assert any(c["name"] == "policy-detail" for c in result["calls"])
    assert any(c["name"] == "approvals" for c in result["calls"])


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "owner",
        "unknown-user",
        "rejected",
        "bypass",
        "wrong-environment",
        "api-denied",
    ],
)
def test_actual_environment_approval_is_required_after_wait(api, tmp_path, change):
    live(api)
    if change == "missing":
        api["approvals"] = []
    elif change == "owner":
        api["approvals"][0]["user"] = OWNER
    elif change == "unknown-user":
        api["approvals"][0]["user"] = {**REVIEWER, "id": 999}
    elif change in {"rejected", "bypass"}:
        api["approvals"][0]["state"] = change
    elif change == "wrong-environment":
        api["approvals"][0]["environments"][0]["id"] = 99
    result = execute(
        api,
        tmp_path,
        operations=[
            {"name": "verify"},
            {
                "name": "verify",
                "recheck": True,
                "patch": {"error_at": "approvals"} if change == "api-denied" else {},
            },
        ],
    )
    assert result["results"][0]["outputs"]["approved"] == "true"
    refused(result)
    assert len([w for w in result["writes"] if w["name"] == "ref"]) == 1


@pytest.mark.parametrize("change", ["main", "candidate", "decision", "environment"])
def test_changes_while_waiting_cannot_consume_hoben_secrets(api, tmp_path, change):
    live(api)
    updated = copy.deepcopy(api)
    if change == "main":
        updated["branches"]["main"]["commit"]["sha"] = HEAD
    elif change == "candidate":
        updated["branches"]["experimental"]["commit"]["sha"] = HEAD
    elif change == "decision":
        updated["comments"][0]["updated_at"] = "2026-10-09T00:00:02Z"
    else:
        updated["environment"]["updated_at"] = "2026-10-09T00:00:04Z"
    key = {
        "main": "branches",
        "candidate": "branches",
        "decision": "comments",
        "environment": "environment",
    }[change]
    result = execute(
        api,
        tmp_path,
        operations=[
            {"name": "verify"},
            {"name": "verify", "recheck": True, "patch": {key: updated[key]}},
        ],
    )
    assert result["results"][0]["outputs"]["approved"] == "true"
    refused(result)


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "main",
        "pr",
        "failed-run",
        "ci-run",
        "observations",
        "report-missing",
        "report-expired",
        "report-sha",
        "latest-failure",
        "wrong-url",
    ],
)
def test_live_requires_real_successful_dry_run_for_same_sha_and_gate(
    api, tmp_path, change
):
    live(api)
    if change == "missing":
        api["claims"] = {}
    elif change in {"main", "pr"}:
        stamp = json.loads(next(iter(api["claims"].values()))["message"])
        stamp["main_sha" if change == "main" else "pull_request"] = (
            HEAD if change == "main" else 56
        )
        next(iter(api["claims"].values()))["message"] = json.dumps(stamp)
    elif change == "failed-run":
        api["runs"]["120"]["conclusion"] = "failure"
    elif change == "ci-run":
        api["runs"]["120"]["path"] = ".github/workflows/validate.yml"
    elif change == "observations":
        api["jobs"]["120"].append({"name": "observations", "conclusion": "success"})
    elif change == "report-missing":
        api["artifacts"]["120"] = []
    elif change == "report-expired":
        api["artifacts"]["120"][0]["expired"] = True
    elif change == "report-sha":
        api["artifacts"]["120"][0]["workflow_run"]["head_sha"] = HEAD
    elif change == "latest-failure":
        api["combined"]["statuses"].insert(
            0, {**api["combined"]["statuses"][0], "state": "failure"}
        )
    else:
        api["combined"]["statuses"][0]["target_url"] += "0"
    result = execute(api, tmp_path)
    refused(result, "dry_run_required")
    assert not result["writes"]


@pytest.mark.parametrize("state", ["in_progress", "waiting"])
def test_concurrent_campaign_on_second_page_is_refused(api, tmp_path, state):
    api["active"] = [
        {"id": i, "status": state, "path": "unrelated"} for i in range(100)
    ]
    api["active"].append(
        {
            "id": 1001,
            "status": state,
            "path": ".github/workflows/opened-client-boundary.yml",
        }
    )
    result = execute(api, tmp_path)
    refused(result, "concurrent_hoben_run")
    assert not result["writes"]


def test_real_dry_report_only_uses_trusted_crypto_no_candidate_or_hoben(api, tmp_path):
    result = execute(
        api,
        tmp_path,
        operations=[{"name": "dry"}],
        env={"HOBEN_USER_GUID": "SYNTHETIC_PRIVATE_TOKEN_PACKET"},
    )
    assert (
        not result["results"][0]["failed"]
        and not result["calls"]
        and not result["writes"]
    )
    directory = tmp_path / "work/hoben-experimental-exports"
    report = json.loads((directory / "report.json").read_text())
    assert report["candidate_sha"] == SHA and report["executed_sessions"] == 0
    assert report["boundary_proven"] is False
    assert set(p.name for p in directory.iterdir()) == {"report.json"}
    assert directory.stat().st_mode & 0o777 == 0o700
    assert (directory / "report.json").stat().st_mode & 0o777 == 0o600


def public_report(*, phase="live", result="inconclusive"):
    report = {
        "schema": 1,
        "scenario": "h1h2",
        "phase": phase,
        "main_sha": MAIN,
        "candidate_sha": SHA,
        "run_id": 123,
        "boundary_proven": False,
        "result": result,
        "reason": "hypotheses_unproven",
        "executed_sessions": 0,
    }
    if phase == "live":
        sessions = (
            [
                {
                    "mode": "H1" if i < 6 else "H2",
                    "pause_seconds": (0, 0.1, 1)[(i % 6) // 2],
                    "repetition": i % 2 + 1,
                    "partial": True,
                    "prefix_complete": False,
                    "rx_bytes": 0,
                    "read_calls": 1,
                    "pongs_before_open": 0,
                    "pongs_under_h2": 0,
                    "v4_requests": 0,
                    "correlated_responses": 0,
                    "exception_responses": 0,
                    "stop": "peer_eof",
                    "emission_stop": None,
                    "opening_context": {"eligible": False, "status": "missing_opening"},
                    "h1_status": "inconclusive",
                    "h2_status": "inconclusive",
                    "comparison": "insufficient_data",
                }
                for i in range(12)
            ]
            if result == "inconclusive"
            else []
        )
        report.update(
            observation_seconds=90,
            planned_sessions=12,
            eligible_sessions=0,
            executed_sessions=len(sessions),
            sessions=sessions,
        )
    else:
        report.update(result="dry_run_pass", reason="no_hoben_connection")
    if result == "failure":
        report["reason"] = "collection_interrupted"
    return report


def publish_env():
    return {
        "EXPERIMENTAL_CLAIMED": "true",
        "EXPERIMENTAL_APPROVED": "true",
        "EXPERIMENTAL_JOB_RESULT": "success",
        "EXPERIMENTAL_COLLECT_RESULT": "success",
    }


def test_failure_report_cannot_be_relabelled_success_by_job_conclusion(api, tmp_path):
    live(api)
    result = execute(
        api,
        tmp_path,
        operations=[{"name": "verify"}, {"name": "publish", "env": publish_env()}],
        report=public_report(result="failure"),
    )
    assert not result["results"][-1]["failed"]
    assert result["writes"][-2]["args"]["state"] == "failure"
    assert "live: failure" in result["writes"][-1]["args"]["body"]


@pytest.mark.parametrize(
    "change",
    ["private", "proof", "sha", "run", "nan", "free-text", "counts", "h1-pong"],
)
def test_publication_never_trusts_extra_private_fields_or_impossible_counts(
    api, tmp_path, change
):
    live(api)
    report = public_report()
    if change == "private":
        report["UserGuid"] = "SYNTHETIC_PRIVATE_TOKEN_PACKET"
    elif change == "proof":
        report["boundary_proven"] = True
    elif change == "sha":
        report["candidate_sha"] = HEAD
    elif change == "run":
        report["run_id"] = 120
    elif change == "nan":
        report["executed_sessions"] = float("nan")
    elif change == "free-text":
        report["reason"] = "SYNTHETIC_PRIVATE_TOKEN_PACKET"
    else:
        # Keep the complete campaign so rejection exercises the impossible
        # counters themselves, independently of the short-campaign guard.
        report["sessions"][0].update(
            pongs_under_h2=int(change == "h1-pong"),
            exception_responses=int(change == "counts"),
        )
    result = execute(
        api,
        tmp_path,
        operations=[{"name": "verify"}, {"name": "publish", "env": publish_env()}],
        report=report,
    )
    assert result["results"][-1]["failed"]
    assert result["writes"][-2]["args"]["state"] == "failure"


def test_publication_is_idempotent_and_unclaimed_replay_cannot_clobber_status(
    api, tmp_path
):
    ops = [
        {"name": "verify"},
        {"name": "publish", "env": publish_env()},
        {"name": "publish"},
        {
            "name": "publish",
            "env": {"EXPERIMENTAL_CLAIMED": "false", "EXPERIMENTAL_APPROVED": "false"},
        },
    ]
    result = execute(
        api, tmp_path, operations=ops, report=public_report(phase="dry-run")
    )
    assert len([w for w in result["writes"] if w["name"] == "comment"]) == 1
    assert len([w for w in result["writes"] if w["name"] == "status"]) == 3


@pytest.mark.parametrize(
    "state,conclusion,expected",
    [
        ("queued", None, "queued"),
        ("waiting", None, "queued"),
        ("in_progress", None, "running"),
        ("completed", "success", "success"),
        ("completed", "failure", "failure"),
        ("completed", "cancelled", "cancelled"),
    ],
)
def test_repeated_discovery_after_an_hour_is_read_only_and_sha_bound(
    api, tmp_path, state, conclusion, expected
):
    api["claims"][f"hoben-experimental-dry-run-h1h2-{SHA}"] = claim_tag(id=123)
    api["runs"]["123"].update(status=state, conclusion=conclusion)
    api["artifacts"]["123"] = [artifact(123)]
    api["combined"]["statuses"][0]["target_url"] = (
        f"https://github.com/{REPO}/actions/runs/123"
    )
    result = execute(
        api,
        tmp_path,
        operations=[
            {"name": "discover"},
            {"name": "discover", "now": "2026-10-09T01:00:00Z"},
        ],
    )
    assert not result["writes"]
    assert result["results"][0] == result["results"][1]
    observed = result["results"][0]["result"]
    assert (
        observed["state"] == expected
        and observed["run_id"] == 123
        and observed["sha"] == SHA
    )
    assert observed["report_artifact_id"] == 777


def test_live_skipped_collection_is_not_run_and_wrong_run_is_not_discovered(
    api, tmp_path
):
    live(api)
    api["claims"][f"hoben-experimental-live-h1h2-{SHA}"] = claim_tag("live", 123)
    api["runs"]["123"].update(status="completed", conclusion="failure")
    api["jobs"]["123"] = [
        {"name": "request", "conclusion": "success"},
        {"name": "observations", "conclusion": "skipped"},
    ]
    api["combined"]["statuses"] = []
    result = execute(api, tmp_path, operations=[{"name": "discover"}])
    assert result["results"][0]["result"]["state"] == "NOT RUN" and not result["writes"]
    api["runs"]["123"]["head_sha"] = HEAD
    result = execute(api, tmp_path, operations=[{"name": "discover"}])
    assert result["results"][0]["failed"] and not result["writes"]


def test_workflow_has_no_automatic_live_trigger_and_separates_secret_and_write_jobs():
    text = (ROOT / WORKFLOW).read_text()
    workflow = yaml.load(text, Loader=yaml.BaseLoader)
    assert workflow["on"] == {"issues": {"types": ["labeled"]}}
    assert workflow["concurrency"]["cancel-in-progress"] == "false"
    jobs = workflow["jobs"]
    assert jobs["observations"]["environment"] == "hoben-experimental"
    assert set(jobs["observations"]["permissions"].values()) == {"read"}
    for name in ("request", "dry-run", "publish"):
        assert "environment" not in jobs[name] and "HOBEN_" not in json.dumps(
            jobs[name]
        )
    for job in jobs.values():
        for step in job["steps"]:
            if step.get("uses", "").startswith("actions/checkout@"):
                assert step["with"]["persist-credentials"] == "false"
            if step.get("uses", "").startswith("actions/upload-artifact@"):
                assert step["with"]["retention-days"] == "7"
                assert "*" not in step["with"]["path"]
    assert "candidate" not in json.dumps(jobs["publish"])
    assert "captures.cms" not in json.dumps(jobs["publish"])
    assert (
        jobs["observations"]["steps"][1]["with"]["ref"]
        == "${{ needs.request.outputs.sha }}"
    )
