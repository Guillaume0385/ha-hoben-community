"""Synthetic closed v3 contracts; no network, real identity or producer hookup."""

import ast
import copy
import json
import subprocess
from pathlib import Path

import pytest
import yaml

from scripts.session_suite import validate_suite
from scripts.session_suite_v3 import CONTRACT

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/session_suite_v3_cases.json"
CORPUS = json.loads(FIXTURE.read_text())
PROOF = CORPUS["proof"]


def materialize(case):
    report = copy.deepcopy(CORPUS["reports"][case["base"]])
    for change in case["changes"]:
        target = report
        for key in change["path"][:-1]:
            target = target[key]
        key = change["path"][-1]
        if change.get("delete"):
            del target[key]
        else:
            target[key] = change["value"]
    return report


def node(script, payload):
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=True,
        timeout=20,
    )
    assert not result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("case", CORPUS["cases"], ids=lambda c: c["name"])
def test_shared_closed_contract(case):
    report = materialize(case)
    if case["valid"]:
        assert validate_suite(report, PROOF) == report
    else:
        with pytest.raises((ValueError, TypeError)):
            validate_suite(report, PROOF)


def test_node_consumes_identical_fixtures_with_identical_projections():
    reports = [materialize(c) for c in CORPUS["cases"]]
    result = node(
        """
const [reports,p]=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
const api=require('./.github/scripts/session-suite-report.cjs');
process.stdout.write(JSON.stringify(reports.map(r=>{
  try{return {accepted:true,report:api.validate(r,p)};}
  catch(_){return {accepted:false};}
})));
""",
        [reports, PROOF],
    )
    for case, report, actual in zip(CORPUS["cases"], reports, result, strict=True):
        assert actual["accepted"] is case["valid"], case["name"]
        if actual["accepted"]:
            assert actual["report"] == validate_suite(report, PROOF)


def test_projection_detaches_receipt_and_history_from_mutable_input():
    report = copy.deepcopy(CORPUS["reports"]["success"])
    projected = validate_suite(report, PROOF)
    report["session_reconnect_no_pong"]["quarantine"]["receipt"] = "invalid"
    assert (
        projected["session_reconnect_no_pong"]["quarantine"]["receipt"]
        == "valid_at_consumption"
    )
    with pytest.raises(ValueError):
        validate_suite(report, PROOF)


def test_nonfinite_numbers_payloads_and_objects_are_rejected_in_both_languages():
    reports = []
    for field in [
        "pongs",
        "causal_ms",
        "timing.functional_end_ms",
        "rx_diagnostic.bytes",
    ]:
        for value in [
            float("nan"),
            float("inf"),
            -float("inf"),
            {},
            [],
            "synthetic-private",
            2**53,
        ]:
            case = {
                "base": "success",
                "changes": [
                    {
                        "path": ["session_reconnect_no_pong", *field.split(".")],
                        "value": value,
                    }
                ],
            }
            report = materialize(case)
            with pytest.raises((ValueError, TypeError)):
                validate_suite(report, PROOF)
            # Non-finite JSON is itself invalid for the Node reader.
            reports.append(json.dumps(report))
    result = node(
        """
const [texts,p]=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
const api=require('./.github/scripts/session-suite-report.cjs');
process.stdout.write(JSON.stringify(texts.map(text=>{
 try{api.validate(JSON.parse(text),p);return false;}catch(_){return true;}
})));
""",
        [reports, PROOF],
    )
    assert all(result)


