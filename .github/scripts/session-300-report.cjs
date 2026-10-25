"use strict";
// Independent, secretless projection at both export and isolated publication.
const fs = require("node:fs"), path = require("node:path");
const safe = require("./experimental-report-file.cjs");
const need = v => {if (!v) throw Error("invalid_session_300_report");};
const keys = ["schema","scenario","merge_sha","candidate_sha","run_id","run_attempt",
  "pr_number","boundary_proven","result","terminal","duration_ms","opens",
  "reconnections","pings","pongs","reads","reads_ok","reads_failed","responses",
  "rx_bytes_total","rx_chunks_total","read_slot",
  "failure_phase","failure_category","message_category"];
const stops = new Set(["completed","recovery_verified","protocol","budget","transport",
  "timeout","modbus","closed","cancelled","internal","context","authorization"]);
const messages = new Map([
  ["none",["unclassified"]], ["opening",["unclassified"]],
  ["scheduled_read",["unclassified"]], ["lifecycle_transition",["unclassified"]],
  ["teardown",["unclassified"]], ["tls_read",["unclassified"]],
  ["frame_boundary",["unclassified","ambiguous"]], ["message_classification",["unknown"]],
  ["request_correlation",["data_response"]], ["response_validation",["data_response"]],
  ["pong_tx",["ping"]],
  ["close_client",["close_client"]],
]);
function validIgnoredMessages(value, rxBytes) {
  if (!value || typeof value !== "object" || Array.isArray(value) ||
      Object.keys(value).sort().join() !== "27,7") return false;
  let total = 0;
  for (const [key,minimum] of [["7",9],["27",13]]) {
    const bins = value[key];
    if (!Array.isArray(bins) || bins.length !== 253) return false;
    for (let i=0; i<253; i++) {
      const count = bins[i];
      if (!Number.isSafeInteger(count) || count < 0 || count > 1048576) return false;
      total += (minimum+i)*count;
    }
  }
  return total <= rxBytes;
}
function validCloseClient(value, opens, rxBytes, reconnect=false) {
  if (!value || typeof value !== "object" || Array.isArray(value) ||
      Object.keys(value).sort().join() !== "after_threshold_ms,phase,subcodes") return false;
  const codes=value.subcodes,after=value.after_threshold_ms;
  return value.phase==="post_open" && Array.isArray(codes) && codes.length>=1 &&
    codes.length<=Math.min(3,opens) && codes.every(v=>Number.isSafeInteger(v)&&v>=0&&v<=255) &&
    2*codes.length<=rxBytes && (after===null ||
      reconnect&&Number.isSafeInteger(after)&&after>=0&&after<=480000);
}
function validate(r, p) {
  const expected = [...keys];
  if (r && Object.hasOwn(r,"ignored_messages")) expected.push("ignored_messages");
  if (r && Object.hasOwn(r,"close_client")) expected.push("close_client");
  need(r && typeof r === "object" && !Array.isArray(r) &&
    Object.keys(r).sort().join() === [...expected].sort().join());
  need(r.schema === 1 && r.scenario === "session-300" && r.boundary_proven === false);
  need(["merge_sha","candidate_sha"].every(k => /^[a-f0-9]{40}$/.test(r[k])));
  need(["merge_sha","candidate_sha","run_id","run_attempt","pr_number"].every(k => r[k] === p[k]));
  need(Number.isSafeInteger(r.run_attempt) && r.run_attempt >= 1 && r.run_attempt <= 50 &&
    Number.isSafeInteger(r.run_id) && r.run_id > 0 &&
    Number.isSafeInteger(r.pr_number) && r.pr_number > 0);
  for (const [k,max] of Object.entries({duration_ms:300000,opens:3,reconnections:2,
    pings:1048576,pongs:1048576,reads:6,reads_ok:6,reads_failed:6,responses:6,
    rx_bytes_total:1048576,rx_chunks_total:1048576,read_slot:6})) {
    need(Number.isSafeInteger(r[k]) && r[k] >= 0 && r[k] <= max);
  }
  need(["continuous_300s","reconnected","interrupted","inconclusive","not_run"].includes(r.result)
    && stops.has(r.terminal) && r.reconnections === Math.max(0,r.opens-1) &&
    r.pongs <= r.pings && r.reads_ok+r.reads_failed === r.reads &&
    r.reads_ok <= r.responses && r.responses <= r.reads);
  need(messages.has(r.failure_phase) &&
    r.failure_category === r.terminal &&
    messages.get(r.failure_phase).includes(r.message_category) &&
    r.read_slot === r.reads && r.rx_chunks_total <= r.rx_bytes_total &&
    (r.failure_phase === "none") === ["completed","recovery_verified"].includes(r.terminal));
  if (Object.hasOwn(r,"ignored_messages")) need(validIgnoredMessages(r.ignored_messages,r.rx_bytes_total));
  if (Object.hasOwn(r,"close_client")) need(validCloseClient(r.close_client,r.opens,r.rx_bytes_total));
  if (r.failure_phase==="close_client") need(Object.hasOwn(r,"close_client")&&r.terminal==="closed");
  if (["continuous_300s","reconnected"].includes(r.result)) {
    need(r.duration_ms === 300000 && r.reads_ok > 0 && r.pings === r.pongs);
    need(r.result === "continuous_300s" ? r.opens === 1 && r.reads_failed === 0 &&
      r.terminal === "completed" : r.opens >= 2 && r.terminal === "recovery_verified");
  } else need(!["completed","recovery_verified"].includes(r.terminal));
  return Object.fromEntries([...expected].sort().map(k => [k,r[k]]));
}
function readReport(file, proof) {
  return validate(JSON.parse(safe.snapshot(file,4096).toString("utf8")),proof);
}
function prepare({core,proof}) {
  try {
    const r = readReport(path.join(process.env.RUNNER_TEMP,"hoben-session-300-exports/report.json"),proof);
    core.setOutput("report_b64",Buffer.from(JSON.stringify(r)).toString("base64"));
  } catch (_) {core.setFailed("NOT RUN: session-300 export refused.");}
}
function publish({core,proof,encoded}) {
  let file;
  try {
    need(typeof encoded === "string" && encoded.length <= 5500);
    const bytes = Buffer.from(encoded,"base64");
    need(bytes.toString("base64") === encoded && bytes.length <= 4096);
    const r = validate(JSON.parse(bytes.toString("utf8")),proof);
    const parent = process.env.RUNNER_TEMP;
    need(typeof parent === "string" && path.isAbsolute(parent));
    const dir = path.join(parent,"hoben-session-300-public");
    fs.mkdirSync(dir,{mode:0o700});
    file = path.join(dir,"report.json");
    fs.writeFileSync(file,JSON.stringify(r),{mode:0o600,flag:"wx"});
    readReport(file,proof);
    core.setOutput("report","true");
  } catch (_) {
    if (file) {try {fs.unlinkSync(file);} catch (_) {}}
    core.setFailed("NOT RUN: session-300 publication refused.");
  }
}
module.exports = {validate,validIgnoredMessages,validCloseClient,readReport,prepare,publish};
