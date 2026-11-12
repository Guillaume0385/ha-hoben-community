'use strict';
// #207 D4-B2: deterministic GET-only fixture collector. No HTTP client or credentials.
const {inspect} = require('./ha-live-gate-evidence-offline.cjs');
const API = 'https://api.github.com';
const ROOT = '/repos/Guillaume0385/ha-hoben-community';
const SOURCES = Object.freeze(['branch', 'run', 'prs', 'head_commit', 'merge_commit',
  'reviews', 'ci_run', 'ci_jobs', 'environment', 'deployment', 'approvals',
  'workflow', 'concurrency']);
const PAGED = new Set(['prs', 'reviews', 'ci_jobs', 'approvals', 'concurrency']);
const CONTEXT = ['repository', 'sender', 'actor', 'triggering_actor', 'event', 'ref',
  'sha', 'run_id', 'attempt', 'scenario', 'workflow', 'pr_number', 'pr_head_sha',
  'ci_run_id', 'deployment_id'];
const MAX_PAGES = 8;
const MAX_REQUESTS = 24;
const MAX_RESPONSE_BYTES = 24 * 1024;
const MAX_FIXTURE_BYTES = 65536;
const REQUEST_TIMEOUT_MS = 350;
const TOTAL_TIMEOUT_MS = 5000;
const fail = () => { throw Error('ha_live_offline_transport_refused'); };
const need = condition => { if (!condition) fail(); };
const positive = value => Number.isSafeInteger(value) && value > 0;
const sha = value => typeof value === 'string' && /^[a-f0-9]{40}$/.test(value);
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
function fields(value, expected) {
  need(object(value) && Object.keys(value).sort().join('|') === [...expected].sort().join('|'));
}
// Reject accessors, non-JSON primitives, cycles, sensitive keys and oversized input
// before copying; error strings never include material from mock replies.
function safeCopy(value, limit = MAX_FIXTURE_BYTES) {
  const seen = new Set();
  let nodes = 0;
  function walk(v, depth) {
    need(++nodes <= 3000 && depth <= 14);
    if (v === null || typeof v === 'boolean') return;
    if (typeof v === 'number') { need(Number.isSafeInteger(v)); return; }
    if (typeof v === 'string') { need(v.length <= 2048); return; }
    need(typeof v === 'object' && !seen.has(v));
    need(Array.isArray(v) || [Object.prototype, null].includes(Object.getPrototypeOf(v)));
    need(Object.getOwnPropertySymbols(v).length === 0);
    seen.add(v);
    for (const [key, descriptor] of Object.entries(Object.getOwnPropertyDescriptors(v))) {
      need(!['__proto__', 'prototype', 'constructor'].includes(key) &&
        !/(?:secret|token|guid|password|authorization)/i.test(key) &&
        Object.hasOwn(descriptor, 'value'));
      walk(descriptor.value, depth + 1);
    }
    seen.delete(v);
  }
  walk(value, 0);
  const json = JSON.stringify(value);
  need(typeof json === 'string' && Buffer.byteLength(json) <= limit);
  return JSON.parse(json);
}
function validateContext(raw) {
  const c = safeCopy(raw);
  fields(c, CONTEXT);
  fields(c.repository, ['id', 'full_name']);
  need(c.repository.id === 1401398724 && c.repository.full_name === 'Guillaume0385/ha-hoben-community');
  for (const who of ['sender', 'actor', 'triggering_actor']) {
    fields(c[who], ['id', 'login', 'type']);
    need(c[who].id === 18246624 && c[who].login === 'Guillaume0385' && c[who].type === 'User');
  }
  need(c.event === 'workflow_dispatch' && c.ref === 'refs/heads/experimental' &&
    c.attempt === 1 && c.scenario === 'hoben-live' &&
    c.workflow === '.github/workflows/hoben-ha-manual.yml' &&
    sha(c.sha) && sha(c.pr_head_sha) && positive(c.run_id) &&
    positive(c.pr_number) && positive(c.ci_run_id) && positive(c.deployment_id));
  return c;
}
function route(name, c) {
  const routes = {
    branch: `${ROOT}/branches/experimental`,
    run: `${ROOT}/actions/runs/${c.run_id}`,
    prs: `${ROOT}/commits/${c.sha}/pulls`,
    head_commit: `${ROOT}/commits/${c.pr_head_sha}`,
    merge_commit: `${ROOT}/commits/${c.sha}`,
    reviews: `${ROOT}/pulls/${c.pr_number}/reviews`,
    ci_run: `${ROOT}/actions/runs/${c.ci_run_id}`,
    ci_jobs: `${ROOT}/actions/runs/${c.ci_run_id}/jobs`,
    environment: `${ROOT}/environments/hoben-live`,
    deployment: `${ROOT}/deployments/${c.deployment_id}`,
    approvals: `${ROOT}/actions/runs/${c.run_id}/approvals`,
    workflow: `${ROOT}/contents/.github/workflows/hoben-ha-manual.yml?ref=${c.sha}`,
    concurrency: `${ROOT}/actions/runs`,
  };
  return routes[name];
}
function pagePath(name, context, page) {
  const base = route(name, context);
  return PAGED.has(name)
    ? `${base}${base.includes('?') ? '&' : '?'}per_page=100&page=${page}`
    : base;
}
function freeze(value) {
  if (value && typeof value === 'object') {
    Object.values(value).forEach(freeze);
    Object.freeze(value);
  }
  return value;
}
async function get(mockTransport, path, signal, remainingMs) {
  need(remainingMs > 0 && !signal?.aborted);
  const controller = new AbortController();
  let timer;
  let listener;
  const timeout = Math.min(REQUEST_TIMEOUT_MS, remainingMs);
  // A hostile fake may ignore AbortSignal. Race it so collection still stops.
  try {
    const pending = Promise.resolve().then(() => mockTransport.request(Object.freeze({
      method: 'GET', url: API + path, signal: controller.signal,
    })));
    const expiry = new Promise((_, reject) => {
      timer = setTimeout(() => { controller.abort(); reject(Error('timeout')); }, timeout);
    });
    const cancelled = new Promise((_, reject) => {
      listener = () => { controller.abort(); reject(Error('cancelled')); };
      signal?.addEventListener('abort', listener, {once: true});
      if (signal?.aborted) listener();
    });
    return await Promise.race([pending, expiry, cancelled]);
  } finally {
    clearTimeout(timer);
    if (listener) signal?.removeEventListener('abort', listener);
  }
}
function parseResponse(raw, name, path, page, now, context) {
  const r = safeCopy(raw, MAX_RESPONSE_BYTES);
  fields(r, ['status', 'headers', 'body']);
  need(r.status === 200); // redirects and all HTTP failures are terminal
  need(object(r.headers));
  for (const key of Object.keys(r.headers))
    need(['date', 'content-type', 'link'].includes(key));
  need(r.headers['content-type'] === 'application/json' &&
    typeof r.headers.date === 'string' &&
    /^\w{3}, \d{2} \w{3} \d{4} \d{2}:\d{2}:\d{2} GMT$/.test(r.headers.date));
  const at = Date.parse(r.headers.date);
  need(Number.isSafeInteger(at) && new Date(at).toUTCString() === r.headers.date &&
    at <= now && now - at <= 30000);
  const list = PAGED.has(name);
  const items = list ? r.body : [r.body];
  need(Array.isArray(items) && items.length > 0 && items.length <= (list ? 100 : 1));
  for (const item of items) need(object(item));
  const nextPath = pagePath(name, context, page + 1);
  const next = r.headers.link === undefined ? null : nextPath;
  if (next !== null) {
    need(list && page < MAX_PAGES &&
      r.headers.link === `<${API}${nextPath}>; rel="next"`);
  }
  // A full page without Link is ambiguous: never silently truncate.
  if (list && items.length === 100) need(next !== null);
  return {request:path, status:200, items, next};
}
async function collect(options) {
  try {
    const {mockTransport, context, now, signal} = options || {};
    need(object(mockTransport) && typeof mockTransport.request === 'function' &&
      Number.isSafeInteger(now) && now >= 0 &&
      (signal === undefined || (signal && typeof signal.aborted === 'boolean' &&
        typeof signal.addEventListener === 'function' &&
        typeof signal.removeEventListener === 'function')));
    const c = validateContext(context);
    const started = Date.now();
    let requests = 0;
    const sources = {};
    for (const name of SOURCES) {
      const pages = [];
      const seen = new Set();
      for (let page = 1; page <= MAX_PAGES; page++) {
        need(++requests <= MAX_REQUESTS);
        const path = pagePath(name, c, page);
        const raw = await get(mockTransport, path, signal, TOTAL_TIMEOUT_MS - (Date.now() - started));
        const record = parseResponse(raw, name, path, page, now, c);
        for (const item of record.items) {
          const id = name === 'prs' ? item.number : item.id;
          if (PAGED.has(name)) {
            need(positive(id) && !seen.has(id));
            seen.add(id);
          }
        }
        pages.push(record);
        if (record.next === null) break;
        need(page < MAX_PAGES);
      }
      need(pages.length > 0 && pages.at(-1).next === null);
      sources[name] = {pages};
    }
    const fixture = safeCopy({execution:'offline', observed_at:now, context:c, sources});
    // Reuse D4-B1 as a second, independent semantic verifier. It never attests
    // fixture provenance or opens live admission, even for plausible responses.
    const evidence = inspect(fixture, now);
    return freeze({execution:'offline', admission:'NOT RUN', secrets_allowed:false,
      live_ready:false, fixture, evidence});
  } catch (_) { fail(); }
}
module.exports = Object.freeze({collect});
