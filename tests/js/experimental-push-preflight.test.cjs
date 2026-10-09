"use strict";

const { test } = require("node:test");
const assert = require("node:assert/strict");
const { verify, REPOSITORY, WORKFLOW, SCENARIOS } =
  require("../../.github/scripts/experimental-push-preflight.cjs");

const sha = "a".repeat(40);
const before = "b".repeat(40);
function setup() {
  const pr = {
    number: 57, state: "closed", merged: true, merged_at: "2026-10-09T08:00:00Z",
    merged_by: { login: "Guillaume0385" }, merge_commit_sha: sha, draft: false,
    base: { ref: "experimental", repo: { full_name: REPOSITORY } },
    head: { repo: { full_name: REPOSITORY } },
  };
  const context = {
    eventName: "push", ref: "refs/heads/experimental", actor: "Guillaume0385", sha,
    payload: {
      repository: { full_name: REPOSITORY, id: 1401398724 },
      sender: { login: "Guillaume0385" },
      ref: "refs/heads/experimental", after: sha, before, created: false,
      deleted: false, forced: false,
    },
  };
  const env = {
    GITHUB_ACTOR: "Guillaume0385",
    GITHUB_TRIGGERING_ACTOR: "Guillaume0385",
    GITHUB_RUN_ATTEMPT: "1", GITHUB_WORKFLOW_REF: WORKFLOW,
    GITHUB_REPOSITORY: REPOSITORY, GITHUB_REF: context.ref, GITHUB_SHA: sha,
  };
  const github = { rest: {
    repos: {
      getBranch: async () => ({ data: { protected: true, commit: { sha } } }),
      listPullRequestsAssociatedWithCommit: async () => ({ data: [pr] }),
    },
    pulls: { get: async () => ({ data: pr }) },
  }};
  return { github, context, scenario: "hoben-live", env, pr };
}

test("two fixed scenarios pass only the secretless MANAGER merge preflight", async () => {
  assert.deepEqual(SCENARIOS, ["hoben-live", "hoben-experimental"]);
  for (const scenario of SCENARIOS) {
    const args = setup();
    args.scenario = scenario;
    assert.deepEqual(await verify(args), {
      scenario, sha, pr: 57, status: "dry-run-only",
    });
  }
});

const invalid = {
  "unexpected scenario": a => { a.scenario = "read-v4-state"; },
  "wrong actor": a => { a.context.actor = "attacker"; },
  "wrong sender": a => { a.context.payload.sender.login = "attacker"; },
  "rerun": a => { a.env.GITHUB_RUN_ATTEMPT = "2"; },
  "wrong workflow": a => { a.env.GITHUB_WORKFLOW_REF = WORKFLOW.replace("experimental", "main"); },
  "wrong ref": a => { a.context.ref = "refs/heads/main"; a.env.GITHUB_REF = "refs/heads/main"; },
  "wrong repo": a => { a.context.payload.repository.full_name = "attacker/fork"; },
  "wrong repository ID": a => { a.context.payload.repository.id = 123; },
  "wrong SHA": a => { a.context.payload.after = before; },
  "forced push": a => { a.context.payload.forced = true; },
  "deleted ref": a => { a.context.payload.deleted = true; },
  "non-push event": a => { a.context.eventName = "issues"; },
  "untrusted base": a => { a.pr.base.ref = "main"; },
  "fork source": a => { a.pr.head.repo.full_name = "attacker/fork"; },
  "no manager merge": a => { a.pr.merged_by.login = "attacker"; },
  "no merge": a => { a.pr.merged = false; },
  "ambiguous associated PRs": a => {
    a.github.rest.repos.listPullRequestsAssociatedWithCommit =
      async () => ({ data: [a.pr, { ...a.pr, number: 58 }] });
  },
  "no associated PR": a => {
    a.github.rest.repos.listPullRequestsAssociatedWithCommit =
      async () => ({ data: [] });
  },
  "branch SHA changed": a => {
    a.github.rest.repos.getBranch =
      async () => ({ data: { protected: true, commit: { sha: before } } });
  },
  "unprotected branch": a => {
    a.github.rest.repos.getBranch =
      async () => ({ data: { protected: false, commit: { sha } } });
  },
};
for (const [name, modify] of Object.entries(invalid)) {
  test("fail closed: " + name, async () => {
    const args = setup();
    modify(args);
    await assert.rejects(verify(args), /NOT RUN/);
  });
}

test("GitHub API errors never yield success", async () => {
  const args = setup();
  args.github.rest.pulls.get = async () => { throw new Error("403"); };
  await assert.rejects(verify(args), /403/);
});
