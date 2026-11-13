'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {classify} = require('../../.github/scripts/ha-live-d4-observation.cjs');
const event = (kind,at_ms,generation=1) => ({
  kind,at_ms,generation,correlated:kind==='fresh_v4_correlated',
});
const base=()=>({schema:1,scenario:'hoben-live',sha:'a'.repeat(40),run_id:1,attempt:1,
  events:[event('unknown_drop',0),event('fresh_v4_correlated',1000),
    event('tls_open',301000)],
  cleanup:{completed:true,at_ms:302000,generation:1}});
const good = x => {const r=classify(x);assert.equal(r.admission,'NOT RUN');
  assert.equal(r.execution,'offline');assert.equal(r.live_ready,false);
  assert.equal(r.secrets_allowed,false);assert.equal(r.boundary_proven,false);
  assert.equal(r.simulation_only,true);return r.observation;};
test('300 seconds after genuinely correlated fresh read on same TLS generation',()=>{
  assert.equal(good(base()),'SUCCESS');
});
test('exactly 299999 ms or no unknown drop or no correlation is inconclusive',()=>{
  const late=base();late.events[2].at_ms=300999;
  late.cleanup.at_ms=301000;
  assert.equal(good(late),'INCONCLUSIVE');
  const noUnknown=base();noUnknown.events.shift();
  assert.equal(good(noUnknown),'INCONCLUSIVE');
  const noCorr=base();noCorr.events[1]=event('tls_open',1000);
  assert.equal(good(noCorr),'INCONCLUSIVE');
  const newGeneration=base();newGeneration.events[1]=event('fresh_v4_correlated',1000,2);
  newGeneration.events[2]=event('tls_open',301000,2);
  newGeneration.cleanup.generation=2;
  assert.equal(good(newGeneration),'INCONCLUSIVE');
});
test('actual EOF, local close, timeout or cleanup failure never pass',()=>{
  for(const kind of ['eof','timeout','local_close','transport_error']){
    const v=base();v.events.push(event(kind,301500));
    assert.equal(good(v),'FAILED');
  }
  const v=base();v.cleanup.completed=false;
  assert.equal(good(v),'FAILED');
});
test('unknown fields, secret material, fake correlation, bad times all refuse',()=>{
  const variants=[];
  for(const extra of [{rx_hex:'00'}, {guid:'SENSITIVE_IDENTIFIER'}, {token:'PRIVATE'}]){
    variants.push({...base(),...extra});
  }
  const a=base();a.events[1].correlated=false;variants.push(a);
  const b=base();b.events[1].kind='message_header_0x0e';variants.push(b);
  const c=base();c.events.push(event('tls_open',300000));variants.push(c);
  const d=base();d.cleanup.at_ms=300000;variants.push(d);
  const e=base();e.events[0].at_ms=-1;variants.push(e);
  const f=base();f.attempt=2;variants.push(f);
  for(const v of variants){
    assert.throws(()=>classify(v), err=>{
      assert.equal(err.message,'ha_live_d4_observation_refused');
      assert.doesNotMatch(err.message,/SENSITIVE_IDENTIFIER|PRIVATE/);
      return true;
    });
  }
});
