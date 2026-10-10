"use strict";
const {test} = require("node:test");
const assert = require("node:assert/strict");
const gate = require("../../.github/scripts/experimental-lab-gate.cjs");
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
  const approval = {schema: 1, scenario: "h1h2", candidate_sha: head, ci_run_id: 456};
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
    protection_rules: []};
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
  a.history.push({state: "approved",
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

test("fixed public categories never expose arbitrary error messages or data", () => {
  const categories = {
    invalid_provenance: "provenance",
    "NOT RUN: experimental merge/identity/HEAD gate not satisfied": "provenance",
    preflight_unverified: "preflight",
    merge_changed: "merge",
    manager_decision_unverified: "decision",
    review_unverified: "decision",
    ci_unverified: "ci",
    environment_api_inaccessible: "environment_api",
    environment_response_incomplete: "environment_response",
    environment_branch_invalid: "environment_branch",
    environment_reviewers_invalid: "environment_reviewers",
    claim_unverified: "claim",
    approval_unverified: "approval",
  };
  for (const [input, expected] of Object.entries(categories)) {
    assert.equal(gate.refusalCategory(new Error(input)), expected);
    assert.match(expected, /^[a-z_]+$/);
  }
  for (const dangerous of [
    "API 403: https://private.invalid/path?token=SYNTHETIC_SECRET",
    "environment_api_inaccessible; RX=SYNTHETIC_PRIVATE_PACKET",
    "HOBEN_USER_GUID=SYNTHETIC_PRIVATE_VALUE",
    "manager_decision_unverified\\nAuthorization: SYNTHETIC_SECRET",
    null, undefined, {}, {message: "environment_api_inaccessible"},
  ]) {
    const source = typeof dangerous === "string" ? new Error(dangerous) : dangerous;
    assert.equal(gate.refusalCategory(source), "other");
  }
});

test("every environment refusal uses a stable, non-sensitive public category and no claim", async () => {
  const cases = [
    ["api denied", "environment_api", a => {
      a.github.rest.repos.getEnvironment = async () => {
        throw Object.assign(new Error("SYNTHETIC_PRIVATE_HEADER"), {status: 403});
      };
    }],
    ["environment missing", "environment_response", a => {
      a.github.rest.repos.getEnvironment = async () => ({data: null});
    }],
    ["branch wildcard", "environment_branch", a => { a.branch.name = "*"; }],
    ["branch protection disabled", "environment_branch", a => {
      a.environment.deployment_branch_policy.custom_branch_policies = false;
    }],
    ["malformed reviewer rule", "environment_reviewers", a => {
      requireIndependentReviewer(a); a.environment.protection_rules[0].reviewers = [];
    }],
    ["self review permitted", "environment_reviewers", a => {
      requireIndependentReviewer(a); a.environment.protection_rules[0].prevent_self_review = false;
    }],
    ["team not verified", "environment_reviewers", a => {
      requireIndependentReviewer(a); a.environment.protection_rules[0].reviewers[0].type = "Team";
    }],
  ];
  for (const [title, category, mutate] of cases) {
    const a = setup(); mutate(a);
    await assert.rejects(gate.verify(a), error => {
      assert.equal(gate.refusalCategory(error), category, title);
      assert.match(error.message, /^environment_[a-z_]+$/);
      assert.ok(!error.message.includes("SYNTHETIC_PRIVATE"));
      return true;
    });
    assert.equal(a.writes, 0, title);
    assert.equal(a.refs.size, 0, title);
    assert.equal(a.tags.size, 0, title);
  }
});

test("decision, merge, CI failures are categorized before any reservation", async () => {
  for (const [category, mutate] of [
    ["merge", a => {
      // First GitHub lookup passes provenance; changed PR on re-read must
      // fail the independent merge gate before claims or secrets.
      let calls = 0;
      a.github.rest.pulls.get = async () =>
        ({data: ++calls === 1 ? a.pr : {...a.pr, merged: false}});
    }],
    ["decision", a => { a.comments = []; }],
    ["ci", a => { a.jobs[0].conclusion = "failure"; }],
  ]) {
    const a = setup(); mutate(a);
    await assert.rejects(gate.verify(a), error => {
      assert.equal(gate.refusalCategory(error), category);
      return true;
    });
    assert.equal(a.writes, 0);
  }
});

test("approval failure after reservation is categorized without repeating admission", async () => {
  const a = setup(); requireIndependentReviewer(a); await gate.verify(a);
  a.history[0].state = "rejected";
  await assert.rejects(gate.verify({...a, recheck: true}), error => {
    assert.equal(gate.refusalCategory(error), "approval");
    return true;
  });
  assert.equal(a.writes, 1);
});

test("new report-only decision rejects any arbitrary certificate or secret parameter", async () => {
  const a = setup();
  a.approval.recipient_sha256 = "0".repeat(64); a.decision();
  await assert.rejects(gate.verify(a), /manager_decision_unverified/);
  assert.equal(a.writes, 0);
});

test("a superseded decision on an earlier HEAD is history, never an approval of the new HEAD", async () => {
  const a = setup();
  a.comments.unshift({...a.comment, id: 1, body: gate.MARKER + "\n" + JSON.stringify({...a.approval, candidate_sha: "f".repeat(40)})});
  await gate.verify(a);
  const b = setup(); b.comments = [a.comments[0]];
  await assert.rejects(gate.verify(b), /manager_decision_unverified/);
});

test("missing MANAGER approval remains a hard refusal even for Issue-less PRs", async () => {
  const a = setup();
  a.pr.body = "Documentation-only change without an Issue reference";
  a.issues.state = "closed";
  a.issues.labels = [{name: "state:blocked"}];
  a.comments = [];
  await assert.rejects(gate.verify(a), error => {
    assert.equal(gate.refusalCategory(error), "decision");
    return true;
  });
  assert.equal(a.writes, 0);
});

for (const type of ["code", "tests", "documentation", "workflow"]) {
  for (const linked of [true, false]) {
    test("MANAGER-reviewed " + type + " PR " + (linked ? "with" : "without") +
      " Refs #54 can be selected safely", async () => {
      const a = setup();
      a.pr.body = type + (linked ? " Refs #54" : " — unrelated to issue #54");
      a.issues.state = "closed";
      a.issues.labels = [{name: "state:blocked"}];
      const result = await gate.verify(a);
      assert.equal(result.status, "READY FOR ENVIRONMENT");
      assert.equal(a.writes, 1);
      assert.equal((await gate.verify({...a, recheck: true})).status, "approved");
    });
  }
}



function nativeRerun(a, number, includeApproval = true) {
  a.env.GITHUB_RUN_ATTEMPT = String(number);
  a.run.run_attempt = number;
  a.run.triggering_actor = {...user};
  const dry = {name: "dry-run", id: 501, run_id: 123, run_attempt: number,
    head_sha: sha, status: "completed", conclusion: "success",
    started_at: "2026-10-09T08:12:00Z"};
  const admission = {name: "admission", id: 502, run_id: 123, run_attempt: number,
    head_sha: sha, status: "in_progress", conclusion: null};
  const collect = {name: "collect", id: 503, run_id: 123, run_attempt: number,
    head_sha: sha, status: "in_progress", conclusion: null};
  a.rerunJobs = [dry, admission, collect];
  a.github.rest.actions.listJobsForWorkflowRun = async p =>
    ({data: p.run_id === 123 ? a.rerunJobs : a.jobs});
  a.github.rest.actions.listJobsForWorkflowRunAttempt = async p =>
    ({data: [{name: "dry-run", run_attempt: p.attempt_number,
      conclusion: "success"}]});
  const original = a.github.rest.git.createRef;
  a.github.rest.git.createRef = async args => {
    const response = await original(args);
    admission.status = "completed"; admission.conclusion = "success";
    return response;
  };
  if (includeApproval) {
    const decision = {schema: 2, scenario: "h1h2", candidate_sha: head,
      ci_run_id: 456, pr_number: a.pr.number, merge_sha: sha,
      run_id: a.context.runId, run_attempt: number};
    a.comments.push({id: 3000 + number, user: {...user},
      created_at: "2026-10-09T08:11:00Z",
      updated_at: "2026-10-09T08:11:00Z",
      body: gate.MARKER_V2 + "\\n" + JSON.stringify(decision)});
  }
  return a;
}

for (const attempt of [2, 3]) {
  test("native full rerun " + attempt + " admits new decision, reserves exactly once", async () => {
    const a = nativeRerun(setup(), attempt);
    const proof = {number: attempt, beganAt: Date.parse("2026-10-09T08:12:00Z")};
    assert.equal(require("../../.github/scripts/experimental-native-rerun.cjs")
      .authorizeDecision({comments: a.comments, marker: gate.MARKER_V2,
        scenario: "h1h2", candidateSha: head, ciId: 456, pr: a.pr,
        mergeSha: sha, runId: a.context.runId, proof}).approval.run_attempt, attempt);
    assert.equal((await gate.verify(a)).status, "READY FOR ENVIRONMENT");
    assert.equal(a.writes, 1);
    assert.match([...a.refs.keys()][0], new RegExp("-run123-attempt" + attempt + "$"));
    assert.equal((await gate.verify({...a, recheck: true})).status, "approved");
    await assert.rejects(gate.verify(a));
    assert.equal(a.writes, 1);
  });

  for (const [cause, mutator] of [
    ["absent fresh decision", a => {a.comments = [a.comment];}],
    ["partial job rerun stale dry-run", a => {a.rerunJobs[0].run_attempt = 1;}],
    ["partial job rerun stale admission", a => {a.rerunJobs[1].run_attempt = 1;}],
    ["untrusted triggering actor", a => {a.run.triggering_actor.id = 1;}],
    ["untrusted env triggering actor", a => {a.env.GITHUB_TRIGGERING_ACTOR = "untrusted";}],
    ["duplicate approval", a => {a.comments.push({...a.comments.at(-1), id: 9898});}],
    ["approval modified", a => {a.comments.at(-1).updated_at = "2026-10-09T08:11:01Z";}],
    ["invalid CI", a => {a.jobs[0].conclusion = "failure";}],
    ["invalid branch", a => {a.pr.base.ref = "main";}],
    ["policy denied", a => {a.environment.name = "untrusted";}],
  ]) {
    test("NOT RUN " + attempt + " " + cause, async () => {
      const a = nativeRerun(setup(), attempt);
      mutator(a);
      await assert.rejects(gate.verify(a));
      assert.equal(a.writes, 0);
    });
  }
}


test("native rerun requires a NEW actual independent environment approval", async () => {
  const a = nativeRerun(setup(), 2);
  requireIndependentReviewer(a);
  assert.equal((await gate.verify(a)).status, "PENDING APPROVAL");
  await assert.rejects(gate.verify({...a, recheck: true}), /approval_unverified/);
  a.history[0].created_at = "2026-10-09T08:11:59Z";
  await assert.rejects(gate.verify({...a, recheck: true}), /approval_unverified/);
  a.history[0].created_at = "2026-10-09T08:12:01Z";
  assert.equal((await gate.verify({...a, recheck: true})).status, "approved");
});

test("native rerun recheck refuses changed policy or decision even with a claim", async () => {
  const a = nativeRerun(setup(), 3);
  await gate.verify(a);
  a.comments.at(-1).updated_at = "2026-10-09T08:11:01Z";
  await assert.rejects(gate.verify({...a, recheck: true}));
  a.comments.at(-1).updated_at = a.comments.at(-1).created_at;
  a.environment.protection_rules.push({type: "wait_timer", wait_timer: 3});
  await assert.rejects(gate.verify({...a, recheck: true}), /claim_unverified/);
  assert.equal(a.writes, 1);
});
