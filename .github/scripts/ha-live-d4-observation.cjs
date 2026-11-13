'use strict';
// #207 D4-D synthetic observation classifier. Cannot attest a real HA run.
// Events must be supplied by the actual future client/HA owner, never by header guesses.
const TYPES = new Set(['unknown_drop','fresh_v4_correlated','tls_open','eof','timeout',
  'local_close','transport_error']);
const deny = () => {throw Error('ha_live_d4_observation_refused');};
const need = ok => {if (!ok) deny();};
const integer = (v,lo,hi) => Number.isSafeInteger(v) && v >= lo && v <= hi;
const exact = (v,fields) => {
  need(v !== null && typeof v === 'object' && !Array.isArray(v) &&
    [null,Object.prototype].includes(Object.getPrototypeOf(v)) &&
    Object.keys(v).sort().join('|') === fields.sort().join('|'));
};
function classify(raw) {
  try {
    exact(raw,['schema','scenario','sha','run_id','attempt','events','cleanup']);
    need(raw.schema === 1 && raw.scenario === 'hoben-live' &&
      typeof raw.sha === 'string' && /^[a-f0-9]{40}$/.test(raw.sha) &&
      integer(raw.run_id,1,Number.MAX_SAFE_INTEGER) && raw.attempt === 1 &&
      Array.isArray(raw.events) && raw.events.length <= 256);
    exact(raw.cleanup,['completed','at_ms','generation']);
    need(typeof raw.cleanup.completed === 'boolean' &&
      integer(raw.cleanup.at_ms,0,360000) &&
      integer(raw.cleanup.generation,1,2147483647));
    let previous = -1, drop, read, held, failure = false;
    for (const event of raw.events) {
      exact(event,['kind','at_ms','generation','correlated']);
      need(TYPES.has(event.kind) && integer(event.at_ms,0,360000) &&
        event.at_ms > previous && integer(event.generation,1,2147483647) &&
        typeof event.correlated === 'boolean');
      need(event.kind === 'fresh_v4_correlated' || event.correlated === false);
      if (event.kind === 'fresh_v4_correlated') need(event.correlated === true);
      previous = event.at_ms;
      if (event.kind === 'unknown_drop' && drop === undefined) drop = event;
      if (event.kind === 'fresh_v4_correlated' && drop !== undefined &&
          event.generation === drop.generation && event.at_ms > drop.at_ms && read === undefined)
        read = event;
      if (event.kind === 'tls_open' && read !== undefined &&
          event.generation === read.generation && event.at_ms - read.at_ms >= 300000)
        held = event;
      if (['eof','timeout','local_close','transport_error'].includes(event.kind))
        failure = true;
    }
    need(raw.cleanup.at_ms >= previous);
    // A later TLS generation or a premature close is never a continuation.
    need(!held || held.generation === raw.cleanup.generation);
    let observation = 'INCONCLUSIVE';
    if (failure || !raw.cleanup.completed) observation = 'FAILED';
    else if (drop && read && held && read.generation === drop.generation &&
        held.generation === drop.generation && raw.cleanup.completed)
      observation = 'SUCCESS';
    // This is a pure *offline* classification; even SUCCESS is not Live HA.
    return Object.freeze({schema:1,execution:'offline',admission:'NOT RUN',
      secrets_allowed:false,live_ready:false,boundary_proven:false,
      simulation_only:true,observation});
  } catch (_) {deny();}
}
module.exports = Object.freeze({classify});
