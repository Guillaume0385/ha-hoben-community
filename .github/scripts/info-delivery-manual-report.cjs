"use strict";
// #186-D1: pure validation of the #186-C OFFLINE contract. No live admission,
// filesystem, environment, worker, network, or publication implementation.
const MAX_BYTES = 8192;
const LIMITS = Object.freeze({collection_ms: 30000, cleanup_ms: 5000, total_ms: 35000,
  max_drops: 16, max_events: 128, max_report_bytes: MAX_BYTES});
const CONSTANTS = Object.freeze({schema: 1, scenario: 'info-delivery-0x0C', mode: 'offline',
  experimental_hypothesis: true, boundary_proven: false, info_framing: 'INCONCLUSIVE'});
const BOOLEANS = ['started', 'opened_validated', 'same_session', 'rx_reaped', 'cleanup_attested'];
const COUNTERS = Object.freeze({openings: 2, reconnections: 1, info_discarded: 16,
  pings_after_drop: 64, pongs_after_drop: 64, requests_after_drop: 1, reads_after_drop: 1,
  elapsed_ms: 35000, collection_ms: 35000, cleanup_ms: 35000});
const ERRORS = new Set(['none', 'protocol', 'transport', 'authentication', 'internal', 'timeout',
  'cancelled', 'closed', 'cleanup_unproven', 'cleanup_timeout', 'clock', 'budget',
  'multiple_sessions', 'evidence_gap']);
const STEPS = Object.freeze({drop: 'info_discarded', ping: 'pings_after_drop',
  pong: 'pongs_after_drop', request: 'requests_after_drop', read: 'reads_after_drop'});

const invalid = () => Error('invalid_offline_info_report');
const need = condition => { if (!condition) throw invalid(); };
const integer = (value, low, high) => Number.isSafeInteger(value) && low <= value && value <= high;

function record(value, names) {
  need(value !== null && typeof value === 'object' && !Array.isArray(value));
  need([Object.prototype, null].includes(Object.getPrototypeOf(value)));
  const own = Reflect.ownKeys(value);
  need(own.length === names.length && own.every(key => typeof key === 'string' && names.includes(key)));
  // Refuse invisible fields and getters/toJSON before reading or serializing.
  for (const key of own) {
    const descriptor = Object.getOwnPropertyDescriptor(value, key);
    need(Object.hasOwn(descriptor, 'value') && descriptor.enumerable);
  }
}

function sizes(value, count) {
  need(Array.isArray(value) && Object.getPrototypeOf(value) === Array.prototype);
  need(value.length <= count && Reflect.ownKeys(value).length === value.length + 1);
  for (let i = 0; i < value.length; i++) {
    const descriptor = Object.getOwnPropertyDescriptor(value, String(i));
    need(descriptor && Object.hasOwn(descriptor, 'value') && descriptor.enumerable);
    need(integer(descriptor.value, 1, 4096));
  }
}

function verdict(r) {
  // Match #186-C: a real failure always dominates mere absence of Info.
  if (!r.started) return r.first_error === 'none' ? ['NOT RUN', 'not_started'] : ['FAILURE', r.first_error];
  if (!r.cleanup_attested) return ['FAILURE', 'cleanup_unproven'];
  if (r.first_error !== 'none') return ['FAILURE', r.first_error];
  if (!r.same_session || r.openings !== 1 || r.reconnections) return ['FAILURE', 'multiple_sessions'];
  if (!r.info_discarded) return ['INCONCLUSIVE', 'info_absent'];
  const s = r.steps;
  const ordered = Object.values(s).every(n => integer(n, 1, 128)) &&
    s.drop < s.ping && s.ping < s.pong && s.pong < s.request && s.request < s.read;
  if (ordered && r.reads_after_drop === 1 && r.requests_after_drop === 1 &&
      r.pings_after_drop === r.pongs_after_drop && r.pings_after_drop >= 1 &&
      r.info_delivery_bytes.length === r.info_discarded && r.opened_validated && r.rx_reaped)
    return ['SUCCESS', 'post_drop_read_verified'];
  return ['FAILURE', 'insufficient_evidence'];
}

function validateOffline(report) {
  try {
    record(report, [...Object.keys(CONSTANTS), ...BOOLEANS, ...Object.keys(COUNTERS),
      'limits', 'info_delivery_bytes', 'steps', 'first_error', 'result', 'reason']);
    for (const [key, value] of Object.entries(CONSTANTS)) need(report[key] === value);
    record(report.limits, Object.keys(LIMITS));
    for (const [key, value] of Object.entries(LIMITS)) need(report.limits[key] === value);
    for (const key of BOOLEANS) need(typeof report[key] === 'boolean');
    for (const [key, maximum] of Object.entries(COUNTERS)) need(integer(report[key], 0, maximum));
    need(typeof report.first_error === 'string' && ERRORS.has(report.first_error));
    sizes(report.info_delivery_bytes, report.info_discarded);
    record(report.steps, Object.keys(STEPS));
    for (const [step, counter] of Object.entries(STEPS)) {
      const value = report.steps[step];
      need(value === null || integer(value, 1, 128));
      need((value === null) === (report[counter] === 0));
    }
    if (!report.info_discarded) need(Object.values(report.steps).every(n => n === null));
    need(report.reads_after_drop <= report.requests_after_drop);
    need(report.reconnections === Math.max(0, report.openings - 1));
    need(report.started === (report.openings > 0));
    if (!report.started)
      need(report.info_discarded === 0 && !report.rx_reaped && !report.cleanup_attested);
    need(!report.opened_validated || report.started);
    need(!report.same_session || report.opened_validated);
    need(report.elapsed_ms === report.collection_ms + report.cleanup_ms);
    need(!report.cleanup_attested || report.rx_reaped);
    if (report.collection_ms >= LIMITS.collection_ms || report.cleanup_ms > LIMITS.cleanup_ms)
      need(report.first_error !== 'none');
    const [result, reason] = verdict(report);
    need(report.result === result && report.reason === reason);
    const encoded = JSON.stringify(report);
    need(Buffer.byteLength(encoded, 'utf8') <= MAX_BYTES);
    // Detach the validated scalar projection from caller-owned references.
    return JSON.parse(encoded);
  } catch (_) {
    throw invalid(); // Never copy user data or an exception message/cause.
  }
}

function parseOffline(input) {
  try {
    need(typeof input === 'string' || Buffer.isBuffer(input));
    if (typeof input === 'string') need(input.length <= MAX_BYTES);
    const bytes = typeof input === 'string' ? Buffer.from(input, 'utf8') : input;
    need(bytes.length <= MAX_BYTES);
    const text = bytes.toString('utf8');
    need(Buffer.from(text, 'utf8').equals(bytes));
    const report = JSON.parse(text);
    const projection = validateOffline(report);
    // The #186-C encoder emits compact ASCII JSON. A round-trip refuses
    // duplicate keys, aliases/escapes, fractional encodings and hidden suffixes.
    need(JSON.stringify(report) === text);
    return projection;
  } catch (_) {
    throw invalid();
  }
}

function validateForLivePublication() {
  // No attestation/provenance exists in D1. No report or caller flag may
  // upgrade a fixture SUCCESS into an authenticated live observation.
  throw Error('info_live_provenance_not_proven');
}

module.exports = Object.freeze({MAX_BYTES, validateOffline, parseOffline, validateForLivePublication});
