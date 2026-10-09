"use strict";
const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const report = require("../../.github/scripts/experimental-live-report.cjs");

function nominal() {
  return {
    schema: 1, scenario: "ha-parity", status: "success",
    refreshes_completed: 2, decoded_refreshes: 2,
    device_identity_assigned: true, device_identity_reused: true, closed: true,
    session_mode: "one-shot", ping_pong: "unsupported",
    data_updated: "unsupported", persistent_session: "unsupported",
    reconnect: "not_tested", error: "none",
  };
}

test("exact public success report validates, two one-shot refreshes only", () => {
  assert.deepEqual(report.validate(nominal()), nominal());
});

for (const [name, mutate] of Object.entries({
  "extra household register": r => {r.registers = [2048, 2026];},
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
    assert.throws(() => report.validate(model), /invalid_report/);
  });
}

test("bounded regular report: reject symlinks, oversized files and raw objects", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "live-allowlist-"));
  try {
    const file = path.join(dir, "report.json");
    fs.writeFileSync(file, JSON.stringify(nominal()));
    assert.deepEqual(report.readReport(file), nominal());
    const alias = path.join(dir, "alias.json");
    fs.symlinkSync(file, alias);
    assert.throws(() => report.readReport(alias), /invalid_report/);
    fs.writeFileSync(file, JSON.stringify({...nominal(), private: "SYNTHETIC_SECRET"}));
    assert.throws(() => report.readReport(file), /invalid_report/);
    fs.writeFileSync(file, "A".repeat(4097));
    assert.throws(() => report.readReport(file), /invalid_report/);
  } finally {
    fs.rmSync(dir, {recursive: true, force: true});
  }
});
