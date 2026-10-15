"use strict";

// No Hoben I/O here. Admission writes an atomic claim on a separate runner;
// recheck has read-only permissions, after GitHub's environment approval.
const crypto = require("node:crypto");
const push = {REPOSITORY: "Guillaume0385/ha-hoben-community"};
const WORKFLOW = push.REPOSITORY + "/.github/workflows/hoben-session-300.yml@refs/heads/experimental";
const rerun = require("./experimental-native-rerun.cjs");
const policy = {schema: 1, scenario: "session-300", environment: "hoben-experimental"};
const API = { owner: "Guillaume0385", repo: "ha-hoben-community" };
const MANAGER_ID = 18246624;
const REPO_ID = 1401398724;
const MARKER = "<!-- hoben-session-300-approval:v1 -->";
const FILE = ".github/workflows/hoben-session-300.yml";
const SHA = /^[a-f0-9]{40}$/;
const positive = n => Number.isSafeInteger(n) && n > 0;
const digest = v => crypto.createHash("sha256").update(JSON.stringify(v)).digest("hex");
const need = (fact, reason) => { if (!fact) throw new Error(reason); };
const suite = require("./session-suite-contract.cjs");
const legacyContract = Object.freeze({
  marker: MARKER, scenario: "session-300", claimPrefix: "hoben-session-300-",
  validApproval: (a, candidate) => a && !Array.isArray(a) &&
    Object.keys(a).sort().join() === ["schema","scenario","candidate_sha","ci_run_id"].sort().join() &&
    a.schema === 1 && a.scenario === "session-300" && a.candidate_sha === candidate && positive(a.ci_run_id),
});
const suiteContract = Object.freeze({
  marker: suite.MARKER, scenario: "session-suite", claimPrefix: "hoben-session-suite-",
  validApproval: suite.validApproval, claimContract: suite.CONTRACT,
});
// Only these fixed, non-sensitive categories may appear in Actions summaries.
// Never publish an exception message, API response, URL or reviewer identity.
const PUBLIC_REFUSALS = Object.freeze({
  invalid_policy: "provenance",
  invalid_provenance: "provenance",
  "NOT RUN: experimental merge/identity/HEAD gate not satisfied": "provenance",
  preflight_unverified: "preflight",
  merge_changed: "merge",
  merged_tree_unreviewed: "merge",
  manager_decision_unverified: "decision",
  review_unverified: "decision",
  ci_unverified: "ci",
  environment_api_inaccessible: "environment_api",
  environment_response_incomplete: "environment_response",
  environment_branch_invalid: "environment_branch",
  environment_reviewers_invalid: "environment_reviewers",
  concurrent_observation: "claim",
  claim_unverified: "claim",
  approval_unverified: "approval",
  attempt_unverified: "provenance",
  partial_rerun: "preflight",
  decision_unverified: "decision",
});
function refusalCategory(error) {
  const reason = error instanceof Error ? error.message : null;
  return typeof reason === "string" && Object.hasOwn(PUBLIC_REFUSALS, reason)
    ? PUBLIC_REFUSALS[reason] : "other";
}
const sameRepo = r => r?.full_name === push.REPOSITORY && r.id === REPO_ID;

function workflowPath(value, file, allowedRefs) {
  if (typeof value !== "string") return false;
  const [name, ...refs] = value.split("@");
  return name === file && (refs.length === 0 || refs.length === 1 && allowedRefs.includes(refs[0]));
}

