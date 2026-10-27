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
  "merge_sha", "run_id", "run_attempt", "pr_number",
  "status", "refreshes_completed", "decoded_refreshes",
  "device_identity_assigned", "device_identity_reused", "closed", "error"].sort());
const ERRORS = ["none", "invalid_context", "client_failure", "timeout", "close_failure"];

function validate(model, context) {
  if (!model || typeof model !== "object" || Array.isArray(model) ||
      Object.keys(model).sort().join() !== KEYS.join()) throw Error("invalid_report");
  if (!context || !/^[0-9a-f]{40}$/.test(context.sha) ||
      !Number.isSafeInteger(context.runId) || context.runId <= 0 ||
      !Number.isSafeInteger(context.runAttempt) ||
      context.runAttempt < 1 || context.runAttempt > 50 ||
      !Number.isSafeInteger(context.prNumber) || context.prNumber <= 0 ||
      model.merge_sha !== context.sha || model.run_id !== context.runId ||
      model.run_attempt !== context.runAttempt ||
      model.pr_number !== context.prNumber) throw Error("invalid_report");
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

function readReport(filename, context) {
  const stat = fs.lstatSync(filename);
  if (!stat.isFile() || stat.isSymbolicLink() || stat.size < 20 || stat.size > 4096) {
    throw Error("invalid_report");
  }
  return validate(JSON.parse(fs.readFileSync(filename, "utf8")), context);
}

// Limit GitHub job-output handoff to a fixed, independently validated
// allowlist. The publisher is a new runner with no Hoben secrets or candidate
// collector process, so it cannot race the collection runner's public file.
const MAX_REPORT_BYTES = 4096;
function encode(model) {
  const bytes = Buffer.from(JSON.stringify(model), "utf8");
  if (bytes.length > MAX_REPORT_BYTES) throw Error("invalid_report");
  return bytes.toString("base64");
}

function prepare({core, context}) {
  try {
    const parent = process.env.RUNNER_TEMP;
    if (typeof parent !== "string" || !path.isAbsolute(parent)) throw Error("invalid_path");
    const model = readReport(path.join(parent, "hoben-live-public", "report.json"), context);
    core.setOutput("report_b64", encode(model));
    core.setOutput("report", "true");
  } catch (_) {
    core.setFailed("NOT RUN: missing or invalid sanitized HA parity report.");
  }
}

function publish({core, context, encoded}) {
  try {
    if (typeof encoded !== "string" || encoded.length > 5464 ||
        !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(encoded)) {
      throw Error("invalid_report");
    }
    const bytes = Buffer.from(encoded, "base64");
    if (bytes.toString("base64") !== encoded || bytes.length > MAX_REPORT_BYTES) {
      throw Error("invalid_report");
    }
    const model = validate(JSON.parse(bytes.toString("utf8")), context);
    const parent = process.env.RUNNER_TEMP;
    if (typeof parent !== "string" || !path.isAbsolute(parent)) throw Error("invalid_path");
    const dir = path.join(parent, "hoben-live-public");
    fs.mkdirSync(dir, {mode: 0o700});
    const file = path.join(dir, "report.json");
    fs.writeFileSync(file, JSON.stringify(model), {mode: 0o600, flag: "wx"});
    readReport(file, context);
    core.setOutput("report", "true");
  } catch (_) {
    core.setFailed("NOT RUN: isolated HA parity report rejected.");
  }
}

module.exports = {readReport, validate, prepare, publish};
