"use strict";
const {test} = require("node:test");
const assert = require("node:assert/strict");
const gate = require("../../.github/scripts/experimental-lab-gate.cjs");
const cms = require("../../.github/scripts/experimental-ciphertext.cjs");
const push = require("../../.github/scripts/experimental-push-preflight.cjs");
const policy = require("../../.github/config/hoben-experimental.json");
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
  const approval = {schema: 1, scenario: "h1h2", candidate_sha: head, ci_run_id: 456,
    recipient_sha256: policy.recipient_sha256};
  const comment = {id: 987, user: {...user}, created_at: "2026-10-09T08:05:00Z",
    updated_at: "2026-10-09T08:05:00Z", body: gate.MARKER + "\n" + JSON.stringify(approval)};
  const ci = {id: 456, head_sha: head, head_branch: pr.head.ref, event: "pull_request", run_attempt: 1,
    status: "completed", conclusion: "success", repository: {...repo}, head_repository: {...repo},
    path: ".github/workflows/validate.yml", updated_at: "2026-10-09T08:00:00Z", pull_requests: []};
  const run = {id: 123, head_sha: sha, head_branch: "experimental", event: "push", run_attempt: 1,
    actor: {...user}, repository: {...repo}, head_repository: {...repo}, path: ".github/workflows/hoben-experimental.yml"};
  const dry = {name: "dry-run", head_sha: sha, status: "completed", conclusion: "success"};
  const jobs = ["tests", "ha-tests", "hacs", "hassfest"].map(name =>
    ({name, head_sha: head, status: "completed", conclusion: "success"}));
  const reviewer = {login: "independent-synthetic-reviewer", id: 999, type: "User"};
  const environment = {id: 789, name: "hoben-experimental",
    deployment_branch_policy: {protected_branches: false, custom_branch_policies: true},
    protection_rules: [{id: 100, type: "required_reviewers", prevent_self_review: true,
      reviewers: [{type: "User", reviewer}]}]};
  const branch = {id: 12, node_id: "SYNTHETIC_POLICY", name: "experimental", type: "branch"};
  const history = [{state: "approved", user: {...reviewer}, environments: [{id: 789, name: "hoben-experimental"}]}];
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
      listJobsForWorkflowRun: async p => ({data: p.run_id === 123 ? [dry] : jobs}),
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

test("secretless assembly exercises real CMS before any secret-bearing job", async () => {
  const a = setup();
  assert.equal((await gate.dryRun(a)).status, "dry-run-only");
  assert.equal(a.writes, 0);
});

test("MANAGER decision + all four CI jobs + environment, then independent approval", async () => {
  const a = setup();
  assert.equal((await gate.verify(a)).status, "PENDING APPROVAL");
  assert.equal(a.writes, 1);
  assert.equal((await gate.verify({...a, recheck: true})).status, "approved");
  assert.equal(a.writes, 1); // Recheck never writes on the secret runner.
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
  "decision recipient": a => { a.approval.recipient_sha256 = "0".repeat(64); a.decision(); },
  "no Issue link": a => { a.pr.body = "No authorization"; },
  "blocked Issue": a => { a.issues.labels = [{name: "state:blocked"}]; },
  "closed Issue": a => { a.issues.state = "closed"; },
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
  "no required reviewers": a => { a.environment.protection_rules = []; },
  "self review allowed": a => { a.environment.protection_rules[0].prevent_self_review = false; },
  "only MANAGER reviewer": a => { a.environment.protection_rules[0].reviewers[0].reviewer = {...user}; },
  "team membership unproven": a => { a.environment.protection_rules[0].reviewers[0].type = "Team"; },
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

for (const fault of ["missing", "rejected", "wrong-user", "self", "wrong-environment", "policy-changed", "decision-changed", "SHA-changed"]) {
  test("refuse after environment waiting: " + fault, async () => {
    const a = setup(); await gate.verify(a);
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
  await assert.rejects(gate.verify(a), /duplicate/);
});

test("REST branch type missing requires positive detail proof; absence in both refuses", async () => {
  const a = setup(); delete a.branch.type;
  await gate.verify(a);
  const b = setup(); delete b.branch.type;
  b.github.rest.repos.getDeploymentBranchPolicy = async () => ({data: b.branch});
  await assert.rejects(gate.verify(b), /environment_unverified/);
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
      await assert.rejects(gate.verify(a), /environment_unverified/);
      assert.equal(a.writes, 0);
      assert.equal(a.refs.size, 0);
      assert.equal(a.tags.size, 0);
    });
  }
}

test("policy reads returning missing data, missing reviewer or wrong branch fail before claim", async () => {
  for (const mutate of [
    a => { a.github.rest.repos.getEnvironment = async () => ({data: null}); },
    a => { a.github.rest.repos.listDeploymentBranchPolicies = async () => ({data: null}); },
    a => { a.github.rest.repos.listDeploymentBranchPolicies = async () => ({data: []}); },
    a => { a.branch.name = "main"; },
    a => { a.environment.protection_rules[0].reviewers = []; },
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
  await assert.rejects(gate.verify({...a, recheck: true}), /environment_unverified/);
  assert.equal(a.writes, 1);
  assert.equal(a.refs.size, 1);
});

test("CMS unavailable refuses dry-run and admission before reservations", async () => {
  const original = cms.preflight;
  cms.preflight = () => { throw Error("synthetic crypto failure"); };
  try {
    const a = setup(); await assert.rejects(gate.dryRun(a));
    await assert.rejects(gate.verify(a)); assert.equal(a.writes, 0);
  } finally { cms.preflight = original; }
});

test("a superseded decision on an earlier HEAD is history, never an approval of the new HEAD", async () => {
  const a = setup();
  a.comments.unshift({...a.comment, id: 1, body: gate.MARKER + "\n" + JSON.stringify({...a.approval, candidate_sha: "f".repeat(40)})});
  await gate.verify(a);
  const b = setup(); b.comments = [a.comments[0]];
  await assert.rejects(gate.verify(b), /manager_decision_unverified/);
});