async function mergedPush(github, context, env) {
  const p = context.payload || {};
  need(context.eventName === "push" && context.ref === "refs/heads/experimental" &&
    context.actor === "Guillaume0385" && env.GITHUB_ACTOR === context.actor &&
    env.GITHUB_TRIGGERING_ACTOR === context.actor && env.GITHUB_RUN_ATTEMPT === "1" &&
    env.GITHUB_WORKFLOW_REF === WORKFLOW && env.GITHUB_WORKFLOW_SHA === context.sha &&
    env.GITHUB_REPOSITORY === push.REPOSITORY && env.GITHUB_REF === context.ref &&
    env.GITHUB_SHA === context.sha && SHA.test(context.sha) && positive(context.runId) &&
    env.GITHUB_RUN_ID === String(context.runId) && sameRepo(p.repository) &&
    p.sender?.id === MANAGER_ID && p.sender.login === context.actor && p.sender.type === "User" &&
    p.ref === context.ref && p.after === context.sha && SHA.test(p.before) && p.before !== p.after &&
    ["created", "deleted", "forced"].every(k => p[k] === false), "invalid_provenance");
  const {data: branch} = await github.rest.repos.getBranch({...API, branch: "experimental"});
  need(branch?.protected === true && branch.commit?.sha === context.sha, "merge_changed");
  const associated = await github.paginate(github.rest.repos.listPullRequestsAssociatedWithCommit,
    {...API, commit_sha: context.sha, per_page: 100});
  need(Array.isArray(associated), "merge_changed");
  const choices = associated.filter(p => p.merge_commit_sha === context.sha &&
    p.base?.ref === "experimental" && sameRepo(p.base.repo) && sameRepo(p.head?.repo) &&
    p.state === "closed" && p.merged_at);
  need(choices.length === 1 && positive(choices[0].number), "merge_changed");
  return {sha: context.sha, pr: choices[0].number, scenario: "session-300", status: "dry-run-only"};
}

async function dryRun({ github, context, env = process.env }) {
  const result = await mergedPush(github, context, env);
  return result; // Secret-free: no identity, certificate, transport or network I/O.
}

async function suiteDryRun(options) {
  return {...await dryRun(options), scenario: "session-suite"};
}

async function successfulPreflight(github, context, env, recheck) {
  const {data: run} = await github.rest.actions.getWorkflowRun({...API, run_id: context.runId});
  const manager = u => u?.id === MANAGER_ID && u.login === "Guillaume0385" && u.type === "User";
  need(run?.id === context.runId && run.run_attempt === 1 && run.event === "push" &&
    run.head_sha === context.sha && run.head_branch === "experimental" && manager(run.actor) &&
    manager(run.triggering_actor) && sameRepo(run.repository) && sameRepo(run.head_repository) &&
    workflowPath(run.path, FILE, ["refs/heads/experimental"]), "preflight_unverified");
  const jobs = await github.paginate(github.rest.actions.listJobsForWorkflowRun,
    {...API, run_id: context.runId, filter: "latest", per_page: 100});
  need(Array.isArray(jobs), "preflight_unverified");
  const dry = jobs.filter(j => j.name === "dry-run");
  need(dry.length === 1 && dry[0].head_sha === context.sha && dry[0].run_id === context.runId &&
    dry[0].run_attempt === 1 && dry[0].status === "completed" && dry[0].conclusion === "success" &&
    Number.isFinite(Date.parse(dry[0].started_at)), "preflight_unverified");
  const admission = jobs.filter(j => j.name === "admission");
  need(admission.length === 1 && admission[0].head_sha === context.sha &&
    admission[0].run_id === context.runId && admission[0].run_attempt === 1 &&
    (recheck ? admission[0].status === "completed" && admission[0].conclusion === "success"
      : ["in_progress", "queued"].includes(admission[0].status)), "preflight_unverified");
  return {number: 1, beganAt: Date.parse(dry[0].started_at)};
}

async function managerDecision(github, pr, context, proof, contract) {
  need(SHA.test(pr.head?.sha) && positive(pr.number) &&
    typeof pr.head.ref === "string" && pr.head.ref.length > 0,
  "manager_decision_unverified");
  const comments = await github.paginate(github.rest.issues.listComments,
    { ...API, issue_number: pr.number, per_page: 100 });
  // Keep original pre-merge v1 binding for PR/HEAD/CI, even on repeats.
  // Reject a malformed/duplicate original decision, not only the new v2.
  const choices = comments.filter(c => c.user?.login === "Guillaume0385" &&
    c.user.id === MANAGER_ID && c.user.type === "User" && c.body?.startsWith(contract.marker));
  need(choices.length === 1, "manager_decision_unverified");
  let approvalValue;
  try { approvalValue = JSON.parse(choices[0].body.slice(contract.marker.length).trim()); }
  catch (_) { throw Error("manager_decision_unverified"); }
  const chosen = {comment: choices[0], approval: approvalValue};
  const { comment, approval } = chosen;
  need(contract.validApproval(approval, pr.head.sha) &&
    positive(comment.id) && comment.created_at === comment.updated_at &&
    Number.isFinite(Date.parse(comment.created_at)) &&
    Date.parse(comment.created_at) < Date.parse(pr.merged_at),
  "manager_decision_unverified");
  return {approval, comment};
}

