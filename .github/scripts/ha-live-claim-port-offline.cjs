'use strict';
// #207 D4-C2: offline-only, injected atomic-create port. No GitHub client or live gate.
const CONTRACT = 'hoben-207-ha-live-admission-v1';
const REPO = 'Guillaume0385/ha-hoben-community';
const REF = 'refs/heads/experimental';
const SHA = /^[0-9a-f]{40}$/;
const MAX_CLAIMS = 64;
const denied = () => {throw Error('ha_live_claim_port_offline_refused');};
const need = ok => {if (!ok) denied();};
const positive = n => Number.isSafeInteger(n) && n > 0;
const plain = v => v !== null && typeof v === 'object' && !Array.isArray(v) &&
  [Object.prototype, null].includes(Object.getPrototypeOf(v));

// Copy only bounded, own data properties. Neither caller nor store gets to run
// getters/toJSON or to smuggle arbitrary metadata into an offline claim.
function copy(input) {
  let nodes = 0;
  const seen = new Set();
  function visit(value, depth) {
    need(++nodes <= 96 && depth <= 5);
    if (value === null || typeof value === 'boolean') return value;
    if (typeof value === 'number') {need(Number.isSafeInteger(value));return value;}
    if (typeof value === 'string') {need(value.length <= 256);return value;}
    need(plain(value) && !seen.has(value) && Object.getOwnPropertySymbols(value).length === 0);
    seen.add(value);
    const out = {};
    for (const [key, descriptor] of Object.entries(Object.getOwnPropertyDescriptors(value))) {
      need(!['__proto__', 'constructor', 'prototype'].includes(key) && key.length <= 64 &&
        !/(?:secret|token|guid|password|authorization)/i.test(key) &&
        Object.hasOwn(descriptor, 'value'));
      out[key] = visit(descriptor.value, depth + 1);
    }
    seen.delete(value);
    return out;
  }
  const result = visit(input, 0);
  need(Buffer.byteLength(JSON.stringify(result)) <= 2048);
  return result;
}
function exact(value, names) {
  need(plain(value) && Object.keys(value).sort().join('|') === [...names].sort().join('|'));
}
function request(input) {
  const v = copy(input);
  exact(v, ['repository', 'ref', 'sha', 'contract', 'run_id', 'attempt']);
  exact(v.repository, ['id', 'full_name']);
  need(v.repository.id === 1401398724 && v.repository.full_name === REPO &&
    v.ref === REF && typeof v.sha === 'string' && SHA.test(v.sha) &&
    v.contract === CONTRACT && positive(v.run_id) && v.attempt === 1);
  return v;
}
function metadata(input) {
  const value = copy(input);
  exact(value, ['repository', 'ref', 'sha', 'contract', 'run_id', 'attempt', 'version']);
  need(value.version === 1);
  const {version, ...context} = value;
  request(context);
  return value;
}
function keyOf(value) {return `${CONTRACT}:${value.sha}`;}
function same(a, b) {return JSON.stringify(a) === JSON.stringify(b);}
function options(raw) {
  need(plain(raw));
  need(Object.keys(raw).every(k => k === 'timeoutMs' || k === 'signal'));
  const timeoutMs = raw.timeoutMs === undefined ? 1000 : raw.timeoutMs;
  const signal = raw.signal;
  need(Number.isSafeInteger(timeoutMs) && timeoutMs >= 1 && timeoutMs <= 5000);
  need(signal === undefined || signal instanceof AbortSignal);
  return {timeoutMs, signal};
}
async function bounded(operation, remaining, signal) {
  need(remaining > 0 && !(signal?.aborted));
  let timer, onAbort;
  try {
    return await Promise.race([
      Promise.resolve().then(operation),
      new Promise((_, reject) => {
        timer = setTimeout(() => reject(Error('timeout')), remaining);
        if (signal) {
          onAbort = () => reject(Error('aborted'));
          signal.addEventListener('abort', onAbort, {once: true});
          if (signal.aborted) onAbort();
        }
      }),
    ]);
  } finally {
    clearTimeout(timer);
    if (signal && onAbort) signal.removeEventListener('abort', onAbort);
  }
}

class OfflineClaimPort {
  #store;
  #attempted = new Set();
  constructor(store) {this.#store = store;}
  async reserve(input, rawOptions = {}) {
    try {
      const v = request(input);
      const {timeoutMs, signal} = options(rawOptions);
      const key = keyOf(v);
      need(!this.#attempted.has(key) && this.#attempted.size < MAX_CLAIMS);
      // An uncertain result burns the local attempt. Never retry the write,
      // release a claim, or resolve ambiguity using a second write.
      this.#attempted.add(key);
      need(typeof this.#store?.createIfAbsent === 'function' &&
        typeof this.#store?.lookup === 'function' && !signal?.aborted);
      const expected = {...v, version: 1};
      const deadline = Date.now() + timeoutMs;
      const ack = copy(await bounded(
        () => this.#store.createIfAbsent({key, metadata: copy(expected)}),
        deadline - Date.now(), signal));
      exact(ack, ['created', 'key', 'metadata']);
      need(ack.created === true && ack.key === key && same(metadata(ack.metadata), expected));
      // Readback rejects a lying/missing ACK in the test store; neither ACK nor
      // readback establishes real GitHub atomicity, persistence or permission.
      const read = copy(await bounded(
        () => this.#store.lookup({key}), deadline - Date.now(), signal));
      exact(read, ['found', 'key', 'metadata']);
      need(read.found === true && read.key === key && same(metadata(read.metadata), expected));
      return Object.freeze({schema: 1, execution: 'offline', simulation: 'RESERVED_ONLY',
        admission: 'NOT RUN', complete: false, secrets_allowed: false, live_ready: false});
    } catch (_) {denied();}
  }
}

class SharedMockClaimStore {
  #records = new Map();
  get size() {return this.#records.size;}
  // Check and insert are synchronous with no await between them, even when
  // several independent OfflineClaimPort instances call concurrently.
  async createIfAbsent(input) {
    const v = copy(input);
    exact(v, ['key', 'metadata']);
    const record = metadata(v.metadata);
    need(v.key === keyOf(record));
    if (this.#records.has(v.key)) return {created: false};
    need(this.#records.size < MAX_CLAIMS);
    this.#records.set(v.key, record);
    return {created: true, key: v.key, metadata: copy(record)};
  }
  async lookup(input) {
    const v = copy(input);
    exact(v, ['key']);
    need(typeof v.key === 'string' && v.key.startsWith(`${CONTRACT}:`) &&
      SHA.test(v.key.slice(CONTRACT.length + 1)));
    if (!this.#records.has(v.key)) return {found: false};
    return {found: true, key: v.key, metadata: copy(this.#records.get(v.key))};
  }
}
module.exports = Object.freeze({CONTRACT, OfflineClaimPort, SharedMockClaimStore});
