'use strict';
// R5 v2. Independent closed validation, no packets, HA imports or I/O.
const {object,check,int}=require('../../scripts/ha-session-evidence.cjs');
const recoverable=['eof','timeout','transport','tls','close_client'];
const isMulti=e=>e.recovery!==null&&typeof e.recovery==='object'&&Object.hasOwn(e.recovery,'schema');
function validate(e) {
  const r=e.recovery,w=e.window,final=e.cleanup.observation;
  object(r,['mode','boundary_proven','outcome','accepted_at_ms','suppressed_pongs','loss_generation','loss_after_ms','reopened_after_ms','read_generation','read_sequence','recovery_pongs','stable_ms','schema','generations','diagnostic']);
  check(r.schema===2&&r.mode==='pong_inhibition_after_120s'&&r.boundary_proven===false);
  check(['not_exercised','no_disconnect','reopen_failed','stability_lost','verified','timeout','internal','closed'].includes(r.outcome));
  for(const k of ['accepted_at_ms','loss_after_ms','reopened_after_ms'])check(r[k]===null||int(r[k],0,600000));
  for(const k of ['loss_generation','read_generation'])check(r[k]===null||int(r[k],1,3));
  check(r.read_sequence===null||int(r.read_sequence,1,6));
  for(const k of ['suppressed_pongs','recovery_pongs'])check(int(r[k],0,1048576));
  check(int(r.stable_ms,0,120000));
  object(r.diagnostic,['interruption','cleanup']);
  for(const [slot,v] of Object.entries(r.diagnostic)) {
    if(v===null)continue;
    object(v,['category','owner','generation','inhibition_exercised','subcode']);
    check([...recoverable,'closed','cancelled','internal','protocol'].includes(v.category));
    check((slot==='cleanup'?['transport_close','observer_cleanup']:['transport_read','transport_write','opening','session']).includes(v.owner));
    check(int(v.generation,1,3)&&typeof v.inhibition_exercised==='boolean');
    check(v.category==='close_client'?int(v.subcode,0,255):v.subcode===null);
  }
  check(r.diagnostic.interruption===null||r.outcome!=='verified');
  check(r.diagnostic.cleanup===null||final.cleanup_failed||!e.cleanup.completed);
  const rows=r.generations;
  check(Array.isArray(rows)&&rows.length<=3&&rows.length===final.attempts);
  rows.forEach((row,i)=>{
    object(row,['generation','connect_ms','opened_ms','loss_ms','category','subcode','cleanup_ms','pongs']);
    check(row.generation===i+1);
    for(const k of ['connect_ms','opened_ms','loss_ms','cleanup_ms']){check(row[k]===null||int(row[k],0,600000));if(e.diagnostic_schema===1&&row[k]!==null)check(row[k]<=e.diagnostic.end_ms);}
    check(int(row.pongs,0,1048576)&&(row.category===null||recoverable.includes(row.category)));
    check((row.loss_ms===null)===(row.category===null));
    check(row.category==='close_client'?int(row.subcode,0,255):row.subcode===null);
    if(row.opened_ms!==null)check(row.connect_ms!==null&&row.connect_ms<=row.opened_ms&&row.opened_ms<=w.elapsed_ms);
    if(row.loss_ms!==null)check(row.opened_ms!==null&&row.opened_ms<=row.loss_ms&&row.loss_ms<=w.elapsed_ms);
    if(row.cleanup_ms!==null)check((row.connect_ms===null||row.cleanup_ms>=row.connect_ms)&&(row.loss_ms===null||row.cleanup_ms>=row.loss_ms));
    if(i>0&&row.connect_ms!==null){const old=rows[i-1];check(old.loss_ms!==null&&old.cleanup_ms!==null&&old.cleanup_ms<=row.connect_ms);}
  });
  if(r.outcome!=='verified')return false;
  check(e.diagnostic_schema===1);
  const d=e.diagnostic,o=w.observation;
  check(rows.length>=2&&d.owners.length===rows.length&&d.first!==null&&recoverable.includes(d.first[3]));
  const finalFailed=!e.cleanup.completed||final.cleanup_failed;
  if(finalFailed)check(!e.completed&&['unexpected','timeout','closed'].includes(e.terminal)&&(d.terminal===null||d.terminal[4]==='cleanup'));
  else check(d.terminal===null&&d.cleanup===null&&e.completed&&e.terminal==='none');
  check(w.active&&o!==null&&!o.stopped&&!o.cleanup_failed&&(finalFailed||final.stopped&&final.cleaned_generation===rows.length));
  check([o.generation,o.read_generation,final.generation,r.read_generation].every(g=>g===rows.length));
  check(o.loss_generation===final.loss_generation&&o.read_sequence===final.read_sequence&&o.read_sequence===r.read_sequence);
  check(r.stable_ms===120000&&r.suppressed_pongs>0&&rows.at(-1).loss_ms===null&&rows.at(-1).pongs===r.recovery_pongs&&r.recovery_pongs>0);
  check(rows.at(-1).opened_ms!==null&&rows.at(-1).opened_ms+120000<=w.elapsed_ms);
  const control=r.loss_generation;
  check(control===1);
  const first=rows[control-1],following=rows[control];
  check(['eof','close_client'].includes(first.category)&&r.accepted_at_ms===first.opened_ms);
  check(r.loss_after_ms!==null&&r.reopened_after_ms!==null&&120000<=r.loss_after_ms&&r.loss_after_ms<r.reopened_after_ms&&r.reopened_after_ms<240000);
  check(first.loss_ms===first.opened_ms+r.loss_after_ms&&following.opened_ms===first.opened_ms+r.reopened_after_ms);
  rows.forEach((row,i)=>{
    const g=i+1,owner=d.owners[i];
    check(row.opened_ms!==null&&owner.role==='a'&&owner.generation===g&&owner.accepted_generation===g&&owner.accepted);
    if(g<rows.length||!finalFailed)check(row.cleanup_ms!==null&&owner.stage==='reaped'&&owner.pending===0&&owner.close[3]!==null);
    check(owner.close_client_subcode===row.subcode);
    if(g<rows.length)check(row.loss_ms!==null&&(row.category!=='close_client'||[3,6].includes(row.subcode)));
    const good=e.samples.filter(s=>s.decoded&&s.observation.read_generation===g);
    check(good.length>0&&owner.last_read!==null);
    good.forEach((s,j)=>{
      const so=s.observation;
      check(s.available&&s.error==='none'&&so.read_sequence===j+1&&row.opened_ms<=s.at_ms&&(row.loss_ms===null||s.at_ms<=row.loss_ms)&&!so.stopped&&!so.cleanup_failed);
      if(g>1){const old=rows[i-1];check(so.cleaned_generation===g-1);
        if(old.category==='timeout'){const prior=e.samples.filter(t=>t.decoded&&t.observation.read_generation===g-1).at(-1);check(prior);for(const k of ['loss_generation','loss_kind','close_client_subcode'])check(so[k]===prior.observation[k]);}
        else check(so.loss_generation===g-1&&so.loss_kind===(old.category==='close_client'?'close_client':'transport')&&so.close_client_subcode===old.subcode);}
    });
    check(owner.last_read[0]===good.at(-1).observation.read_sequence);
  });
  check(e.samples.at(-1).decoded&&e.samples.at(-1).observation.read_generation===rows.length);
  for(const k of ['loss_generation','loss_kind','close_client_subcode'])check(o[k]===e.samples.at(-1).observation[k]&&o[k]===final[k]);
  for(const s of e.samples)if(!s.decoded)check(['transport','timeout','closed'].includes(s.error)&&e.samples.some(t=>t.ordinal>s.ordinal&&t.decoded&&t.observation.read_generation>s.observation.generation));
  return true;
}
module.exports={isMulti,validate};