async function reviewsAndCI(github, pr, decision) {
  const reviews = await github.paginate(github.rest.pulls.listReviews,
    { ...API, pull_number: pr.number, per_page: 100 });
  const active = new Map();
  for (const review of reviews) {
    if (["APPROVED", "CHANGES_REQUESTED"].includes(review.state)) active.set(review.user.id, review.state);
  }
  need(![...active.values()].includes("CHANGES_REQUESTED"), "review_unverified");
  let cursor = null;
  const seen = new Set();
  do {
    const result = await github.graphql(
      "query($owner:String!,$name:String!,$number:Int!,$cursor:String){repository(owner:$owner,name:$name){pullRequest(number:$number){reviewThreads(first:100,after:$cursor){nodes{isResolved}pageInfo{hasNextPage endCursor}}}}}",
      { owner: API.owner, name: API.repo, number: pr.number, cursor });
    const threads = result.repository.pullRequest.reviewThreads;
    need(Array.isArray(threads.nodes) && threads.nodes.every(t => t.isResolved === true), "review_unverified");
    cursor = threads.pageInfo.hasNextPage ? threads.pageInfo.endCursor : null;
    need(!threads.pageInfo.hasNextPage || typeof cursor === "string" && cursor.length > 0 && !seen.has(cursor),
      "review_unverified");
    seen.add(cursor);
  } while (cursor);
  const { data: ci } = await github.rest.actions.getWorkflowRun({ ...API, run_id: decision.approval.ci_run_id });
  need(ci.id === decision.approval.ci_run_id && ci.head_sha === pr.head.sha &&
    ci.head_branch === pr.head.ref && ci.event === "pull_request" && ci.run_attempt === 1 &&
    ci.status === "completed" && ci.conclusion === "success" &&
    sameRepo(ci.repository) && sameRepo(ci.head_repository) &&
    workflowPath(ci.path, ".github/workflows/validate.yml",
      ["refs/pull/" + pr.number + "/merge", pr.head.ref, "refs/heads/" + pr.head.ref]) &&
    Number.isFinite(Date.parse(ci.updated_at)) &&
    Date.parse(ci.updated_at) <= Date.parse(decision.comment.created_at) &&
    Array.isArray(ci.pull_requests), "ci_unverified");
  // After merge GitHub may clear pull_requests. The authenticated, immutable
  // MANAGER decision explicitly binds this CI run to this PR/HEAD; the SHA alone
  // is never sufficient. Any remaining conflicting association still refuses.
  need(ci.pull_requests.length <= 1 && ci.pull_requests.every(r =>
    r.number === pr.number && r.head?.sha === pr.head.sha && r.base?.ref === "experimental"), "ci_unverified");
  const jobs = await github.paginate(github.rest.actions.listJobsForWorkflowRun,
    { ...API, run_id: ci.id, filter: "latest", per_page: 100 });
  need(jobs.length === 4 && ["tests", "ha-tests", "hacs", "hassfest"].every(name => {
    const matches = jobs.filter(j => j.name === name);
    return matches.length === 1 && matches[0].head_sha === pr.head.sha &&
      matches[0].status === "completed" && matches[0].conclusion === "success";
  }), "ci_unverified");
}

// GitHub documents Actions:read for these three read-only endpoints, not
// Administration. The actual run token must still prove access: 401/403/404,
// omitted fields and unknown API responses all deny admission before any claim.
async function readEnvironmentEvidence(operation) {
  try {
    return await operation();
  } catch (_) {
    // Includes 401/403/404 and transport errors; raw API errors never escape.
    throw new Error("environment_api_inaccessible");
  }
}

