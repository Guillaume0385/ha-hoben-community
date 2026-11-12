'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {OfflineClaimPort, SharedMockClaimStore, CONTRACT} = require('../../.github/scripts/ha-live-claim-port-offline.cjs');
const A = 'a'.repeat(40), B = 'b'.repeat(40);
const base = Object.freeze({repository: {id: 1401398724, full_name: 'Guillaume0385/ha-hoben-community'}, ref: 'refs/heads/experimental', sha: A, contract: CONTRACT, run_id: 101, attempt: 1});
const clone = v => structuredClone(v);
const refused = async promise => assert.rejects(promise, e => e instanceof Error && e.message === 'ha_live_claim_port_offline_refused');

test('two independent ports race on one shared atomic mock: exactly one simulated reservation', async () => {
  const shared = new SharedMockClaimStore();
  const ports = Array.from({length: 32}, () => new OfflineClaimPort(shared));
  const results = await Promise.allSettled(ports.map((p, i) => p.reserve({...clone(base), run_id: i + 1})));
  assert.equal(results.filter(x => x.status === 'fulfilled').length, 1);
  assert.equal(results.filter(x => x.status === 'rejected').length, 31);
  assert.equal(shared.size, 1);
  const accepted = results.find(x => x.status === 'fulfilled').value;
  assert.deepEqual(accepted, {schema: 1, execution: 'offline', simulation: 'RESERVED_ONLY', admission: 'NOT RUN', complete: false, secrets_allowed: false, live_ready: false});
  assert.equal(Object.isFrozen(accepted), true);
});

test('SHA/contract scoped replay is refused across runs and fresh ports', async () => {
  const shared = new SharedMockClaimStore();
  const first = new OfflineClaimPort(shared);
  await first.reserve(clone(base));
  await refused(first.reserve(clone(base)));
  await refused(new OfflineClaimPort(shared).reserve({...clone(base), run_id: 999}));
  await refused(new OfflineClaimPort(shared).reserve({...clone(base), attempt: 2}));
  const different = await new OfflineClaimPort(shared).reserve({...clone(base), sha: B});
  assert.equal(different.live_ready, false);
  assert.equal(shared.size, 2);
});

test('invalid identities, refs, SHA, run, attempt, contract and extra/private keys refuse before store', async () => {
  let calls = 0;
  const store = {createIfAbsent: async () => {calls++; throw Error('PRIVATE_TOKEN');}, lookup: async () => {calls++; return null;}};
  const bad = [
    v => {v.repository.id = 1;}, v => {v.repository.full_name = 'other/repo';},
    v => {v.ref = 'refs/heads/main';}, v => {v.ref = 'refs/tags/offline';},
    v => {v.sha = B.toUpperCase();}, v => {v.sha = 'xyz';},
    v => {v.contract = 'other-contract';}, v => {v.run_id = 0;},
    v => {v.run_id = '101';}, v => {v.attempt = 2;},
    v => {v.secret = 'PRIVATE_TOKEN';}, v => {v.repository.device_guid = 'PRIVATE_TOKEN';},
    v => {v.branch = 'experimental';}, v => {v.contract = 'x'.repeat(65536);},
    v => {v.repository = null;}, v => {v.repository = Object.create({id: 1401398724});},
  ];
  for(const change of bad) {const input = clone(base);change(input);await refused(new OfflineClaimPort(store).reserve(input));}
  assert.equal(calls, 0);
});

test('store response lies or conflicts: no simulated success, no automatic retry', async () => {
  for(const output of [
    {created: true, key: 'wrong', metadata: {}},
    {created: false},
    {created: true},
    {created: true, key: 'hoben-207-ha-live-admission-v1:' + A, metadata: {...clone(base), run_id: 99, version: 1}},
    {created: true, key: 'hoben-207-ha-live-admission-v1:' + A, metadata: {...clone(base), version: 1}, secret: 'PRIVATE_TOKEN'},
    null, 'created',
  ]) {
    let count = 0;
    const store = {createIfAbsent: async () => {count++;return output;}, lookup: async () => {count++;return null;}};
    const port = new OfflineClaimPort(store);
    await refused(port.reserve(clone(base)));
    await refused(port.reserve(clone(base)));
    assert.equal(count, 1);
  }
});

test('false successful ACK without actual persistence refuses', async () => {
  const key = 'hoben-207-ha-live-admission-v1:' + A;
  const metadata = {...clone(base), version: 1};
  let calls = 0;
  const store = {createIfAbsent: async () => {calls++;return {created:true,key,metadata};}, lookup: async () => {calls++;return {found:false};}};
  await refused(new OfflineClaimPort(store).reserve(clone(base)));
  assert.equal(calls, 2);
});

