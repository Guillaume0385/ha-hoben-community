"use strict";
// D7's separate protected-worker contract. Structural validation is NOT
// authentication: live publication additionally requires the reserved GitHub
// launch/result tags, fresh gate proofs and the protected collector receipt.
const fs=require('node:fs'), path=require('node:path'), crypto=require('node:crypto');
const files=require('./experimental-report-file.cjs');
const LIMITS=Object.freeze({observation_ms:3540000,cleanup_ms:60000,total_ms:3600000});
const FIELDS=Object.freeze(['merge_sha','candidate_sha','pr_number','ci_run_id','run_id',
  'run_attempt','environment_id','environment_digest','claim_sha','contract_digest','launch_tag_sha']);
const OBS=Object.freeze({started:false,opening_accepted:false,tls_verified:false,connections:0,
  deliveries:0,received_bytes:0,candidate_observed:false,candidate_delivery_bytes:0,
  candidate_at_ms:null,candidate_delivery_offset:null,discarded_deliveries:0,
  continuation:'not_proven',post_candidate_reads:0,tls_deliveries_since_candidate:0,
  tls_bytes_since_candidate:0,delivery_timeline:[],delivery_timeline_omitted:0,
  candidate_leads_unproven:0,ping_leads_unproven:0,response_leads_unproven:0,
  data_updated_leads_unproven:0,candidate_segments:[],candidate_segments_omitted:0,
  peer_eof:false,unconfirmed_read_requests:0,first_post_info_valid_v4_at_ms:null,
  recovery_stability_start_ms:null,recovery_stability_elapsed_ms:0,
  pings_validated:0,pongs_written:0,read_requests:0,verified_reads:0,observation_complete:false,
  first_error:'none',cleanup_error:'none',cleanup_started_ms:null,transport_close_requested:false,
  transport_close_completed:false,rx_stopped:false,operations_stopped:false,
  cleanup_attested:false,elapsed_ms:0});
const PROC=Object.freeze({launch_attempted:false,spawned:false,isolated:false,child_report_bound:false,
  term_requested:false,kill_requested:false,children_reaped:0,group_empty:false,
  guardian_waited:false,control_closed:false,exit_ok:false,deadline_exceeded:false,
  first_error:'none',elapsed_ms:0});
const ERRORS=Object.freeze(['none','context','identity','clock','budget','tls','transport',
  'timeout','authentication','authorization','protocol','closed','internal','cancelled',
  'cleanup','process','provenance']);
const API=Object.freeze({owner:'Guillaume0385',repo:'ha-hoben-community'});
const need=v=>{if(!v)throw Error('invalid_info_live_evidence');};
const keys=(v,expected)=>need(v&&typeof v==='object'&&!Array.isArray(v)&&
  Object.keys(v).sort().join() === [...expected].sort().join());
const integer=(v,max)=>Number.isSafeInteger(v)&&v>=0&&v<=max;
const sha=v=>typeof v==='string'&&/^[a-f0-9]{40}$/.test(v);
const hash=v=>crypto.createHash('sha256').update(v).digest('hex');
const equal=(a,b)=>{keys(a,Object.keys(b));need(Object.entries(b).every(([k,v])=>a[k]===v));};
const error=v=>typeof v==='string'&&ERRORS.includes(v);

