"use strict";

// Read only a fixed, bounded report schema. A candidate-controlled file cannot
// escape to GitHub artifacts/logs without independent fixed-value validation.
const fs = require("node:fs");
const path = require("node:path");

const VALUES = Object.freeze({
  schema: 1,
  scenario: "ha-parity",
  session_mode: "one-shot",
  ping_pong: "unsupported",
  data_updated: "unsupported",
  persistent_session: "unsupported",
  reconnect: "not_tested",
});
const KEYS = Object.freeze([...Object.keys(VALUES),
  "status", "refreshes_completed", "decoded_refreshes",
  "device_identity_assigned", "device_identity_reused", "closed", "error"].sort());
const ERRORS = ["none", "invalid_context", "client_failure", "timeout", "close_failure"];

function validate(model) {
  if (!model || typeof model !== "object" || Array.isArray(model) ||
      Object.keys(model).sort().join() !== KEYS.join()) throw Error("invalid_report");
  for (const [key, expected] of Object.entries(VALUES)) {
    if (model[key] !== expected) throw Error("invalid_report");
  }
  if (!["success", "failure"].includes(model.status) ||
      !ERRORS.includes(model.error) ||
      !Number.isInteger(model.refreshes_completed) ||
      !Number.isInteger(model.decoded_refreshes) ||
      model.refreshes_completed < 0 || model.refreshes_completed > 2 ||
      model.decoded_refreshes !== model.refreshes_completed ||
      ["device_identity_assigned", "device_identity_reused", "closed"].some(
        name => typeof model[name] !== "boolean")
      ) throw Error("invalid_report");
  if (model.status === "success" &&
      (model.error !== "none" || model.refreshes_completed !== 2 ||
       !model.device_identity_assigned || !model.device_identity_reused ||
       !model.closed)) throw Error("invalid_report");
  if (model.status === "failure" && model.error === "none") {
    throw Error("invalid_report");
  }
  return model;
}

function readReport(filename) {
  const stat = fs.lstatSync(filename);
  if (!stat.isFile() || stat.isSymbolicLink() || stat.size < 20 || stat.size > 4096) {
    throw Error("invalid_report");
  }
  return validate(JSON.parse(fs.readFileSync(filename, "utf8")));
}

function prepare({core}) {
  try {
    const parent = process.env.RUNNER_TEMP;
    if (typeof parent !== "string" || !path.isAbsolute(parent)) throw Error("invalid_path");
    readReport(path.join(parent, "hoben-live-public", "report.json"));
    core.setOutput("report", "true");
  } catch (_) {
    core.setFailed("NOT RUN: missing or invalid sanitized HA parity report.");
  }
}

module.exports = {readReport, validate, prepare};
