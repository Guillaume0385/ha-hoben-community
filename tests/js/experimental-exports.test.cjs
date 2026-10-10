"use strict";
const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs"), os = require("node:os"), path = require("node:path");
const exportsGate = require("../../.github/scripts/experimental-exports.cjs");
const context = {sha: "a".repeat(40), runId: 123};

function report() {
  const sessions = Array.from({length: 12}, (_, i) => ({
    mode: i < 6 ? "H1" : "H2", pause_seconds: [0, 0.1, 1][Math.floor(i % 6 / 2)], repetition: i % 2 + 1,
    partial: false, prefix_complete: true, rx_bytes: 100, read_calls: 2,
    pongs_before_open: 0, pongs_under_h2: 0, v4_requests: i < 6 ? 0 : 2,
    correlated_responses: i < 6 ? 0 : 2, exception_responses: 0,
    stop: "observation_budget", emission_stop: null,
    opening_context: {eligible: true, status: "accepted_v4_prefix"},
    h1_status: "compatible", h2_status: "compatible", comparison: "compatible_with_both",
  }));
  return {schema: 1, scenario: "h1h2", phase: "live", experimental_sha: context.sha, candidate_sha: context.sha,
    run_id: 123, boundary_proven: false, result: "inconclusive", reason: "hypotheses_unproven",
    executed_sessions: 12, planned_sessions: 12, eligible_sessions: 12, observation_seconds: 90, sessions};
}

function withReport(value, run) {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), "hoben-report-offline-"));
  const file = path.join(temp, "report.json");
  fs.writeFileSync(file, JSON.stringify(value));
  try { run(file, temp); } finally { fs.rmSync(temp, {recursive: true, force: true}); }
}

test("public report retains counts/categories and never proves a boundary", () => {
  withReport(report(), file => {
    const value = exportsGate.readReport(file, context);
    assert.equal(value.result, "inconclusive");
    assert.equal(value.report.boundary_proven, false);
  });
});

for (const [name, modify] of Object.entries({
  "identity key": r => { r.user_guid = "SYNTHETIC_PRIVATE"; },
  "raw value in a category": r => { r.sessions[0].stop = "SYNTHETIC_PRIVATE"; },
  "raw value in a number": r => { r.sessions[0].rx_bytes = "SYNTHETIC_PRIVATE"; },
  "unknown nested key": r => { r.sessions[0].payload = "SYNTHETIC_PRIVATE"; },
  "unknown opening key": r => { r.sessions[0].opening_context.raw = "SYNTHETIC_PRIVATE"; },
  "synthetic success": r => { r.phase = "dry-run"; },
  "wrong SHA": r => { r.experimental_sha = "b".repeat(40); },
  "wrong run": r => { r.run_id++; },
  "false boundary": r => { r.boundary_proven = true; },
  "too many sessions": r => { r.sessions.push(r.sessions[0]); r.executed_sessions++; },
  "short success": r => { r.sessions.pop(); r.executed_sessions--; r.eligible_sessions--; },
  "incoherent eligible count": r => { r.eligible_sessions--; },
  "H1 emits reads": r => { r.sessions[0].v4_requests = 1; },
  "H2 emits too many": r => { r.sessions[6].v4_requests = 3; },
  "RX budget exceeded": r => { r.sessions[0].rx_bytes = 1048577; },
  "responses exceed requests": r => { r.sessions[6].exception_responses = 1; },
  "unsafe mode": r => { r.sessions[0].mode = "H3"; },
})) {
  test("refuse public output: " + name, () => {
    const value = report(); modify(value);
    withReport(value, file => assert.throws(() => exportsGate.readReport(file, context)));
  });
}

test("partial cancelled campaign is a failure report, never a synthetic pass", () => {
  const value = report();
  value.sessions = [value.sessions[0]];
  value.sessions[0].stop = "cancelled"; value.sessions[0].partial = true;
  Object.assign(value, {executed_sessions: 1, eligible_sessions: 1, result: "failure", reason: "collection_interrupted"});
  withReport(value, file => assert.equal(exportsGate.readReport(file, context).result, "failure"));
});

