"use strict";

// Pure, secret-free prerequisite for native GitHub Actions "Re-run all jobs".
// Not wired into either Hoben gate yet: attempt >1 MUST stay NOT RUN until
// full independent security tests and MANAGER review are completed.
const manager = Object.freeze({login: "Guillaume0385", id: 18246624, type: "User"});
const repository = "Guillaume0385/ha-hoben-community";
const shaPattern = /^[0-9a-f]{40}$/;
const attemptPattern = /^(?:[1-9]|[1-4][0-9]|50)$/;
const whole = n => Number.isSafeInteger(n) && n > 0;
const need = (ok, code) => { if (!ok) throw Error(code); };
const isManager = u => u?.login === manager.login &&
  u.id === manager.id && u.type === manager.type;
const when = s => typeof s === "string" && Number.isFinite(Date.parse(s)) ?
  Date.parse(s) : NaN;

function authorizeAttempt({context, env, run, jobs, previousJobs, workflow, phase}) {
  const attempt = Number(env.GITHUB_RUN_ATTEMPT);
  need(attemptPattern.test(env.GITHUB_RUN_ATTEMPT || "") &&
    context.eventName === "push" && context.ref === "refs/heads/experimental" &&
    shaPattern.test(context.sha) && whole(context.runId) &&
    env.GITHUB_RUN_ID === String(context.runId) &&
    env.GITHUB_REF === context.ref && env.GITHUB_SHA === context.sha &&
    env.GITHUB_ACTOR === manager.login &&
    env.GITHUB_TRIGGERING_ACTOR === manager.login &&
    env.GITHUB_WORKFLOW_REF === workflow &&
    env.GITHUB_WORKFLOW_SHA === context.sha,
  "attempt_unverified");
  need(run?.id === context.runId && run.run_attempt === attempt &&
    run.head_sha === context.sha && run.head_branch === "experimental" &&
    run.event === "push" && isManager(run.actor) &&
    run.repository?.full_name === repository &&
    run.repository?.id === 1401398724 &&
    run.head_repository?.id === run.repository.id &&
    run.head_repository?.full_name === repository &&
    [workflow.split("@")[0].split("/").slice(-2).join("/"),
      workflow.slice(repository.length + 1)].some(p => p === run.path) ||
    false,
  "attempt_unverified");
  need(attempt === 1 || isManager(run.triggering_actor), "attempt_unverified");
  need(Array.isArray(jobs) && jobs.length <= 8, "partial_rerun");
  const job = name => {
    const found = jobs.filter(j => j.name === name);
    need(found.length === 1 && found[0].head_sha === context.sha &&
      found[0].run_attempt === attempt &&
      found[0].run_id === context.runId,
    "partial_rerun");
    return found[0];
  };
  const dry = job("dry-run");
  const admission = job("admission");
  need(dry.status === "completed" && dry.conclusion === "success" &&
    when(dry.started_at) >= 0, "partial_rerun");
  if (phase === "admission") {
    need(["in_progress", "queued"].includes(admission.status), "partial_rerun");
  } else {
    need(phase === "recheck" && admission.status === "completed" &&
      admission.conclusion === "success", "partial_rerun");
    const collect = job("collect");
    need(["in_progress", "queued", "waiting"].includes(collect.status),
      "partial_rerun");
  }
  // On "Re-run failed jobs", GitHub normally preserves the successful dry-run
  // from the previous attempt. Its attempt number will be stale and denied.
  // If the PREVIOUS dry-run failed, a partial retry can look identical to a
  // full retry. Refuse these ambiguous repeat attempts altogether.
  if (attempt > 1) {
    need(Array.isArray(previousJobs), "partial_rerun");
    const before = previousJobs.filter(j => j.name === "dry-run");
    need(before.length === 1 && before[0].run_attempt === attempt - 1 &&
      before[0].conclusion === "success", "partial_rerun");
  }
  return Object.freeze({number: attempt, beganAt: when(dry.started_at)});
}

function authorizeDecision({comments, marker, scenario, candidateSha, ciId,
  pr, mergeSha, runId, proof}) {
  need(Array.isArray(comments) && typeof marker === "string" &&
    ["h1h2", "ha-parity"].includes(scenario) && shaPattern.test(candidateSha) &&
    shaPattern.test(mergeSha) && whole(ciId) && whole(pr.number) &&
    whole(runId) && whole(proof.number) && when(pr.merged_at) >= 0,
  "decision_unverified");
  const version = proof.number === 1 ? 1 : 2;
  const keys = version === 1 ?
    ["schema", "scenario", "candidate_sha", "ci_run_id"] :
    ["schema", "scenario", "candidate_sha", "ci_run_id",
      "pr_number", "merge_sha", "run_id", "run_attempt"];
  const parsed = comments.filter(c => isManager(c.user) && c.body?.startsWith(marker))
    .map(comment => {
      let d = null;
      try { d = JSON.parse(comment.body.slice(marker.length).trim()); }
      catch (_) { /* fail closed */ }
      return {comment, d};
    }).filter(x => x.d?.candidate_sha === candidateSha &&
      x.d?.scenario === scenario &&
      (version === 1 || x.d?.run_id === runId &&
        x.d?.run_attempt === proof.number));
  need(parsed.length === 1, "decision_unverified");
  const {comment, d} = parsed[0];
  need(d && !Array.isArray(d) &&
    Object.keys(d).sort().join() === keys.sort().join() &&
    d.schema === version && d.scenario === scenario &&
    d.candidate_sha === candidateSha && d.ci_run_id === ciId &&
    whole(comment.id) && when(comment.created_at) >= 0 &&
    comment.created_at === comment.updated_at, "decision_unverified");
  if (version === 1) {
    need(when(comment.created_at) <= when(pr.merged_at), "decision_unverified");
  } else {
    need(d.pr_number === pr.number && d.merge_sha === mergeSha &&
      d.run_id === runId && d.run_attempt === proof.number &&
      when(comment.created_at) >= when(pr.merged_at) &&
      when(comment.created_at) <= proof.beganAt, "decision_unverified");
  }
  return Object.freeze({approval: d, comment});
}

function claimName(scenario, sha, runId, attempt) {
  need(["h1h2", "ha-parity"].includes(scenario) &&
    shaPattern.test(sha) && whole(runId) &&
    whole(attempt) && attempt <= 50, "claim_unverified");
  return "hoben-" + scenario + "-" + sha + "-run" + runId + "-attempt" + attempt;
}

module.exports = {authorizeAttempt, authorizeDecision, claimName};
