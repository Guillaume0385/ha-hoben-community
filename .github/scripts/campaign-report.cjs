'use strict';
// Independent secret-free closed validation. No HTTP, token, claim or admission API.
const fs=require('node:fs'),path=require('node:path');
const {object,check,int,inspect,progress}=require('../../scripts/ha-session-evidence.cjs');
const baseline=require('../../scripts/ha-live-proof.cjs');
const files=require('./experimental-report-file.cjs');
const choices={protocol:['tls-only','session-open','read-v4-state','h1h2','session-300','session-reconnect','all'],
  ha:['hoben-live','open-errors','refresh-v4','session-reuse','session-reconnect','cleanup','availability','all']};
const seconds={protocol:[15,30,45,1800,360,600,3000],ha:[360,90,120,180,600,60,120,1800]};
const errors=['none','authentication','authorization','transport','protocol','timeout','closed','budget','unexpected'];
const reasons=['observed','not_observed','not_started','context_refused','identity_refused','worker_failure','timeout',
  'cancelled','cleanup_failed','report_refused','supervisor_refused','memory','processes','previous_failure','budget'];
const maxBytes=64*1024;
const dual='dual-session-observation';
const cap=(c,s)=>c==='ha'&&s===dual?900000:seconds[c][choices[c].indexOf(s)]*1000;
const names=(c,s)=>{check(Object.hasOwn(choices,c)&&(choices[c].includes(s)||c==='ha'&&s===dual));return s==='all'?choices[c].slice(0,-1):[s];};
const blank=(c='protocol',s=null)=>({opens:0,reads:0,reads_ok:0,pings:c==='ha'||s==='h1h2'?null:0,pongs:c==='ha'||s==='h1h2'?null:0,h1_sessions:c==='ha'?null:0,h2_sessions:c==='ha'?null:0,useful_ms:0,
  completed:false,cleanup:false,reused:false,recovered:false,available:false,continuous:false,
  loss_kind:'none',close_client_subcode:null,error:'none'});

