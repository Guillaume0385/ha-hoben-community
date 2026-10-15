"""Actual Python engine output through isolated Node export/publication/result."""

import asyncio
import json
import subprocess
from pathlib import Path

import pytest
import yaml

from tests.test_session_300_probe import PROOF
from tests.test_session_suite import run_harness

ROOT = Path(__file__).resolve().parents[1]


def node(script, payload):
    r = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )
    assert r.stderr == ""
    return json.loads(r.stdout)


@pytest.mark.parametrize("mode", ["recovered", "first_invalid", "no_disconnect"])
def test_real_dual_report_export_publication_and_aggregate_result(tmp_path, mode):
    _, report = asyncio.run(run_harness(mode))
    out = tmp_path / "hoben-session-suite-exports"
    out.mkdir()
    (out / "report.json").write_text(json.dumps(report))
    result = node(
        """
const [dir,r,p]=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
const fs=require('node:fs'),path=require('node:path');
process.env.RUNNER_TEMP=dir;
const api=require('./.github/scripts/session-suite-report.cjs');
let outputs={},errors=[];
const core={setOutput:(k,v)=>outputs[k]=v,setFailed:m=>errors.push(m)};
api.prepare({core,proof:p});
const encoded=outputs.report_b64; outputs={};
api.publish({core,proof:p,encoded});
const file=path.join(dir,'hoben-session-suite-public/report.json');
const materialized=api.readReport(file,p);
const success=api.completed(materialized,p,'success','success');
const failures=['failure','skipped','cancelled'].map(s=>
  [api.completed(r,p,s,'success'),api.completed(r,p,'success',s)]);
const before=fs.readFileSync(file,'utf8');
api.publish({core,proof:p,encoded}); // Exclusive creation must preserve prior data.
process.stdout.write(JSON.stringify({outputs,errors,success,failures,
  same:JSON.stringify(materialized)===JSON.stringify(api.validate(r,p)),
  unchanged:before===fs.readFileSync(file,'utf8'),mode:fs.statSync(file).mode&0o777,
  bytes:Buffer.from(encoded,'base64').length}));
""",
        [str(tmp_path), report, PROOF],
    )
    assert result["outputs"] == {"report": "true"}
    assert result["success"] == (mode == "recovered")
    assert result["same"] and result["unchanged"]
    assert result["mode"] == 0o600 and result["bytes"] <= 8192
    assert result["failures"] == [[False, False]] * 3
    assert result["errors"] == ["NOT RUN: session-suite publication refused."]


def test_unsafe_payloads_paths_encoding_and_size_never_leave_export(tmp_path):
    _, report = asyncio.run(run_harness())
    result = node(
        r"""
const [dir,r,p]=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
const fs=require('node:fs'),path=require('node:path');
process.env.RUNNER_TEMP=dir;
const api=require('./.github/scripts/session-suite-report.cjs');
const source=path.join(dir,'hoben-session-suite-exports');fs.mkdirSync(source);
const file=path.join(source,'report.json');
const cases=[{...r,guid:'synthetic-private'},
  {...r,session_reconnect_no_pong:{...r.session_reconnect_no_pong,rx_raw:'private'}},
  {...r,session_300:{...r.session_300,temperature:17}},
  {...r,run_attempt:2},{...r,merge_sha:'c'.repeat(40)},
  {...r,session_reconnect_no_pong:{...r.session_reconnect_no_pong,result:'not_run'}}];
let checks=[];
for(const bad of cases){
  let outputs=[],failed=0;
  const core={setOutput:(...a)=>outputs.push(a),setFailed:()=>failed++};
  fs.writeFileSync(file,JSON.stringify(bad)); api.prepare({core,proof:p});
  api.publish({core,proof:p,encoded:Buffer.from(JSON.stringify(bad)).toString('base64')});
  checks.push(failed===2&&outputs.length===0);
}
for(const encoded of ['not base64','a'.repeat(10925),
  Buffer.from(' '.repeat(8193)).toString('base64'),
  Buffer.from(JSON.stringify(r)).toString('base64')+'\n']){
  let failed=0,outputs=[];
  api.publish({core:{setFailed:()=>failed++,setOutput:(...v)=>outputs.push(v)},proof:p,encoded});
  checks.push(failed===1&&outputs.length===0);
}
fs.writeFileSync(file,' '.repeat(8193));
try{api.readReport(file,p);checks.push(false);}catch(_){checks.push(true);}
fs.unlinkSync(file);fs.symlinkSync(path.join(dir,'missing'),file);
try{api.readReport(file,p);checks.push(false);}catch(_){checks.push(true);}
process.stdout.write(JSON.stringify({checks,publicExists:fs.existsSync(path.join(dir,'hoben-session-suite-public'))}));
""",
        [str(tmp_path), report, PROOF],
    )
    assert all(result["checks"]) and not result["publicExists"]


