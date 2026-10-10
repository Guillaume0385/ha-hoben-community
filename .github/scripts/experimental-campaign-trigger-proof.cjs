"use strict";

// Secretless experiment: prove whether a MANAGER-created ref produces a push
// event without touching experimental HEAD or the default branch.
// This gate NEVER authorizes either secret-bearing observation lane.
const API = {owner: "Guillaume0385", repo: "ha-hoben-community"};
const REPOSITORY = "Guillaume0385/ha-hoben-community";
const MANAGER = {login: "Guillaume0385", id: 18246624};
const WORKFLOW = REPOSITORY +
  "/.github/workflows/experimental-campaign-trigger-proof.yml@";
const REF = /^refs\/heads\/(hoben-campaign-proof\/([0-9a-f]{16,32}))$/;
const SHA = /^[a-f0-9]{40}$/;
const ZERO = "0".repeat(40);

function need(value) {
  if (!value) throw Error("trigger_proof_refused");
}

async function verify({github, context, env = process.env}) {
  const match = typeof context.ref === "string" ? REF.exec(context.ref) : null;
  const payload = context.payload || {};
  need(match !== null &&
    context.eventName === "push" && context.actor === MANAGER.login &&
    SHA.test(context.sha) &&
    env.GITHUB_ACTIONS === "true" &&
    env.GITHUB_REPOSITORY === REPOSITORY &&
    env.GITHUB_EVENT_NAME === "push" &&
    env.GITHUB_REF === context.ref &&
    env.GITHUB_SHA === context.sha &&
    env.GITHUB_WORKFLOW_SHA === context.sha &&
    env.GITHUB_WORKFLOW_REF === WORKFLOW + context.ref &&
    env.GITHUB_ACTOR === MANAGER.login &&
    env.GITHUB_TRIGGERING_ACTOR === MANAGER.login &&
    env.GITHUB_RUN_ATTEMPT === "1" &&
    payload.ref === context.ref &&
    payload.after === context.sha &&
    payload.before === ZERO &&
    payload.created === true &&
    payload.deleted === false &&
    payload.forced === false &&
    payload.repository?.full_name === REPOSITORY &&
    payload.repository.id === 1401398724 &&
    payload.sender?.login === MANAGER.login &&
    payload.sender.id === MANAGER.id &&
    payload.sender.type === "User");
  // Compare two independent API reads. A branch name or a push alone does
  // not attest that reviewed code still equals protected experimental HEAD.
  const [{data: stable}, {data: proof}] = await Promise.all([
    github.rest.repos.getBranch({...API, branch: "experimental"}),
    github.rest.repos.getBranch({...API, branch: match[1]})
  ]);
  need(stable?.name === "experimental" &&
    stable.protected === true &&
    stable.commit?.sha === context.sha &&
    proof?.name === match[1] &&
    proof.commit?.sha === context.sha);
  return Object.freeze({
    status: "SECRETLESS_TRIGGER_OBSERVED",
    scenario: "none",
    campaign_id: match[2],
    sha: context.sha,
    authorized_live: false
  });
}

module.exports = {verify, WORKFLOW, REF};