function metrics(m,c,s) {
  object(m,Object.keys(blank()));
  const reads=c==='ha'&&s===dual?15:c==='ha'||s==='session-300'?6:{'tls-only':0,'session-open':0,'read-v4-state':1,h1h2:12,'session-reconnect':10}[s];
  const bounds={opens:s==='h1h2'?12:c==='ha'&&s===dual?3:c==='ha'?2:['session-300','session-reconnect'].includes(s)?3:1,reads,
    reads_ok:reads,pings:1048576,pongs:1048576,h1_sessions:6,h2_sessions:6,useful_ms:cap(c,s)};
  for(const [k,v] of Object.entries(bounds))check((s==='h1h2'&&['pings','pongs'].includes(k))||c==='ha'&&['pings','pongs','h1_sessions','h2_sessions'].includes(k)?m[k]===null:int(m[k],0,v));
  check(m.reads_ok<=m.reads&&(c==='ha'||s==='h1h2'||m.pongs<=m.pings));
  for(const k of ['completed','cleanup','reused','recovered','available','continuous'])check(typeof m[k]==='boolean');
  check(['none','transport','close_client'].includes(m.loss_kind));
  check(m.loss_kind==='close_client'?int(m.close_client_subcode,0,255):m.close_client_subcode===null);
  check(errors.includes(m.error));
}
function status(c,s,m) {
  if(!m.cleanup||!m.completed||m.error!=='none')return 'FAILURE';
  if(s==='h1h2')return m.h1_sessions===6&&m.h2_sessions===6&&m.opens===12&&m.reads===12&&m.reads_ok===12?'SUCCESS':'FAILURE';
  if(s==='session-reconnect')return m.recovered&&m.reads_ok>0&&m.opens>1&&m.loss_kind!=='none'?'SUCCESS':'INCONCLUSIVE';
  if(c==='protocol') {
    if(['tls-only','session-open'].includes(s))return m.opens===1?'SUCCESS':'FAILURE';
    if(s==='session-300')return m.useful_ms>=300000&&m.reads_ok>0&&m.pings===m.pongs?'SUCCESS':'FAILURE';
    return m.reads_ok===1?'SUCCESS':'FAILURE';
  }
  if(c==='ha'&&s===dual)return m.available&&(m.opens===2&&m.reads===13&&m.reads_ok===13&&m.continuous&&!m.recovered||m.opens===3&&m.reads_ok<=m.reads&&m.reads<=15&&m.recovered&&!m.continuous)?'SUCCESS':'FAILURE';
  if(s==='hoben-live') {
    const nominal=m.continuous&&m.reads_ok===6&&m.reused;
    const recovered=m.recovered&&m.opens===2&&m.reads===6&&m.reads_ok>=1&&m.reads_ok<=6&&m.available;
    return m.useful_ms>=300000&&(nominal||recovered)?'SUCCESS':'FAILURE';
  }
  if(['session-reuse','availability'].includes(s)) {
    const expected=s==='session-reuse'?3:2;
    const nominal=m.reads===expected&&m.reads_ok===expected&&(s!=='session-reuse'||m.reused);
    const recovered=m.recovered&&m.opens===2&&m.reads===expected&&m.reads_ok>=1&&m.reads_ok<=expected;
    return m.available&&(nominal||recovered)?'SUCCESS':'FAILURE';
  }
  const expected={'open-errors':1,'refresh-v4':2,'session-reuse':3,cleanup:1,availability:2}[s];
  return m.available&&m.reads===expected&&m.reads_ok===expected?'SUCCESS':'FAILURE';
}
function haControlled(e) {
  if(!Object.hasOwn(e,'recovery'))return false;
  const r=e.recovery,w=e.window,o=w.observation;
  object(r,['mode','boundary_proven','outcome','accepted_at_ms','suppressed_pongs',
    'loss_generation','loss_after_ms','reopened_after_ms','read_generation','read_sequence','recovery_pongs','stable_ms',
    ...(Object.hasOwn(r,'diagnostic')?['diagnostic']:[])]);
  if(Object.hasOwn(r,'diagnostic')) {
    object(r.diagnostic,['interruption','cleanup']);
    for(const [slot,v] of Object.entries(r.diagnostic)) {
      if(v===null)continue;
      object(v,['category','owner','generation','inhibition_exercised','subcode']);
      check(['eof','timeout','tls','transport','close_client','closed','cancelled','internal','protocol'].includes(v.category));
      check((slot==='cleanup'?['transport_close','observer_cleanup']:['transport_read','transport_write','opening','session']).includes(v.owner));
      check(int(v.generation,1,2)&&typeof v.inhibition_exercised==='boolean');
      check(v.category==='close_client'?int(v.subcode,0,255):v.subcode===null);
    }
    check(r.diagnostic.interruption===null||r.outcome!=='verified');
    check(r.diagnostic.cleanup===null||e.cleanup.observation.cleanup_failed||!e.cleanup.completed);
  }
  check(r.mode==='pong_inhibition_after_120s'&&r.boundary_proven===false);
  check(['not_exercised','no_disconnect','reopen_failed','stability_lost','verified','timeout','internal','closed'].includes(r.outcome));
  for(const k of ['accepted_at_ms','loss_after_ms','reopened_after_ms'])check(r[k]===null||int(r[k],0,600000));
  for(const k of ['loss_generation','read_generation'])check(r[k]===null||int(r[k],1,2));
  check(r.read_sequence===null||int(r.read_sequence,1,6));
  for(const k of ['suppressed_pongs','recovery_pongs'])check(int(r[k],0,1048576));
  check(int(r.stable_ms,0,120000));
  const proven=r.accepted_at_ms!==null&&r.suppressed_pongs>0&&r.recovery_pongs>0&&
    r.loss_generation===1&&r.read_generation===2&&r.read_sequence!==null&&r.stable_ms===120000&&
    r.loss_after_ms!==null&&r.reopened_after_ms!==null&&120000<=r.loss_after_ms&&r.loss_after_ms<r.reopened_after_ms&&r.reopened_after_ms<240000&&
    r.accepted_at_ms+r.reopened_after_ms+120000<=w.elapsed_ms&&w.active&&o!==null&&
    o.generation===2&&o.read_generation===2&&o.loss_generation===1&&['transport','close_client'].includes(o.loss_kind)&&!o.stopped&&!o.cleanup_failed&&
    e.samples.some(s=>s.decoded&&s.available&&s.at_ms>=r.accepted_at_ms+r.reopened_after_ms&&
      s.observation.read_generation===2&&s.observation.read_sequence===r.read_sequence&&s.observation.loss_generation===1&&s.observation.cleaned_generation===1);
  check(r.outcome!=='verified'||proven);
  return r.outcome==='verified'&&proven;
}
function existingRecovery(e) {
  // R1: called only after independent shape, chronology and HA-F1 validation.
  if(e.diagnostic_schema!==1||!e.samples.length)return false;
  const d=e.diagnostic,f=d.first;
  if(f===null||f[0]!=='a'||f[1]!==1||!['eof','transport','tls','timeout','close_client','protocol'].includes(f[3])||
    f[3]==='close_client'&&[2,4,5].includes(f[6])||d.terminal!==null||d.cleanup!==null||d.owners.length!==2||
    !e.completed||e.terminal!=='none'||!e.window.active)return false;
  const [old,next]=d.owners;
  if(![[old,1],[next,2]].every(([o,g])=>o.accepted&&o.accepted_generation===g&&o.stage==='reaped'&&o.pending===0&&o.close[3]!==null))return false;
  const last=e.samples.at(-1),w=e.window.observation,final=e.cleanup.observation;
  if(!last.decoded||!last.available||last.error!=='none'||w===null||!e.cleanup.completed||!final.stopped||final.cleanup_failed||
    final.cleaned_generation!==2||final.loss_generation!==w.loss_generation||next.last_read===null||
    f[2]>old.close[0]||old.close[3]>next.last_read[1])return false;
  const o=last.observation;
  if(!(o.generation===2&&o.read_generation===2&&o.cleaned_generation===1&&!o.stopped&&!o.cleanup_failed&&
    next.last_read[0]===o.read_sequence&&w.generation===2&&w.read_generation===2&&final.generation===2&&
    w.read_sequence===o.read_sequence&&final.read_sequence===o.read_sequence&&!w.stopped&&!w.cleanup_failed))return false;
  return e.samples.every(s=>s.decoded||['transport','timeout','closed','protocol'].includes(s.error)&&s.observation.generation===1&&
    !s.observation.stopped&&!s.observation.cleanup_failed&&e.samples.some(t=>t.decoded&&t.observation.read_generation===2&&
      t.observation.cleaned_generation===1&&t.ordinal>s.ordinal));
}
function liveRecovery(e) {
  // R2 only; the #112 continuous_300s result and other scenarios are unchanged.
  if(e.diagnostic_schema!==1||e.samples.length!==6)return false;
  const d=e.diagnostic,w=e.window,final=e.cleanup.observation,f=d.first;
  if(!e.completed||!w.active||w.observation===null||w.elapsed_ms<300000||w.elapsed_ms>=330000||
    !e.cleanup.completed||!final.stopped||final.cleanup_failed||final.cleaned_generation!==2||
    final.loss_generation!==w.observation.loss_generation||f===null||f[0]!=='a'||f[1]!==1||
    !['eof','transport','tls','timeout','close_client'].includes(f[3])||
    !['tls_read','request_correlation','post_open'].includes(f[4])||
    !['transport_read','transport_write','session','observer'].includes(f[5])||
    f[3]==='close_client'&&![3,6].includes(f[6])||d.terminal!==null||d.cleanup!==null||
    d.owners.length!==2||!e.samples[0].decoded||!e.samples.at(-1).decoded)return false;
  const [old,next]=d.owners;
  for(const [row,g] of [[old,1],[next,2]]) {
    const good=e.samples.filter(s=>s.decoded&&s.observation.generation===g);
    if(!row.accepted||row.accepted_generation!==g||row.stage!=='reaped'||row.pending!==0||
      row.close[3]===null||!good.length||row.last_read===null||row.last_read[0]!==good.length||
      good.some((s,i)=>s.observation.read_generation!==g||s.observation.read_sequence!==i+1||
        g===2&&s.observation.cleaned_generation!==1||s.observation.stopped||s.observation.cleanup_failed))return false;
  }
  const last=e.samples.at(-1).observation;
  if(f[2]<old.last_read[1]||f[2]>old.close[0]||old.close[3]>next.last_read[1]||
    last.generation!==2||last.cleaned_generation!==1||w.observation.generation!==2||
    w.observation.read_generation!==2||final.generation!==2||
    w.observation.read_sequence!==last.read_sequence||final.read_sequence!==last.read_sequence||
    w.observation.stopped||w.observation.cleanup_failed)return false;
  return e.samples.every(s=>s.decoded||s.observation.generation===1&&!s.observation.stopped&&
    !s.observation.cleanup_failed&&e.samples.some(t=>t.decoded&&t.observation.generation===2&&
      t.observation.cleaned_generation===1&&t.ordinal>s.ordinal));
}
function haDetail(s,d) {
  if(s===dual)return require('./ha-dual-evidence.cjs').project(d,blank);
  object(d,['supervisor','evidence']);
  const r=d.supervisor,e=d.evidence;
  const incident=require('./ha-incident-evidence.cjs');
  object(r,['started','reason','memory_bytes','pids','useful_ms','process_ms','elapsed_ms','oom_killed','pids_limited','reaped','network']);
  for(const k of ['started','oom_killed','pids_limited','reaped'])check(typeof r[k]==='boolean');
  check(r.memory_bytes===1073741824&&r.pids===128&&r.process_ms===cap('ha',s)&&r.useful_ms===(s==='hoben-live'?300000:null));
  check(int(r.elapsed_ms,0,r.process_ms)&&r.network==='fixed_tls');
  check(['completed','unavailable','cancelled','timeout','memory','processes','worker_failure'].includes(r.reason));
  if(r.reason==='completed')check(r.started&&r.reaped&&!r.oom_killed&&!r.pids_limited);
  if(r.oom_killed)check(r.reason==='memory');
  if(r.pids_limited&&!r.oom_killed)check(r.reason==='processes');
  let logical;
  if(s==='hoben-live') {
    object(e,['completed','samples','window','cleanup',...incident.extra(e)]);
    logical=baseline.validateObservation({supervisor:{...r,network:'none'},...e},true);
  } else {
    object(e,['completed','samples','window','cleanup','terminal',...incident.extra(e),...(s==='session-reconnect'&&Object.hasOwn(e,'recovery')?['recovery']:[])]);
    check(errors.includes(e.terminal)&&typeof e.completed==='boolean'&&Array.isArray(e.samples)&&e.samples.length<=6);
    check(r.started||e.samples.length===0);
    let previous=null,at=-1;
    for(const [i,v] of e.samples.entries()) {
      object(v,['ordinal','at_ms','decoded','available','error','observation']);
      check(v.ordinal===i+1&&int(v.at_ms,0,r.process_ms-1)&&v.at_ms>=at);
      check(typeof v.decoded==='boolean'&&typeof v.available==='boolean'&&errors.includes(v.error));
      inspect(v.observation);
      if(previous)progress(previous,v.observation);
      if(v.decoded) {
        check(v.available&&v.error==='none'&&v.observation.read_generation!==null&&!v.observation.stopped&&!v.observation.cleanup_failed);
        check(!previous||v.observation.read_generation!==previous.read_generation||v.observation.read_sequence>previous.read_sequence);
      }
      previous=v.observation;at=v.at_ms;
    }
    const w=e.window;
    object(w,['clock','elapsed_ms','observation','active']);
    check(typeof w.active==='boolean'&&['unattested','monotonic','synthetic'].includes(w.clock)&&int(w.elapsed_ms,0,r.process_ms));
    if(w.observation!==null) {
      inspect(w.observation);check(r.started&&w.clock!=='unattested');
      if(previous){progress(previous,w.observation);check(w.elapsed_ms>=at);}
      previous=w.observation;
    } else check(!w.active&&e.samples.length===0);
    if(w.clock==='monotonic')check(w.elapsed_ms<=r.elapsed_ms);
    if(w.clock==='unattested')check(e.samples.length===0&&w.elapsed_ms===0);
    check(!e.completed||e.samples.length>0&&e.terminal==='none'&&w.observation!==null);
    object(e.cleanup,['completed','observation']);check(typeof e.cleanup.completed==='boolean');
    inspect(e.cleanup.observation);if(previous)progress(previous,e.cleanup.observation);
    if(s==='session-reconnect')haControlled(e);
  }
  incident.validate(e,r);
  check(Buffer.byteLength(JSON.stringify(d))<=8192);
  const m=blank('ha'),o=e.cleanup.observation,w=e.window.observation;
  Object.assign(m,{opens:o.attempts,reads:e.samples.length,reads_ok:e.samples.filter(v=>v.decoded).length,useful_ms:e.window.elapsed_ms,
    completed:e.completed&&r.reason==='completed'&&r.reaped&&e.window.clock==='monotonic',
    cleanup:r.reaped&&e.cleanup.completed&&o.stopped&&!o.cleanup_failed&&o.cleaned_generation===o.generation});
  m.reused=e.samples.some((b,i)=>i>0&&e.samples[i-1].decoded&&b.decoded&&e.samples[i-1].observation.read_generation===b.observation.read_generation&&b.observation.read_sequence===e.samples[i-1].observation.read_sequence+1);
  m.recovered=e.samples.some(v=>v.decoded&&v.observation.loss_generation!==null&&v.observation.read_generation>v.observation.loss_generation&&v.observation.cleaned_generation!==null&&v.observation.cleaned_generation>=v.observation.loss_generation&&!v.observation.cleanup_failed);
  if(s==='session-reconnect')m.recovered=haControlled(e);
  if(['session-reuse','availability'].includes(s))m.recovered=existingRecovery(e);
  if(s==='hoben-live')m.recovered=liveRecovery(e);
  if(w){m.loss_kind=w.loss_kind||'none';m.close_client_subcode=w.close_client_subcode;}
  m.available=e.window.active&&e.samples.length>0&&(s==='hoben-live'?e.samples.at(-1).decoded:e.samples.at(-1).available);
  if(s==='hoben-live') {
    m.continuous=logical.criteria.continuous_300s==='SUCCESS';
    const d=e.diagnostic;
    // Permanent first F1 evidence cannot be erased by nominal read flags.
    if(d&&(d.terminal!==null||d.cleanup!==null||d.first!==null&&
      ['authentication','authorization','internal','cancelled','cleanup_failed','closed','exhausted'].includes(d.first[3])))m.error='unexpected';
  }
  else if(e.terminal!=='none')m.error=e.terminal;
  else if(e.samples.length&&!e.samples.at(-1).decoded)m.error=e.samples.at(-1).error;
  if(['session-reuse','availability'].includes(s)&&!m.recovered&&e.diagnostic?.first&&m.error==='none') {
    const d=e.diagnostic,f=d.first,category=f[3];
    const unsafe=d.terminal!==null||d.cleanup!==null||
      ['authentication','authorization','internal','cancelled','cleanup_failed','exhausted','closed'].includes(category)||
      category==='close_client'&&[2,4,5].includes(f[6]);
    if(unsafe||e.samples.some(v=>!v.decoded))
      m.error=({eof:'transport',tls:'transport',close_client:'closed'})[category]||(errors.includes(category)?category:'unexpected');
  }
  return m;
}
function recoveryWitness(w,m) {
  check(w&&typeof w==='object'&&!Array.isArray(w));
  const controlled=Object.hasOwn(w,'mode');
  object(w,['loss_generation','read_generation','read_sequence','stable_ms',
    ...(controlled?['mode','boundary_proven','outcome','suppressed_pongs','loss_after_ms','reopened_after_ms','recovery_pongs']:[])]);
  for(const k of ['loss_generation','read_generation'])check(w[k]===null||int(w[k],1,3));
  check(w.read_sequence===null||int(w.read_sequence,1,10));
  check(int(w.stable_ms,0,controlled?120000:480000));
  if(controlled) {
    check(w.mode==='pong_inhibition_after_120s'&&w.boundary_proven===false);
    check(['verified','not_exercised','no_disconnect','reopen_failed','stability_lost','timeout',
      'budget','transport','protocol','internal','closed','first_not_admissible'].includes(w.outcome));
    check(int(w.suppressed_pongs,0,m.pings-m.pongs)&&int(w.recovery_pongs,0,m.pongs));
    for(const k of ['loss_after_ms','reopened_after_ms'])check(w[k]===null||int(w[k],0,600000));
    check(w.read_sequence===null||w.read_sequence<=m.reads_ok);
  }
  if(m.recovered) {
    check(controlled&&w.outcome==='verified');
    check(w.loss_generation!==null&&w.read_generation!==null&&w.loss_generation<w.read_generation&&w.read_generation<=m.opens);
    check(w.read_sequence!==null&&w.stable_ms===120000&&w.suppressed_pongs>0&&w.recovery_pongs>0);
    check(w.loss_after_ms!==null&&w.reopened_after_ms!==null&&120000<=w.loss_after_ms&&w.loss_after_ms<w.reopened_after_ms&&w.reopened_after_ms<240000);
    check(w.reopened_after_ms+w.stable_ms<=m.useful_ms);
  }
}
function validateStage(v,c) {
  object(v,['scenario','started','elapsed_ms','reason','status','metrics','detail']);
  const s=v.scenario;
  check((choices[c].slice(0,-1).includes(s)||c==='ha'&&s===dual)&&typeof v.started==='boolean'&&int(v.elapsed_ms,0,cap(c,s))&&reasons.includes(v.reason));
  metrics(v.metrics,c,s);
  const expected=!v.started?'NOT RUN':!['observed','not_observed'].includes(v.reason)?'FAILURE':status(c,s,v.metrics);
  check(v.status===expected);
  if(!v.started){check(v.detail===null&&Object.keys(blank(c,s)).every(k=>v.metrics[k]===blank(c,s)[k]));}
  else if(c==='protocol') {
    const d=v.detail;
    const fields=Object.hasOwn(d||{},'ignored_messages')?['rx_bytes','rx_chunks','ignored_messages']:['rx_bytes','rx_chunks'];
    if(Object.hasOwn(d||{},'recovery_witness'))fields.push('recovery_witness');
    object(d,fields);
    check(int(d.rx_bytes,0,(s==='h1h2'?12:1)*1048576)&&int(d.rx_chunks,0,d.rx_bytes));
    check(d.rx_bytes>=v.metrics.reads_ok*50+(v.metrics.pings||0));
    if(Object.hasOwn(d,'recovery_witness')) {
      check(s==='session-reconnect');recoveryWitness(d.recovery_witness,v.metrics);
    }
    if(v.metrics.recovered)check(Object.hasOwn(d,'recovery_witness'));
    if(Object.hasOwn(d,'ignored_messages')) {
      object(d.ignored_messages,['7','27']);let bytes=0;
      for(const t of ['7','27']){const bins=d.ignored_messages[t];check(Array.isArray(bins)&&bins.length===253);
        for(const [i,n] of bins.entries()){check(int(n,0,d.rx_bytes));bytes+=n*(Number(t)===7?9+i:13+i);}}
      check(bytes>0&&bytes<=d.rx_bytes);
    }
  } else if(v.detail!==null) {
    const projected=haDetail(s,v.detail);check(Object.keys(projected).every(k=>projected[k]===v.metrics[k]));
    check(v.detail.supervisor.elapsed_ms<=v.elapsed_ms);
  }
  if(['SUCCESS','INCONCLUSIVE'].includes(v.status))check(v.metrics.useful_ms<=v.elapsed_ms&&(c!=='ha'||v.detail!==null));
  return v;
}
function continuationStopReason(v,c,selection) {
  // Independent of the Python gate: a functional KO does not prove isolation.
  if(c!=='ha')return ['FAILURE','NOT RUN'].includes(v.status)||!v.metrics.cleanup?'previous_failure':null;
  if(!v.started||v.reason!=='observed')return ['observed','not_observed','not_started'].includes(v.reason)?'supervisor_refused':v.reason;
  if(v.detail===null)return 'supervisor_refused';
  const r=v.detail.supervisor;
  if(!r.reaped||!v.metrics.cleanup)return 'cleanup_failed';
  if(r.reason!=='completed')return r.reason==='unavailable'?'supervisor_refused':r.reason;
  if(v.metrics.error==='budget')return 'budget';
  if(selection==='all') {
    const d=v.detail.evidence.diagnostic;
    if(d) {
      const categories=[d.first,d.terminal].filter(e=>e!==null).map(e=>e[3]);
      if(d.cleanup!==null||categories.includes('cleanup_failed')||
        d.owners.some(o=>o.stage!=='reaped'||o.pending!==0||o.close[3]===null))return 'cleanup_failed';
      if(categories.includes('cancelled'))return 'cancelled';
      if(categories.some(c=>['authentication','authorization'].includes(c)))return 'identity_refused';
      if(categories.includes('internal'))return 'worker_failure';
    }
    if(['authentication','authorization'].includes(v.metrics.error))return 'identity_refused';
  }
  return null;
}
function validate(r) {
  object(r,['schema','campaign','selection','provenance','elapsed_ms','stages','collection_result','actions_result']);
  check(r.schema===1);
  const selected=names(r.campaign,r.selection),p=r.provenance;
  object(p,['ref','sha','run_id','run_attempt']);
  check(['refs/heads/experimental','refs/heads/main'].includes(p.ref)&&typeof p.sha==='string'&&/^[a-f0-9]{40}$/.test(p.sha)&&int(p.run_id,1,Number.MAX_SAFE_INTEGER)&&int(p.run_attempt,1,Number.MAX_SAFE_INTEGER));
  check(int(r.elapsed_ms,0,cap(r.campaign,r.selection))&&Array.isArray(r.stages)&&r.stages.length===selected.length);
  let stopped=false;
  r.stages.forEach((v,i)=>{check(v.scenario===selected[i]);validateStage(v,r.campaign);
    if(stopped)check(!v.started&&v.status==='NOT RUN');
    if(r.campaign==='ha'&&r.selection==='all'&&i>0&&!stopped&&!v.started)
      check(!['previous_failure','not_started','not_observed','observed'].includes(v.reason));
    stopped=stopped||continuationStopReason(v,r.campaign,r.selection)!==null;});
  check(r.stages.reduce((n,v)=>n+v.elapsed_ms,0)<=r.elapsed_ms);
  if(r.campaign==='ha')check(r.stages.reduce((n,v)=>n+v.metrics.opens,0)<=15&&r.stages.reduce((n,v)=>n+v.metrics.reads,0)<=42);
  check(['pending','success','failure','cancelled','skipped','unattested'].includes(r.collection_result));
  check(r.actions_result===(r.collection_result==='success'&&r.stages.every(v=>v.status==='SUCCESS')?'SUCCESS':'FAILURE'));
  check(Buffer.byteLength(JSON.stringify(r))<=maxBytes);return r;
}
function selected(env=process.env) {
  try {const file=env.GITHUB_EVENT_PATH;check(fs.statSync(file).size<=256*1024);
    return names(env.CAMPAIGN,JSON.parse(fs.readFileSync(file,'utf8')).inputs.scenario);
  }catch(_){return [];}
}
function prepare(env=process.env) {
  const file=path.join(env.RUNNER_TEMP,'hoben-campaign-public/report.json');
  const raw=files.snapshot(file,maxBytes),r=validate(JSON.parse(raw.toString('utf8')));
  check(Buffer.from(JSON.stringify(r)).equals(raw));
  fs.appendFileSync(env.GITHUB_OUTPUT,'report_b64='+raw.toString('base64')+'\n');
}
// Presentation uses only independently validated fields and this fixed catalog.
// The limits are design ceilings, never minimum durations or success evidence.
function bounds(c,s) {
  if(c==='ha'&&s===dual)return 'A : cadence 60 s, continuité ou récupération prouvée ; B : une lecture, 180–360 s ; stabilité ≥300 s ; 2 connexions simultanées ; 900 s globales ; réserve 60 s ; 1 Gio ; 128 PID';
  if(c==='ha')return (s==='hoben-live'?'300 s utiles ; ':s==='session-reconnect'?'Pong de test inhibés dès 120 s ; reprise <240 s ; stabilité 120 s ; ':'')+'2 ouvertures ; 6 refreshs ; 1 Gio ; 128 PID';
  return {
    'tls-only':'1 TLS ; 0 lecture',
    'session-open':'1 ouverture ; 0 lecture',
    'read-v4-state':'1 ouverture ; 1 lecture / 20 registres',
    h1h2:'6 H1 + 6 H2 ; 90 s / 1 Mio RX par session',
    'session-300':'300 s utiles ; 3 ouvertures ; 6 lectures / ≥60 s ; 1 Mio RX',
    'session-reconnect':'Pong inhibés dès 120 s ; reprise <240 s ; stabilité 120 s ; 3 ouvertures ; 1 Mio RX',
  }[s];
}
function diagnostic(v) {
  if(!['observed','not_observed'].includes(v.reason))return v.reason;
  const r=v.detail?.supervisor,m=v.metrics;
  if(r&&r.reason!=='completed')return r.reason;
  if(m.error!=='none')return m.error;
  if(!m.cleanup)return 'cleanup_failed';
  if(!m.completed||v.status!=='SUCCESS')return 'not_observed';
  return 'observed';
}
function summary(r,env) {
  const c=env.CAMPAIGN,selectedNames=selected(env),duration=n=>(n/1000).toFixed(3)+' s';
  const lines=['## '+(c==='ha'?'Vérification réelle Home Assistant':'Tests expérimentaux MyHOBEN'),''];
  if(r) {
    const p=r.provenance,counts=['SUCCESS','FAILURE','INCONCLUSIVE','NOT RUN'].map(s=>s+' : '+r.stages.filter(v=>v.status===s).length);
    lines.push('Sélection : `'+r.selection+'`. Résultat global : **'+r.actions_result+'**. Job collect : `'+r.collection_result+'`.',
      '',counts.join(' · ')+'.','',
      'Provenance informative : `'+p.ref+'` · SHA `'+p.sha+'` · run `'+p.run_id+'` · tentative `'+p.run_attempt+'`.',
      '', 'Durée totale : '+duration(r.elapsed_ms)+' ; plafond absolu : '+duration(cap(r.campaign,r.selection))+' (nettoyage inclus).','');
  } else lines.push('Résultat global : **FAILURE**. Rapport absent ou refusé : `report_not_attested`. Durée et provenance non attestées.','');
  lines.push('| Scénario | Résultat | Diagnostic | Durée | Plafond absolu | Lectures réussies / tentées | Nettoyage |',
    '| --- | --- | --- | --- | --- | --- | --- |');
  for(const s of selectedNames) {
    const v=r?.stages.find(v=>v.scenario===s);
    lines.push('| '+[s,v?.status||'NOT RUN',v?diagnostic(v):'report_not_attested',v?duration(v.elapsed_ms):'non attestée',
      duration(cap(c,s)),v?.started?v.metrics.reads_ok+' / '+v.metrics.reads:'non attestées',
      v?.started?(v.metrics.cleanup?'attesté':'non attesté'):'non attesté'].join(' | ')+' |');
  }
  for(const v of r?.stages||[]) {
    if(v.scenario==='hoben-live'&&v.started)lines.push('',
      'R2 — hoben-live : continuité '+v.metrics.continuous+' ; récupération prouvée '+v.metrics.recovered+
      ' ; observation utile '+duration(v.metrics.useful_ms)+' ; lectures fraîches '+v.metrics.reads_ok+' / tentées '+v.metrics.reads+
      '. Le premier incident et les lectures échouées restent visibles ; aucune valeur B7 créditée.');
    if(!['session-reuse','availability'].includes(v.scenario)||!v.started)continue;
    lines.push('', 'R1 — '+v.scenario+' : réutilisation réellement attestée '+v.metrics.reused+
      ' ; récupération prouvée '+v.metrics.recovered+' ; lectures fraîches '+v.metrics.reads_ok+' / tentées '+v.metrics.reads+
      '. Une valeur conservée B7 ne compte pas comme acquisition.');
  }
  for(const v of r?.stages||[]) {
    const e=v.detail?.evidence;
    if(e?.diagnostic_schema!==1)continue;
    const d=e.diagnostic;
    lines.push('', 'Diagnostic HA-F1 — '+v.scenario+' (temps relatifs au début de collecte) :');
    for(const [key,label] of [['first','Premier incident'],['terminal','Erreur terminale'],['cleanup','Erreur de nettoyage']]) {
      const x=d[key];
      lines.push('- '+label+' : '+(x?x[0]+' / génération '+x[1]+' / '+x[3]+' / '+x[4]+' / '+x[5]+' à '+x[2]+' ms ; sous-code '+x[6]:'aucun événement attesté')+'.');
    }
    for(const o of d.owners)lines.push('- Owner '+o.role+' / tentative '+o.generation+' / génération acceptée '+o.accepted_generation+' : accepté '+o.accepted+' ; étape '+o.stage+' ; fermeture demandée '+o.close[0]+' / close transport début '+o.close[1]+' / retour '+o.close[2]+' / cleanup attesté '+o.close[3]+' ms ; dernière lecture '+(o.last_read?'séquence '+o.last_read[0]+' à '+o.last_read[1]+' ms, âge '+o.last_read[2]+' ms':'non attestée')+'.');
  }
  for(const v of r?.stages||[]) {
    if(v.scenario!==dual||!v.detail)continue;
    const e=v.detail.evidence;
    lines.push('', 'Dual : frontière OpenedClient non prouvée ; aucune causalité serveur déduite.');
    lines.push('- Résultat fonctionnel : '+(v.metrics.continuous?'continuité':v.metrics.recovered?'récupération prouvée':'non attesté')+'.');
    if(e.schema===2) {
      lines.push('- A : acquisitions décodées '+e.reads.filter(s=>s.decoded).length+' ; demandes échouées '+e.reads.filter(s=>!s.decoded&&s.attempted).length+' ; polls sans émission '+e.reads.filter(s=>!s.attempted).length+'.');
      if(e.incident)lines.push('- Premier incident : '+e.incident.role+' / génération '+e.incident.generation+' / '+e.incident.kind+' / '+e.incident.category+' / '+e.incident.phase+' à '+e.incident.at_ms+' ms ; sous-code '+e.incident.subcode+'.');
      if(e.terminal)lines.push('- Refus terminal : '+e.terminal.role+' / '+e.terminal.category+' / '+e.terminal.phase+'.');
      for(const f of e.cleanup_errors)lines.push('- Échec de nettoyage : '+f.role+' / génération '+f.generation+' / '+f.category+' à '+f.at_ms+' ms.');
      for(const o of e.owners)lines.push('- Ressource '+o.role+' / génération '+o.generation+' : ouverture '+o.open_ms+' ; acceptation '+o.accepted_ms+' ; fermeture '+o.closed_ms+' ; réapage '+o.cleaned_ms+' ms ; attesté '+o.cleanup+'.');
    }
    for(const p of e.phases)for(const role of ['a','b']) {
      const s=p[role];
      lines.push('- '+p.name+' / '+role+' : requêtes '+s.requests+' ; RX '+s.rx_bytes+' octets / '+s.rx_chunks+' livraisons ; continuations '+s.fragments+' ; Pong '+s.pongs+' ; EOF '+s.eof+' ; invalides '+s.invalid+' ; inattendus '+s.unexpected+' ; tronqués '+s.truncated+'.');
    }
    for(const role of ['a','b']) {const x=e.resources[role];lines.push('- '+role+' : ouvertures '+x.opens+' ; fermetures '+x.close_calls+' ; nettoyage '+x.cleanup+'.');}
    if(e.failure)lines.push('- Échec : '+e.failure.role+' / '+e.failure.category+' / '+e.failure.phase+' / sous-code '+e.failure.subcode+'.');
  }
  if(!selectedNames.length)lines.push('', 'Sélection non attestée : NOT RUN.');
  lines.push('', 'Bornes de conception (maxima, aucune preuve de succès) :','');
  for(const s of selectedNames)lines.push('- `'+s+'` : '+bounds(c,s)+'.');
  lines.push('', 'SUCCESS exige une preuve positive et le nettoyage. INCONCLUSIVE ne valide pas le scénario ; NOT RUN signifie absence de preuve suffisante, sans affirmer qu’aucune connexion n’a eu lieu.',
    'Une étape localement attestée ne rend pas la campagne réussie si collect échoue. H1/H2 reste une hypothèse, jamais une frontière universelle prouvée.','');
  return lines.join('\n');
}
function publish(env=process.env) {
  let r=null;
  try {
    const text=env.PUBLIC_REPORT_B64||'';check(text.length>0&&text.length<=Math.ceil(maxBytes/3)*4&&/^[A-Za-z0-9+/]*={0,2}$/.test(text));
    const raw=Buffer.from(text,'base64');check(raw.toString('base64')===text&&raw.length<=maxBytes);
    r=validate(JSON.parse(raw.toString('utf8')));check(Buffer.from(JSON.stringify(r)).equals(raw));
    check(r.campaign===env.CAMPAIGN&&JSON.stringify(r.stages.map(v=>v.scenario))===JSON.stringify(selected(env)));
    r.collection_result=['success','failure','cancelled','skipped'].includes(env.COLLECT_RESULT)?env.COLLECT_RESULT:'unattested';
    r.actions_result=r.collection_result==='success'&&r.stages.every(v=>v.status==='SUCCESS')?'SUCCESS':'FAILURE';
    validate(r);
    const folder=path.join(env.RUNNER_TEMP,'hoben-campaign-published');fs.mkdirSync(folder,{mode:0o700});
    fs.writeFileSync(path.join(folder,'report.json'),JSON.stringify(r),{mode:0o600,flag:'wx'});
    fs.appendFileSync(env.GITHUB_OUTPUT,'report=true\n');
  }catch(_){r=null;}
  const success=r!==null&&r.actions_result==='SUCCESS'&&env.COLLECT_RESULT==='success';
  fs.appendFileSync(env.GITHUB_STEP_SUMMARY,summary(r,env));
  if(!success){process.stderr.write('::error::FAILURE: manual campaign success not attested.\n');process.exitCode=1;}
}
if(require.main===module){try{check(process.argv.length===3);if(process.argv[2]==='prepare')prepare();else{check(process.argv[2]==='publish');publish();}}catch(_){process.stderr.write('::error::NOT RUN: closed campaign report refused.\n');process.exitCode=1;}}
module.exports={validate,validateStage,haDetail,prepare,publish,choices,seconds};
