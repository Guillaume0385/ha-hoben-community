"use strict";
const {test} = require("node:test");
const assert = require("node:assert/strict");
const gate = require("../../.github/scripts/session-300-gate.cjs");
const push = require("../../.github/scripts/experimental-push-preflight.cjs");
const policy = {environment: "hoben-experimental"};
// These tests may exercise local OpenSSL, but never a network transport.
for (const [name, methods] of [["node:net", ["connect", "createConnection"]],
  ["node:tls", ["connect"]], ["node:dns", ["lookup", "resolve"]]]) {
  for (const method of methods) require(name)[method] = () => { throw Error("network forbidden"); };
}
const sha = "a".repeat(40), head = "b".repeat(40);
const repo = {full_name: push.REPOSITORY, id: 1401398724};
const user = {login: "Guillaume0385", id: 18246624, type: "User"};

function setup() {
  const pr = {number: 59, body: "Refs #54", state: "closed", draft: false,
    merged: true, merged_at: "2026-10-09T08:10:00Z", merged_by: {...user}, merge_commit_sha: sha,
    base: {ref: "experimental", repo: {...repo}}, head: {ref: "codex/issue-54-lane", sha: head, repo: {...repo}}};
  const context = {eventName: "push", ref: "refs/heads/experimental", actor: user.login, sha, runId: 123,
    payload: {repository: {...repo}, sender: {...user}, ref: "refs/heads/experimental", after: sha,
      before: "c".repeat(40), created: false, deleted: false, forced: false}};
  const env = {GITHUB_ACTOR: user.login, GITHUB_TRIGGERING_ACTOR: user.login,
    GITHUB_RUN_ATTEMPT: "1", GITHUB_RUN_ID: "123", GITHUB_WORKFLOW_REF: gate.WORKFLOW,
    GITHUB_WORKFLOW_SHA: sha, GITHUB_REPOSITORY: push.REPOSITORY, GITHUB_REF: context.ref, GITHUB_SHA: sha};
  const approval = {schema: 1, scenario: "session-300", candidate_sha: head, ci_run_id: 456};
  const comment = {id: 987, user: {...user}, created_at: "2026-10-09T08:05:00Z",
    updated_at: "2026-10-09T08:05:00Z", body: gate.MARKER + "\n" + JSON.stringify(approval)};
  const ci = {id: 456, head_sha: head, head_branch: pr.head.ref, event: "pull_request", run_attempt: 1,
    status: "completed", conclusion: "success", repository: {...repo}, head_repository: {...repo},
    path: ".github/workflows/validate.yml", updated_at: "2026-10-09T08:00:00Z", pull_requests: []};
  const run = {id: 123, head_sha: sha, head_branch: "experimental", event: "push", run_attempt: 1,
    actor: {...user}, triggering_actor: {...user}, repository: {...repo}, head_repository: {...repo}, path: ".github/workflows/hoben-session-300.yml"};
  const dry = {run_id: 123, run_attempt: 1, started_at: "2026-10-09T08:11:00Z", name: "dry-run", head_sha: sha, status: "completed", conclusion: "success"};
  const jobs = ["tests", "ha-tests", "hacs", "hassfest"].map(name =>
    ({name, head_sha: head, status: "completed", conclusion: "success"}));
  const reviewer = {login: "independent-synthetic-reviewer", id: 999, type: "User"};
  const environment = {id: 789, name: "hoben-experimental",
    deployment_branch_policy: {protected_branches: false, custom_branch_policies: true},
    protection_rules: []};
  const branch = {id: 12, node_id: "SYNTHETIC_POLICY", name: "experimental", type: "branch"};
  const history = [{created_at: "2026-10-09T08:12:00Z", state: "approved", user: {...reviewer}, environments: [{id: 789, name: "hoben-experimental"}]}];
  const refs = new Map(), tags = new Map();
  let counter = 0;
  const world = {pr, context, env, approval, comment, ci, run, dry, jobs, environment, branch,
    history, refs, tags, comments: [comment], reviews: [], threads: [], associated: [pr], issues: {
      number: 54, id: 5768789242, state: "open", labels: [{name: "state:review"}]}, writes: 0};
  world.github = {rest: {
    repos: {
      getBranch: async () => ({data: {protected: true, commit: {sha}}}),
      listPullRequestsAssociatedWithCommit: async () => ({data: world.associated}),
      getEnvironment: async () => ({data: environment}),
      listDeploymentBranchPolicies: async () => ({data: [branch]}),
      getDeploymentBranchPolicy: async () => ({data: {...branch, type: "branch"}}),
    },
    pulls: {get: async () => ({data: pr}), listReviews: async () => ({data: world.reviews})},
    issues: {get: async () => ({data: world.issues}), listComments: async () => ({data: world.comments})},
    actions: {
      getWorkflowRun: async p => ({data: p.run_id === 123 ? run : ci}),
      listJobsForWorkflowRun: async p => ({data: p.run_id === 123 ? [dry, {name: "admission", head_sha: sha, run_id: 123, run_attempt: 1,
        status: world.admissionStatus || (world.writes > 0 ? "completed" : "in_progress"), conclusion: world.writes > 0 ? "success" : null}] : jobs}),
      listWorkflowRunsForRepo: async () => ({data: []}),
    },
    git: {
      getCommit: async p => ({data: {sha: p.commit_sha, tree: {sha: "e".repeat(40)}}}),
      createTag: async p => { const id = (++counter).toString(16).padStart(40, "0");
        tags.set(id, {...p, object: {sha: p.object, type: "commit"}}); return {data: {sha: id}}; },
      createRef: async p => { if (refs.has(p.ref)) throw Error("duplicate claim");
        world.writes++; refs.set(p.ref, {ref: p.ref, object: {type: "tag", sha: p.sha}}); return {data: {}}; },
      getRef: async p => ({data: refs.get("refs/" + p.ref)}),
      getTag: async p => ({data: tags.get(p.tag_sha)}),
    },
  },
  paginate: async (method, parameters) => (await method(parameters)).data,
  graphql: async () => ({repository: {pullRequest: {reviewThreads: {nodes: world.threads,
    pageInfo: {hasNextPage: false, endCursor: null}}}}}),
  request: async () => ({data: history})};
  world.decision = () => { comment.body = gate.MARKER + "\n" + JSON.stringify(approval); };
  return world;
}

