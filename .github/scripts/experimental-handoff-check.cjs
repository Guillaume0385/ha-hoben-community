"use strict";

// Advisory-only, offline pre-merge handoff inspection for Issue #54.
// This code has NO GitHub API client, token, network, environment or write path.
// The secretless check does not authorize admission: experimental-lab-gate.cjs
// verifies the real GitHub evidence again AFTER the reviewed MANAGER merge.
const fs = require("node:fs");
const policy = require("../config/hoben-experimental.json");

const SHA = /^[a-f0-9]{40}$/;
const REPO = "Guillaume0385/ha-hoben-community";
const REPO_ID = 1401398724;
const MANAGER_ID = 18246624;
const MARKER = "<!-- hoben-experimental-approval:v1 -->";
const JOBS = ["tests", "ha-tests", "hacs", "hassfest"];
const sameRepo = repo => repo?.full_name === REPO && repo.id === REPO_ID;
const positive = n => Number.isSafeInteger(n) && n > 0;
const date = s => typeof s === "string" && Number.isFinite(Date.parse(s));
const result = checks => ({
  verdict: Object.values(checks).every(v => v === "ok") ? "READY FOR MANAGER REVIEW" : "NOT READY",
  checks,
  advisory_only: true,
});

function evaluate({ pr, issue, ci, jobs, comments } = {}) {
  const checks = { pr: "pr_unverified", link: "unlinked_pr",
    issue: "issue_unverified", ci: "ci_incomplete", decision: "missing_manager_decision" };
  if (!pr || !positive(pr.number) || pr.state !== "open" ||
      pr.merged !== false || pr.draft !== false ||
      pr.base?.ref !== "experimental" || !sameRepo(pr.base.repo) ||
      !sameRepo(pr.head?.repo) || !SHA.test(pr.head.sha) ||
      typeof pr.head.ref !== "string") return result(checks);
  checks.pr = "ok";
  if (!/(?:^|\s)Refs #54(?:\s|$)/.test(pr.body || "")) return result(checks);
  checks.link = "ok";

  const states = (issue?.labels || []).map(l => l.name).filter(n => n?.startsWith("state:"));
  if (issue?.number === 54 && issue.id === policy.tracking_issue_id &&
      issue.state === "open" && !issue.pull_request && states.length === 1) {
    checks.issue = states[0] === "state:review" ? "ok" :
      states[0] === "state:blocked" ? "blocked_issue" : "issue_not_in_review";
  }
  if (checks.issue !== "ok") return result(checks);

  const associations = ci?.pull_requests;
  const correctAssociation = Array.isArray(associations) && associations.length === 1 &&
    associations[0].number === pr.number &&
    associations[0].head?.sha === pr.head.sha &&
    associations[0].base?.ref === "experimental";
  const workflowPath = ci?.path === ".github/workflows/validate.yml" ||
    ci?.path === ".github/workflows/validate.yml@refs/heads/" + pr.head.ref ||
    ci?.path === ".github/workflows/validate.yml@refs/pull/" + pr.number + "/merge";
  if (ci && positive(ci.id) && ci.event === "pull_request" && ci.run_attempt === 1 &&
      ci.head_sha === pr.head.sha && ci.head_branch === pr.head.ref &&
      ci.status === "completed" && ci.conclusion === "success" &&
      sameRepo(ci.repository) && sameRepo(ci.head_repository) &&
      workflowPath && date(ci.updated_at) && correctAssociation &&
      Array.isArray(jobs) && jobs.length === 4 &&
      JOBS.every(name => jobs.filter(j => j.name === name &&
        j.head_sha === pr.head.sha && j.status === "completed" &&
        j.conclusion === "success").length === 1)) checks.ci = "ok";
  if (checks.ci !== "ok") return result(checks);

  const approvals = Array.isArray(comments) ? comments.filter(c =>
    c?.body?.startsWith(MARKER)) : [];
  if (!approvals.length) return result(checks);
  checks.decision = "stale_or_invalid_manager_decision";
  if (approvals.length !== 1) return result(checks);
  const comment = approvals[0];
  let approval;
  try { approval = JSON.parse(comment.body.slice(MARKER.length).trim()); }
  catch (_) { return result(checks); }
  if (!approval || Array.isArray(approval) || typeof approval !== "object") return result(checks);
  if (Object.keys(approval).sort().join() !==
      ["schema", "scenario", "candidate_sha", "ci_run_id"].sort().join()) {
    return result(checks);
  }
  if (comment.user?.login === "Guillaume0385" &&
      comment.user?.id === MANAGER_ID && comment.user?.type === "User" &&
      positive(comment.id) && comment.created_at === comment.updated_at &&
      date(comment.created_at) && Date.parse(comment.created_at) >= Date.parse(ci.updated_at) &&
      approval.schema === 1 && approval.scenario === "h1h2" &&
      approval.candidate_sha === pr.head.sha && approval.ci_run_id === ci.id) checks.decision = "ok";
  return result(checks);
}

module.exports = { evaluate };

// Optional local diagnostic: node .github/scripts/experimental-handoff-check.cjs evidence.json
// Only fixed codes are printed, NEVER the input JSON, comments, identities or exceptions.
if (require.main === module) {
  let report;
  try {
    if (process.argv.length !== 3) throw Error("input");
    const stat = fs.statSync(process.argv[2]);
    if (!stat.isFile() || stat.size > 131072) throw Error("input");
    report = evaluate(JSON.parse(fs.readFileSync(process.argv[2], "utf8")));
  } catch (_) {
    report = { verdict: "NOT READY", advisory_only: true, checks: { input: "input_unavailable" } };
  }
  process.stdout.write(JSON.stringify(report) + "\n");
  if (report.verdict !== "READY FOR MANAGER REVIEW") process.exitCode = 1;
}
