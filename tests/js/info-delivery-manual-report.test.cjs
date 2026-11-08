"use strict";
const test = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), vm = require('node:vm');
const file = require.resolve('../../.github/scripts/info-delivery-manual-report.cjs');
const api = require(file);

// Independent scalar fixtures. Python tests additionally supply actual #186-C
// reports from the real V4Session and compare both validators.
function success() {
  return {schema: 1, scenario: 'info-delivery-0x0C', mode: 'offline',
    experimental_hypothesis: true, boundary_proven: false, info_framing: 'INCONCLUSIVE',
    limits: {collection_ms: 30000, cleanup_ms: 5000, total_ms: 35000,
      max_drops: 16, max_events: 128, max_report_bytes: 8192},
    started: true, opened_validated: true, same_session: true, openings: 1, reconnections: 0,
    info_discarded: 1, info_delivery_bytes: [1], pings_after_drop: 1, pongs_after_drop: 1,
    requests_after_drop: 1, reads_after_drop: 1,
    steps: {drop: 3, ping: 4, pong: 5, request: 6, read: 9},
    rx_reaped: true, cleanup_attested: true, first_error: 'none',
    elapsed_ms: 150, collection_ms: 100, cleanup_ms: 50,
    result: 'SUCCESS', reason: 'post_drop_read_verified'};
}
function absent() {
  return {...success(), info_discarded: 0, info_delivery_bytes: [], pings_after_drop: 0,
    pongs_after_drop: 0, requests_after_drop: 0, reads_after_drop: 0,
    steps: {drop: null, ping: null, pong: null, request: null, read: null},
    result: 'INCONCLUSIVE', reason: 'info_absent'};
}
function notRun() {
  return {...absent(), started: false, opened_validated: false, same_session: false,
    openings: 0, rx_reaped: false, cleanup_attested: false, elapsed_ms: 0,
    collection_ms: 0, cleanup_ms: 0, result: 'NOT RUN', reason: 'not_started'};
}
const refused = run => assert.throws(run, error =>
  error.message === 'invalid_offline_info_report' && error.cause === undefined);

for (const [name, fixture] of Object.entries({success, absent, notRun})) {
  test('closed offline projection: ' + name, () => {
    const report = fixture();
    const projected = api.validateOffline(report);
    assert.deepEqual(projected, report);
    assert.notEqual(projected, report);
    assert.notEqual(projected.limits, report.limits);
    assert.notEqual(projected.steps, report.steps);
    for (const value of [JSON.stringify(report), Buffer.from(JSON.stringify(report))])
      assert.deepEqual(api.parseOffline(value), report);
  });
}

test('opaque whole delivery size and last-drop proof do not assert Info framing', () => {
  const r = success(); r.info_discarded = 16; r.info_delivery_bytes = Array(16).fill(4096);
  r.steps = {drop: 120, ping: 121, pong: 122, request: 123, read: 128};
  assert.equal(api.validateOffline(r).result, 'SUCCESS');
  assert.equal(api.validateOffline(r).boundary_proven, false);
  assert.equal(api.validateOffline(r).info_framing, 'INCONCLUSIVE');
});

const errors = ['protocol', 'transport', 'authentication', 'internal', 'timeout', 'cancelled',
  'closed', 'cleanup_unproven', 'cleanup_timeout', 'clock', 'budget', 'multiple_sessions', 'evidence_gap'];
for (const error of errors) test('first incident dominates absence of Info: ' + error, () => {
  const r = {...absent(), first_error: error, result: 'FAILURE', reason: error};
  assert.deepEqual(api.validateOffline(r), r);
  refused(() => api.validateOffline({...r, result: 'SUCCESS', reason: 'post_drop_read_verified'}));
  refused(() => api.validateOffline({...r, result: 'INCONCLUSIVE', reason: 'info_absent'}));
});

test('cleanup refusal preserves first cause and cannot credit an abort alone', () => {
  const r = {...success(), first_error: 'timeout', cleanup_attested: false,
    result: 'FAILURE', reason: 'cleanup_unproven'};
  assert.equal(api.validateOffline(r).first_error, 'timeout');
  refused(() => api.validateOffline({...r, reason: 'timeout'}));
  refused(() => api.validateOffline({...r, result: 'SUCCESS', reason: 'post_drop_read_verified'}));
});