function validateProof(p) {
  keys(p,FIELDS);
  for(const k of ['merge_sha','candidate_sha','claim_sha','launch_tag_sha'])need(sha(p[k]));
  for(const k of ['environment_digest','contract_digest'])need(typeof p[k]==='string'&&/^[a-f0-9]{64}$/.test(p[k]));
  for(const k of ['pr_number','ci_run_id','run_id','environment_id'])need(integer(p[k],Number.MAX_SAFE_INTEGER)&&p[k]>0);
  need(p.run_attempt===1);return p;
}
function validateObservation(o) {
  keys(o,Object.keys(OBS));
  for(const [k,v] of Object.entries(OBS))if(typeof v==='boolean')need(typeof o[k]==='boolean');
  need(integer(o.connections,1)&&integer(o.discarded_deliveries,1));
  for(const k of ['deliveries','post_candidate_reads','tls_deliveries_since_candidate',
    'delivery_timeline_omitted','candidate_leads_unproven','ping_leads_unproven',
    'response_leads_unproven','data_updated_leads_unproven','pings_validated',
    'pongs_written','read_requests','verified_reads','unconfirmed_read_requests'])
      need(integer(o[k],8192));
  need(integer(o.candidate_segments_omitted,8192));
  need(integer(o.received_bytes,1048576)&&integer(o.tls_bytes_since_candidate,1048576));
  need(integer(o.candidate_delivery_bytes,4096)&&integer(o.elapsed_ms,3600000));
  for(const k of ['candidate_at_ms','cleanup_started_ms',
    'first_post_info_valid_v4_at_ms','recovery_stability_start_ms'])
      need(o[k]===null||integer(o[k],o.elapsed_ms));
  need(error(o.first_error)&&error(o.cleanup_error));
  need(o.continuation==='not_proven'&&
    o.verified_reads<=o.read_requests-o.unconfirmed_read_requests&&
    o.first_post_info_valid_v4_at_ms===null&&
    o.recovery_stability_start_ms===null&&o.recovery_stability_elapsed_ms===0);
  need(o.pongs_written<=o.pings_validated);
  need(o.post_candidate_reads+Number(o.candidate_observed)===o.tls_deliveries_since_candidate&&
    o.tls_deliveries_since_candidate<=o.deliveries&&o.tls_bytes_since_candidate<=o.received_bytes);
  const heads=o.candidate_leads_unproven+o.ping_leads_unproven+
    o.response_leads_unproven+o.data_updated_leads_unproven;
  need(heads<=o.post_candidate_reads);
  need(Array.isArray(o.delivery_timeline)&&o.delivery_timeline.length<=96);
  need(o.delivery_timeline_omitted===o.tls_deliveries_since_candidate-o.delivery_timeline.length);
  let previous=-1,bytes=0;
  for(const entry of o.delivery_timeline) {
    need(Array.isArray(entry)&&entry.length===2&&integer(entry[0],o.elapsed_ms)&&
      entry[0]>=previous&&integer(entry[1],4096)&&entry[1]>=1);
    previous=entry[0];bytes+=entry[1];
  }
  need(bytes<=o.tls_bytes_since_candidate);
  if(!o.delivery_timeline_omitted)need(bytes===o.tls_bytes_since_candidate);
  need(Array.isArray(o.candidate_segments)&&o.candidate_segments.length<=16);
  need(o.candidate_segments.length+o.candidate_segments_omitted===
    Number(o.candidate_observed)+o.candidate_leads_unproven);
  for(const seg of o.candidate_segments) {
    keys(seg,['start_at_ms','observed_bytes_between_candidates','tls_deliveries','end_kind']);
    need(integer(seg.start_at_ms,o.elapsed_ms)&&
      integer(seg.observed_bytes_between_candidates,1048576)&&
      integer(seg.tls_deliveries,8192)&&
      seg.observed_bytes_between_candidates>=seg.tls_deliveries&&seg.tls_deliveries>=1);
    need(['delivery_lead_unproven','tls_eof','observation_end'].includes(seg.end_kind));
  }
  if(o.candidate_observed) {
    need(o.started&&o.opening_accepted&&o.candidate_at_ms!==null&&
      o.candidate_at_ms<3540000&&o.candidate_delivery_offset===0&&
      o.candidate_delivery_bytes>=1&&o.discarded_deliveries===1&&
      o.received_bytes>=o.candidate_delivery_bytes&&
      o.tls_bytes_since_candidate>=o.candidate_delivery_bytes&&
      o.delivery_timeline.length>=1&&o.delivery_timeline[0][0]===o.candidate_at_ms&&
      o.delivery_timeline[0][1]===o.candidate_delivery_bytes);
  } else {
    need(o.candidate_at_ms===null&&o.candidate_delivery_offset===null&&
      o.candidate_delivery_bytes===0&&o.discarded_deliveries===0&&
      o.tls_deliveries_since_candidate===0&&o.tls_bytes_since_candidate===0&&
      o.delivery_timeline.length===0&&o.candidate_segments.length===0&&
      heads===0&&o.candidate_segments_omitted===0);
  }
  if(o.observation_complete)need(o.cleanup_started_ms!==null&&o.cleanup_started_ms>=3540000);
  if(o.opening_accepted)need(o.started&&o.tls_verified&&o.connections===1);
  if(o.peer_eof)need(o.started&&o.opening_accepted);
  if(o.cleanup_attested)need(o.cleanup_started_ms!==null&&o.cleanup_error==='none'&&
    ['transport_close_requested','transport_close_completed','rx_stopped','operations_stopped'].every(k=>o[k]));
  return o;
}
function validateProcess(p) {
  keys(p,Object.keys(PROC));
  for(const [k,v] of Object.entries(PROC))if(typeof v==='boolean')need(typeof p[k]==='boolean');
  need(integer(p.children_reaped,16)&&integer(p.elapsed_ms,3600000)&&error(p.first_error));
  if(p.isolated)need(p.spawned);
  if(p.spawned)need(p.launch_attempted);
  if(p.group_empty)need(p.isolated&&p.children_reaped>=1);
  if(p.exit_ok)need(p.guardian_waited);
  if(p.kill_requested)need(p.term_requested);
  if(p.deadline_exceeded)need(p.first_error==='timeout'&&p.elapsed_ms===3600000);
  return p;
}
function verdict(o,p) {
  validateObservation(o);validateProcess(p);
  if(!p.launch_attempted&&!o.started)return ['NOT RUN','not_started'];
  if(!['spawned','isolated','child_report_bound','group_empty','guardian_waited','control_closed','exit_ok'].every(k=>p[k])||
    p.first_error!=='none'||p.term_requested||p.kill_requested)return ['FAILURE','process'];
  if(o.first_error!=='none')return ['FAILURE',o.first_error];
  if(!o.cleanup_attested)return ['FAILURE','cleanup'];
  if(!o.opening_accepted||o.connections!==1||!o.tls_verified)return ['FAILURE','provenance'];
  if(o.peer_eof)return ['INCONCLUSIVE','server_eof'];
  if(o.candidate_observed&&o.discarded_deliveries===1)return ['INCONCLUSIVE','candidate_observed_continuation_not_proven'];
  if(!o.candidate_observed&&o.observation_complete)return ['INCONCLUSIVE','candidate_absent'];
  return ['FAILURE','provenance'];
}
function validateStructure(r,p) {
  validateProof(p);
  keys(r,['schema','scenario','selection','execution','info_framing','boundary_proven',
    'limits','proof','observation','process','result','reason']);
  need(r.schema===3&&r.scenario==='info-passive-observation'&&r.selection==='hoben-live'&&
    r.execution==='protected_worker'&&r.info_framing==='INCONCLUSIVE'&&r.boundary_proven===false);
  equal(r.limits,LIMITS);equal(validateProof(r.proof),p);
  const [result,reason]=verdict(r.observation,r.process);
  need(r.result===result&&r.reason===reason);
  if(r.observation.started)need(r.process.spawned&&r.observation.elapsed_ms<=r.process.elapsed_ms);
  need(Buffer.byteLength(JSON.stringify(r))<=8192);return r;
}
function proof(env,context) {
  return validateProof({merge_sha:context.sha,candidate_sha:env.APPROVED_CANDIDATE,
    pr_number:Number(env.APPROVED_PR),ci_run_id:Number(env.APPROVED_CI),run_id:context.runId,
    run_attempt:Number(env.GITHUB_RUN_ATTEMPT),environment_id:Number(env.APPROVED_ENVIRONMENT),
    environment_digest:env.APPROVED_POLICY,claim_sha:env.APPROVED_CLAIM,
    contract_digest:env.APPROVED_CONTRACT,launch_tag_sha:env.APPROVED_LAUNCH});
}
function baseProof(d,context) {
  return {merge_sha:context.sha,candidate_sha:d.candidate_sha,pr_number:d.pr,
    ci_run_id:d.ci_run_id,run_id:context.runId,run_attempt:1,environment_id:d.environment_id,
    environment_digest:d.environment_digest,claim_sha:d.claim_sha,contract_digest:d.contract_digest};
}
function folder(root) {
  need(typeof root==='string'&&path.isAbsolute(root));
  return path.join(fs.realpathSync(root),'hoben-info-private');
}
function privateFile(file,max) {
  const s=fs.lstatSync(file);
  need(s.isFile()&&!s.isSymbolicLink()&&(s.mode&0o777)===0o600&&s.uid===process.getuid());
  return files.snapshot(file,max);
}

