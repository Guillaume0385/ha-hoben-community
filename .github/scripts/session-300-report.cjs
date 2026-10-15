"use strict";
// Independent, secretless projection at both export and isolated publication.
const fs = require("node:fs"), path = require("node:path");
const safe = require("./experimental-report-file.cjs");
const need = v => {if (!v) throw Error("invalid_session_300_report");};
const keys = ["schema","scenario","merge_sha","candidate_sha","run_id","run_attempt",
  "pr_number","boundary_proven","result","terminal","duration_ms","opens",
  "reconnections","pings","pongs","reads","reads_ok","reads_failed","responses"];
const stops = new Set(["completed","recovery_verified","protocol","budget","transport",
  "timeout","modbus","closed","cancelled","internal","context","authorization"]);
function validate(r, p) {
  need(r && typeof r === "object" && !Array.isArray(r) &&
    Object.keys(r).sort().join() === [...keys].sort().join());
  need(r.schema === 1 && r.scenario === "session-300" && r.boundary_proven === false);
  need(["merge_sha","candidate_sha"].every(k => /^[a-f0-9]{40}$/.test(r[k])));
  need(["merge_sha","candidate_sha","run_id","run_attempt","pr_number"].every(k => r[k] === p[k]));
  need(r.run_attempt === 1 && Number.isSafeInteger(r.run_id) && r.run_id > 0 &&
    Number.isSafeInteger(r.pr_number) && r.pr_number > 0);
  for (const [k,max] of Object.entries({duration_ms:300000,opens:3,reconnections:2,
    pings:1048576,pongs:1048576,reads:6,reads_ok:6,reads_failed:6,responses:6})) {
    need(Number.isSafeInteger(r[k]) && r[k] >= 0 && r[k] <= max);
  }
  need(["continuous_300s","reconnected","interrupted","inconclusive","not_run"].includes(r.result)
    && stops.has(r.terminal) && r.reconnections === Math.max(0,r.opens-1) &&
    r.pongs <= r.pings && r.reads_ok+r.reads_failed === r.reads &&
    r.reads_ok <= r.responses && r.responses <= r.reads);
  if (["continuous_300s","reconnected"].includes(r.result)) {
    need(r.duration_ms === 300000 && r.reads_ok > 0 && r.pings === r.pongs);
    need(r.result === "continuous_300s" ? r.opens === 1 && r.reads_failed === 0 &&
      r.terminal === "completed" : r.opens >= 2 && r.terminal === "recovery_verified");
  } else need(!["completed","recovery_verified"].includes(r.terminal));
  return Object.fromEntries([...keys].sort().map(k => [k,r[k]]));
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
module.exports = {validate,readReport,prepare,publish};