test('failed chronology is faithfully FAILURE, never repaired to SUCCESS', () => {
  const r = success(); r.steps.read = r.steps.request;
  refused(() => api.validateOffline(r));
  r.result = 'FAILURE'; r.reason = 'insufficient_evidence';
  assert.equal(api.validateOffline(r).result, 'FAILURE');
});

test('phase overrun is representable only as failure within the total bound', () => {
  const r = {...success(), collection_ms: 30000, cleanup_ms: 5000, elapsed_ms: 35000,
    first_error: 'budget', result: 'FAILURE', reason: 'budget'};
  assert.equal(api.validateOffline(r).result, 'FAILURE');
  refused(() => api.validateOffline({...r, first_error: 'none'}));
  const clean = {...r, collection_ms: 100, cleanup_ms: 5001, elapsed_ms: 5101,
    first_error: 'cleanup_timeout', reason: 'cleanup_timeout'};
  assert.equal(api.validateOffline(clean).result, 'FAILURE');
  refused(() => api.validateOffline({...clean, first_error: 'none'}));
});

for (const key of Object.keys(success())) test('missing field refused: ' + key, () => {
  const r = success(); delete r[key]; refused(() => api.validateOffline(r));
});
const changes = {
  'extra-private': r => {r.payload = 'PRIVATE_INFO_D1';},
  'free-error': r => {r.first_error = 'PRIVATE_INFO_D1';},
  'free-reason': r => {r.reason = 'PRIVATE_INFO_D1';},
  'live-mode': r => {r.mode = 'live';},
  'invented-info-length': r => {r.info_total_bytes = 2;},
  'wire-proof': r => {r.boundary_proven = true;},
  'framing-proof': r => {r.info_framing = 'proven';},
  'not-hypothesis': r => {r.experimental_hypothesis = false;},
  'schema-bool': r => {r.schema = true;},
  'wrong-scenario': r => {r.scenario = 'all';},
  'boolean-type': r => {r.started = 1;},
  'size-zero': r => {r.info_delivery_bytes = [0];},
  'size-large': r => {r.info_delivery_bytes = [4097];},
  'size-bool': r => {r.info_delivery_bytes = [true];},
  'size-missing': r => {r.info_delivery_bytes = [];},
  'size-excess': r => {r.info_delivery_bytes = [1, 1];},
  'reconnected': r => {r.openings = 2; r.reconnections = 1;},
  'reconnection-inconsistent': r => {r.reconnections = 1;},
  'unopened': r => {r.opened_validated = false;},
  'another-owner': r => {r.same_session = false;},
  'unreaped': r => {r.rx_reaped = false;},
  'cleanup-unproven': r => {r.cleanup_attested = false;},
  'unequal-clock': r => {r.elapsed_ms++;},
  'missing-request': r => {r.requests_after_drop = 0; r.steps.request = null;},
  'missing-read': r => {r.reads_after_drop = 0; r.steps.read = null;},
  'false-pong': r => {r.pongs_after_drop = 2;},
  'no-ping': r => {r.pings_after_drop = 0; r.steps.ping = null;},
  'step-bool': r => {r.steps.read = true;},
  'step-null': r => {r.steps.read = null;},
  'step-too-late': r => {r.steps.read = 129;},
  'step-private': r => {r.steps.private = 'PRIVATE_INFO_D1';},
  'step-missing': r => {delete r.steps.drop;},
  'changed-verdict': r => {r.result = 'INCONCLUSIVE';},
  'limits-live-hour': r => {r.limits.total_ms = 3600000;},
  'limits-extra': r => {r.limits.private = 'PRIVATE_INFO_D1';},
  'fake-attestation': r => {r.attestation = {authenticated: true};},
};
for (const [name, mutate] of Object.entries(changes)) test('rejects contradiction: ' + name, () => {
  const r = success(); mutate(r); refused(() => api.validateOffline(r));
});
for (const [key, maximum] of Object.entries({openings: 2, reconnections: 1, info_discarded: 16,
  pings_after_drop: 64, pongs_after_drop: 64, requests_after_drop: 1, reads_after_drop: 1,
  elapsed_ms: 35000, collection_ms: 35000, cleanup_ms: 35000})) {
  for (const [name, value] of Object.entries({negative: -1, over: maximum + 1,
    boolean: true, string: '1', null: null, fraction: 0.5, nan: NaN, infinity: Infinity}))
    test('strict counter ' + key + '/' + name, () => {
      refused(() => api.validateOffline({...success(), [key]: value}));
    });
}