test('readback mismatch/extra keys or false readback never authorizes', async () => {
  for(const lookup of [null, {found:false}, {found:true,key:'other',metadata:{}}, {found:true,key:'hoben-207-ha-live-admission-v1:' + A,metadata:{...clone(base),version:1,extra:'PRIVATE_TOKEN'}}]){
    const store = new SharedMockClaimStore();
    const adapter = {createIfAbsent: v => store.createIfAbsent(v), lookup: async () => lookup};
    await refused(new OfflineClaimPort(adapter).reserve(clone(base)));
    assert.equal(store.size,1);
    await refused(new OfflineClaimPort(adapter).reserve({...clone(base),run_id:102}));
  }
});

test('persist-then-throw ambiguous crash refuses and tombstone prevents replay between instances', async () => {
  const backing = new SharedMockClaimStore();
  const adapter = {createIfAbsent: async value => {await backing.createIfAbsent(value);throw Error('PRIVATE_TOKEN');}, lookup: value => backing.lookup(value)};
  const port = new OfflineClaimPort(adapter);
  await refused(port.reserve(clone(base)));
  await refused(port.reserve(clone(base)));
  await refused(new OfflineClaimPort(backing).reserve({...clone(base),run_id:102}));
  assert.equal(backing.size,1);
});

test('timeout and abort refuse, no replay after a late store completion', async () => {
  const backing = new SharedMockClaimStore();
  let release;
  const gate = new Promise(resolve => {release = resolve;});
  const delayed = {createIfAbsent: async v => {await gate;return backing.createIfAbsent(v);}, lookup: v => backing.lookup(v)};
  const port = new OfflineClaimPort(delayed);
  await refused(port.reserve(clone(base), {timeoutMs: 10}));
  await refused(port.reserve(clone(base)));
  release();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(backing.size,1);
  await refused(new OfflineClaimPort(backing).reserve({...clone(base),run_id:103}));
  const ac = new AbortController(); ac.abort();
  await refused(new OfflineClaimPort(new SharedMockClaimStore()).reserve(clone(base), {signal: ac.signal}));
  const controller = new AbortController();
  const late = new OfflineClaimPort({createIfAbsent: () => new Promise(() => {}), lookup: () => {throw Error('NEVER');}});
  const pending = late.reserve(clone(base), {signal: controller.signal, timeoutMs: 1000});
  controller.abort(); await refused(pending);
  await refused(late.reserve(clone(base)));
});

test('strict options and malformed/adversarial store implementations fail closed', async () => {
  const stores = [null, {}, {createIfAbsent: ()=>true}, {lookup: ()=>null},
    {createIfAbsent: async () => {throw Error('PRIVATE_TOKEN');},lookup: async () => null},
    {createIfAbsent: async () => new Promise(() => {}),lookup: async () => null}];
  for(const store of stores){const port = new OfflineClaimPort(store);await refused(port.reserve(clone(base),{timeoutMs:10}));}
  for(const opts of [{timeoutMs:0},{timeoutMs:5001},{timeoutMs:NaN},{timeoutMs:1.5},{unknown:true},{signal:{aborted:false}},null]){
    await refused(new OfflineClaimPort(new SharedMockClaimStore()).reserve(clone(base),opts));
  }
  const payload = clone(base);
  Object.defineProperty(payload,'getter',{enumerable:true,get(){throw Error('PRIVATE_TOKEN');}});
  await refused(new OfflineClaimPort(new SharedMockClaimStore()).reserve(payload));
  const circular = clone(base);circular.cycle=circular;
  await refused(new OfflineClaimPort(new SharedMockClaimStore()).reserve(circular));
});

test('store rejects capacity; immutable snapshots do not depend on mutated caller data', async () => {
  const store = new SharedMockClaimStore();
  const input = clone(base), port = new OfflineClaimPort(store);
  await port.reserve(input);input.sha = B;input.run_id = 88;
  await refused(new OfflineClaimPort(store).reserve(clone(base)));
  for(let i=1;i<64;i++) {
    await new OfflineClaimPort(store).reserve({...clone(base), sha: i.toString(16).padStart(40,'0')});
  }
  assert.equal(store.size,64);
  await refused(new OfflineClaimPort(store).reserve({...clone(base),sha:B}));
});

test('no GitHub API, mutation/release, live approval or tokens are exposed', () => {
  const api = require('../../.github/scripts/ha-live-claim-port-offline.cjs');
  assert.deepEqual(Object.keys(api).sort(), ['CONTRACT','OfflineClaimPort','SharedMockClaimStore'].sort());
  const mock = new SharedMockClaimStore();
  assert.equal(mock.release, undefined);assert.equal(mock.delete, undefined);
  assert.equal(mock.overwrite, undefined);assert.equal(mock.clear, undefined);
  assert.equal(api.verify, undefined);assert.equal(api.main, undefined);
});