for (const kind of ["symlink", "directory", "fifo", "oversized"]) {
  test("refuse public file: " + kind, () => {
    withReport(report(), (file, temp) => {
      fs.unlinkSync(file);
      if (kind === "symlink") fs.symlinkSync(path.join(temp, "private.json"), file);
      else if (kind === "directory") fs.mkdirSync(file);
      else if (kind === "fifo") require("node:child_process").execFileSync("mkfifo", [file]);
      else fs.writeFileSync(file, "x".repeat(2097153));
      assert.throws(() => exportsGate.readReport(file, context));
    });
  });
}

test("report-only export never attempts CMS and rejects unsafe projection", () => {
  withReport(report(), (file, temp) => {
    const dir = path.join(temp, "hoben-experimental-exports");
    fs.mkdirSync(dir);
    const invalid = report(); invalid.private = "SYNTHETIC_PRIVATE";
    fs.writeFileSync(path.join(dir, "report.json"), JSON.stringify(invalid));
    const before = process.env.RUNNER_TEMP;
    process.env.RUNNER_TEMP = temp;
    const outputs = {}, failures = [];
    const core = {setOutput: (k,v) => {outputs[k] = v;}, setFailed: v => failures.push(v)};
    try {
      exportsGate.prepare({context, core});
      assert.equal(outputs.report, undefined);
      assert.equal(outputs.ciphertext, undefined);
      assert.equal(failures.length, 1);
      assert.ok(!fs.existsSync(path.join(temp, "hoben-experimental-public")));
    } finally {
      if (before === undefined) delete process.env.RUNNER_TEMP;
      else process.env.RUNNER_TEMP = before;
    }
  });
});

test("safe report publishes exactly report.json and never ciphertext", () => {
  withReport(report(), (file, temp) => {
    const dir = path.join(temp, "hoben-experimental-exports");
    fs.mkdirSync(dir);
    fs.copyFileSync(file, path.join(dir, "report.json"));
    const before = process.env.RUNNER_TEMP; process.env.RUNNER_TEMP = temp;
    const outputs = {}, failures = [];
    const core = {setOutput: (k,v) => {outputs[k] = v;}, setFailed: v => failures.push(v)};
    try {
      exportsGate.prepare({context, core});
      assert.deepEqual(outputs, {report: "true"});
      assert.equal(failures.length, 0);
      assert.deepEqual(fs.readdirSync(path.join(temp, "hoben-experimental-public")),
        ["report.json"]);
      assert.ok(!fs.existsSync(path.join(dir, "captures.cms")));
    } finally {
      if (before === undefined) delete process.env.RUNNER_TEMP;
      else process.env.RUNNER_TEMP = before;
    }
  });
});

// Keep the independent Node export-boundary regressions when the CMS lane changes.
// These fixtures contain only synthetic counts/timings, never network bytes.
function timeline() {
  return {
    basis: "client_monotonic_relative",
    reads: [
      {index: 0, offset: 0, requested: 4096, received: 50,
        started_ms: 100, ended_ms: 200, duration_ms: 100,
        gap_previous_ms: null, since_last_tx_ms: 99, state: "received"},
      {index: 1, offset: 50, requested: 4096, received: 50,
        started_ms: 300, ended_ms: 400, duration_ms: 100,
        gap_previous_ms: 100, since_last_tx_ms: 299, state: "received"},
    ],
    tx: [{category: "open_client", started_ms: 0, ended_ms: 1, duration_ms: 1}],
    h2_candidates: [],
    unattributed: [{offset: 48, length: 52, basis: "h2_unproven_suffix"}],
    close: {state: "closed", started_ms: 500, ended_ms: 520, duration_ms: 20},
    fragmented_candidates: 0,
    concatenated_reads: 0,
  };
}