test("secretless dry-run does not depend on local CMS keys or public certificates", async () => {
  const a = setup();
  assert.equal((await gate.dryRun(a)).status, "dry-run-only");
  assert.equal(a.writes, 0);
});

function requireIndependentReviewer(a) {
  const reviewer = {login: "independent-synthetic-reviewer", id: 999, type: "User"};
  a.environment.protection_rules = [{
    id: 100, type: "required_reviewers", prevent_self_review: true,
    reviewers: [{type: "User", reviewer}],
  }];
}

test("single maintainer: reviewed SHA, CI and branch policy require no GitHub reviewer", async () => {
  const a = setup();
  assert.equal((await gate.verify(a)).status, "READY FOR ENVIRONMENT");
  assert.equal(a.writes, 1);
  a.github.request = async () => { throw Error("unexpected approvals API read"); };
  assert.equal((await gate.verify({...a, recheck: true})).status, "approved");
  assert.equal(a.writes, 1); // Recheck never writes on the secret runner.
});

test("configured required reviewer cannot be bypassed without real GitHub approval", async () => {
  const a = setup(); requireIndependentReviewer(a);
  assert.equal((await gate.verify(a)).status, "PENDING APPROVAL");
  a.history.splice(0);
  await assert.rejects(gate.verify({...a, recheck: true}), /approval_unverified/);
  a.history.push({created_at: "2026-10-09T08:12:00Z", state: "approved",
    user: {login: "independent-synthetic-reviewer", id: 999, type: "User"},
    environments: [{id: a.environment.id, name: a.environment.name}]});
  assert.equal((await gate.verify({...a, recheck: true})).status, "approved");
  assert.equal(a.writes, 1);
});

