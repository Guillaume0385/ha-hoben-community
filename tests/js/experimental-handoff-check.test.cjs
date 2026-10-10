"use strict";

const { test } = require("node:test");
const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const handoff = require("../../.github/scripts/experimental-handoff-check.cjs");

const sha = "b".repeat(40);
const repo = {full_name: "Guillaume0385/ha-hoben-community", id: 1401398724};
const manager = {login: "Guillaume0385", id: 18246624, type: "User"};
const marker = "<!-- hoben-experimental-approval:v1 -->";
const file = path.resolve(__dirname, "../../.github/scripts/experimental-handoff-check.cjs");

// Pure offline fixture: synthetic identifiers, fake GitHub metadata, no API, no stove.
function fixture() {
  const pr = {number: 62, state: "open", merged: false, draft: false, body: "Refs #54",
    base: {ref: "experimental", repo: {...repo}},
    head: {ref: "codex/issue-54-handoff-premerge", sha, repo: {...repo}}};
  const ci = {id: 678, event: "pull_request", run_attempt: 1,
    head_sha: sha, head_branch: pr.head.ref, status: "completed", conclusion: "success",
    repository: {...repo}, head_repository: {...repo},
    path: ".github/workflows/validate.yml", updated_at: "2026-10-09T17:00:00Z",
    pull_requests: [{number: pr.number, head: {sha}, base: {ref: "experimental"}}]};
  const jobs = ["tests", "ha-tests", "hacs", "hassfest"].map(name =>
    ({name, head_sha: sha, status: "completed", conclusion: "success"}));
  const decision = {schema: 1, scenario: "h1h2", candidate_sha: sha,
    ci_run_id: 678};
  const comment = {id: 321, user: {...manager},
    created_at: "2026-10-09T17:01:00Z", updated_at: "2026-10-09T17:01:00Z",
    body: marker + "\n" + JSON.stringify(decision)};
  return {pr, ci, jobs, comments: [comment], decision, comment};
}

function inspect(f) {
  return handoff.evaluate({pr: f.pr, ci: f.ci,
    jobs: f.jobs, comments: f.comments});
}

test("complete handoff is advisory only, with exact PR, CI and MANAGER decision", () => {
  const a = fixture();
  const report = inspect(a);
  assert.deepEqual(report, {verdict: "READY FOR MANAGER REVIEW", advisory_only: true,
    checks: {pr: "ok", ci: "ok", decision: "ok"}});
});

const cases = [
  ["#61 had no premerge MANAGER decision", a => {a.comments = [];},
    "decision", "missing_manager_decision"],
  ["CI missing hassfest", a => {a.jobs.pop();}, "ci", "ci_incomplete"],
  ["CI success wrapper but failed job", a => {a.jobs[0].conclusion = "failure";},
    "ci", "ci_incomplete"],
  ["CI linked to wrong PR", a => {a.ci.pull_requests[0].number = 61;},
    "ci", "ci_incomplete"],
  ["CI linked to wrong SHA", a => {a.ci.head_sha = "c".repeat(40);},
    "ci", "ci_incomplete"],
  ["PR targets main", a => {a.pr.base.ref = "main";}, "pr", "pr_unverified"],
  ["fork", a => {a.pr.head.repo.full_name = "another/repo";}, "pr", "pr_unverified"],
  ["decision for old HEAD", a => {
    a.decision.candidate_sha = "c".repeat(40);
    a.comment.body = marker + "\n" + JSON.stringify(a.decision);
  }, "decision", "stale_or_invalid_manager_decision"],
  ["wrong CI ID in decision", a => {
    a.decision.ci_run_id++;
    a.comment.body = marker + "\n" + JSON.stringify(a.decision);
  }, "decision", "stale_or_invalid_manager_decision"],
  ["unexpected legacy recipient in decision", a => {
    a.decision.recipient_sha256 = "0".repeat(64);
    a.comment.body = marker + "\n" + JSON.stringify(a.decision);
  }, "decision", "stale_or_invalid_manager_decision"],
  ["edited decision", a => {a.comment.updated_at = "2026-10-09T17:02:00Z";},
    "decision", "stale_or_invalid_manager_decision"],
  ["untrusted decision author", a => {a.comment.user.id = 1;},
    "decision", "stale_or_invalid_manager_decision"],
  ["decision before successful CI", a => {a.comment.created_at = a.comment.updated_at =
    "2026-10-09T16:59:00Z";}, "decision", "stale_or_invalid_manager_decision"],
  ["duplicate decisions", a => {a.comments.push({...a.comment, id: 322});},
    "decision", "stale_or_invalid_manager_decision"],
  ["malformed JSON decision", a => {a.comment.body = marker + "\nnot-json";},
    "decision", "stale_or_invalid_manager_decision"],
];
for (const [name, mutate, key, expected] of cases) {
  test("NOT READY, no admission: " + name, () => {
    const a = fixture();
    mutate(a);
    const report = inspect(a);
    assert.equal(report.verdict, "NOT READY");
    assert.equal(report.advisory_only, true);
    assert.equal(report.checks[key], expected);
    assert.equal(Object.values(report.checks).every(v => v === "ok"), false);
  });
}


test("documentation PR without Refs #54 remains eligible after MANAGER decision", () => {
  const a = fixture();
  a.pr.body = "Documentation only, unrelated to Issue 54";
  assert.equal(inspect(a).verdict, "READY FOR MANAGER REVIEW");
});

test("decision legitimately missing before CI does not turn a PR validation into a false success", () => {
  const a = fixture();
  a.comments = [];
  assert.equal(inspect(a).checks.decision, "missing_manager_decision");
  assert.equal(inspect(a).verdict, "NOT READY");
  // The helper is never wired to a privileged workflow; this is informational.
  assert.equal(typeof handoff.verify, "undefined");
});

test("CLI only prints fixed categories; input never exposed, even on invalid input", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "hoben-handoff-test-"));
  try {
    const evidence = path.join(dir, "evidence.json");
    const a = fixture();
    a.pr.body = "SYNTHETIC_PRIVATE_VALUE";
    a.comments = [];
    fs.writeFileSync(evidence, JSON.stringify(a));
    const output = spawnSync(process.execPath, [file, evidence],
      {encoding: "utf8", timeout: 4000});
    assert.equal(output.status, 1);
    assert.equal(output.stdout.includes("SYNTHETIC_PRIVATE_VALUE"), false);
    assert.equal(JSON.parse(output.stdout).checks.decision, "missing_manager_decision");
    const invalid = spawnSync(process.execPath, [file, "nonexistent-unsafe-file"],
      {encoding: "utf8", timeout: 4000});
    assert.equal(invalid.status, 1);
    assert.equal(JSON.parse(invalid.stdout).checks.input, "input_unavailable");
  } finally {
    fs.rmSync(dir, {recursive: true, force: true});
  }
});
