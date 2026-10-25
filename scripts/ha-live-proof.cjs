'use strict';
// Independent C2a validator. No engine, Actions API, publication or live claim.
const {check,object,int,inspect,progress}=require('./ha-session-evidence.cjs');
const reasons=['completed','unavailable','cancelled','timeout','memory','processes','worker_failure'];

function validateReport(r) {
  object(r,['schema','scenario','execution','admission','boundary_proven','provenance',
    'supervisor','completed','samples','window','cleanup','criteria','outcome']);
  check(r.schema===2 && r.scenario==='ha-persistent-live' && r.execution==='offline' &&
    r.admission==='NOT RUN' && r.boundary_proven===false);
  const p=r.provenance;
  object(p,['merge_sha','pr_number','run_id','run_attempt']);
  check(typeof p.merge_sha==='string' && /^[0-9a-f]{40}$/.test(p.merge_sha) &&
    int(p.pr_number,1,Number.MAX_SAFE_INTEGER) && int(p.run_id,1,Number.MAX_SAFE_INTEGER) && p.run_attempt===1);
  const g=r.supervisor;
  object(g,['started','reason','memory_bytes','pids','useful_ms','process_ms',
    'elapsed_ms','oom_killed','pids_limited','reaped','network']);
  for(const k of ['started','oom_killed','pids_limited','reaped']) check(typeof g[k]==='boolean');
  check(int(g.memory_bytes,1,1073741824) && int(g.pids,1,128) && int(g.useful_ms,1,300000) &&
    int(g.process_ms,1,360000) && int(g.elapsed_ms,0,360000) && reasons.includes(g.reason) && g.network==='none');
  check(g.useful_ms<g.process_ms);
  if(g.reason==='completed') check(g.started && g.reaped && !g.oom_killed && !g.pids_limited && g.elapsed_ms<=g.process_ms);
  if(g.oom_killed) check(g.reason==='memory');
  if(g.pids_limited && !g.oom_killed) check(g.reason==='processes');
  check(Array.isArray(r.samples) && r.samples.length<=6 && typeof r.completed==='boolean' &&
    (!r.completed || r.samples.length===6) && (g.started || r.samples.length===0));
  let previous=null, reuse=false, recovered=false;
  for(const [i,s] of r.samples.entries()) {
    object(s,['ordinal','at_ms','decoded','observation']);
    check(int(s.at_ms,i*50000,299999) && (i!==0 || s.at_ms===0));
    if(i) check(s.at_ms>=r.samples[i-1].at_ms);
    check(s.ordinal===i+1 && typeof s.decoded==='boolean');
    const o=s.observation;
    inspect(o);
    if(previous) {
      progress(previous.observation,o);
      if(previous.decoded && s.decoded && previous.observation.read_generation===o.read_generation &&
        o.read_sequence===previous.observation.read_sequence+1) reuse=true;
    }
    if(s.decoded) {
      check(o.read_generation!==null && !o.stopped && !o.cleanup_failed);
      check(!previous || o.read_generation!==previous.observation.read_generation ||
        o.read_sequence>previous.observation.read_sequence);
      if(o.loss_generation!==null && o.read_generation>o.loss_generation &&
        o.cleaned_generation!==null && o.cleaned_generation>=o.loss_generation && !o.cleanup_failed) recovered=true;
    }
    previous=s;
  }
  const w=r.window;
  object(w,['clock','elapsed_ms','observation','active']);
  check(typeof w.active==='boolean' && (w.observation!==null || !w.active));
  check(['unattested','monotonic','synthetic'].includes(w.clock) && int(w.elapsed_ms,0,360000));
  if(w.observation!==null) {
    inspect(w.observation);
    check(w.clock!=='unattested' && g.started);
    if(previous) {
      progress(previous.observation,w.observation);
      check(w.elapsed_ms>=previous.at_ms);
    }
  }
  if(r.completed) check(w.elapsed_ms>=300000 && w.elapsed_ms<330000 && w.observation!==null && g.useful_ms===300000);
  if(w.clock==='monotonic') check(w.elapsed_ms<=g.elapsed_ms);
  if(w.clock==='unattested') check(!r.samples.length && w.elapsed_ms===0);
  object(r.cleanup,['completed','observation']);
  check(typeof r.cleanup.completed==='boolean');
  const final=r.cleanup.observation;
  inspect(final);
  if(w.observation!==null) progress(w.observation,final);
  else if(previous) progress(previous.observation,final);
  const safe=g.reason==='completed' && g.reaped;
  let expected={
    collection:r.samples.length ? r.completed ? 'SUCCESS':'FAILURE':'NOT RUN',
    tls_reuse:reuse ? 'SUCCESS':r.completed ? 'FAILURE':r.samples.length ? 'INCONCLUSIVE':'NOT RUN',
    reconnection:recovered && safe ? 'SUCCESS':r.samples.length ? 'INCONCLUSIVE':'NOT RUN',
    cleanup:r.cleanup.completed && final.stopped && !final.cleanup_failed &&
      final.cleaned_generation===final.generation ? 'SUCCESS':'FAILURE',
    continuous_300s:r.completed && safe && r.samples.every(s=>s.decoded) &&
      w.observation!==null && w.observation.loss_generation===null &&
      w.observation.generation===r.samples[0].observation.read_generation &&
      w.observation.read_generation===w.observation.generation && w.active &&
      !w.observation.stopped && !w.observation.cleanup_failed ? 'SUCCESS':r.samples.length ? 'FAILURE':'NOT RUN',
    supervision:safe ? 'SUCCESS':g.started ? 'FAILURE':'NOT RUN',
  };
  if(!g.started) {
    expected=Object.fromEntries(Object.keys(expected).map(k=>[k,'NOT RUN']));
    if(g.reason!=='unavailable') expected.supervision='FAILURE';
  }
  object(r.criteria,Object.keys(expected));
  for(const k of Object.keys(expected)) check(r.criteria[k]===expected[k]);
  const values=Object.values(expected);
  const overall=values.includes('FAILURE') ? 'FAILURE':expected.collection==='NOT RUN' ? 'NOT RUN':
    values.every(v=>v==='SUCCESS') ? 'SUCCESS':'INCONCLUSIVE';
  check(r.outcome===overall && Buffer.byteLength(JSON.stringify(r))<=8192);
  return r;
}

function parseReport(text) {
  try {
    check(typeof text==='string' && Buffer.byteLength(text)<=8192);
    const r=validateReport(JSON.parse(text));
    check(JSON.stringify(r)===text);
    return r;
  } catch(_) {throw Error('invalid inactive HA live proof');}
}
module.exports={validateReport,parseReport};
