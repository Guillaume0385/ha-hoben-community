'use strict';
// Shared shape checks only; no campaign policy or I/O.
const FIELDS = ['attempts', 'generation', 'read_generation', 'read_sequence',
  'loss_generation', 'loss_kind', 'close_client_subcode', 'cleaned_generation',
  'cleanup_failed', 'stopped'];
const check = condition => { if (!condition) throw new Error('invalid offline HA session proof'); };
const object = (v, names) => check(v !== null && typeof v === 'object' && !Array.isArray(v) &&
  Object.keys(v).length === names.length && names.every(k => Object.hasOwn(v, k)));
const int = (v, lo, hi) => Number.isSafeInteger(v) && v >= lo && v <= hi;

function inspect(o) {
  object(o, FIELDS);
  check(int(o.attempts, 0, 2));
  for (const k of ['generation', 'read_generation', 'loss_generation', 'cleaned_generation'])
    check(o[k] === null || int(o[k], 1, 2));
  check(o.generation === null || o.generation <= o.attempts);
  for (const k of ['read_generation', 'loss_generation', 'cleaned_generation'])
    check(o[k] === null || (o.generation !== null && o[k] <= o.generation));
  check((o.read_sequence === null) === (o.read_generation === null));
  check(o.read_sequence === null || int(o.read_sequence, 1, 6));
  check(o.read_generation === null || o.read_generation === o.generation);
  check([null, 'transport', 'close_client'].includes(o.loss_kind));
  check((o.loss_kind === null) === (o.loss_generation === null));
  check(o.loss_kind === 'close_client' ? int(o.close_client_subcode, 0, 255) : o.close_client_subcode === null);
  check(typeof o.cleanup_failed === 'boolean' && typeof o.stopped === 'boolean');
}

function progress(p, o) {
  check(o.attempts >= p.attempts);
  for (const k of ['generation', 'loss_generation', 'cleaned_generation']) check((o[k] || 0) >= (p[k] || 0));
  for (const k of ['cleanup_failed', 'stopped']) check(!p[k] || o[k]);
  if (o.loss_generation === p.loss_generation) check(o.loss_kind === p.loss_kind && o.close_client_subcode === p.close_client_subcode);
  if (o.generation === p.generation && p.read_sequence !== null) check(o.read_sequence !== null && o.read_sequence >= p.read_sequence);
}


module.exports={check,object,int,inspect,progress};
