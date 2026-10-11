"use strict";
const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const report = require("../../.github/scripts/experimental-live-report.cjs");
const proof = {sha: "a".repeat(40), runId: 123, runAttempt: 1, prNumber: 62};

function nominal() {
  return {
    schema: 1, scenario: "ha-parity", status: "success",
    merge_sha: proof.sha, run_id: proof.runId,
    run_attempt: proof.runAttempt, pr_number: proof.prNumber,
    refreshes_completed: 2, decoded_refreshes: 2,
    device_identity_assigned: true, device_identity_reused: true, closed: true,
    session_mode: "one-shot", ping_pong: "unsupported",
    data_updated: "unsupported", persistent_session: "unsupported",
    reconnect: "not_tested", error: "none",
  };
}

test("exact public success report validates, two one-shot refreshes only", () => {
  assert.deepEqual(report.validate(nominal(), proof), nominal());
});

for (const [name, mutate] of Object.entries({
  "extra household register": r => {r.registers = [2048, 2026];},
  "wrong merged SHA": r => {r.merge_sha = "b".repeat(40);},
  "wrong run": r => {r.run_id++;},
  "wrong attempt": r => {r.run_attempt++;},
  "wrong PR": r => {r.pr_number++;},
  "string PR": r => {r.pr_number = "62";},
  "extra private metadata": r => {r.private = "SYNTHETIC_PRIVATE";},
  "fake persistent socket": r => {r.session_mode = "persistent";},
  "fake Ping Pong": r => {r.ping_pong = "verified";},
  "fake DataUpdated": r => {r.data_updated = "verified";},
  "wrong profile shape": r => {r.scenario = "h1h2";},
  "less than two refreshes": r => {r.refreshes_completed = 1; r.decoded_refreshes = 1;},
  "no adopted identity": r => {r.device_identity_assigned = false;},
  "no reused identity": r => {r.device_identity_reused = false;},
  "not closed": r => {r.closed = false;},
  "raw exception": r => {r.error = "USER_GUID_SYNTHETIC_PRIVATE";},
  "failure labelled success": r => {r.error = "client_failure";},
  "failure with none error": r => {r.status = "failure";},
  "oversized count": r => {r.decoded_refreshes = 3;},
})) {
  test("reject unexpected/sensitive report: " + name, () => {
    const model = nominal(); mutate(model);
    assert.throws(() => report.validate(model, proof), /invalid_report/);
  });
}

test("bounded regular report: reject symlinks, oversized files and raw objects", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "live-allowlist-"));
  try {
    const file = path.join(dir, "report.json");
    fs.writeFileSync(file, JSON.stringify(nominal()));
    assert.deepEqual(report.readReport(file, proof), nominal());
    const alias = path.join(dir, "alias.json");
    fs.symlinkSync(file, alias);
    assert.throws(() => report.readReport(alias, proof), /invalid_report/);
    fs.writeFileSync(file, JSON.stringify({...nominal(), private: "SYNTHETIC_SECRET"}));
    assert.throws(() => report.readReport(file, proof), /invalid_report/);
    fs.writeFileSync(file, "A".repeat(4097));
    assert.throws(() => report.readReport(file, proof), /invalid_report/);
  } finally {
    fs.rmSync(dir, {recursive: true, force: true});
  }
});


test("report of earlier attempt cannot be reused for later attempt or PR", () => {
  assert.throws(() => report.validate(nominal(), {...proof, runAttempt: 2}), /invalid_report/);
  assert.throws(() => report.validate(nominal(), {...proof, prNumber: 63}), /invalid_report/);
  assert.throws(() => report.validate(nominal(), {...proof, sha: "b".repeat(40)}), /invalid_report/);
  assert.throws(() => report.validate(nominal(), undefined), /invalid_report/);
});

test("isolated publisher preserves validated handoff despite source replacement", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "live-publish-"));
  const old = process.env.RUNNER_TEMP;
  try {
    const collect = path.join(root, "collect");
    const publish = path.join(root, "publish");
    fs.mkdirSync(path.join(collect, "hoben-live-public"), {recursive: true});
    fs.mkdirSync(publish);
    const source = path.join(collect, "hoben-live-public", "report.json");
    fs.writeFileSync(source, JSON.stringify(nominal()));
    const outputs = {}, failures = [];
    const core = {setOutput: (key, value) => {outputs[key] = value;}, setFailed: value => failures.push(value)};
    process.env.RUNNER_TEMP = collect;
    report.prepare({core, context: proof});
    assert.deepEqual(failures, []);
    assert.equal(outputs.report, "true");
    assert.equal(fs.existsSync(path.join(publish, "hoben-live-public")), false);
    fs.rmSync(source);
    fs.symlinkSync(path.join(root, "missing.json"), source);
    process.env.RUNNER_TEMP = publish;
    const published = {}, rejected = [];
    report.publish({core: {setOutput: (key, value) => {published[key] = value;}, setFailed: value => rejected.push(value)}, context: proof, encoded: outputs.report_b64});
    assert.deepEqual(rejected, []);
    assert.equal(published.report, "true");
    assert.deepEqual(JSON.parse(fs.readFileSync(path.join(publish, "hoben-live-public", "report.json"))), nominal());
  } finally {
    if (old === undefined) delete process.env.RUNNER_TEMP;
    else process.env.RUNNER_TEMP = old;
    fs.rmSync(root, {recursive: true, force: true});
  }
});

test("publisher rejects malformed, private, oversized and mismatched campaign handoffs", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "live-reject-"));
  const old = process.env.RUNNER_TEMP;
  try {
    process.env.RUNNER_TEMP = root;
    const cases = [
      "not-base64!", "A".repeat(6000),
      ...[
        {...nominal(), private: "SYNTHETIC_PRIVATE"},
        {...nominal(), merge_sha: "b".repeat(40)},
        {...nominal(), pr_number: 99},
        {...nominal(), run_id: 999},
        {...nominal(), run_attempt: 2},
        {...nominal(), scenario: "h1h2"},
      ].map(model => Buffer.from(JSON.stringify(model)).toString("base64")),
    ];
    for (const encoded of cases) {
      const failures = [], outputs = {};
      report.publish({core: {setOutput: (k,v) => {outputs[k]=v;}, setFailed: v => failures.push(v)}, context: proof, encoded});
      assert.equal(outputs.report, undefined);
      assert.equal(failures.length, 1);
      assert.match(failures[0], /^NOT RUN:/);
      assert.equal(fs.existsSync(path.join(root, "hoben-live-public", "report.json")), false);
    }
  } finally {
    if (old === undefined) delete process.env.RUNNER_TEMP;
    else process.env.RUNNER_TEMP = old;
    fs.rmSync(root, {recursive: true, force: true});
  }
});