def test_v3_publication_exact_size_private_modes_and_complete_status(tmp_path):
    result = node(
        """
const [dir,r,p]=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
const fs=require('node:fs'),path=require('node:path');
const api=require('./.github/scripts/session-suite-report.cjs');
process.env.RUNNER_TEMP=dir;
const exports=path.join(dir,'hoben-session-suite-exports');
fs.mkdirSync(exports,{mode:0o700});const file=path.join(exports,'report.json');
const text=JSON.stringify(r),bytes=Buffer.byteLength(text);
fs.writeFileSync(file,text+' '.repeat(8192-bytes),{mode:0o600});
const exact=api.readReport(file,p);let outputs={},errors=[];
const core={setOutput:(k,v)=>outputs[k]=v,setFailed:v=>errors.push(v)};
api.prepare({core,proof:p});const encoded=outputs.report_b64;
api.publish({core,proof:p,encoded});
const publicFile=path.join(dir,'hoben-session-suite-public/report.json');
const success=api.completed(api.readReport(publicFile,p),p,'success','success');
const failures=['failure','skipped','cancelled',undefined].map(s=>
 [api.completed(r,p,s,'success'),api.completed(r,p,'success',s)]);
let oversized=false;fs.appendFileSync(file,' ');
try{api.readReport(file,p);}catch(_){oversized=true;}
api.prepare({core,proof:p});
process.stdout.write(JSON.stringify({exact,success,failures,oversized,errors,
 fileMode:fs.statSync(publicFile).mode&0o777,
 dirMode:fs.statSync(path.dirname(publicFile)).mode&0o777,
 encodedBytes:Buffer.from(encoded,'base64').length,encodedLength:encoded.length}));
""",
        [str(tmp_path), CORPUS["reports"]["success"], PROOF],
    )
    assert result["exact"] == CORPUS["reports"]["success"]
    assert result["success"] and result["oversized"]
    assert result["failures"] == [[False, False]] * 4
    assert result["fileMode"] == 0o600 and result["dirMode"] == 0o700
    assert result["encodedBytes"] <= 8192 and result["encodedLength"] <= 10924
    assert result["errors"] == ["NOT RUN: session-suite export refused."]


def test_all_valid_fixtures_fit_envelope_and_incomplete_never_complete():
    reports = CORPUS["reports"]
    for report in reports.values():
        assert len(json.dumps(validate_suite(report, PROOF)).encode()) < 8192
    result = node(
        """
const [rs,p]=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
const api=require('./.github/scripts/session-suite-report.cjs');
process.stdout.write(JSON.stringify(Object.fromEntries(Object.entries(rs).map(([k,r])=>
 [k,api.completed(r,p,'success','success')]))));
""",
        [reports, PROOF],
    )
    assert {k for k, v in result.items() if v} == {"success", "v1", "v2"}


@pytest.mark.parametrize(
    "name",
    [
        "success",
        "no_eof",
        "not_run",
        "second_loss",
        "opening_without_t0",
        "origin_eof_after_entry_-1",
        "origin_eof_after_entry_0",
        "origin_eof_after_entry_1",
        "stopped_after_consumption",
        "stopped_after_acceptance",
    ]
    + [c["name"] for c in CORPUS["cases"] if c["name"].startswith("stop_")],
)
def test_unchanged_workflow_result_checks_v3_and_partial_job_results(name):
    workflow = yaml.load(
        (ROOT / ".github/workflows/hoben-session-300.yml").read_text(),
        Loader=yaml.BaseLoader,
    )
    script = workflow["jobs"]["result"]["steps"][-1]["with"]["script"]
    result = node(
        """
const [script,r,p]=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
const api=require('./.github/scripts/session-suite-report.cjs');
Object.assign(process.env,{APPROVED_PR:String(p.pr_number),APPROVED_CANDIDATE:p.candidate_sha,
 GITHUB_RUN_ATTEMPT:'1'});
const AsyncFunction=Object.getPrototypeOf(async()=>{}).constructor;
async function check(collection,publication,missing=false) {
 Object.assign(process.env,{COLLECTION_RESULT:collection,PUBLICATION_RESULT:publication});
 const statuses=[],errors=[],summaries=[];
 const core={setFailed:s=>errors.push(s),summary:{addRaw:s=>{
  summaries.push(s);return {write:async()=>{}};
 }}};
 const github={rest:{repos:{createCommitStatus:async s=>statuses.push(s)}}};
 const context={sha:p.merge_sha,runId:p.run_id,
  repo:{owner:'Guillaume0385',repo:'ha-hoben-community'}};
 const localRequire=()=>({...api,readReport:()=>{
  if(missing)throw Error('synthetic-private');return api.validate(r,p);
 }});
 await new AsyncFunction('require','core','github','context',script)(
  localRequire,core,github,context);
 return {state:statuses[0].state,errors,summaries};
}
(async()=>process.stdout.write(JSON.stringify([
 await check('success','success'),await check('failure','success'),
 await check('success','skipped'),await check('success','cancelled'),
 await check('success','success',true)
])))();
""",
        [
            script,
            CORPUS["reports"][name]
            if name in CORPUS["reports"]
            else materialize(next(c for c in CORPUS["cases"] if c["name"] == name)),
            PROOF,
        ],
    )
    assert [r["state"] for r in result] == (
        ["success"] if name in {"success", "origin_eof_after_entry_1"} else ["failure"]
    ) + ["failure"] * 4
    assert "synthetic-private" not in json.dumps(result)