async function environmentPolicy(github) {
  const { data: environment } = await readEnvironmentEvidence(() =>
    github.rest.repos.getEnvironment({ ...API, environment_name: policy.environment }));
  need(environment && typeof environment === "object" &&
    typeof environment.name === "string" && positive(environment.id) &&
    environment.deployment_branch_policy &&
    typeof environment.deployment_branch_policy.protected_branches === "boolean" &&
    typeof environment.deployment_branch_policy.custom_branch_policies === "boolean" &&
    Array.isArray(environment.protection_rules), "environment_response_incomplete");
  need(environment.name === policy.environment &&
    environment.deployment_branch_policy.protected_branches === false &&
    environment.deployment_branch_policy.custom_branch_policies === true,
  "environment_branch_invalid");
  const branches = await readEnvironmentEvidence(() =>
    github.paginate(github.rest.repos.listDeploymentBranchPolicies,
      { ...API, environment_name: policy.environment, per_page: 100 }));
  need(Array.isArray(branches), "environment_response_incomplete");
  need(branches.length === 1 && branches[0]?.name === "experimental", "environment_branch_invalid");
  need(positive(branches[0].id) && typeof branches[0].node_id === "string" &&
    branches[0].node_id.length > 0, "environment_response_incomplete");
  let branch = branches[0];
  if (!Object.hasOwn(branch, "type")) {
    const { data: detail } = await readEnvironmentEvidence(() =>
      github.rest.repos.getDeploymentBranchPolicy({ ...API,
        environment_name: policy.environment, branch_policy_id: branch.id }));
    need(detail && typeof detail === "object" && positive(detail.id) &&
      typeof detail.node_id === "string" && typeof detail.name === "string" &&
      typeof detail.type === "string", "environment_response_incomplete");
    need(detail.id === branch.id && detail.node_id === branch.node_id &&
      detail.name === branch.name, "environment_branch_invalid");
    branch = detail;
  }
  need(branch.type === "branch", "environment_branch_invalid");
  const rules = environment.protection_rules;
  need(rules.every(r => r && ["required_reviewers", "branch_policy", "wait_timer"].includes(r.type)),
    "environment_reviewers_invalid");
  const required = rules.filter(r => r.type === "required_reviewers");
  // A sole maintainer can use an environment without mandatory reviewers.
  // If GitHub actually configures them, never bypass the rule.
  need(required.length <= 1, "environment_reviewers_invalid");
  let reviewers = [];
  if (required.length === 1) {
    need(positive(required[0].id) && Array.isArray(required[0].reviewers),
      "environment_response_incomplete");
    need(required[0].prevent_self_review === true && required[0].reviewers.length > 0 &&
      required[0].reviewers.every(r => r.type === "User" && r.reviewer?.type === "User" &&
        positive(r.reviewer.id) && typeof r.reviewer.login === "string" &&
        r.reviewer.login.length > 0), "environment_reviewers_invalid");
    reviewers = required[0].reviewers.map(r => ({ id: r.reviewer.id, login: r.reviewer.login }))
      .sort((a, b) => a.id - b.id);
    need(reviewers.some(r => r.id !== MANAGER_ID && r.login !== "Guillaume0385"),
      "environment_reviewers_invalid");
  }
  return { id: environment.id, reviewers, approvalRequired: required.length === 1,
    digest: digest({ id: environment.id,
    name: environment.name, deployment_branch_policy: environment.deployment_branch_policy,
    protection_rules: environment.protection_rules, branch }) };
}

async function noOtherObservation(github, context) {
  const historical = new Set(["live-validation.yml", "manager-live-hoben.yml", "opened-client-boundary.yml"]);
  // Historical live workflows do not share the experimental mutex. Inspect
  // every pre-start state as well as running jobs at admission AND recheck.
  // An unidentified active run is not proof of absence of a competing probe.
  for (const status of ["requested", "queued", "pending", "waiting", "in_progress"]) {
    const runs = await github.paginate(github.rest.actions.listWorkflowRunsForRepo,
      { ...API, status, per_page: 100 });
    need(Array.isArray(runs) && !runs.some(r =>
      !Number.isSafeInteger(r.id) ||
      (r.id !== context.runId &&
        (typeof r.path !== "string" || historical.has(r.path.split("@")[0].split("/").pop())))),
    "concurrent_observation");
  }
}