async function writeLaunchPermit({github,context,root}) {
  // No caller-provided "approved" decision can mint a launch capability.
  const decision=await require('./manual-hoben-gate.cjs').verify({github,context,recheck:true});
  need(decision.selection==='hoben-live'&&
    (decision.status==='PENDING APPROVAL'||decision.status==='READY FOR ENVIRONMENT'));
  const base=baseProof(decision,context), nonce=crypto.randomBytes(32).toString('hex');
  validateProof({...base,launch_tag_sha:'0'.repeat(40)});
  const name='hoben-info-start-'+context.runId+'-attempt1';
  const claim={schema:1,kind:'info-launch-permit',proof:base,nonce_digest:hash(nonce)};
  const {data:tag}=await github.rest.git.createTag({...API,tag:name,message:JSON.stringify(claim),
    object:context.sha,type:'commit'});need(sha(tag.sha));
  await github.rest.git.createRef({...API,ref:'refs/tags/'+name,sha:tag.sha});
  const {data:ref}=await github.rest.git.getRef({...API,ref:'tags/'+name});
  need(ref.ref==='refs/tags/'+name&&ref.object?.type==='tag'&&ref.object.sha===tag.sha);
  const p=validateProof({...base,launch_tag_sha:tag.sha});
  const directory=folder(root);fs.mkdirSync(directory,{mode:0o700});
  fs.writeFileSync(path.join(directory,'permit.json'),JSON.stringify({schema:2,proof:p,nonce}),
    {flag:'wx',mode:0o600});
  return p;
}
async function gateProof(github,context,p) {
  const d=await require('./manual-hoben-gate.cjs').verify({github,context,recheck:true});
  equal(validateProof({...baseProof(d,context),launch_tag_sha:p.launch_tag_sha}),p);
  const name='hoben-info-start-'+context.runId+'-attempt1';
  const {data:ref}=await github.rest.git.getRef({...API,ref:'tags/'+name});
  need(ref.ref==='refs/tags/'+name&&ref.object?.type==='tag'&&ref.object.sha===p.launch_tag_sha);
  const {data:tag}=await github.rest.git.getTag({...API,tag_sha:p.launch_tag_sha});
  need(tag.tag===name&&tag.object?.type==='commit'&&tag.object.sha===context.sha);
  const message=JSON.parse(tag.message);
  keys(message,['schema','kind','proof','nonce_digest']);
  need(message.schema===1&&message.kind==='info-launch-permit'&&
    typeof message.nonce_digest==='string'&&/^[a-f0-9]{64}$/.test(message.nonce_digest));
  equal(message.proof,baseProof(d,context));
}

