"use strict";
const {test} = require("node:test");
const assert = require("node:assert/strict");
const contract = require("../../.github/scripts/experimental-native-rerun.cjs");
const sha = "a".repeat(40), candidateSha = "b".repeat(40);
const repo = {full_name: "Guillaume0385/ha-hoben-community", id: 1401398724};
const owner = {login: "Guillaume0385", id: 18246624, type: "User"};
const workflow = repo.full_name +
  "/.github/workflows/hoben-experimental.yml@refs/heads/experimental";

function setup(number = 1, phase = "admission") {
  const context = {eventName: "push", ref: "refs/heads/experimental",
    actor: owner.login, runId: 123, sha};
  const env = {
    GITHUB_RUN_ATTEMPT: String(number), GITHUB_RUN_ID: "123",
    GITHUB_REF: context.ref, GITHUB_SHA: sha, GITHUB_ACTOR: owner.login,
    GITHUB_TRIGGERING_ACTOR: owner.login, GITHUB_WORKFLOW_REF: workflow,
    GITHUB_WORKFLOW_SHA: sha
  };
  const run = {id: 123, run_attempt: number, event: "push", head_sha: sha,
    head_branch: "experimental", actor: {...owner}, triggering_actor: {...owner},
    repository: {...repo}, head_repository: {...repo},
    path: ".github/workflows/hoben-experimental.yml"};
  const jobs = [
    {name: "dry-run", status: "completed", conclusion: "success",
      started_at: "2026-10-10T12:00:00Z"},
    {name: "admission", status: phase === "recheck" ? "completed" : "in_progress",
      conclusion: phase === "recheck" ? "success" : null},
    {name: "collect", status: "in_progress", conclusion: null}
  ].map((j, i) => ({id: i + 100, run_id: 123, run_attempt: number,
    head_sha: sha, ...j}));
  const previousJobs = [{name: "dry-run", run_attempt: number - 1,
    conclusion: "success"}];
  return {context, env, run, jobs, previousJobs, workflow, phase};
}

for (const attempt of [1, 2, 3]) {
  for (const phase of ["admission", "recheck"]) {
    test("full synthetic run attempt " + attempt + " phase " + phase, () => {
      const input = setup(attempt, phase);
      const result = contract.authorizeAttempt(input);
      assert.deepEqual(result, {
        number: attempt, beganAt: Date.parse("2026-10-10T12:00:00Z")
      });
      assert(Object.isFrozen(result));
    });
  }
}

for (let [name, mutation] of Object.entries({
  "wrong SHA": a => {a.env.GITHUB_SHA = candidateSha;},
  "wrong run id": a => {a.run.id++;},
  "wrong run attempt": a => {a.run.run_attempt = 1;},
  "unknown real triggering actor": a => {delete a.run.triggering_actor;},
  "untrusted triggering actor": a => {a.run.triggering_actor.id++;},
  "untrusted env triggering actor": a => {a.env.GITHUB_TRIGGERING_ACTOR = "other";},
  "untrusted original actor": a => {a.run.actor.id++;},
  "fork": a => {a.run.head_repository.id++;},
  "main branch": a => {a.run.head_branch = "main";},
  "untrusted workflow": a => {a.run.path = "other.yml";},
  "zero attempt": a => {a.env.GITHUB_RUN_ATTEMPT = "0";},
  "attempt too high": a => {a.env.GITHUB_RUN_ATTEMPT = "51";},
  "stale dry run from failed-jobs retry": a => {a.jobs[0].run_attempt--;},
  "stale admission": a => {a.jobs[1].run_attempt--;},
  "duplicate dry run": a => {a.jobs.push({...a.jobs[0]});},
  "failed previous dry run": a => {a.previousJobs[0].conclusion = "failure";},
  "missing previous job history": a => {a.previousJobs = null;},
  "missing dry start timestamp": a => {delete a.jobs[0].started_at;},
  "original run failed dry step": a => {a.jobs[0].conclusion = "failure";},
  "admission already completed unexpectedly": a => {a.jobs[1].status = "completed";},
  "oversized job set": a => {a.jobs.push(...Array(6).fill(a.jobs[2]));}
})) {
  test("NOT RUN: " + name, () => {
    const input = setup(2);
    mutation(input);
    assert.throws(() => contract.authorizeAttempt(input),
      /attempt_unverified|partial_rerun/);
  });
}