@pytest.mark.parametrize("delta", [-1, 0, 1])
def test_completed_requires_eof_strictly_after_origin_entry(delta):
    case = next(
        c for c in CORPUS["cases"] if c["name"] == f"origin_eof_after_entry_{delta}"
    )
    result = node(
        """
const [r,p]=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
const api=require('./.github/scripts/session-suite-report.cjs');
let completed=false;
try {completed=api.completed(r,p,'success','success');} catch(_) {}
process.stdout.write(JSON.stringify(completed));
""",
        [materialize(case), PROOF],
    )
    assert result is (delta > 0)


def test_v3_maximum_canonical_base64_and_encoded_overflow(tmp_path):
    result = node(
        """
const [dir,r,p]=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
const fs=require('node:fs'),path=require('node:path');
const api=require('./.github/scripts/session-suite-report.cjs');
const text=JSON.stringify(r),padded=text+' '.repeat(8192-Buffer.byteLength(text));
let checks=[];
const cases=[padded,padded+' ',null];
for(let i=0;i<cases.length;i++) {
 const parent=path.join(dir,String(i));fs.mkdirSync(parent);
 process.env.RUNNER_TEMP=parent;
 let outputs={},errors=[];
 const core={setOutput:(k,v)=>outputs[k]=v,setFailed:s=>errors.push(s)};
 const encoded=i===2 ? Buffer.from(padded).toString('base64')+String.fromCharCode(10)
  : Buffer.from(cases[i]).toString('base64');
 api.publish({core,proof:p,encoded});
 checks.push({length:encoded.length,ok:outputs.report==='true',failed:errors.length,
  exists:fs.existsSync(path.join(parent,'hoben-session-suite-public'))});
}
process.stdout.write(JSON.stringify(checks));
""",
        [str(tmp_path), CORPUS["reports"]["success"], PROOF],
    )
    assert result[0] == {"length": 10924, "ok": True, "failed": 0, "exists": True}
    assert all(not r["ok"] and r["failed"] == 1 and not r["exists"] for r in result[1:])


def test_contract_only_does_not_change_or_enable_installed_producers():
    source = (ROOT / "scripts/session_suite.py").read_text()
    module = ast.parse(source)
    for name in ["second_empty", "_observe_reconnect", "observe_suite"]:
        function = next(
            n
            for n in module.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name
        )
        assert "validate_v3" not in ast.unparse(function)
        for node_ in ast.walk(function):
            if isinstance(node_, ast.Dict):
                for key, value in zip(node_.keys, node_.values, strict=True):
                    if isinstance(key, ast.Constant) and key.value == "schema":
                        assert isinstance(value, ast.Constant) and value.value == 2
    assert set(CONTRACT) == {"timing", "quarantine", "stability", "rx_diagnostic"}
