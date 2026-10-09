"use strict";

// Secretless dry-run only. Never call Hoben, read secrets, or grant live access.
const REPOSITORY = "Guillaume0385/ha-hoben-community";
const MANAGER = "Guillaume0385";
const BRANCH = "experimental";
const WORKFLOW = REPOSITORY + "/.github/workflows/experimental-manager-preflight.yml@refs/heads/experimental";
const LAB_WORKFLOW = REPOSITORY + "/.github/workflows/hoben-experimental.yml@refs/heads/experimental";
const SCENARIOS = Object.freeze(["hoben-live", "hoben-experimental"]);
const SHA = /^[a-f0-9]{40}$/;

function deny() {
  throw new Error("NOT RUN: experimental merge/identity/HEAD gate not satisfied");
}

function isSha(value) {
  return typeof value === "string" && SHA.test(value);
}

async function verify({ github, context, scenario, env = process.env, workflow = WORKFLOW }) {
  const p = context.payload || {};
  if (![WORKFLOW, LAB_WORKFLOW].includes(workflow) ||
      !SCENARIOS.includes(scenario) ||
      context.eventName !== "push" ||
      context.ref !== "refs/heads/" + BRANCH ||
      context.actor !== MANAGER ||
      env.GITHUB_ACTOR !== MANAGER ||
      env.GITHUB_TRIGGERING_ACTOR !== MANAGER ||
      env.GITHUB_RUN_ATTEMPT !== "1" ||
      env.GITHUB_WORKFLOW_REF !== workflow ||
      env.GITHUB_REPOSITORY !== REPOSITORY ||
      env.GITHUB_REF !== context.ref ||
      env.GITHUB_SHA !== context.sha ||
      p.repository?.full_name !== REPOSITORY ||
      p.repository?.id !== 1401398724 ||
      p.sender?.login !== MANAGER ||
      p.ref !== context.ref ||
      p.created === true || p.deleted === true || p.forced === true ||
      !isSha(context.sha) || p.after !== context.sha || !isSha(p.before) ||
      p.before === context.sha) {
    deny();
  }

  const owner = "Guillaume0385";
  const repo = "ha-hoben-community";
  const branchResponse = await github.rest.repos.getBranch({ owner, repo, branch: BRANCH });
  if (branchResponse.data?.protected !== true ||
      branchResponse.data?.commit?.sha !== context.sha) {
    deny();
  }

  const associated = await github.rest.repos.listPullRequestsAssociatedWithCommit({
    owner, repo, commit_sha: context.sha, per_page: 100,
  });
  const candidates = (associated.data || []).filter(pr =>
    pr?.merge_commit_sha === context.sha &&
    pr?.base?.ref === BRANCH &&
    pr?.base?.repo?.full_name === REPOSITORY &&
    pr?.head?.repo?.full_name === REPOSITORY &&
    pr?.merged_at != null && pr?.state === "closed"
  );
  // Ambiguous results are never an authorization.
  if (candidates.length !== 1 || !Number.isSafeInteger(candidates[0].number)) {
    deny();
  }
  const number = candidates[0].number;
  const detail = await github.rest.pulls.get({ owner, repo, pull_number: number });
  const pr = detail.data;
  if (pr?.merged !== true || !pr?.merged_at ||
      pr?.merged_by?.login !== MANAGER ||
      pr?.merge_commit_sha !== context.sha ||
      pr?.base?.ref !== BRANCH ||
      pr?.base?.repo?.full_name !== REPOSITORY ||
      pr?.head?.repo?.full_name !== REPOSITORY ||
      pr?.number !== number || pr?.draft === true) {
    deny();
  }

  return Object.freeze({ scenario, sha: context.sha, pr: number, status: "dry-run-only" });
}

module.exports = { verify, REPOSITORY, WORKFLOW, LAB_WORKFLOW, SCENARIOS };
