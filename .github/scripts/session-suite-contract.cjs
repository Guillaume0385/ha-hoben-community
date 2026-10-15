"use strict";
// Fixed review contract, never executable budgets supplied by a comment/input.
// This module neither grants access nor removes the suite-installation barrier.
const MARKER = "<!-- hoben-session-suite-approval:v1 -->";
function freeze(value) {
  if (value && typeof value === "object") {
    Object.values(value).forEach(freeze);
    Object.freeze(value);
  }
  return value;
}
const CONTRACT = freeze({
  scenarios: ["session-300", "session-reconnect-no-pong"],
  limits: {
    suite_process_seconds: 1020,
    session_300: {
      useful_seconds: 300, process_seconds: 360,
      max_opens: 3, max_rx_bytes: 1048576, max_reads: 6, min_read_interval_seconds: 60,
    },
    session_reconnect_no_pong: {
      process_seconds: 600, observation_seconds: 590, cleanup_seconds: 10,
      max_opens: 3, max_rx_bytes: 1048576, max_reads: 10, min_read_interval_seconds: 60,
      suppress_after_seconds: 120, eof_wait_seconds: 180, stable_seconds: 120,
    },
  },
});
// Closed recursive comparison: object key ordering is immaterial, array order
// is mandatory, extra/missing keys and numeric strings/booleans are refused.
function exact(actual, expected) {
  if (expected === null || typeof expected !== "object") return actual === expected;
  if (!actual || typeof actual !== "object" || Array.isArray(actual) !== Array.isArray(expected))
    return false;
  const keys = Object.keys(expected).sort();
  return Object.keys(actual).sort().join() === keys.join() &&
    keys.every(k => exact(actual[k], expected[k]));
}
function validApproval(approval, candidate) {
  return exact(approval, {
    schema: 1, scenario: "session-suite", candidate_sha: candidate,
    ci_run_id: approval?.ci_run_id, ...CONTRACT,
  }) && Number.isSafeInteger(approval.ci_run_id) && approval.ci_run_id > 0;
}
module.exports = Object.freeze({MARKER, CONTRACT, validApproval});
