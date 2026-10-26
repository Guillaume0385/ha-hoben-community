'use strict';
// Secret-free validation/publication on a fresh runner. No Actions write API.
const fs=require('node:fs'),path=require('node:path');
const files=require('./experimental-report-file.cjs');
const logical=require('../../scripts/ha-live-proof.cjs');
const need=x=>{if(!x)throw Error('invalid_ha_live_report');};
const keys=(v,k)=>need(v&&typeof v==='object'&&!Array.isArray(v)&&
  Object.keys(v).sort().join() === [...k].sort().join());
const fields=['merge_sha','candidate_sha','pr_number','ci_run_id','run_id','run_attempt',
  'environment_id','environment_digest','claim_sha'];
function proof(env=process.env,context) {
  return {merge_sha:context.sha,candidate_sha:env.APPROVED_CANDIDATE,
    pr_number:Number(env.APPROVED_PR),ci_run_id:Number(env.APPROVED_CI),
    run_id:context.runId,run_attempt:Number(env.GITHUB_RUN_ATTEMPT),
    environment_id:Number(env.APPROVED_ENVIRONMENT),environment_digest:env.APPROVED_POLICY,
    claim_sha:env.APPROVED_CLAIM};
}
function validate(r,p) {
  keys(p,fields);
  for(const k of ['merge_sha','candidate_sha','claim_sha'])need(typeof p[k]==='string'&&/^[a-f0-9]{40}$/.test(p[k]));
  need(typeof p.environment_digest==='string'&&/^[a-f0-9]{64}$/.test(p.environment_digest));
  for(const k of ['pr_number','ci_run_id','run_id','environment_id'])need(Number.isSafeInteger(p[k])&&p[k]>0);
  need(p.run_attempt===1);
  keys(r,['schema','scenario','execution','admission','boundary_proven','proof','supervisor',
    'completed','samples','window','cleanup','criteria','outcome']);
  need(r.schema===3&&r.scenario==='hoben-live'&&r.admission==='VERIFIED'&&r.boundary_proven===false);
  keys(r.proof,fields);need(fields.every(k=>r.proof[k]===p[k]));
  need(r.supervisor.network==='fixed_tls');
  need(r.execution===(r.supervisor.started?'live':'NOT RUN'));
  need(['unattested','monotonic'].includes(r.window.clock));
  // Logical projection only; never accept a C1/C2a envelope as live provenance.
  logical.validateReport({schema:2,scenario:'ha-persistent-live',execution:'offline',
    admission:'NOT RUN',boundary_proven:false,
    provenance:{merge_sha:p.merge_sha,pr_number:p.pr_number,run_id:p.run_id,run_attempt:1},
    supervisor:{...r.supervisor,network:'none'},completed:r.completed,samples:r.samples,
    window:r.window,cleanup:r.cleanup,criteria:r.criteria,
    outcome:Object.values(r.criteria).includes('FAILURE')?'FAILURE':r.criteria.collection==='NOT RUN'?'NOT RUN':
      Object.values(r.criteria).every(v=>v==='SUCCESS')?'SUCCESS':'INCONCLUSIVE'});
  const successful=['collection','tls_reuse','continuous_300s','cleanup','supervision'].every(k=>r.criteria[k]==='SUCCESS');
  need(r.outcome===(successful?'SUCCESS':r.criteria.collection==='NOT RUN'&&r.criteria.supervision==='NOT RUN'?'NOT RUN':'FAILURE'));
  need(Buffer.byteLength(JSON.stringify(r))<=8192);
  return r;
}
function read(file,p) {
  const raw=files.snapshot(file,8192).toString('utf8'),r=validate(JSON.parse(raw),p);
  need(JSON.stringify(r)===raw);return r;
}
function encode(r,p){return Buffer.from(JSON.stringify(validate(r,p))).toString('base64');}
function decode(text,p) {
  need(typeof text==='string'&&text.length<=10924&&/^[A-Za-z0-9+/]*={0,2}$/.test(text));
  const b=Buffer.from(text,'base64');need(b.length<=8192&&b.toString('base64')===text);
  const r=validate(JSON.parse(b.toString('utf8')),p);
  need(Buffer.from(JSON.stringify(r)).equals(b));return r;
}
function prepare({core,proof:p}) {
  try {const r=read(path.join(process.env.RUNNER_TEMP,'hoben-ha-live-public/report.json'),p);
    core.setOutput('report_b64',encode(r,p));}
  catch(_){core.setFailed('NOT RUN: HA public report refused.');}
}
function publish({core,proof:p,text}) {
  try {const r=decode(text,p),folder=path.join(process.env.RUNNER_TEMP,'hoben-ha-live-published');
    fs.mkdirSync(folder,{mode:0o700});fs.writeFileSync(path.join(folder,'report.json'),JSON.stringify(r),{mode:0o600,flag:'wx'});
    core.setOutput('report','true');}
  catch(_){core.setFailed('NOT RUN: HA publication refused.');}
}
module.exports={proof,validate,read,encode,decode,prepare,publish};