const refused = {
  "wrong actor": a => { a.context.actor = "outsider"; },
  "wrong sender": a => { a.context.payload.sender.id = 1; },
  "fork": a => { a.pr.head.repo.full_name = "outsider/fork"; },
  "base main": a => { a.pr.base.ref = "main"; },
  "direct push": a => { a.associated = []; },
  "forced push": a => { a.context.payload.forced = true; },
  "wrong SHA": a => { a.context.payload.after = head; },
  "wrong workflow SHA": a => { a.env.GITHUB_WORKFLOW_SHA = head; },
  "rerun": a => { a.env.GITHUB_RUN_ATTEMPT = "2"; },
  "preflight failed": a => { a.dry.conclusion = "failure"; },
  "preflight skipped": a => { a.dry.conclusion = "skipped"; },
  "preflight SHA": a => { a.dry.head_sha = head; },
  "wrong preflight workflow": a => { a.run.path += "@refs/heads/main"; },
  "no decision": a => { a.comments = []; },
  "untrusted reviewer": a => { a.comment.user = {login: "outsider", id: 1, type: "User"}; },
  "duplicate decision": a => { a.comments.push({...a.comment, id: 2}); },
  "decision edited": a => { a.comment.updated_at = "2026-10-09T08:06:00Z"; },
  "decision post-merge": a => { a.comment.created_at = a.comment.updated_at = "2026-10-09T08:11:00Z"; },
  "decision SHA": a => { a.approval.candidate_sha = sha; a.decision(); },
  "decision scenario": a => { a.approval.scenario = "hoben-live"; a.decision(); },
  "decision arbitrary key": a => { a.approval.script = "anything"; a.decision(); },
  "legacy recipient field": a => { a.approval.recipient_sha256 = "0".repeat(64); a.decision(); },
  "pending changes": a => { a.reviews = [{user: {id: 3}, state: "CHANGES_REQUESTED"}, {user: {id: 3}, state: "COMMENTED"}]; },
  "unresolved thread": a => { a.threads = [{isResolved: false}]; },
  "CI wrong SHA": a => { a.ci.head_sha = sha; },
  "CI wrong branch": a => { a.ci.head_branch = "other"; },
  "CI push instead of PR": a => { a.ci.event = "push"; },
  "CI other PR": a => { a.ci.pull_requests = [{number: 60, head: {sha: head}, base: {ref: "experimental"}}]; },
  "CI base main": a => { a.ci.pull_requests = [{number: 59, head: {sha: head}, base: {ref: "main"}}]; },
  "CI workflow spoof": a => { a.ci.path += "@refs/heads/main"; },
  "CI after decision": a => { a.ci.updated_at = "2026-10-09T08:06:00Z"; },
  "CI missing association field": a => { delete a.ci.pull_requests; },
  "CI green run with failed job": a => { a.jobs[1].conclusion = "failure"; },
  "CI missing HACS": a => { a.jobs.splice(2, 1); },
  "CI duplicate tests": a => { a.jobs[2].name = "tests"; },
  "CI job wrong SHA": a => { a.jobs[0].head_sha = sha; },
  "environment swapped": a => { a.environment.name = "hoben-live"; },
  "unrestricted environment": a => { a.environment.deployment_branch_policy = null; },
  "wildcard branch": a => { a.branch.name = "*"; },
  "tag policy": a => { a.branch.type = "tag"; },
  "self review allowed": a => { requireIndependentReviewer(a);
    a.environment.protection_rules[0].prevent_self_review = false; },
  "only MANAGER reviewer": a => { requireIndependentReviewer(a);
    a.environment.protection_rules[0].reviewers[0].reviewer = {...user}; },
  "team membership unproven": a => { requireIndependentReviewer(a);
    a.environment.protection_rules[0].reviewers[0].type = "Team"; },
  "duplicate reviewer rules": a => { requireIndependentReviewer(a);
    a.environment.protection_rules.push({...a.environment.protection_rules[0]}); },
  "environment API unavailable": a => { a.github.rest.repos.getEnvironment = async () => {throw Error("403");}; },
  "unreviewed merge tree": a => { a.github.rest.git.getCommit = async p =>
    ({data: {sha: p.commit_sha, tree: {sha: p.commit_sha}}}); },
  "another observation": a => { a.github.rest.actions.listWorkflowRunsForRepo = async () =>
    ({data: [{id: 777, path: ".github/workflows/live-validation.yml@refs/heads/main"}]}); },
};
for (const [name, modify] of Object.entries(refused)) {
  test("refuse before reservation/secrets: " + name, async () => {
    const a = setup(); modify(a);
    await assert.rejects(gate.verify(a));
    assert.equal(a.writes, 0);
  });
}

