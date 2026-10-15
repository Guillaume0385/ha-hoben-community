"use strict";
const {test}=require("node:test"), assert=require("node:assert/strict");
const fs=require("node:fs"), os=require("node:os"), path=require("node:path");
const api=require("../../.github/scripts/session-300-report.cjs");
const proof={merge_sha:"a".repeat(40),candidate_sha:"b".repeat(40),run_id:123,run_attempt:1,pr_number:89};
const good=()=>({schema:1,scenario:"session-300",boundary_proven:false,...proof,
  result:"continuous_300s",terminal:"completed",duration_ms:300000,opens:1,reconnections:0,
  pings:10,pongs:10,reads:5,reads_ok:5,reads_failed:0,responses:5,rx_bytes_total:128,rx_chunks_total:3,read_slot:5,failure_phase:"none",failure_category:"completed",message_category:"unclassified"});
test("strict success projection and recovery are distinct",()=>{
  assert.equal(api.validate(good(),proof).result,"continuous_300s");
  const r={...good(),opens:2,reconnections:1,result:"reconnected",terminal:"recovery_verified",failure_category:"recovery_verified"};
  assert.equal(api.validate(r,proof).result,"reconnected");
});
for(const [key,value] of Object.entries({registers:[17],temperature:12,identity:"private",
  terminal:"private-exception",scenario:"h1h2",merge_sha:"c".repeat(40),candidate_sha:"d".repeat(40),
  run_id:321,run_attempt:2,pr_number:90,boundary_proven:true,duration_ms:299999,
  opens:4,reconnections:1,reads:7,reads_ok:4,pongs:11,schema:true,result:"success",rx_bytes_total:1048577,rx_chunks_total:-1,read_slot:7,failure_phase:"raw",failure_category:"private",message_category:"0x0e"})){
  test("refuse extra or inconsistent field "+key,()=>{
    assert.throws(()=>api.validate({...good(),[key]:value},proof));
  });
}
test("reject symlink, oversized JSON and noncanonical base64 without publishing",()=>{
  const root=fs.mkdtempSync(path.join(os.tmpdir(),"session300-"));
  const original=process.env.RUNNER_TEMP;
  process.env.RUNNER_TEMP=root;
  try{
    const file=path.join(root,"good.json");fs.writeFileSync(file,JSON.stringify(good()));
    assert.equal(api.readReport(file,proof).result,"continuous_300s");
    const link=path.join(root,"link");fs.symlinkSync(file,link);
    assert.throws(()=>api.readReport(link,proof));
    fs.writeFileSync(file," ".repeat(4097));assert.throws(()=>api.readReport(file,proof));
    let failed=0, outputs=[];
    const core={setFailed:()=>failed++,setOutput:(...v)=>outputs.push(v)};
    api.publish({core,proof,encoded:"not base64"});assert.equal(failed,1);
    assert.deepEqual(outputs,[]);
    const encoded=Buffer.from(JSON.stringify(good())).toString("base64");
    api.publish({core,proof,encoded});assert.deepEqual(outputs,[["report","true"]]);
    const published=path.join(root,"hoben-session-300-public/report.json");
    assert.deepEqual(api.readReport(published,proof),api.validate(good(),proof));
    assert.equal(fs.statSync(published).mode&0o777,0o600);
  }finally{
    if(original===undefined)delete process.env.RUNNER_TEMP;else process.env.RUNNER_TEMP=original;
    fs.rmSync(root,{recursive:true,force:true});
  }
});
test("collector export is fixed, bounded and independently checked",()=>{
  const root=fs.mkdtempSync(path.join(os.tmpdir(),"session300-"));
  const original=process.env.RUNNER_TEMP;process.env.RUNNER_TEMP=root;
  try{
    fs.mkdirSync(path.join(root,"hoben-session-300-exports"));
    const file=path.join(root,"hoben-session-300-exports/report.json");
    fs.writeFileSync(file,JSON.stringify(good()));
    let value,failed=false;
    const core={setOutput:(k,v)=>{assert.equal(k,"report_b64");value=v;},setFailed:()=>failed=true};
    api.prepare({core,proof});assert(!failed&&value.length<5500);
    fs.writeFileSync(file,JSON.stringify({...good(),secret:"synthetic-private"}));
    value=undefined;api.prepare({core,proof});assert(failed&&value===undefined);
  }finally{
    if(original===undefined)delete process.env.RUNNER_TEMP;else process.env.RUNNER_TEMP=original;
    fs.rmSync(root,{recursive:true,force:true});
  }
});

test("second-slot failure is categorical and rejects payload leakage",()=>{
  const failed={...good(),result:"inconclusive",terminal:"protocol",duration_ms:60091,
    reads:2,reads_ok:1,reads_failed:1,responses:1,read_slot:2,
    failure_phase:"scheduled_read",failure_category:"protocol"};
  assert.equal(api.validate(failed,proof).failure_phase,"scheduled_read");
  assert.throws(()=>api.validate({...failed,message_category:"private"},proof));
  assert.throws(()=>api.validate({...failed,read_slot:3},proof));
  assert.throws(()=>api.validate({...failed,rx_raw:"synthetic-private"},proof));
});
