'use strict';
// #207 D4-D: authenticated GET port and fail-closed live preflight. No live grant.
// A mock source is never an authoritative claim, approval or policy.
const API = 'https://api.github.com';
const ROOT = '/repos/Guillaume0385/ha-hoben-community';
const SHA = /^[0-9a-f]{40}$/;
const OWNER = Object.freeze({id:18246624, login:'Guillaume0385'});
const deny = () => {throw Error('ha_live_d4_security_refused');};
const need = condition => {if (!condition) deny();};
const isObject = x => x !== null && typeof x === 'object' && !Array.isArray(x);
const positive = x => Number.isSafeInteger(x) && x > 0;
const paths = Object.freeze([
  `${ROOT}/branches/experimental`,
  `${ROOT}/branches/experimental/protection`,
  `${ROOT}/environments/hoben-live`,
  `${ROOT}/rulesets?includes_parents=true`,
]);
function clean(value, max = 24576) {
  let count = 0;
  const seen = new Set();
  function walk(v, depth) {
    need(++count <= 2500 && depth <= 12);
    if (v === null || typeof v === 'boolean') return;
    if (typeof v === 'string') {need(v.length <= 8192);return;}
    if (typeof v === 'number') {need(Number.isSafeInteger(v));return;}
    need((Array.isArray(v) || isObject(v)) && !seen.has(v));
    need([Object.prototype, Array.prototype, null].includes(Object.getPrototypeOf(v)));
    seen.add(v);
    for (const [k,d] of Object.entries(Object.getOwnPropertyDescriptors(v))) {
      need(Object.hasOwn(d,'value') && !['__proto__','prototype','constructor'].includes(k) &&
        !/(secret|token|password|guid|authorization)/i.test(k));
      walk(d.value,depth+1);
    }
    need(Object.getOwnPropertySymbols(v).length === 0);
    seen.delete(v);
  }
  walk(value,0);
  const raw = JSON.stringify(value);
  need(typeof raw === 'string' && Buffer.byteLength(raw) <= max);
  return JSON.parse(raw);
}
function context(raw) {
  const c = clean(raw,4096);
  need(isObject(c) && Object.keys(c).sort().join('|') === [
    'actor','attempt','event','ref','repository','run_id','scenario',
    'sha','triggering_actor','workflow',
  ].sort().join('|'));
  need(c.repository === 'Guillaume0385/ha-hoben-community' &&
    c.actor === OWNER.login && c.triggering_actor === OWNER.login &&
    c.event === 'workflow_dispatch' && c.ref === 'refs/heads/experimental' &&
    c.scenario === 'hoben-live' && c.workflow === '.github/workflows/hoben-ha-manual.yml' &&
    typeof c.sha === 'string' && SHA.test(c.sha) && positive(c.run_id) && c.attempt === 1);
  return Object.freeze(c);
}
function fetchPort({token, fetchImpl = globalThis.fetch} = {}) {
  need(typeof token === 'string' && /^\S{10,256}$/.test(token) &&
    typeof fetchImpl === 'function');
  // The token is stored only in a closure; not returned or included in errors.
  return Object.freeze({
    async get(path, {signal} = {}) {
      try {
        need(paths.includes(path) && !(signal?.aborted));
        const response = await fetchImpl(API + path, {
          method:'GET',
          redirect:'manual',
          signal,
          headers: Object.freeze({
            Accept:'application/vnd.github+json',
            Authorization:`Bearer ${token}`,
            'X-GitHub-Api-Version':'2022-11-28',
          }),
        });
        need(response && response.status === 200 && response.redirected !== true);
        need(response.headers.get('content-type')?.toLowerCase().startsWith('application/json'));
        const length = response.headers.get('content-length');
        need(length === null || (/^\d{1,5}$/.test(length) && Number(length) <= 24576));
        const data = await response.text();
        need(Buffer.byteLength(data) <= 24576);
        return clean(JSON.parse(data));
      } catch (_) {deny();}
    },
  });
}
function policy(branch, protection, environment, rulesets, c) {
  need(isObject(branch) && branch.name === 'experimental' &&
    branch.protected === true && branch.commit?.sha === c.sha);
  // protected:true alone is not branch-protection evidence.
  need(isObject(protection) && isObject(protection.required_pull_request_reviews) &&
    positive(protection.required_pull_request_reviews.required_approving_review_count) &&
    protection.required_pull_request_reviews.dismiss_stale_reviews === true &&
    protection.required_pull_request_reviews.require_code_owner_reviews === true);
  need(isObject(environment) && environment.name === 'hoben-live' &&
    environment.prevent_self_review === true && environment.can_admins_bypass === false &&
    Array.isArray(environment.protection_rules));
  const rules = environment.protection_rules.filter(x => x?.type === 'required_reviewers');
  need(rules.length === 1 && Array.isArray(rules[0].reviewers) &&
    rules[0].reviewers.length > 0 && rules[0].reviewers.length <= 6);
  need(rules[0].reviewers.some(x => x.type === 'User' &&
    positive(x.reviewer?.id) && x.reviewer.id !== OWNER.id));
  need(environment.deployment_branch_policy?.protected_branches === false &&
    environment.deployment_branch_policy?.custom_branch_policies === true);
  // No ruleset, unknown enforcement, bypass or an unverifiable tag ref => refused.
  need(Array.isArray(rulesets) && rulesets.length > 0);
  need(rulesets.every(r => r?.enforcement === 'active' &&
    Array.isArray(r.bypass_actors) && r.bypass_actors.length === 0));
  // A list endpoint cannot certify protections on an individual claim ref.
  // The eventual indelible-claim provider needs its own separately reviewed proof.
  deny();
}
async function preflight({rawContext, port, now = Date.now()} = {}) {
  try {
    const c = context(rawContext);
    need(port && typeof port.get === 'function' &&
      Number.isSafeInteger(now) && now > 0);
    // No call can be skipped: 403, 400, missing path, invalid response or
    // incomplete provenance all fail with one constant, non-sensitive category.
    const [branch, protection, environment, rulesets] = await Promise.all(
      paths.map(path => port.get(path)));
    policy(clean(branch),clean(protection),clean(environment),clean(rulesets),c);
  } catch (_) {deny();}
}
function refusedResult() {
  return Object.freeze({schema:1,execution:'NOT RUN',admission:'NOT RUN',
    complete:false,secrets_allowed:false,live_ready:false,reason:'evidence_unverifiable'});
}
module.exports = Object.freeze({context,fetchPort,preflight,refusedResult});
