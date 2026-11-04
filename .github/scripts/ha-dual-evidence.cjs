'use strict';
// Independent closed scalar proof. No Python, network, payload or identity API.
const {object,check,int}=require('../../scripts/ha-session-evidence.cjs');
const roles=['a','b'],phases=['before','overlap','after'];
const errors=['none','authentication','authorization','transport','protocol','timeout','closed','budget','unexpected'];
const states=['connected','reconnecting','recovering','disconnected'];
const categories=['none','protocol','transport','timeout','tls_verification','closed','modbus_exception','unexpected_error'];
const provenancePhases=['unknown','opening','frame_boundary','message_classification','request_correlation','response_validation','post_open','tls_read','message_type','mbap_header','pdu_decode','model_decode','identity_storage','cleanup'];
const types=['unknown','opened_client','ping','close_client','data_response_client','data_response_server','data_updated','device_auth_req'];
const counts=['rx_bytes','rx_chunks','fragments','buffered_max','pongs','opening_pongs','requests','eof','invalid','unexpected','truncated'];
const time=v=>v===null||int(v,0,900000);
const phase=v=>v<180000?0:v<360000?1:2;
function frame(v) {
  object(v,['event','generation','message_type','expected_total_bytes','received_bytes','length_scope','provenance','phase','category','status','at_ms']);
  check(['header','error'].includes(v.event)&&(v.generation==='unknown'||int(v.generation,1,2)));
  check(types.includes(v.message_type));
  check(v.received_bytes==='unknown'||int(v.received_bytes,0,4096));
  check(v.expected_total_bytes==='unknown'||int(v.expected_total_bytes,1,265));
  check(['frame','post_open_hypothesis','unproven'].includes(v.length_scope));
  check(['validated_header','fixed_contract','unproven'].includes(v.provenance));
  check(provenancePhases.includes(v.phase)&&categories.includes(v.category));
  check(['complete','partial','invalid','unknown'].includes(v.status)&&time(v.at_ms));
  const n=v.expected_total_bytes,t=v.message_type;
  if(n==='unknown')check(v.provenance==='unproven'&&v.length_scope==='unproven');
  else if(v.provenance==='fixed_contract')check(t==='ping'&&n===1&&v.length_scope==='frame'||t==='close_client'&&n===2&&v.length_scope==='post_open_hypothesis');
  else check(v.provenance==='validated_header'&&v.length_scope==='frame'&&(['data_response_client','data_response_server'].includes(t)&&n>=9&&n<=261||t==='data_updated'&&n>=13&&n<=265));
}
const total=(e,role,k)=>e.phases.reduce((n,p)=>n+p[role][k],0);
function positive(e) {
  const b=e.b;
  return e.t0_ms!==null&&e.error==='none'&&!e.overflow&&e.failure===null&&e.reads.length===12&&e.a_end_active&&
    e.reads.every(s=>s.decoded&&s.available&&s.at_ms-s.scheduled_ms<=5000)&&
    Object.values(e.resources).every(r=>r.accepted&&r.opens===1&&r.close_calls===1&&r.close_completed&&r.cleanup)&&
    Object.values(b).every(v=>v!==null)&&b.start_ms>=180000&&b.start_ms<=185000&&b.accepted_ms<=185000&&b.accepted_ms<=b.read_ms&&b.read_ms<360000&&b.read_ms<=b.accepted_ms+30000&&
    b.close_ms>=360000&&b.close_ms<=365000&&b.close_ms<=b.closed_ms&&b.closed_ms<=b.close_ms+10000&&e.b_read_sequence===1&&
    e.b_active_at_close&&e.end_ms>=Math.max(660000,b.closed_ms+300000)&&
    JSON.stringify(e.transitions.map(t=>[t.role,t.state]))===JSON.stringify([['a','connected'],['b','connected'],['b','disconnected'],['a','disconnected']])&&
    JSON.stringify(e.transitions.slice(0,3).map(t=>t.at_ms))===JSON.stringify([0,b.accepted_ms,b.closed_ms])&&e.transitions.at(-1).at_ms>=e.end_ms&&
    e.phases.every(p=>roles.every(role=>['eof','invalid','unexpected','truncated'].every(k=>p[role][k]===0)))&&total(e,'a','requests')===12&&total(e,'b','requests')===1&&roles.every(role=>e.phases.reduce((n,p)=>n+p[role].types[1],0)===1&&e.phases.reduce((n,p)=>n+p[role].types[4],0)===(role==='a'?12:1))&&roles.every(role=>total(e,role,'pongs')===e.phases.reduce((n,p)=>n+p[role].types[2]+p[role].opening_pongs,0));
}
function evidence(e) {
  object(e,['schema','boundary_proven','clock','completed','error','t0_ms','end_ms','a_end_active','reads','b','b_read_sequence','b_active_at_close','resources','phases','transitions','failure','overflow']);
  check(e.schema===1&&e.boundary_proven===false&&['unattested','synthetic','monotonic'].includes(e.clock));
  for(const k of ['completed','a_end_active','b_active_at_close','overflow'])check(typeof e[k]==='boolean');
  check(errors.includes(e.error)&&time(e.t0_ms)&&int(e.end_ms,0,900000));
  check(Array.isArray(e.reads)&&e.reads.length<=12);
  check(e.clock!=='unattested'||e.reads.length===0&&e.t0_ms===null);
  let previous=-1;
  for(const [i,s] of e.reads.entries()) {
    object(s,['scheduled_ms','at_ms','end_ms','decoded','available','state','generation','sequence','error']);
    check(s.scheduled_ms===i*60000&&int(s.at_ms,s.scheduled_ms,900000)&&s.at_ms>=previous&&int(s.end_ms,s.at_ms,900000));previous=s.end_ms;
    check(typeof s.decoded==='boolean'&&typeof s.available==='boolean'&&states.includes(s.state)&&errors.includes(s.error));
    check((s.generation===null||int(s.generation,1,2))&&(s.sequence===null||int(s.sequence,1,12))&&((s.generation===null)===(s.sequence===null)));
    if(s.decoded)check(s.available&&s.state==='connected'&&s.error==='none'&&s.generation===1&&s.sequence===i+1);
    check(e.t0_ms!==null&&s.end_ms<=e.end_ms);
  }
  const b=e.b;object(b,['start_ms','accepted_ms','read_ms','close_ms','closed_ms']);
  let prior=null;
  for(const k of ['start_ms','accepted_ms','read_ms','close_ms','closed_ms']) {
    const v=b[k];check(time(v));if(v!==null){check((prior===null||v>=prior)&&(v<=e.end_ms||k==='closed_ms'));prior=v;}
  }
  check(int(e.b_read_sequence,0,1)&&((b.read_ms!==null)===(e.b_read_sequence===1)));
  object(e.resources,roles);
  for(const r of Object.values(e.resources)) {
    object(r,['opens','accepted','close_calls','close_completed','cleanup']);
    check(int(r.opens,0,1)&&int(r.close_calls,0,1));
    for(const k of ['accepted','close_completed','cleanup'])check(typeof r[k]==='boolean');
    check(!r.accepted||r.opens===1);check(!r.close_completed||r.close_calls===1&&r.opens===1);
    check(!r.cleanup||r.close_completed||r.opens===0&&r.close_calls===0);
  }
  check((b.accepted_ms===null||e.resources.b.accepted)&&(b.closed_ms===null||e.resources.b.cleanup));
  check(Array.isArray(e.phases)&&e.phases.length===3);
  for(const [i,p] of e.phases.entries()) {
    object(p,['name',...roles]);check(p.name===phases[i]);
    for(const role of roles) {
      const s=p[role];object(s,[...counts,'types','last_frame']);
      for(const k of counts)check(int(s[k],0,k==='rx_bytes'?1048576:4096));
      check(s.fragments<=s.rx_chunks&&Array.isArray(s.types)&&s.types.length===types.length&&s.types.every(n=>int(n,0,4096)));
      if(s.last_frame!==null){frame(s.last_frame);check(s.last_frame.at_ms===null||phase(s.last_frame.at_ms)===i);}
    }
  }
  for(const role of roles)check(total(e,role,'rx_bytes')<=1048576&&total(e,role,'requests')<=(role==='a'?12:1));
  check(Array.isArray(e.transitions)&&e.transitions.length<=8);let last=-1;
  for(const t of e.transitions){object(t,['role','at_ms','state']);check(roles.includes(t.role)&&states.includes(t.state)&&int(t.at_ms,0,900000)&&t.at_ms>=last);last=t.at_ms;}
  if(e.failure!==null) {
    const f=e.failure;object(f,['role','at_ms','category','phase','subcode']);
    check(roles.includes(f.role)&&time(f.at_ms)&&errors.slice(1).includes(f.category)&&provenancePhases.includes(f.phase));
    check(f.subcode===null||f.category==='closed'&&int(f.subcode,0,255));check(e.error!=='none');
  }
  check(!e.overflow||e.error==='budget');if(e.completed)check(positive(e));
}
function project(d,blank) {
  object(d,['supervisor','evidence']);const r=d.supervisor,e=d.evidence;
  object(r,['started','reason','memory_bytes','pids','useful_ms','process_ms','elapsed_ms','oom_killed','pids_limited','reaped','network']);
  for(const k of ['started','oom_killed','pids_limited','reaped'])check(typeof r[k]==='boolean');
  check(r.memory_bytes===1073741824&&r.pids===128&&r.process_ms===900000&&r.useful_ms===null&&int(r.elapsed_ms,0,900000)&&r.network==='fixed_tls');
  check(['completed','unavailable','cancelled','timeout','memory','processes','worker_failure'].includes(r.reason));
  if(r.reason==='completed')check(r.started&&r.reaped&&!r.oom_killed&&!r.pids_limited);
  check(!r.oom_killed||r.reason==='memory');check(!r.pids_limited||r.oom_killed||r.reason==='processes');
  evidence(e);check(r.started||e.reads.length===0&&Object.values(e.resources).every(x=>x.opens===0));
  if(e.clock==='monotonic'&&e.t0_ms!==null)check(e.t0_ms+e.end_ms<=r.elapsed_ms);
  check(Buffer.byteLength(JSON.stringify(d))<=8192);
  const m=blank('ha');
  Object.assign(m,{opens:Object.values(e.resources).reduce((n,r)=>n+r.opens,0),reads:total(e,'a','requests')+total(e,'b','requests'),
    reads_ok:e.reads.filter(s=>s.decoded).length+e.b_read_sequence,useful_ms:e.end_ms,
    completed:e.completed&&e.clock==='monotonic'&&r.reason==='completed'&&r.reaped,
    cleanup:r.reaped&&Object.values(e.resources).every(x=>x.cleanup),continuous:positive(e),
    reused:e.reads.length>1&&e.reads.every(s=>s.decoded),available:e.a_end_active&&e.reads.length>0&&e.reads.at(-1).available,error:e.error});
  if(e.failure&&['transport','closed'].includes(e.failure.category)) {
    m.loss_kind=e.failure.subcode===null?'transport':'close_client';m.close_client_subcode=e.failure.subcode;
  }
  return m;
}
module.exports={project};