async function collectorProof(github,context,phase) {
  const jobs=await github.paginate(github.rest.actions.listJobsForWorkflowRun,
    {...API,run_id:context.runId,per_page:100});
  const matches=jobs.filter(j=>j.name==='collect-info');need(matches.length===1);
  const job=matches[0];
  need(job.run_id===context.runId&&job.run_attempt===1&&job.head_sha===context.sha&&Array.isArray(job.steps));
  const named=name=>{const steps=job.steps.filter(s=>s.name===name);need(steps.length===1);return steps[0];};
  const admission=named('Info post-approval admission'),
    capture=named('One passive Info session with independent OS guardian'),
    exported=named('Info protected export');
  need(admission.status==='completed'&&admission.conclusion==='success'&&
    capture.status==='completed'&&capture.conclusion==='success');
  need([admission,capture,exported].every(s=>integer(s.number,100)&&s.number>0));
  need(admission.number<capture.number&&capture.number<exported.number);
  const stamps=[admission.started_at,admission.completed_at,capture.started_at,
    capture.completed_at,exported.started_at];
  need(stamps.every(t=>typeof t==='string'&&/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,3})?Z$/.test(t)));
  const times=stamps.map(Date.parse);
  need(times.every(Number.isFinite)&&times.every((t,i)=>i===0||t>=times[i-1]));
  if(phase==='collect')need(job.status==='in_progress'&&exported.status==='in_progress');
  else need(job.status==='completed'&&job.conclusion==='success'&&
    exported.status==='completed'&&exported.conclusion==='success');
  return {capture_wall_ms:times[3]-times[2]};
}

