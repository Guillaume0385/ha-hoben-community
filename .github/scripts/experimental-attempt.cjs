"use strict";

// Shared, secret-free admission contract for native GitHub Actions Re-run all jobs.
// No retry, partial job, inherited v1 decision or old environment approval may
// ever silently authorize a second observation. Unknown API evidence fails closed.
const API = {owner: "Guillaume0385", repo: "ha-hoben-community"};
const MANAGER = {login: "Guillaume0385", id: 18246624, type: "User"};
const MAX_ATTEMPTS = 50;
const safe = n => Number.isSafeInteger(n) && n > 0;
const need = (ok, reason) => { if (!ok) throw Error(reason); };
const time = t => typeof t === "string" && Number.isFinite(Date.parse(t)) ?
  Date.parse(t) : NaN;

function attempt(context, env) {
  const number = Number(env.GITHUB_RUN_ATTEMPT);
  need(safe(context.runId) && env.GITHUB_RUN_ID === String(context.runId) &&
    /^([1-9][0-9]?)$/.test(env.GITHUB_RUN_ATTEMPT || "") &&
    number <= MAX_ATTEMPTS &&
    env.GITHUB_TRIGGERING_ACTOR === MANAGER.login &&
    env.GITHUB_ACTOR === MANAGER.login,
  "attempt_unverified");
  return number;
}

function isManager(u) {
  return u?.login === MANAGER.login && u.id === MANAGER.id && u.type === "User";
}

async function evidence(github, context, env, workflow, stage) {
  const number = attempt(context, env);
  const {data: run} = await github.rest.actions.getWorkflowRun({
    ...API, run_id: context.runId
  });
  need(run?.id === context.runId && run.event === "push" &&
    run.run_attempt === number && run.head_sha === context.sha &&
    run.head_branch === "experimental" && isManager(run.actor) &&
    run.repository?.full_name === "Guillaume0385/ha-hoben-community" &&
    run.repository?.id === 1401398724 &&
    run.head_repository?.full_name === run.repository.full_name &&
    run.head_repository?.id === run.repository.id &&
    typeof run.path === "string" &&
    (run.path === workflow || run.path === workflow + "@refs/heads/experimental"),
  "attempt_unverified");
  // Github.actor always describes the ORIGINAL push on a rerun, and is NOT
  // evidence for who clicked Re-run all jobs.
  if (number > 1) need(isManager(run.triggering_actor), "attempt_unverified");
  const jobs = await github.paginate(github.rest.actions.listJobsForWorkflowRun,
    {...API, run_id: context.runId, filter: "latest", per_page: 100});
  need(Array.isArray(jobs) && jobs.length <= 12, "partial_rerun");
  const find = name => {
    const found = jobs.filter(j => j.name === name);
    need(found.length === 1, "partial_rerun");
    const job = found[0];
    need(job.run_id === context.runId && job.run_attempt === number &&
      job.head_sha === context.sha, "partial_rerun");
    return job;
  };
  const dry = find("dry-run");
  const admission = find("admission");
  need(dry.status === "completed" && dry.conclusion === "success" &&
    safe(dry.id) && safe(admission.id) &&
    ["queued", "in_progress", "waiting", "completed"].includes(admission.status),
  "partial_rerun");
  if (stage === "recheck") {
    need(admission.status === "completed" && admission.conclusion === "success",
      "partial_rerun");
    const collect = find("collect");
    need(["queued", "waiting", "in_progress"].includes(collect.status),
      "partial_rerun");
  }
  // Refuse ambiguous partial-rerun cases from an earlier failed preflight.
  // If dry-run previously failed, a "Re-run failed jobs" could rerun the
  // entire dependency graph and become indistinguishable from a full rerun.
  if (number > 1) {
    const previous = await github.paginate(
      github.rest.actions.listJobsForWorkflowRunAttempt,
      {...API, run_id: context.runId, attempt_number: number - 1, per_page: 100});
    const pastDry = previous.filter(j => j.name === "dry-run");
    need(pastDry.length === 1 && pastDry[0].run_attempt === number - 1 &&
      pastDry[0].conclusion === "success", "partial_rerun");
  }
  need(Number.isFinite(time(dry.started_at)), "attempt_unverified");
  return {number, dryStartedAt: time(dry.started_at)};
}

function managerDecision(comments, marker, fields, scenario, pr, context, proof, ciId) {
  const found = comments.filter(c => isManager(c.user) &&
    typeof c.body === "string" && c.body.startsWith(marker));
  const parsed = found.map(comment => {
    let decision;
    try { decision = JSON.parse(comment.body.slice(marker.length).trim()); }
    catch (_) { return null; }
    return {comment, decision};
  }).filter(Boolean).filter(x => x.decision?.candidate_sha === pr.head.sha &&
    x.decision?.scenario === scenario &&
    (proof.number === 1 || x.decision?.run_id === context.runId &&
      x.decision?.run_attempt === proof.number));
  need(parsed.length === 1, "manager_decision_unverified");
  const {comment, decision} = parsed[0];
  need(decision && !Array.isArray(decision) && typeof decision === "object" &&
    Object.keys(decision).sort().join() === fields.slice().sort().join() &&
    decision.schema === (proof.number === 1 ? 1 : 2) &&
    decision.scenario === scenario &&
    decision.candidate_sha === pr.head.sha &&
    safe(decision.ci_run_id) && safe(comment.id) &&
    time(comment.created_at) === time(comment.updated_at) &&
    Number.isFinite(time(comment.created_at)),
  "manager_decision_unverified");
  if (proof.number === 1) {
    need(time(comment.created_at) <= time(pr.merged_at),
      "manager_decision_unverified");
  } else {
    need(decision.run_id === context.runId &&
      decision.run_attempt === proof.number &&
      decision.merge_sha === context.sha &&
      decision.pr_number === pr.number &&
      time(comment.created_at) >= time(pr.merged_at) &&
      time(comment.created_at) <= proof.dryStartedAt,
      "manager_decision_unverified");
  }
  need(ciId === undefined || decision.ci_run_id === ciId, "manager_decision_unverified");
  return {approval: decision, comment};
}

function claimName(prefix, context, number) {
  need(/^[a-z0-9-]+$/.test(prefix) && /^[a-f0-9]{40}$/.test(context.sha) &&
    safe(context.runId) && safe(number) && number <= MAX_ATTEMPTS,
  "claim_unverified");
  return prefix + context.sha + "-r" + context.runId + "-a" + number;
}

module.exports = {attempt, evidence, managerDecision, claimName, isManager};