// Historical Hoben workflows lack the common mutex. The API status filter must
// include pre-start runs, and admission AND pre-secret recheck must refuse them.
for (const state of ["requested", "queued", "pending", "waiting", "in_progress"]) {
  test("refuse historical " + state + " before reservation", async () => {
    const a = setup();
    a.github.rest.actions.listWorkflowRunsForRepo = async ({status}) =>
      ({data: status === state
        ? [{id: 777, path: ".github/workflows/live-validation.yml@refs/heads/main"}]
        : []});
    await assert.rejects(gate.verify(a));
    assert.equal(a.writes, 0);
  });
  test("refuse historical " + state + " arising before secret recheck", async () => {
    const a = setup();
    await gate.verify(a);
    a.github.rest.actions.listWorkflowRunsForRepo = async ({status}) =>
      ({data: status === state
        ? [{id: 778, path: ".github/workflows/manager-live-hoben.yml@refs/heads/main"}]
        : []});
    await assert.rejects(gate.verify({...a, recheck: true}));
    assert.equal(a.writes, 1); // claim already reserved; never consumed twice
  });
}
test("refuse an active workflow with unknown identity before reservation", async () => {
  const a = setup();
  a.github.rest.actions.listWorkflowRunsForRepo = async ({status}) =>
    ({data: status === "queued" ? [{id: 778}] : []});
  await assert.rejects(gate.verify(a));
  assert.equal(a.writes, 0);
});

for (const fault of ["missing", "rejected", "wrong-user", "self", "wrong-environment", "policy-changed", "decision-changed", "SHA-changed"]) {
  test("refuse after environment waiting: " + fault, async () => {
    const a = setup(); requireIndependentReviewer(a); await gate.verify(a);
    if (fault === "missing") a.history.splice(0);
    if (fault === "rejected") a.history[0].state = "rejected";
    if (fault === "wrong-user") a.history[0].user.id = 2;
    if (fault === "self") a.history[0].user = {...user};
    if (fault === "wrong-environment") a.history[0].environments[0].name = "hoben-live";
    if (fault === "policy-changed") a.environment.protection_rules[0].id++;
    if (fault === "decision-changed") a.comment.id++;
    if (fault === "SHA-changed") a.github.rest.repos.getBranch = async () => ({data: {protected: true, commit: {sha: head}}});
    await assert.rejects(gate.verify({...a, recheck: true}));
    assert.equal(a.writes, 1);
  });
}

test("three concurrent requests and a cancelled claim cannot repeat the same SHA/scenario", async () => {
  const a = setup();
  const results = await Promise.allSettled([gate.verify(a), gate.verify(a), gate.verify(a)]);
  assert.equal(results.filter(r => r.status === "fulfilled").length, 1);
  assert.equal(a.writes, 1);
  a.admissionStatus = "in_progress";
  await assert.rejects(gate.verify(a), /duplicate/);
});

test("REST branch type missing requires positive detail proof; absence in both refuses", async () => {
  const a = setup(); delete a.branch.type;
  await gate.verify(a);
  const b = setup(); delete b.branch.type;
  b.github.rest.repos.getDeploymentBranchPolicy = async () => ({data: b.branch});
  await assert.rejects(gate.verify(b), /environment_response_incomplete/);
});