test('absence cannot carry post-drop evidence or manufactured SUCCESS', () => {
  for (const name of ['drop', 'ping', 'pong', 'request', 'read']) {
    const r = absent(); r.steps[name] = 1; refused(() => api.validateOffline(r));
  }
  refused(() => api.validateOffline({...absent(), result: 'SUCCESS', reason: 'post_drop_read_verified'}));
  refused(() => api.validateOffline({...absent(), requests_after_drop: 1, reads_after_drop: 1}));
});

for (const kind of ['drop', 'reaped', 'cleanup']) test('NOT RUN cannot claim activity: ' + kind, () => {
  const r = notRun();
  if (kind === 'drop') {
    r.info_discarded = 1; r.info_delivery_bytes = [1]; r.steps.drop = 1;
  } else if (kind === 'reaped') r.rx_reaped = true;
  else {r.rx_reaped = true; r.cleanup_attested = true;}
  refused(() => api.validateOffline(r));
});

test('transport encoding refuses size excess, duplicates, aliases and malformed UTF-8', () => {
  const text = JSON.stringify(success());
  for (const input of [null, {}, true, Buffer.alloc(8193), ' '.repeat(8193),
    text + '\n', text + '{}', '\ufeff' + text,
    text.replace('"schema":1', '"schema":1.0'),
    text.replace('"mode":"offline"', '"mode":"live","mode":"offline"'),
    text.replace('"result":"SUCCESS"', '"result":"FAILURE","result":"SUCCESS"'),
    Buffer.concat([Buffer.from(text), Buffer.from([255])])])
    refused(() => api.parseOffline(input));
  assert.equal(api.MAX_BYTES, 8192);
});

test('hidden data, accessors, prototype tricks and array holes are refused without inspection', () => {
  const reports = [];
  const invisible = success(); Object.defineProperty(invisible, 'private', {value: 'PRIVATE_INFO_D1'});
  const symbol = success(); symbol[Symbol('private')] = 'PRIVATE_INFO_D1';
  const getter = success(); Object.defineProperty(getter, 'reason', {
    enumerable: true, get() {throw Error('PRIVATE_GETTER_MUST_NOT_RUN');}});
  const prototype = Object.assign(Object.create({private: 'PRIVATE_INFO_D1'}), success());
  const serialize = success(); serialize.toJSON = () => {throw Error('PRIVATE_SERIALIZER_MUST_NOT_RUN');};
  const holes = success(); holes.info_delivery_bytes = Array(1);
  const arrayExtra = success(); arrayExtra.info_delivery_bytes.private = 'PRIVATE_INFO_D1';
  reports.push(invisible, symbol, getter, prototype, serialize, holes, arrayExtra);
  for (const r of reports) refused(() => api.validateOffline(r));
});

test('live publication is always refused regardless of report or forged proof', () => {
  for (const r of [undefined, null, success(), absent(), notRun(),
    {...success(), mode: 'live', authenticated: true},
    {...success(), proof: {worker: 'real', authenticated: true, supervised: true}}])
    assert.throws(() => api.validateForLivePublication(r, {allowOffline: true, authorized: true}),
      {message: 'info_live_provenance_not_proven'});
});

test('module executes without require, environment, filesystem, network or timers', () => {
  const denied = () => {throw Error('IO_MUST_NOT_RUN');};
  const context = {module: {exports: {}}, Buffer, require: denied, fetch: denied,
    setTimeout: denied, process: new Proxy({}, {get: denied})};
  vm.runInNewContext(fs.readFileSync(file, 'utf8'), context, {timeout: 1000});
  assert.equal(context.module.exports.parseOffline(JSON.stringify(success())).result, 'SUCCESS');
  assert.throws(() => context.module.exports.validateForLivePublication(success()),
    /info_live_provenance_not_proven/);
  assert.deepEqual(Object.keys(api).sort(),
    ['MAX_BYTES', 'parseOffline', 'validateForLivePublication', 'validateOffline']);
});
