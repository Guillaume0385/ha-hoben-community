"use strict";
const test = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), os = require('node:os');
const crypto = require('node:crypto');
const route = require('../../.github/scripts/info-manual-route.cjs');
const report = require('../../.github/scripts/info-manual-report.cjs');
const gate = require('../../.github/scripts/manual-hoben-gate.cjs');
const root = path.resolve(__dirname, '../..');
const sha = 'a'.repeat(40);
const copy = v => JSON.parse(JSON.stringify(v));
const hash = text => crypto.createHash('sha256').update(text).digest('hex');
const snapshot = () => ({manifest: JSON.parse(fs.readFileSync(path.join(root, route.MANIFEST))),
  files: Object.fromEntries(route.FILES.map(f => [f, fs.readFileSync(path.join(root, f), 'utf8')]))});
function remote() {
  const s = snapshot(); s.reads = [];
  s.context = {sha, ref: 'refs/heads/experimental'};
  s.github = {rest: {repos: {getContent: async q => {
    assert.equal(q.owner, 'Guillaume0385'); assert.equal(q.repo, 'ha-hoben-community');
    assert.equal(q.ref, sha); s.reads.push(q);
    if (s.apiError) throw Error('PRIVATE_API_EXCEPTION');
    const text = q.path === route.MANIFEST ? JSON.stringify(s.manifest) : s.files[q.path];
    return {data: {type: 'file', path: q.path, size: Buffer.byteLength(text),
      encoding: 'base64', content: Buffer.from(text).toString('base64'), ...s.response}};
  }}}};
  return s;
}

test('reviewed sources connect the passive route but are not runtime attestation', async () => {
  const s = remote();
  const result = await route.inspect(s);
  assert.equal(result.ready, true);
  assert.equal(result.status, 'CONNECTED FOR PASSIVE OBSERVATION');
  assert.deepEqual(result.policy, route.POLICY);
  assert.deepEqual(result, route.local(root));
  assert.deepEqual(s.reads.map(q => q.path), [route.MANIFEST, ...route.FILES]);
  assert.deepEqual(await route.requireConnected(s), result);
});
for (const proof of ['ready', 'proven', 'isolated_fixture', true, 1, {}, null]) {
  test('a manifest value is never a live proof: '+JSON.stringify(proof), async () => {
    const s = remote(); s.manifest.policy.continuation = proof;
    await assert.rejects(() => route.inspect(s));
    await assert.rejects(() => route.requireConnected({...s, ready: true, allowLive: true}));
  });
}
for (const file of route.FILES) test('reviewed file hash is required: '+file, async () => {
  const s = remote(); s.files[file] += '\n';
  await assert.rejects(() => route.inspect(s));
  // Updating a hash does not turn source integrity into live attestation.
  s.manifest.files[file] = hash(s.files[file]);
  if (file === '.github/workflows/hoben-ha-manual.yml') await assert.rejects(() => route.inspect(s));
  else assert.equal((await route.inspect(s)).ready, true); // Integrity alone is not admission.
});
for (const mutation of [
  s => {s.manifest.extra = 'PRIVATE';}, s => {s.manifest.files['/tmp/arbitrary'] = 'a'.repeat(64);},
  s => {s.manifest.files['https://private.invalid'] = 'a'.repeat(64);},
  s => {s.manifest.proofs = {};}, s => {s.manifest.limits.total_ms = 3600001;},
  s => {s.manifest.limits.cleanup_ms = 59999;}, s => {s.manifest.environment = 'hoben-live';},
  s => {s.manifest.selection = 'all';}, s => {s.manifest.schema = 1;},
  s => {s.context.ref = 'refs/heads/main';}, s => {s.context.sha = 'not-a-sha';},
  s => {s.apiError = true;}, s => {s.response = {type: 'symlink'};},
  s => {s.response = {path: '/tmp/private'};}, s => {s.response = {size: 262145};},
  s => {s.response = {content: 'not base64!'};}, s => {s.response = {encoding: 'utf8'};},
  s => {s.response = {content: Buffer.from([255]).toString('base64'), size: 1};},
]) test('remote metadata, policy or private input tampering refuses', async () => {
  const s = remote(); mutation(s);
  await assert.rejects(() => route.requireConnected(s), {message: 'manual_info_route_not_connected'});
  assert.ok(s.reads.every(q => [route.MANIFEST, ...route.FILES].includes(q.path)));
});

