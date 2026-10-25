// Independent C1 validator. No Actions API, admission, file I/O or live entry.
'use strict';

const LIMITS = Object.freeze({useful_ms: 300000, process_ms: 360000, cleanup_ms: 10000,
  refreshes: 6, opens: 2, rx_bytes: 1048576, memory_bytes: 1073741824,
  report_bytes: 8192, retention_days: 7, connect_ms: 10000, transport_close_ms: 5000, handshake_ms: 30000, read_ms: 30000, retry_ms: 1000});
const {check,object,int,inspect,progress}=require('./ha-session-evidence.cjs');

function validateReport(r) {
  object(r, ['schema', 'scenario', 'execution', 'provenance', 'limits', 'system_enforcement',
    'boundary_proven', 'elapsed_ms', 'completed', 'samples', 'cleanup', 'criteria', 'outcome']);
  check(r.schema === 1 && r.scenario === 'ha-persistent-c1' && r.execution === 'offline');
  check(r.system_enforcement === 'NOT RUN' && r.boundary_proven === false);
  object(r.limits, Object.keys(LIMITS));
  for (const k of Object.keys(LIMITS)) check(r.limits[k] === LIMITS[k]);
  object(r.provenance, ['merge_sha', 'pr_number', 'run_id', 'run_attempt']);
  check(typeof r.provenance.merge_sha === 'string' && /^[0-9a-f]{40}$/.test(r.provenance.merge_sha));
  check(int(r.provenance.pr_number, 1, Number.MAX_SAFE_INTEGER) && int(r.provenance.run_id, 1, Number.MAX_SAFE_INTEGER));
  check(r.provenance.run_attempt === 1 && int(r.elapsed_ms, 0, 300000) && typeof r.completed === 'boolean');
  check(Array.isArray(r.samples) && r.samples.length <= 6 && (!r.completed || r.samples.length === 6));
  let prev = null, reuse = false, recovered = false;
  for (const [index, s] of r.samples.entries()) {
    object(s, ['ordinal', 'decoded', 'observation']);
    check(s.ordinal === index + 1 && typeof s.decoded === 'boolean');
    const o = s.observation;
    inspect(o);
    if (prev) {
      const p = prev.observation;
      progress(p, o);
      if (prev.decoded && s.decoded && p.read_generation === o.read_generation && o.read_sequence === p.read_sequence + 1)
        reuse = true;
    }
    if (s.decoded) {
      check(o.read_generation !== null && !o.stopped && !o.cleanup_failed);
      check(!prev || o.read_generation !== prev.observation.read_generation || o.read_sequence > prev.observation.read_sequence);
      if (o.loss_generation !== null && o.read_generation > o.loss_generation &&
          o.cleaned_generation !== null && o.cleaned_generation >= o.loss_generation && !o.cleanup_failed)
        recovered = true;
    }
    prev = s;
  }
  object(r.cleanup, ['completed', 'observation']);
  check(typeof r.cleanup.completed === 'boolean');
  const final = r.cleanup.observation;
  inspect(final);
  if (prev) progress(prev.observation, final);
  const expected = {
    collection: r.samples.length === 0 ? 'NOT RUN' : r.completed ? 'SUCCESS' : 'FAILURE',
    tls_reuse: reuse ? 'SUCCESS' : r.completed ? 'FAILURE' : r.samples.length ? 'INCONCLUSIVE' : 'NOT RUN',
    reconnection: recovered ? 'SUCCESS' : r.samples.length ? 'INCONCLUSIVE' : 'NOT RUN',
    cleanup: r.cleanup.completed && final.stopped && !final.cleanup_failed &&
      final.cleaned_generation === final.generation ? 'SUCCESS' : 'FAILURE',
  };
  object(r.criteria, Object.keys(expected));
  for (const k of Object.keys(expected)) check(r.criteria[k] === expected[k]);
  const states = Object.values(expected);
  const overall = states.includes('FAILURE') ? 'FAILURE' : expected.collection === 'NOT RUN' ?
    'NOT RUN' : states.every(s => s === 'SUCCESS') ? 'SUCCESS' : 'INCONCLUSIVE';
  check(r.outcome === overall);
  check(Buffer.byteLength(JSON.stringify(r)) <= 8192);
  return r;
}

function parseReport(text) {
  try {
    check(typeof text === 'string' && Buffer.byteLength(text) <= 8192);
    const r = validateReport(JSON.parse(text));
    check(JSON.stringify(r) === text); // duplicates, noncanonical numbers/escapes
    return r;
  } catch (_) { throw new Error('invalid offline HA session proof'); }
}

module.exports = {validateReport, parseReport};