// All API failures are simulated offline. A green unit test is not evidence
// that the real GITHUB_TOKEN can read environment settings on a runner.
for (const [endpoint, prepare] of [
  ["getEnvironment", a => "getEnvironment"],
  ["listDeploymentBranchPolicies", a => "listDeploymentBranchPolicies"],
  ["getDeploymentBranchPolicy", a => { delete a.branch.type; return "getDeploymentBranchPolicy"; }],
]) {
  for (const status of [401, 403, 404]) {
    test(`policy API ${endpoint} HTTP ${status}: NOT RUN before claim or secrets`, async () => {
      const a = setup(), method = prepare(a);
      const failure = Object.assign(new Error("synthetic denied"), {status});
      a.github.rest.repos[method] = async () => { throw failure; };
      await assert.rejects(gate.verify(a), /environment_api_inaccessible/);
      assert.equal(a.writes, 0);
      assert.equal(a.refs.size, 0);
      assert.equal(a.tags.size, 0);
    });
  }
}

test("policy reads returning missing data, invalid reviewer rule or wrong branch fail before claim", async () => {
  for (const mutate of [
    a => { a.github.rest.repos.getEnvironment = async () => ({data: null}); },
    a => { a.github.rest.repos.listDeploymentBranchPolicies = async () => ({data: null}); },
    a => { a.github.rest.repos.listDeploymentBranchPolicies = async () => ({data: []}); },
    a => { a.branch.name = "main"; },
    a => { requireIndependentReviewer(a);
      a.environment.protection_rules[0].reviewers = []; },
  ]) {
    const a = setup(); mutate(a);
    await assert.rejects(gate.verify(a));
    assert.equal(a.writes, 0);
    assert.equal(a.refs.size, 0);
  }
});

test("API refusal after environment approval blocks recheck and never starts another claim", async () => {
  const a = setup();
  await gate.verify(a);
  assert.equal(a.writes, 1);
  a.github.rest.repos.getEnvironment = async () => {
    throw Object.assign(new Error("synthetic permission denied"), {status: 403});
  };
  await assert.rejects(gate.verify({...a, recheck: true}), /environment_api_inaccessible/);
  assert.equal(a.writes, 1);
  assert.equal(a.refs.size, 1);
});


test("fresh reviewer timestamp is required and reruns are never admitted", async () => {
  const a = setup(); requireIndependentReviewer(a); await gate.verify(a);
  delete a.history[0].created_at;
  await assert.rejects(gate.verify({...a,recheck:true}));
  assert.equal(a.writes,1);
});
test("HEAD changed during admission cannot reach secrets", async () => {
  const a = setup(); let calls=0;
  a.github.rest.repos.getBranch = async () => ({data:{protected:true,commit:{sha:++calls===1?sha:head}}});
  await assert.rejects(gate.verify(a));
});
test("malformed duplicate owner decision is a refusal", async () => {
  const a=setup();a.comments.push({...a.comment,id:999,body:gate.MARKER+"invalid"});
  await assert.rejects(gate.verify(a));assert.equal(a.writes,0);
});

// Run the same evidence mutations through the suite entry point: the new
// contract must not acquire a parallel, weaker implementation of the gate.
const suiteGate = require("../../.github/scripts/session-suite-gate.cjs");
function suiteSetup() {
  const a = setup();
  Object.assign(a.approval, {scenario: "session-suite", ...structuredClone(suiteGate.CONTRACT)});
  a.decision = () => {a.comment.body = suiteGate.MARKER + "\n" + JSON.stringify(a.approval);};
  a.decision();
  return a;
}