function prepareReport(file, temp) {
  const dir = path.join(temp, "hoben-experimental-exports");
  fs.mkdirSync(dir);
  fs.copyFileSync(file, path.join(dir, "report.json"));
  const before = process.env.RUNNER_TEMP;
  process.env.RUNNER_TEMP = temp;
  const outputs = {}, failures = [];
  const core = {setOutput: (k,v) => {outputs[k] = v;}, setFailed: v => failures.push(v)};
  try {
    exportsGate.prepare({context, core});
    return {outputs, failures, destination: path.join(temp, "hoben-experimental-public")};
  } finally {
    if (before === undefined) delete process.env.RUNNER_TEMP;
    else process.env.RUNNER_TEMP = before;
  }
}

test("strict public timeline is permitted only as bounded timing and unknown offsets", () => {
  const r = report(); r.sessions[0].timing_observations = timeline();
  withReport(r, (file, temp) => {
    const value = exportsGate.readReport(file, context);
    assert.deepEqual(value.report.sessions[0].timing_observations, timeline());
    assert.equal(value.report.boundary_proven, false);
    const {outputs, failures, destination} = prepareReport(file, temp);
    assert.deepEqual(outputs, {report: "true"});
    assert.deepEqual(failures, []);
    assert.deepEqual(fs.readdirSync(destination), ["report.json"]);
    const published = JSON.parse(fs.readFileSync(path.join(destination, "report.json")));
    assert.deepEqual(published, value.report);
  });
});

test("zero-byte EOF read remains in the public timeline of a partial campaign", () => {
  const r = report();
  r.sessions = [r.sessions[0]];
  Object.assign(r, {executed_sessions: 1, eligible_sessions: 1,
    result: "failure", reason: "collection_interrupted"});
  const s = r.sessions[0];
  Object.assign(s, {partial: true, stop: "peer_eof", read_calls: 3,
    timing_observations: timeline()});
  s.timing_observations.reads.push({index: 2, offset: 100, requested: 4096, received: 0,
    started_ms: 450, ended_ms: 480, duration_ms: 30,
    gap_previous_ms: 50, since_last_tx_ms: 449, state: "eof"});
  withReport(r, (file, temp) => {
    const value = exportsGate.readReport(file, context);
    assert.equal(value.result, "failure");
    assert.deepEqual(value.report.sessions[0].timing_observations, s.timing_observations);
    const {outputs, failures, destination} = prepareReport(file, temp);
    assert.deepEqual(outputs, {report: "true"});
    assert.deepEqual(failures, []);
    assert.equal(exportsGate.readReport(path.join(destination, "report.json"), context).result,
      "failure");
  });
});

for (const [title, modify] of Object.entries({
  "private ID": t => {t.device_guid = "SYNTHETIC_PRIVATE_ID";},
  "raw values": t => {t.reads[0].payload = [83, 69, 67];},
  "free text kind": t => {t.tx[0].category = "SYNTHETIC_PRIVATE";},
  "bad offset": t => {t.reads[1].offset = 49;},
  "oversized duration": t => {t.reads[0].duration_ms = 180001;},
  "missing read": t => {t.reads.pop();},
  "too many bytes": t => {t.reads[0].received = 4097;},
  "unknown data": t => {t.unattributed[0].bytes = "SYNTHETIC_PRIVATE_RX";},
  "invented frame": t => {t.h2_candidates.push({offset: 50});},
  "misleading fragment claim": t => {t.fragmented_candidates = 1;},
  "changed close": t => {t.close.duration_ms = 1234;},
  "malformed number": t => {t.reads[0].started_ms = NaN;},
})) {
  test("reject suspect public timeline: " + title, () => {
    const r = report(); r.sessions[0].timing_observations = timeline();
    modify(r.sessions[0].timing_observations);
    withReport(r, (file, temp) => {
      assert.throws(() => exportsGate.readReport(file, context), /invalid_public_timeline/);
      const {outputs, failures, destination} = prepareReport(file, temp);
      assert.deepEqual(outputs, {});
      assert.deepEqual(failures, ["Public report refused before upload."]);
      assert.ok(!fs.existsSync(destination));
    });
  });
}