async function prepare({github,context,core,proof:p,root}) {
  const directory=folder(root), keyFile=path.join(directory,'attestation.key');
  try {
    await gateProof(github,context,p);
    const clockProof=await collectorProof(github,context,'collect');
    const envelope=JSON.parse(privateFile(path.join(directory,'sealed-report.json'),12288));
    keys(envelope,['report','signature']);
    const r=validateStructure(envelope.report,p), bytes=Buffer.from(JSON.stringify(r));
    need(r.process.elapsed_ms<=clockProof.capture_wall_ms+2000&&
      clockProof.capture_wall_ms<=r.process.elapsed_ms+120000);
    const key=privateFile(keyFile,32);need(key.length===32);
    need(typeof envelope.signature==='string'&&/^[a-f0-9]{64}$/.test(envelope.signature));
    const signature=crypto.createHmac('sha256',key).update(bytes).digest();
    need(crypto.timingSafeEqual(signature,Buffer.from(envelope.signature,'hex')));
    need((!r.process.launch_attempted&&!r.observation.started)||
      (r.process.group_empty&&r.process.guardian_waited&&r.process.control_closed));
    // Immutable result receipt authenticates this protected job's exact bytes;
    // a separate publisher never receives the private signing key.
    const name='hoben-info-result-'+context.runId+'-attempt1';
    const receipt={schema:1,kind:'info-protected-result',proof:p,report_sha256:hash(bytes)};
    const {data:tag}=await github.rest.git.createTag({...API,tag:name,
      message:JSON.stringify(receipt),object:context.sha,type:'commit'});need(sha(tag.sha));
    await github.rest.git.createRef({...API,ref:'refs/tags/'+name,sha:tag.sha});
    const {data:ref}=await github.rest.git.getRef({...API,ref:'tags/'+name});
    need(ref.ref==='refs/tags/'+name&&ref.object?.type==='tag'&&ref.object.sha===tag.sha);
    core.setOutput('report_b64',bytes.toString('base64'));core.setOutput('receipt_sha',tag.sha);
  }catch(_){core.setFailed('FAILURE: Info collector authentication or report refused.');}
  finally {
    for(const name of ['attestation.key','sealed-report.json'])try{fs.unlinkSync(path.join(directory,name));}catch(_){}
  }
}
function decode(text,p) {
  need(typeof text==='string'&&text.length<=10924&&/^[A-Za-z0-9+/]*={0,2}$/.test(text));
  const bytes=Buffer.from(text,'base64');need(bytes.length<=8192&&bytes.toString('base64')===text);
  const r=validateStructure(JSON.parse(bytes.toString('utf8')),p);
  need(Buffer.from(JSON.stringify(r)).equals(bytes));return r;
}
async function validateForLivePublication({github,context,report:r,proof:p,receiptSha}) {
  validateStructure(r,p);need(sha(receiptSha));
  await gateProof(github,context,p);
  const clockProof=await collectorProof(github,context,'publish');
  need(r.process.elapsed_ms<=clockProof.capture_wall_ms+2000&&
    clockProof.capture_wall_ms<=r.process.elapsed_ms+120000);
  const name='hoben-info-result-'+context.runId+'-attempt1';
  const {data:ref}=await github.rest.git.getRef({...API,ref:'tags/'+name});
  need(ref.ref==='refs/tags/'+name&&ref.object?.type==='tag'&&ref.object.sha===receiptSha);
  const {data:tag}=await github.rest.git.getTag({...API,tag_sha:receiptSha});
  need(tag.tag===name&&tag.object?.type==='commit'&&tag.object.sha===context.sha);
  const receipt=JSON.parse(tag.message);
  keys(receipt,['schema','kind','proof','report_sha256']);
  need(receipt.schema===1&&receipt.kind==='info-protected-result');
  equal(receipt.proof,p);need(receipt.report_sha256===hash(JSON.stringify(r)));
  return r;
}
async function publish({github,context,core,proof:p,text,receiptSha,root}) {
  try {
    const r=decode(text,p);
    await validateForLivePublication({github,context,report:r,proof:p,receiptSha});
    const directory=path.join(fs.realpathSync(root),'hoben-info-published');
    fs.mkdirSync(directory,{mode:0o700});
    fs.writeFileSync(path.join(directory,'report.json'),JSON.stringify(r),{flag:'wx',mode:0o600});
    core.setOutput('report','true');
  }catch(_){core.setFailed('FAILURE: Info live publication refused.');}
}
function read(file,p) {
  const bytes=files.snapshot(file,8192),r=validateStructure(JSON.parse(bytes),p);
  need(Buffer.from(JSON.stringify(r)).equals(bytes));return r;
}
module.exports=Object.freeze({LIMITS,FIELDS,OBS,PROC,ERRORS,validateProof,validateStructure,
  verdict,proof,writeLaunchPermit,prepare,decode,validateForLivePublication,publish,read});