test("suite: fixed contract, independent claim and read-only recheck", async () => {
  const a = suiteSetup();
  assert.equal((await suiteGate.dryRun(a)).scenario, "session-suite");
  assert.equal(a.writes, 0);
  assert.equal((await suiteGate.verify(a)).scenario, "session-suite");
  const name = "refs/tags/hoben-session-suite-" + head;
  assert.deepEqual([...a.refs.keys()], [name]);
  const tag = a.tags.get(a.refs.get(name).object.sha);
  const claim = JSON.parse(tag.message);
  assert.equal(claim.scenario, "session-suite");
  assert.deepEqual(claim.contract, suiteGate.CONTRACT);
  assert.equal((await suiteGate.verify({...a,recheck:true})).status, "approved");
  assert.equal(a.writes, 1);
  assert(Object.isFrozen(suiteGate.CONTRACT.limits.session_300));
  assert(Object.isFrozen(suiteGate.CONTRACT.scenarios));
});

test("suite stays PENDING APPROVAL until a fresh independent approval is verified", async () => {
  const a = suiteSetup(); requireIndependentReviewer(a);
  const fresh = structuredClone(a.history[0]);
  assert.equal((await suiteGate.verify(a)).status, "PENDING APPROVAL");
  assert.equal(a.writes, 1);
  a.history.splice(0);
  await assert.rejects(suiteGate.verify({...a, recheck: true}), /approval_unverified/);
  a.history.push({...fresh, created_at: "2026-10-09T08:00:00Z"});
  await assert.rejects(suiteGate.verify({...a, recheck: true}), /approval_unverified/);
  a.history.splice(0, 1, fresh);
  assert.equal((await suiteGate.verify({...a, recheck: true})).status, "approved");
  assert.equal(a.writes, 1); // Waiting/recheck never create or release another claim.
});

for (const [name, modify] of Object.entries(refused)) {
  test("suite refuses before claim: " + name, async () => {
    const a = suiteSetup(); modify(a);
    await assert.rejects(suiteGate.verify(a));
    assert.equal(a.writes, 0);
  });
}

for (const [name, modify] of Object.entries({
  "scenarios reversed": a => {a.approval.scenarios.reverse();},
  "scenario two alone": a => {a.approval.scenarios.shift();},
  "third scenario": a => {a.approval.scenarios.push("ha-parity");},
  "missing scenarios": a => {delete a.approval.scenarios;},
  "missing limits": a => {delete a.approval.limits;},
  "extra limit": a => {a.approval.limits.destination = "private";},
  "missing max opens": a => {delete a.approval.limits.session_300.max_opens;},
  "larger global budget": a => {a.approval.limits.suite_process_seconds++;},
  "smaller global budget": a => {a.approval.limits.suite_process_seconds--;},
  "boolean limit": a => {a.approval.limits.session_300.max_opens = true;},
  "string limit": a => {a.approval.limits.session_reconnect_no_pong.max_reads = "10";},
  "missing EOF wait": a => {delete a.approval.limits.session_reconnect_no_pong.eof_wait_seconds;},
  "changed stable window": a => {a.approval.limits.session_reconnect_no_pong.stable_seconds = 119;},
  "extra nested limit": a => {a.approval.limits.session_300.script = "private";},
})) {
  test("suite refuses non-fixed contract: " + name, async () => {
    const a = suiteSetup(); modify(a); a.decision();
    await assert.rejects(suiteGate.verify(a), /manager_decision_unverified/);
    assert.equal(a.writes, 0);
  });
}

for (const marker of [gate.MARKER,"<!-- hoben-experimental-approval:v1 -->",
  "<!-- hoben-experimental-approval:v2 -->","<!-- hoben-live-approval:v1 -->"]) {
  test("suite never consumes a legacy approval " + marker, async () => {
    const a = suiteSetup(); a.comment.body = marker + "\n" + JSON.stringify(a.approval);
    await assert.rejects(suiteGate.verify(a), /manager_decision_unverified/);
    assert.equal(a.writes, 0);
  });
}
test("suite marker with old four-field session-300 decision is refused", async () => {
  const a = setup();a.comment.body = suiteGate.MARKER + "\n" + JSON.stringify(a.approval);
  await assert.rejects(suiteGate.verify(a), /manager_decision_unverified/);
  assert.equal(a.writes, 0);
});