test('NOT RUN report never attests an observation, connection, cleanup or live success', () => {
  const r = report.notRun();
  assert.deepEqual(report.decode(JSON.stringify(r)), r);
  assert.equal(r.mode, 'readiness'); assert.equal(r.result, 'NOT RUN');
  assert.equal(r.observation_started, false); assert.equal(r.connection_started, false);
  assert.equal(r.cleanup_attested, false); assert.equal(r.process_reap, 'not_proven');
  assert.equal(r.live_provenance, 'not_proven'); assert.equal(r.boundary_proven, false);
  assert.equal(r.info_framing, 'INCONCLUSIVE');
  assert.ok(Buffer.byteLength(JSON.stringify(r)) < 8192);
});
for (const [key, value] of [
  ['schema', 2], ['mode', 'live'], ['mode', 'offline'], ['result', 'SUCCESS'],
  ['result', 'INCONCLUSIVE'], ['result', 'FAILURE'], ['readiness', 'READY'],
  ['observation_started', true], ['connection_started', true], ['cleanup_attested', true],
  ['process_reap', 'proven'], ['live_provenance', true], ['boundary_proven', true],
  ['info_framing', 'PROVEN'], ['blockers', []], ['private', 'PRIVATE_GUID_RX_PAYLOAD'],
  ['pid', 123], ['path', '/tmp/private'], ['exception', 'PRIVATE_TRACE'],
  ['selection', 'all'], ['scenario', 'ha-live'],
]) test('closed report refuses '+key+'='+JSON.stringify(value), () => {
  const r = report.notRun(); r[key] = value;
  assert.throws(() => report.validate(r), {message: 'invalid_info_readiness_report'});
});
for (const key of Object.keys(report.notRun())) test('report omission refuses: '+key, () => {
  const r = report.notRun(); delete r[key]; assert.throws(() => report.validate(r));
});
test('size cap and offline-to-live substitution remain closed', () => {
  assert.throws(() => report.decode(' '.repeat(8193)));
  assert.throws(() => report.decode(JSON.stringify({schema: 1, mode: 'offline', result: 'SUCCESS'})));
  const d1 = require('../../.github/scripts/info-delivery-manual-report.cjs');
  assert.throws(() => d1.validateForLivePublication(report.notRun()));
});
test('public artifact is fixed, private, exclusive and contains no raw candidate data', () => {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'info-readiness-'));
  try {
    const r = report.writeNotRun(temp), folder = path.join(temp, 'hoben-info-readiness');
    const file = path.join(folder, 'report.json');
    assert.deepEqual(JSON.parse(fs.readFileSync(file)), r);
    assert.equal(fs.statSync(file).mode & 0o777, 0o600);
    assert.equal(fs.statSync(folder).mode & 0o777, 0o700);
    assert.throws(() => report.writeNotRun(temp));
    assert.throws(() => report.writeNotRun('relative'));
    assert.ok(!/PRIVATE|stdout|stderr|payload|header|guid|trace|pid|path/i.test(fs.readFileSync(file, 'utf8')));
  } finally { fs.rmSync(temp, {recursive: true, force: true}); }
});
test('summary cannot turn publication success into functional SUCCESS', async () => {
  let raw = '', failures = [], table;
  const core = {setFailed: s => failures.push(s), summary: {
    addHeading() {return this;}, addTable(v) {table = v; return this;},
    addRaw(v) {raw += v; return this;}, async write() {}}};
  await report.summarize({core, report: report.notRun()});
  assert.ok(table.some(row => row[1] === 'NOT RUN'));
  assert.ok(raw.includes('pas') || raw.includes('jamais'));
  assert.deepEqual(failures, ['NOT RUN: manual_info_route_not_connected']);
  failures = []; const fake = report.notRun(); fake.result = 'SUCCESS';
  await assert.rejects(() => report.summarize({core, report: fake}));
  assert.deepEqual(failures, []);
});

// This real gate path is already exhaustively exercised by manual-hoben.test.
// Admission still requires owner, environment, review, CI and one-use claims.
test('gate has no live override or source-integrity-only success', () => {
  assert.deepEqual(gate.CHOICES, ['h1h2', 'session-300', 'session-reconnect', 'all', 'hoben-live']);
  assert.equal(Object.hasOwn(gate, 'enableInfo'), false);
  const m = snapshot();
  for (const value of [true, 'ready', 'proven']) {
    const altered = copy(m.manifest); altered.ready = value;
    assert.throws(() => route.assess(altered, m.files));
  }
});

test('Info route refuses a second secret even after source hash is repinned', async () => {
  const s=remote(),file='.github/workflows/hoben-manual.yml';
  const old='        HOBEN_USER_GUID: ${{ secrets.HOBEN_USER_GUID }}'+String.fromCharCode(10);
  assert.ok(s.files[file].includes(old));
  s.files[file]=s.files[file].replace(old,old+
    '        HOBEN_DEVICE_GUID: ${{ secrets.HOBEN_DEVICE_GUID }}'+String.fromCharCode(10));
  s.manifest.files[file]=hash(s.files[file]);
  await assert.rejects(() => route.inspect(s),
    {message:'manual_info_route_not_connected'});
});