async function actualApproval(github, context, environment, proof) {
  const { data: history } = await github.request("GET /repos/{owner}/{repo}/actions/runs/{run_id}/approvals",
    { ...API, run_id: context.runId });
  need(Array.isArray(history), "approval_unverified");
  need(rerun.freshEnvironmentApproval(history.filter(h =>
    Number.isFinite(Date.parse(h.created_at)) && Date.parse(h.created_at) >= proof.beganAt),
    environment, proof, policy.environment),
    "approval_unverified");
}

async function verifyContract({ github, context, env = process.env, recheck = false }, contract) {
  const merged = await mergedPush(github, context, env);
  const proof = await successfulPreflight(github, context, env, recheck);
  const { data: pr } = await github.rest.pulls.get({ ...API, pull_number: merged.pr });
  need(pr.number === merged.pr && pr.draft === false && pr.merged === true && pr.state === "closed" &&
    Number.isFinite(Date.parse(pr.merged_at)) &&
    pr.merge_commit_sha === context.sha && pr.merged_by?.login === "Guillaume0385" &&
    pr.merged_by.id === MANAGER_ID && pr.base?.ref === "experimental" &&
    sameRepo(pr.base.repo) && sameRepo(pr.head.repo), "merge_changed");
  const { data: candidate } = await github.rest.git.getCommit({ ...API, commit_sha: pr.head.sha });
  const { data: mergedCommit } = await github.rest.git.getCommit({ ...API, commit_sha: context.sha });
  need(candidate.sha === pr.head.sha && mergedCommit.sha === context.sha &&
    SHA.test(candidate.tree?.sha) && candidate.tree.sha === mergedCommit.tree?.sha,
  "merged_tree_unreviewed");
  const decision = await managerDecision(github, pr, context, proof, contract);
  await reviewsAndCI(github, pr, decision);
  const environment = await environmentPolicy(github);
  await noOtherObservation(github, context);
  const name = contract.claimPrefix + pr.head.sha;
  const claim = { schema: 1, scenario: contract.scenario,
    sha: context.sha, run_id: context.runId,
    run_attempt: 1,
    pr: pr.number, candidate_sha: pr.head.sha, decision_id: decision.comment.id,
    decision_digest: digest({ id: decision.comment.id, body: decision.comment.body,
      created_at: decision.comment.created_at, updated_at: decision.comment.updated_at,
      user: { id: decision.comment.user.id, login: decision.comment.user.login,
        type: decision.comment.user.type } }), environment_digest: environment.digest,
    ...(contract.claimContract ? {contract: contract.claimContract} : {}) };
  if (recheck) {
    const { data: reference } = await github.rest.git.getRef({ ...API, ref: "tags/" + name });
    need(reference.ref === "refs/tags/" + name && reference.object?.type === "tag", "claim_unverified");
    const { data: tag } = await github.rest.git.getTag({ ...API, tag_sha: reference.object.sha });
    need(tag.tag === name && tag.object?.type === "commit" && tag.object.sha === context.sha &&
      digest(JSON.parse(tag.message)) === digest(claim), "claim_unverified");
    if (environment.approvalRequired) await actualApproval(github, context, environment, proof);
  } else {
    // createRef is atomic. An existing reservation (including cancellation or
    // failure) cannot be replaced or retried. No secret is present in this job.
    const { data: tag } = await github.rest.git.createTag({ ...API, tag: name,
      message: JSON.stringify(claim), object: context.sha, type: "commit" });
    await github.rest.git.createRef({ ...API, ref: "refs/tags/" + name, sha: tag.sha });
  }
  const {data: finalBranch} = await github.rest.repos.getBranch({...API, branch: "experimental"});
  need(finalBranch.protected === true && finalBranch.commit?.sha === context.sha, "merge_changed");
  return { sha: context.sha, candidate_sha: pr.head.sha, pr: pr.number, scenario: contract.scenario,
    status: recheck ? "approved" : environment.approvalRequired ? "PENDING APPROVAL" : "READY FOR ENVIRONMENT" };
}

// Fixed wrappers keep all existing provenance/review/CI/environment/recheck
// evidence identical. Supplying a contract in options never selects a profile.
async function verify(options) { return verifyContract(options, legacyContract); }
async function suiteVerify(options) { return verifyContract(options, suiteContract); }

module.exports = { dryRun, verify, refusalCategory,
  WORKFLOW, MARKER, workflowPath, suiteDryRun, suiteVerify };