@pytest.mark.parametrize(
    "mode", ["recovered", "first_invalid", "no_disconnect", "missing"]
)
def test_actual_workflow_result_cannot_claim_partial_success(tmp_path, mode):
    workflow = yaml.load(
        (ROOT / ".github/workflows/hoben-session-300.yml").read_text(),
        Loader=yaml.BaseLoader,
    )
    script = workflow["jobs"]["result"]["steps"][-1]["with"]["script"]
    report = None if mode == "missing" else asyncio.run(run_harness(mode))[1]
    result = node(
        """
const [script,r,p]=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
const api=require('./.github/scripts/session-suite-report.cjs');
Object.assign(process.env,{APPROVED_PR:String(p.pr_number),APPROVED_CANDIDATE:p.candidate_sha,
  GITHUB_RUN_ATTEMPT:'1',COLLECTION_RESULT:'success',PUBLICATION_RESULT:'success'});
const statuses=[],summaries=[],errors=[];
const core={setFailed:s=>errors.push(s),summary:{addRaw:s=>{
  summaries.push(s);return {write:async()=>{}};
}}};
const github={rest:{repos:{createCommitStatus:async s=>statuses.push(s)}}};
const context={sha:p.merge_sha,runId:p.run_id,
  repo:{owner:'Guillaume0385',repo:'ha-hoben-community'}};
const localRequire=()=>({...api,readReport:()=>{
  if(!r)throw Error('private');return api.validate(r,p);
}});
const AsyncFunction=Object.getPrototypeOf(async()=>{}).constructor;
const execute=new AsyncFunction('require','core','github','context',script);
execute(localRequire,core,github,context)
  .then(()=>process.stdout.write(JSON.stringify({statuses,summaries,errors})));
""",
        [script, report, PROOF],
    )
    assert result["statuses"][0]["context"] == "hoben-experimental-session-suite"
    assert result["statuses"][0]["state"] == (
        "success" if mode == "recovered" else "failure"
    )
    assert bool(result["errors"]) == (mode != "recovered")
    assert "private" not in json.dumps(result)
    assert any(
        "session-300:" in s and "session-reconnect-no-pong:" in s
        for s in result["summaries"]
    )


@pytest.mark.parametrize("job", ["dry-run", "admission", "collect"])
def test_actual_pre_secret_refusal_reports_two_not_run_without_private_errors(job):
    workflow = yaml.load(
        (ROOT / ".github/workflows/hoben-session-300.yml").read_text(),
        Loader=yaml.BaseLoader,
    )
    steps = workflow["jobs"][job]["steps"]
    step = next(s for s in steps if "with" in s and "script" in s["with"])
    script = step["with"]["script"]
    result = node(
        """
const [script]=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
const outputs=[],errors=[],summaries=[];
const core={setOutput:(...v)=>outputs.push(v),setFailed:s=>errors.push(s),
  summary:{addRaw:s=>{summaries.push(s);return {write:async()=>{}};}}};
const deny=async()=>{throw Error('synthetic-private-error');};
const gate={dryRun:deny,verify:deny,refusalCategory:()=> 'decision'};
const AsyncFunction=Object.getPrototypeOf(async()=>{}).constructor;
const execute=new AsyncFunction('require','core','github','context',script);
execute(()=>gate,core,{},{}).then(()=>
  process.stdout.write(JSON.stringify({outputs,errors,summaries})));
""",
        [script],
    )
    assert not result["outputs"] and result["errors"]
    assert "synthetic-private" not in json.dumps(result)
    assert any(
        "session-300: NOT RUN" in s and "session-reconnect-no-pong: NOT RUN" in s
        for s in result["summaries"]
    )
