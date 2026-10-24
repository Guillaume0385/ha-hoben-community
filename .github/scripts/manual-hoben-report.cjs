"use strict";
// Construct and revalidate one bounded public bundle on separate runners.
const fs=require('node:fs'),path=require('node:path');
const safe=require('./experimental-report-file.cjs');
const h1=require('./experimental-exports.cjs');
const first=require('./session-300-report.cjs');
const suite=require('./session-suite-report.cjs');
const MAX_BYTES=340*1024+8192+2048;
// Each public environment value must also fit Linux's per-string exec limit.
const PART_BYTES=120000,PARTS=4;
const PLANS={h1h2:['h1h2'],'session-300':['session-300'],
  'session-reconnect':['session-reconnect'],all:['h1h2','session-300','session-reconnect']};
const need=v=>{if(!v)throw Error('invalid_manual_report');};
const keys=(v,k)=>need(v&&typeof v==='object'&&!Array.isArray(v)&&
  Object.keys(v).sort().join() === [...k].sort().join());
function validate(r,p) {
  keys(r,['schema','selection','started','process_ok','proof','h1h2','session']);
  need(r.schema===1&&Object.hasOwn(PLANS,r.selection)&&r.selection===p.selection&&
    typeof r.process_ok==='boolean'&&Array.isArray(r.started));
  keys(r.proof,['merge_sha','candidate_sha','run_id','run_attempt','pr_number']);
  need(Object.keys(r.proof).every(k=>r.proof[k]===p[k])&&p.run_attempt===1);
  need(/^[a-f0-9]{40}$/.test(p.merge_sha)&&/^[a-f0-9]{40}$/.test(p.candidate_sha)&&
    Number.isSafeInteger(p.run_id)&&p.run_id>0&&Number.isSafeInteger(p.pr_number)&&p.pr_number>0);
  const plan=PLANS[r.selection];
  need(r.started.length<=plan.length&&r.started.every((s,i)=>s===plan[i]));
  if(r.h1h2!==null) {
    need(r.started.includes('h1h2'));
    need(Buffer.byteLength(JSON.stringify(r.h1h2))<=340*1024);
    h1.validate(r.h1h2,{sha:p.merge_sha,runId:p.run_id,runAttempt:1,prNumber:p.pr_number});
  }
  if(r.session!==null) {
    need(Buffer.byteLength(JSON.stringify(r.session))<=(r.selection==='session-300'?4096:8192));
    if(r.selection==='all') {
      suite.validate(r.session,p);
      need(r.started.includes('session-300')&&r.h1h2?.result==='inconclusive');
      need((r.session.session_reconnect_no_pong.result!=='not_run')===r.started.includes('session-reconnect'));
    } else if(r.selection==='session-300') {
      first.validate(r.session,p);need(r.started.includes('session-300'));
    } else {
      need(r.selection==='session-reconnect'&&r.started.includes('session-reconnect'));
      suite.validateSecond(r.session,p);
    }
  }
  if(r.selection==='all'&&r.started.length>1)need(r.h1h2?.result==='inconclusive');
  return r;
}
function states(r) {
  const output={h1h2:'NOT RUN','session-300':'NOT RUN','session-reconnect':'NOT RUN'};
  for(const s of r.started)output[s]='FAILURE';
  if(r.h1h2)output.h1h2=r.h1h2.result==='inconclusive'?'INCONCLUSIVE':'FAILURE';
  const sessionState=x=>['continuous_300s','reconnected','recovered_120s'].includes(x.result)?'SUCCESS':
    x.result==='inconclusive'?'INCONCLUSIVE':x.result==='not_run'?'NOT RUN':'FAILURE';
  if(r.session) {
    if(r.selection==='all') {
      output['session-300']=sessionState(r.session.session_300);
      output['session-reconnect']=sessionState(r.session.session_reconnect_no_pong);
    } else output[r.selection]=sessionState(r.session);
  }
  if(!r.process_ok&&r.started.length)output[r.started[r.started.length-1]]='FAILURE';
  return output;
}
function completed(r,p) {
  validate(r,p);
  const s=states(r);
  return r.process_ok&&PLANS[r.selection].every(x=>
    x==='h1h2'?s[x]==='INCONCLUSIVE':s[x]==='SUCCESS');
}
function json(file,limit){return JSON.parse(safe.snapshot(file,limit).toString('utf8'));}
function readReport(file,p){return validate(json(file,MAX_BYTES),p);}
function prepare({core,proof:p}) {
  try {
    const root=process.env.RUNNER_TEMP;
    const status=json(path.join(root,'hoben-manual-control/report.json'),1024);
    keys(status,['schema','selection','started','process_ok']);
    const r={...status,proof:Object.fromEntries(
      ['merge_sha','candidate_sha','run_id','run_attempt','pr_number'].map(k=>[k,p[k]])),h1h2:null,session:null};
    if(status.started.includes('h1h2')) {
      const file=path.join(root,'hoben-experimental-exports/report.json');
      if(fs.existsSync(file))r.h1h2=h1.readReport(file,
        {sha:p.merge_sha,runId:p.run_id,runAttempt:1,prNumber:p.pr_number}).report;
    }
    const folder={all:'hoben-session-suite-exports','session-300':'hoben-session-300-exports',
      'session-reconnect':'hoben-session-reconnect-exports'}[p.selection];
    if(folder&&fs.existsSync(path.join(root,folder,'report.json')))
      r.session=json(path.join(root,folder,'report.json'),p.selection==='session-300'?4096:8192);
    const bytes=Buffer.from(JSON.stringify(validate(r,p)));
    need(bytes.length<=MAX_BYTES);
    const encoded=bytes.toString('base64');
    for(let i=0;i<PARTS;i++)core.setOutput('report_'+i+'_b64',encoded.slice(i*PART_BYTES,(i+1)*PART_BYTES));
  }catch(_){core.setFailed('NOT RUN: manual export refused.');}
}
function publish({core,proof:p,parts}) {
  let file,created=false;
  try {
    need(Array.isArray(parts)&&parts.length===PARTS&&parts.every(x=>typeof x==='string'&&x.length<=PART_BYTES));
    const encoded=parts.join('');
    need(encoded.length<=4*Math.ceil(MAX_BYTES/3));
    const bytes=Buffer.from(encoded,'base64');
    need(bytes.length<=MAX_BYTES&&bytes.toString('base64')===encoded);
    const r=validate(JSON.parse(bytes.toString('utf8')),p);
    const folder=path.join(process.env.RUNNER_TEMP,'hoben-manual-public');
    fs.mkdirSync(folder,{mode:0o700});fs.chmodSync(folder,0o700);
    file=path.join(folder,'report.json');
    const fd=fs.openSync(file,fs.constants.O_WRONLY|fs.constants.O_CREAT|fs.constants.O_EXCL|fs.constants.O_NOFOLLOW,0o600);
    created=true;
    try{fs.fchmodSync(fd,0o600);fs.writeFileSync(fd,JSON.stringify(r));}finally{fs.closeSync(fd);}
    readReport(file,p);core.setOutput('report','true');
  }catch(_){if(created){try{fs.unlinkSync(file);}catch(_){}}core.setFailed('NOT RUN: manual publication refused.');}
}
module.exports={validate,states,completed,prepare,publish,readReport,MAX_BYTES};
