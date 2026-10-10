"use strict";
const {test} = require("node:test");
const assert = require("node:assert/strict");
const {verify, WORKFLOW} =
  require("../../.github/scripts/experimental-campaign-trigger-proof.cjs");

const sha = "a".repeat(40);
const id = "0123456789abcdef";
const name = "hoben-campaign-proof/" + id;
const ref = "refs/heads/" + name;
const actor = "Guillaume0385";

function fixture() {
  const payload = {
    ref, before: "0".repeat(40), after: sha,
    created: true, deleted: false, forced: false,
    repository: {full_name: "Guillaume0385/ha-hoben-community", id: 1401398724},
    sender: {login: actor, id: 18246624, type: "User"}
  };
  const context = {ref, sha, payload, eventName: "push", actor, runAttempt: 1};
  const env = {
    GITHUB_ACTIONS: "true", GITHUB_REPOSITORY: payload.repository.full_name,
    GITHUB_EVENT_NAME: "push", GITHUB_REF: ref, GITHUB_SHA: sha,
    GITHUB_WORKFLOW_SHA: sha, GITHUB_WORKFLOW_REF: WORKFLOW + ref,
    GITHUB_ACTOR: actor, GITHUB_TRIGGERING_ACTOR: actor, GITHUB_RUN_ATTEMPT: "1"
  };
  const branches = {
    experimental: {name: "experimental", protected: true, commit: {sha}},
    [name]: {name, protected: false, commit: {sha}}
  };
  const calls = [];
  const github = {rest: {repos: {
    getBranch: async ({owner, repo, branch}) => {
      calls.push(branch);
      assert.equal(owner, "Guillaume0385");
      assert.equal(repo, "ha-hoben-community");
      if (!branches[branch]) throw Error("SYNTHETIC-PRIVATE-API-FAILURE");
      return {data: branches[branch]};
    }
  }}};
  return {context, env, github, branches, calls, payload};
}

test("unique branch created at reviewed protected HEAD is secretless proof only", async () => {
  const f = fixture();
  const result = await verify({github: f.github, context: f.context, env: f.env});
  assert.deepEqual(result, {
    status: "SECRETLESS_TRIGGER_OBSERVED", scenario: "none",
    campaign_id: id, sha, authorized_live: false
  });
  assert.deepEqual(f.calls.sort(), ["experimental", name].sort());
  assert.equal(Object.isFrozen(result), true);
});

for (const [fault, mutate] of Object.entries({
  "normal push not new branch": f => {f.payload.created = false;},
  "other branch": f => {f.context.ref = "refs/heads/main";},
  "other workflow": f => {f.env.GITHUB_WORKFLOW_REF = "wrong";},
  "wrong actor": f => {f.context.actor = "other";},
  "wrong sender ID": f => {f.payload.sender.id++;},
  "forked repository": f => {f.payload.repository.id++;},
  "rerun": f => {f.context.runAttempt = 2;},
  "rerun env": f => {f.env.GITHUB_RUN_ATTEMPT = "2";},
  "different SHA": f => {f.env.GITHUB_SHA = "b".repeat(40);},
  "workflow SHA moved": f => {f.env.GITHUB_WORKFLOW_SHA = "b".repeat(40);},
  "tag injection": f => {f.context.ref = "refs/tags/" + name;},
  "branch name injection": f => {f.context.ref = ref + "/other";},
  "uppercase id": f => {f.context.ref = ref.toUpperCase();},
  "branch reuse": f => {f.payload.before = "b".repeat(40);},
  "wrong after": f => {f.payload.after = "b".repeat(40);},
  "forced": f => {f.payload.forced = true;},
  "deleted": f => {f.payload.deleted = true;},
  "wrong triggering actor": f => {f.env.GITHUB_TRIGGERING_ACTOR = "other";},
  "invalid payload": f => {f.context.payload = {};},
  "unprotected experimental": f => {f.branches.experimental.protected = false;},
  "advanced experimental": f => {f.branches.experimental.commit.sha = "b".repeat(40);},
  "moved proof branch": f => {f.branches[name].commit.sha = "b".repeat(40);},
  "wrong branch name from API": f => {f.branches[name].name = "other";},
  "API refused": f => {delete f.branches.experimental;}
})) {
  test("NOT RUN: " + fault, async () => {
    const f = fixture();
    mutate(f);
    await assert.rejects(
      verify({github: f.github, context: f.context, env: f.env}),
      /trigger_proof_refused|SYNTHETIC-PRIVATE-API-FAILURE/
    );
    assert.ok(f.calls.length <= 2);
  });
}

test("no observational side effect or tag/claim mutation ever available", async () => {
  const f = fixture();
  f.github.rest.git = new Proxy({}, {get: () => { throw Error("unsafe"); }});
  await verify({github: f.github, context: f.context, env: f.env});
});