for (const scenario of ["h1h2", "ha-parity"]) {
  for (const number of [1, 2, 3]) {
    function decision() {
      const proof = {number, beganAt: Date.parse("2026-10-10T12:00:00Z")};
      const marker = `<!-- hoben-${scenario}-approval:v${number === 1 ? 1 : 2} -->`;
      const model = {schema: number === 1 ? 1 : 2, scenario,
        candidate_sha: candidateSha, ci_run_id: 456};
      if (number > 1) Object.assign(model, {pr_number: 59,
        merge_sha: sha, run_id: 123, run_attempt: number});
      const comment = {id: 777, user: {...owner},
        created_at: number === 1 ? "2026-10-09T12:00:00Z" : "2026-10-10T11:59:00Z",
        updated_at: number === 1 ? "2026-10-09T12:00:00Z" : "2026-10-10T11:59:00Z",
        body: marker + "\n" + JSON.stringify(model)};
      return {comments: [comment], marker, scenario, candidateSha,
        ciId: 456, pr: {number: 59, merged_at: "2026-10-09T13:00:00Z"},
        mergeSha: sha, runId: 123, proof};
    }
    test("authentic per-attempt decision " + scenario + " #" + number, () => {
      const x = decision();
      const proof = contract.authorizeDecision(x);
      assert.equal(proof.comment.id, 777);
      assert(Object.isFrozen(proof));
    });
    for (const [name, mutation] of Object.entries({
      "missing": a => {a.comments = [];},
      "edited": a => {a.comments[0].updated_at = "2026-10-10T11:58:59Z";},
      "wrong actor": a => {a.comments[0].user.id++;},
      "wrong scenario": a => {
        const m = JSON.parse(a.comments[0].body.slice(a.marker.length));
        m.scenario = "different"; a.comments[0].body = a.marker + "\n" + JSON.stringify(m);
      },
      "extra field": a => {
        const m = JSON.parse(a.comments[0].body.slice(a.marker.length));
        m.secret = "synthetic"; a.comments[0].body = a.marker + "\n" + JSON.stringify(m);
      },
      "duplicate": a => {a.comments.push({...a.comments[0], id: 888});},
      "CI mismatch": a => {a.ciId++;},
      "SHA mismatch": a => {a.mergeSha = candidateSha;},
      "candidate mismatch": a => {a.candidateSha = sha;},
      "malformed": a => {a.comments[0].body = a.marker + "\n{";},
      "invalid timestamp": a => {a.comments[0].created_at = "not-a-date";}
    })) {
      if (name === "SHA mismatch" && number === 1) continue;
      if (name === "CI mismatch") {
        mutation = a => {const m = JSON.parse(a.comments[0].body.slice(a.marker.length));
          m.ci_run_id++; a.comments[0].body = a.marker + "\n" + JSON.stringify(m);};
      }
      test("reject decision " + scenario + " #" + number + ": " + name, () => {
        const input = decision(); mutation(input);
        assert.throws(() => contract.authorizeDecision(input), /decision_unverified/);
      });
    }
    if (number > 1) {
      test("v1 approval cannot authorize native rerun #" + number, () => {
        const x = decision(), m = JSON.parse(x.comments[0].body.slice(x.marker.length));
        delete m.pr_number; delete m.merge_sha; delete m.run_id; delete m.run_attempt;
        m.schema = 1; x.comments[0].body = x.marker + "\n" + JSON.stringify(m);
        assert.throws(() => contract.authorizeDecision(x), /decision_unverified/);
      });
      test("late approval is denied for rerun #" + number, () => {
        const x = decision();
        x.comments[0].created_at = x.comments[0].updated_at =
          "2026-10-10T12:01:00Z";
        assert.throws(() => contract.authorizeDecision(x), /decision_unverified/);
      });
    }
  }
}
test("distinct irreversible claim keys per attempt and scenario", () => {
  const claims = new Set();
  for (const scenario of ["h1h2", "ha-parity"]) {
    for (const number of [1, 2, 3]) {
      claims.add(contract.claimName(scenario, sha, 123, number));
    }
  }
  assert.equal(claims.size, 6);
  assert.throws(() => contract.claimName("other", sha, 123, 2), /claim_unverified/);
});
