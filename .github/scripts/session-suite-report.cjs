"use strict";
// Strict suite projection; used on export and a separate secretless publisher.
const fs = require("node:fs"), path = require("node:path");
const safe = require("./experimental-report-file.cjs");
const MAX_REPORT_BYTES = 8192;
const firstApi = require("./session-300-report.cjs");
const need = v => { if (!v) throw Error("invalid_session_suite_report"); };
const provenance = ["merge_sha","candidate_sha","run_id","run_attempt","pr_number"];
const limits = {duration_ms:600000,opens:3,reconnections:2,pings:1048576,pongs:1048576,
  reads:10,reads_ok:10,reads_failed:10,responses:10,rx_bytes_total:1048576,
  rx_chunks_total:1048576,pongs_suppressed:1048576,peer_eofs:3,eofs_after_suppression:1,
  stable_ms:120000,recovery_generation:3,recovery_reads_ok:10,recovery_pongs:1048576};
const secondKeys = [...provenance,...Object.keys(limits),"schema","scenario",
  "boundary_proven","result","terminal","eof_after_threshold_ms"];
const suiteKeys = [...provenance,"schema","scenario","boundary_proven","result",
  "duration_ms","session_300","session_reconnect_no_pong"];
const terminals = new Set(["verified","not_exercised","no_disconnect","reopen_failed",
  "stability_lost","timeout","budget","transport","protocol","internal","closed",
  "first_not_admissible"]);
function keys(r, expected) {
  need(r && typeof r === "object" && !Array.isArray(r) &&
    Object.keys(r).sort().join() === [...expected].sort().join());
}
function validateSecond(r,p) {
  keys(r,secondKeys);
  need(r.schema === 1 && r.scenario === "session-reconnect-no-pong" && r.boundary_proven === false);
  need(provenance.every(k => r[k] === p[k]));
  for (const [k,max] of Object.entries(limits))
    need(Number.isSafeInteger(r[k]) && r[k] >= 0 && r[k] <= max);
  need(terminals.has(r.terminal) &&
    ["recovered_120s","inconclusive","interrupted","not_run"].includes(r.result));
  need(r.reconnections === Math.max(0,r.opens-1) &&
    r.pongs+r.pongs_suppressed <= r.pings &&
    r.reads_ok+r.reads_failed === r.reads && r.reads_ok <= r.responses && r.responses <= r.reads &&
    r.rx_chunks_total <= r.rx_bytes_total && r.eofs_after_suppression <= r.peer_eofs &&
    r.peer_eofs <= r.opens && r.recovery_generation <= r.opens &&
    r.recovery_reads_ok <= r.reads_ok && r.recovery_pongs <= r.pongs);
  const eof = r.eof_after_threshold_ms;
  need(eof === null || (Number.isSafeInteger(eof) && eof >= 0 && eof <= 480000));
  need((eof !== null) === (r.eofs_after_suppression === 1));
  if (eof !== null) need(r.pongs_suppressed > 0);
  need((r.result === "recovered_120s") === (r.terminal === "verified"));
  need((r.result === "not_run") === (r.terminal === "first_not_admissible"));
  if (r.result === "not_run") need(Object.keys(limits).every(k => r[k] === 0) && eof === null);
  if (r.result === "recovered_120s") need(eof !== null && eof <= 180000 &&
    r.opens >= 2 && r.recovery_generation >= 2 && r.stable_ms === 120000 &&
    r.duration_ms >= 240000 && r.recovery_reads_ok > 0 && r.recovery_pongs > 0);
  if (r.terminal === "not_exercised") need(r.pongs_suppressed === 0 && eof === null);
  if (r.terminal === "no_disconnect") need(r.pongs_suppressed > 0 && (eof === null || eof > 180000));
  return Object.fromEntries([...secondKeys].sort().map(k => [k,r[k]]));
}
function validate(r,p) {
  keys(r,suiteKeys);
  need(r.schema === 1 && r.scenario === "session-suite" && r.boundary_proven === false);
  need(provenance.every(k => r[k] === p[k]));
  need(Number.isSafeInteger(r.duration_ms) && r.duration_ms >= 0 && r.duration_ms <= 1020000);
  const first = firstApi.validate(r.session_300,p);
  const second = validateSecond(r.session_reconnect_no_pong,p);
  const admissible = ["continuous_300s","reconnected"].includes(first.result);
  need(admissible || second.result === "not_run");
  need(r.result === (admissible && second.result === "recovered_120s" ? "success" : "not_successful"));
  need(r.duration_ms >= first.duration_ms+second.duration_ms);
  return {...Object.fromEntries([...suiteKeys].sort().map(k => [k,r[k]])),
    session_300:first,session_reconnect_no_pong:second};
}
function readReport(file, proof) {
  return validate(JSON.parse(safe.snapshot(file,MAX_REPORT_BYTES).toString("utf8")),proof);
}
function prepare({core,proof}) {
  try {
    const r = readReport(path.join(process.env.RUNNER_TEMP,"hoben-session-suite-exports/report.json"),proof);
    const bytes = Buffer.from(JSON.stringify(r));
    need(bytes.length <= MAX_REPORT_BYTES);
    core.setOutput("report_b64",bytes.toString("base64"));
  } catch (_) {core.setFailed("NOT RUN: session-suite export refused.");}
}
function publish({core,proof,encoded}) {
  let file, created = false;
  try {
    need(typeof encoded === "string" && encoded.length <= 10924);
    const bytes = Buffer.from(encoded,"base64");
    need(bytes.toString("base64") === encoded && bytes.length <= MAX_REPORT_BYTES);
    const r = validate(JSON.parse(bytes.toString("utf8")),proof);
    const parent = process.env.RUNNER_TEMP;
    need(typeof parent === "string" && path.isAbsolute(parent));
    const dir = path.join(parent,"hoben-session-suite-public");
    fs.mkdirSync(dir,{mode:0o700});
    fs.chmodSync(dir,0o700);
    file = path.join(dir,"report.json");
    const fd = fs.openSync(file,fs.constants.O_WRONLY|fs.constants.O_CREAT|
      fs.constants.O_EXCL|fs.constants.O_NOFOLLOW,0o600);
    created = true;
    try {fs.fchmodSync(fd,0o600);fs.writeFileSync(fd,JSON.stringify(r));}
    finally {fs.closeSync(fd);}
    readReport(file,proof);
    core.setOutput("report","true");
  } catch (_) {
    if (created) {try {fs.unlinkSync(file);} catch (_) {}}
    core.setFailed("NOT RUN: session-suite publication refused.");
  }
}
function completed(r, proof, collection, publication) {
  return validate(r,proof).result === "success" && collection === "success" && publication === "success";
}
module.exports = {validate,validateSecond,readReport,prepare,publish,completed,MAX_REPORT_BYTES};
