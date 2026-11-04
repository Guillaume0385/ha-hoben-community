'use strict';
// HA-F1 scalar metadata only. Independent from Python and scenario verdicts.
const {object,check,int}=require('../../scripts/ha-session-evidence.cjs');
const fields=['diagnostic_schema','diagnostic'];
const categories=['timeout','eof','close_client','transport','tls','protocol','internal','cancelled','authentication','authorization','cleanup_failed','closed','exhausted'];
const phases=['unknown','opening','frame_boundary','message_classification','request_correlation','response_validation','post_open','tls_read','message_type','mbap_header','pdu_decode','model_decode','identity_storage','cleanup'];
const sources=['transport_connect','transport_read','transport_write','transport_close','session','observer'];
const stages=['active','stop_operations','session_close','transport_release','tls_close','tls_closed','reaped','construction_failed'];
function extra(e) {
  check(e!==null&&typeof e==='object'&&!Array.isArray(e));
  if(fields.some(k=>Object.hasOwn(e,k))) {
    check(fields.every(k=>Object.hasOwn(e,k))&&e.diagnostic_schema===1);
    return fields;
  }
  return [];
}
function validate(e,r,dual=false) {
  if(!extra(e).length)return; // Historical evidence has no F1 attestation.
  const d=e.diagnostic;
  object(d,['end_ms','first','terminal','cleanup','owners','invalid']);
  check(d.invalid===false&&int(d.end_ms,0,r.process_ms));
  if((dual?e.clock:e.window.clock)==='monotonic')check(d.end_ms<=r.elapsed_ms);
  check(Array.isArray(d.owners)&&d.owners.length<=(dual?3:2));
  const identifiers=[],acceptedCounts={a:0,b:0};
  for(const o of d.owners) {
    object(o,['role','generation','accepted','accepted_generation','close_client_subcode','close','stage','pending','last_read']);
    check((dual?['a','b']:['a']).includes(o.role)&&int(o.generation,1,o.role==='b'?1:2));
    check(o.generation===1+identifiers.filter(([role])=>role===o.role).length);
    check(!identifiers.some(([role,g])=>role===o.role&&g===o.generation));
    identifiers.push([o.role,o.generation]);
    check(typeof o.accepted==='boolean'&&stages.includes(o.stage));
    if(o.accepted){acceptedCounts[o.role]++;check(int(o.accepted_generation,1,2)&&o.accepted_generation===acceptedCounts[o.role]);}else check(o.accepted_generation===null);
    check(o.close_client_subcode===null||int(o.close_client_subcode,0,255));
    if(o.stage==='construction_failed'){check(!o.accepted&&JSON.stringify(o.close)==='[null,null,null,null]'&&o.pending===null&&o.last_read===null&&o.close_client_subcode===null);continue;}
    check(Array.isArray(o.close)&&o.close.length===4);
    let previous=-1;
    for(const v of o.close) {check(v===null||int(v,0,d.end_ms));if(v!==null){check(v>=previous);previous=v;}}
    for(let i=1;i<4;i++)check(o.close[i]===null||o.close[i-1]!==null);
    check(int(o.pending,0,127));
    if(o.close[3]!==null)check(o.pending===0&&o.stage==='reaped');
    if(o.stage==='reaped')check(o.close[3]!==null);
    if(o.close[2]!==null)check(stages.indexOf(o.stage)>=stages.indexOf('tls_closed'));
    const v=o.last_read;
    if(v!==null)check(Array.isArray(v)&&v.length===3&&o.accepted&&int(v[0],1,dual?12:6)&&int(v[1],0,d.end_ms)&&int(v[2],0,d.end_ms)&&v[2]===d.end_ms-v[1]&&(o.close[0]===null||v[1]<=o.close[0]));
  }
  for(const name of ['first','terminal','cleanup']) {
    const v=d[name];if(v===null)continue;
    check(Array.isArray(v)&&v.length===7);
    const [role,g,at,category,phase,source,subcode]=v;
    check(typeof role==='string'&&(g===null||int(g,1,2)));
    check(identifiers.some(([rr,gg])=>rr===role&&gg===g)||role==='a'&&g===null&&d.owners.length===0);
    check(int(at,0,d.end_ms)&&categories.includes(category)&&phases.includes(phase)&&sources.includes(source));
    check(category==='close_client'?int(subcode,0,255):subcode===null);
    if(name!=='first')check(d.first!==null&&d.first[2]<=at);
    if(name==='cleanup'){
      check(phase==='cleanup'&&['transport_close','session','observer'].includes(source));
      if(source==='transport_close'){const o=d.owners.find(o=>o.role===role&&o.generation===g);check(o&&o.close[2]===null&&o.close[3]===null);}
    }
    if(category==='eof'){check(phase==='tls_read'&&source==='transport_read');if(dual)check(e.phases.reduce((n,p)=>n+p[role].eof,0)>0);}
    if(category==='close_client'){
      check(['session','observer'].includes(source));
      check(d.owners.some(o=>o.role===role&&o.generation===g));
      const owner=d.owners.find(o=>o.role===role&&o.generation===g);check(owner.close_client_subcode===subcode);
      if(dual){const proof=name==='first'?e.incident:e.terminal;check(proof!==null&&proof.role===role&&proof.subcode===subcode);}
      else {const owner=d.owners.find(o=>o.role===role&&o.generation===g),witnesses=[...e.samples.map(s=>s.observation),e.cleanup.observation];check(witnesses.some(w=>w.loss_kind==='close_client'&&w.loss_generation===owner.accepted_generation&&w.close_client_subcode===subcode)||e.cleanup.observation.cleanup_failed&&e.cleanup.observation.loss_kind===null&&owner.accepted);}
    }
  }
  if(dual) {
    check(e.schema===2);
    check(JSON.stringify(identifiers)===JSON.stringify(e.owners.map(o=>[o.role,o.generation])));
    const offset=e.t0_ms||0;
    d.owners.forEach((o,i)=>{
      const original=e.owners[i];
      check(o.accepted===original.accepted&&(o.close[2]!==null)===original.close_completed&&(o.close[3]!==null)===original.cleanup);
      if(original.closed_ms!==null)check(o.close[2]>=offset+original.closed_ms-1);
      if(e.completed)check(o.close[3]!==null);
      const successful=o.role==='a'?e.reads.filter(s=>s.decoded&&s.generation===o.accepted_generation):[];
      const expected=o.role==='a'?Math.max(0,...successful.map(s=>s.sequence)):e.b_read_sequence,v=o.last_read;
      check((v===null)===(expected===0));
      if(v!==null){check(v[0]===expected);if(o.role==='a'){const s=successful.at(-1);check(v[1]>=offset+s.at_ms-1&&v[1]<=offset+s.end_ms+1);}else check(v[1]>=offset+e.b.accepted_ms-1&&v[1]<=offset+e.b.read_ms+1);}
    });
    if(e.incident){check(d.first!==null&&d.first[0]===e.incident.role&&d.first[1]===e.incident.generation&&(e.incident.at_ms===null||d.first[2]<=offset+e.incident.at_ms));const allowed={timeout:['timeout'],protocol:['protocol'],transport:['transport','tls','eof'],closed:['closed','close_client','cancelled'],unexpected:['internal','cancelled'],authentication:['authentication'],authorization:['authorization']};check(allowed[e.incident.category]?.includes(d.first[3]));}
    check(e.cleanup_errors.length===0||d.cleanup!==null);
    check(d.cleanup===null||e.owners.some(o=>!o.cleanup));
    if(e.terminal!==null)check(d.terminal!==null&&d.terminal[0]===e.terminal.role&&d.terminal[4]===e.terminal.phase);
  } else {
    const final=e.cleanup.observation;
    check(d.owners.length===final.attempts&&d.owners.filter(o=>o.accepted).length===(final.generation||0));
    check(!final.cleanup_failed||d.cleanup!==null);
    check(e.samples.every(s=>s.decoded)||d.first!==null);
    for(const o of d.owners) {
      const clean=!final.cleanup_failed||o.generation<final.attempts;
      if(o.accepted&&clean&&(final.cleaned_generation||0)>=o.accepted_generation)check(o.close[3]!==null);
      if(o.close[3]!==null)check((!final.cleanup_failed||o.generation<final.attempts)&&(!o.accepted||(final.cleaned_generation||0)>=o.accepted_generation));
      const witnesses=e.samples.map(s=>s.observation);if(e.window.observation!==null)witnesses.push(e.window.observation);
      const expected=Math.max(0,...e.samples.filter(s=>s.decoded&&s.observation.read_generation===o.accepted_generation).map(s=>s.observation.read_sequence));
      check((o.last_read===null)===(expected===0));check(o.last_read===null||o.last_read[0]===expected);
      if(o.last_read!==null)check(witnesses.some(w=>w.read_generation===o.accepted_generation&&w.read_sequence===o.last_read[0]));
    }
  }
  return d;
}
module.exports={extra,validate};