test("suite replay: exactly one concurrent claim; cancellation never releases it", async () => {
  const a = suiteSetup();
  const outcomes = await Promise.allSettled([suiteGate.verify(a),suiteGate.verify(a),suiteGate.verify(a)]);
  assert.equal(outcomes.filter(r => r.status === "fulfilled").length, 1);
  a.admissionStatus = "in_progress";
  await assert.rejects(suiteGate.verify(a));
  assert.equal(a.writes, 1);
});

test("old claim cannot substitute for a suite claim, even with matching content", async () => {
  const a = suiteSetup(); await suiteGate.verify(a);
  const name = "refs/tags/hoben-session-suite-" + head;
  const reservation = a.refs.get(name);
  a.refs.delete(name); // Simulated missing evidence, never a real deletion.
  a.refs.set("refs/tags/hoben-session-300-" + head,reservation);
  await assert.rejects(suiteGate.verify({...a,recheck:true}));
  assert.equal(a.writes, 1);
});
test("claim binds fixed limits, ordered scenarios, run and immutable decision", async () => {
  for (const change of [
    c => {c.contract.scenarios.reverse();},
    c => {c.contract.limits.suite_process_seconds++;},
    c => {c.scenario = "session-300";},
    c => {c.run_id++;},
  ]) {
    const a = suiteSetup(); await suiteGate.verify(a);
    const tag = [...a.tags.values()][0], claim = JSON.parse(tag.message);
    change(claim);tag.message = JSON.stringify(claim);
    await assert.rejects(suiteGate.verify({...a,recheck:true}), /claim_unverified/);
    assert.equal(a.writes, 1);
  }
});
for (const fault of ["missing","rejected","wrong-user","self","wrong-environment",
  "policy-changed","decision-changed","SHA-changed"]) {
  test("suite recheck refuses after environment waiting: " + fault, async () => {
    const a = suiteSetup();requireIndependentReviewer(a);await suiteGate.verify(a);
    if (fault === "missing") a.history.splice(0);
    if (fault === "rejected") a.history[0].state = "rejected";
    if (fault === "wrong-user") a.history[0].user.id = 2;
    if (fault === "self") a.history[0].user = {...user};
    if (fault === "wrong-environment") a.history[0].environments[0].name = "hoben-live";
    if (fault === "policy-changed") a.environment.protection_rules[0].id++;
    if (fault === "decision-changed") a.comment.id++;
    if (fault === "SHA-changed") a.github.rest.repos.getBranch = async () =>
      ({data:{protected:true,commit:{sha:head}}});
    await assert.rejects(suiteGate.verify({...a,recheck:true}));
    assert.equal(a.writes,1);
  });
}
test("suite fresh independent approval required after admission", async () => {
  const a = suiteSetup();requireIndependentReviewer(a);
  assert.equal((await suiteGate.verify(a)).status,"PENDING APPROVAL");
  a.history[0].created_at = "2026-10-09T08:00:00Z";
  await assert.rejects(suiteGate.verify({...a,recheck:true}), /approval_unverified/);
  a.history[0].created_at = "2026-10-09T08:12:00Z";
  assert.equal((await suiteGate.verify({...a,recheck:true})).status,"approved");
});
for (const status of ["requested","queued","pending","waiting","in_progress"]) {
  test("suite historical concurrency remains refused at recheck: " + status, async () => {
    const a = suiteSetup();await suiteGate.verify(a);
    a.github.rest.actions.listWorkflowRunsForRepo = async p => ({data:p.status === status
      ? [{id:777,path:".github/workflows/live-validation.yml"}] : []});
    await assert.rejects(suiteGate.verify({...a,recheck:true}), /concurrent_observation/);
    assert.equal(a.writes,1);
  });
}
test("suite profile cannot be selected or weakened by options/env", async () => {
  const a = setup();
  await assert.rejects(suiteGate.verify({...a,contract:{marker:gate.MARKER},scenario:"session-300"}));
  assert.equal(a.writes,0);
  const b = suiteSetup();
  await assert.rejects(gate.verify({...b,contract:{marker:suiteGate.MARKER}}));
  assert.equal(b.writes,0);
});
