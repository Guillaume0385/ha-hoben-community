'use strict';
// #207 D4-B1. A pure parser for *mocked* GitHub REST replies, never a live gate.
const REPO = 'Guillaume0385/ha-hoben-community';
const ROOT = `/repos/${REPO}`;
const SHA = /^[a-f0-9]{40}$/;
const CHECKS = ['tests', 'ha-tests', 'hacs', 'hassfest'];
const NAMES = ['branch', 'run', 'prs', 'trees', 'review', 'ci', 'environment', 'workflow', 'concurrency'];
const SOURCE_NAMES = ['branch', 'run', 'prs', 'head_commit', 'merge_commit', 'reviews',
  'ci_run', 'ci_jobs', 'environment', 'deployment', 'approvals', 'workflow', 'concurrency'];
const denied = () => { throw Error('ha_live_offline_evidence_refused'); };
const deepFreeze = value => {
  if (value !== null && typeof value === 'object') {
    for (const item of Object.values(value)) deepFreeze(item);
    Object.freeze(value);
  }
  return value;
};
const need = condition => { if (!condition) denied(); };
const integer = n => Number.isSafeInteger(n) && n > 0;
const hash = s => typeof s === 'string' && SHA.test(s);
const plain = v => v !== null && typeof v === 'object' && !Array.isArray(v);
const exact = (v, fields) => {
  need(plain(v) && Object.keys(v).sort().join('|') === [...fields].sort().join('|'));
};
const copy = input => {
  let nodes = 0;
  const seen = new Set();
  function walk(value, depth) {
    need(++nodes <= 3000 && depth <= 14);
    if (value === null || typeof value === 'boolean') return;
    if (typeof value === 'string') { need(value.length <= 2048); return; }
    if (typeof value === 'number') { need(Number.isSafeInteger(value)); return; }
    need(typeof value === 'object' && !seen.has(value));
    need(Array.isArray(value) || [Object.prototype, null].includes(Object.getPrototypeOf(value)));
    need(Object.getOwnPropertySymbols(value).length === 0);
    seen.add(value);
    for (const [key, descriptor] of Object.entries(Object.getOwnPropertyDescriptors(value))) {
      need(!['__proto__', 'constructor', 'prototype'].includes(key) &&
        !/(?:secret|token|guid|password|authorization)/i.test(key) && Object.hasOwn(descriptor, 'value'));
      walk(descriptor.value, depth + 1);
    }
    seen.delete(value);
  }
  walk(input, 0);
  const json = JSON.stringify(input);
  need(Buffer.byteLength(json) <= 65536);
  return JSON.parse(json);
};
const endpoint = (name, context) => {
  const pr = context.pr_number;
  const routes = {
    branch: `${ROOT}/branches/experimental`, run: `${ROOT}/actions/runs/${context.run_id}`,
    prs: `${ROOT}/commits/${context.sha}/pulls`,
    head_commit: `${ROOT}/commits/${context.pr_head_sha}`,
    merge_commit: `${ROOT}/commits/${context.sha}`,
    reviews: `${ROOT}/pulls/${pr}/reviews`,
    ci_run: `${ROOT}/actions/runs/${context.ci_run_id}`,
    ci_jobs: `${ROOT}/actions/runs/${context.ci_run_id}/jobs`,
    environment: `${ROOT}/environments/hoben-live`,
    deployment: `${ROOT}/deployments/${context.deployment_id}`,
    approvals: `${ROOT}/actions/runs/${context.run_id}/approvals`,
    workflow: `${ROOT}/contents/.github/workflows/hoben-ha-manual.yml?ref=${context.sha}`,
    concurrency: `${ROOT}/actions/runs`,
  };
  return routes[name];
};
function source(sources, name, context, list = false) {
  const entry = sources[name];
  exact(entry, ['pages']);
  need(Array.isArray(entry.pages) && entry.pages.length > 0 && entry.pages.length <= 8);
  const route = endpoint(name, context);
  const result = [];
  for (const [index, page] of entry.pages.entries()) {
    exact(page, ['request', 'status', 'items', 'next']);
    const request = list ? `${route}${route.includes('?') ? '&' : '?'}per_page=100&page=${index + 1}` : route;
    need(page.request === request && page.status === 200 && Array.isArray(page.items));
    need(page.items.length > 0 && page.items.length <= (list ? 100 : 1));
    const next = index + 1 < entry.pages.length
      ? `${route}${route.includes('?') ? '&' : '?'}per_page=100&page=${index + 2}` : null;
    need(page.next === next);
    result.push(...page.items);
  }
  need(list || (entry.pages.length === 1 && result.length === 1));
  return list ? result : result[0];
}
function identity(person, owner = false) {
  need(plain(person) && integer(person.id) && typeof person.login === 'string' &&
    /^[a-zA-Z0-9-]{1,39}$/.test(person.login) && person.type === 'User');
  if (owner) need(person.id === 18246624 && person.login === 'Guillaume0385');
  return {id:person.id, login:person.login, type:person.type};
}
function repository(repo, requireOwner = false) {
  need(plain(repo) && repo.id === 1401398724 && repo.full_name === REPO &&
    (!requireOwner || plain(repo.owner)));
  if (repo.owner !== undefined) identity(repo.owner, true);
  return {id:repo.id, full_name:repo.full_name};
}
function millis(value) {
  need(typeof value === 'string' && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,3})?Z$/.test(value));
  const result = Date.parse(value);
  need(Number.isSafeInteger(result) && new Date(result).toISOString().startsWith(value.slice(0,19)));
  return result;
}
function inspect(input, now) {
  try {
    const raw = copy(input);
    exact(raw, ['execution', 'observed_at', 'context', 'sources']);
    need(raw.execution === 'offline' && Number.isSafeInteger(now) && now >= 0 &&
      Number.isSafeInteger(raw.observed_at) && raw.observed_at <= now && now - raw.observed_at <= 30000);
    const c = raw.context;
    exact(c, ['repository', 'sender', 'actor', 'triggering_actor', 'event', 'ref', 'sha', 'run_id',
      'attempt', 'scenario', 'workflow', 'pr_number', 'pr_head_sha', 'ci_run_id', 'deployment_id']);
    const repo = repository(c.repository);
    identity(c.sender, true);identity(c.actor, true);identity(c.triggering_actor, true);
    need(c.event === 'workflow_dispatch' && c.ref === 'refs/heads/experimental' &&
      hash(c.sha) && hash(c.pr_head_sha) && integer(c.run_id) && c.attempt === 1 &&
      integer(c.pr_number) && integer(c.ci_run_id) && integer(c.deployment_id) &&
      c.scenario === 'hoben-live' && c.workflow === '.github/workflows/hoben-ha-manual.yml');
    exact(raw.sources, SOURCE_NAMES);
    const read = (key, list = false) => source(raw.sources, key, c, list);
    const branch = read('branch');
    need(branch.name === 'experimental' && branch.protected === true && branch.commit?.sha === c.sha);
    const run = read('run');
    need(run.id === c.run_id && run.run_attempt === 1 && run.event === c.event &&
      run.head_sha === c.sha && run.head_branch === 'experimental' && run.path === c.workflow);
    repository(run.repository, true);repository(run.head_repository, true);
    const actor = identity(run.actor, true), triggered = identity(run.triggering_actor, true);
    need(actor.id === c.actor.id && triggered.id === c.triggering_actor.id);
    const prs = read('prs', true);
    need(prs.length === 1);
    const pr = prs[0];
    need(pr.number === c.pr_number && pr.merged === true && pr.state === 'closed' &&
      pr.draft === false && pr.head?.sha === c.pr_head_sha &&
      pr.base?.ref === 'experimental' && pr.merge_commit_sha === c.sha &&
      pr.merged_by?.id === c.actor.id);
    repository(pr.head.repo, true);repository(pr.base.repo, true);
    identity(pr.merged_by, true);
    need(millis(pr.merged_at) <= millis(run.created_at) &&
      millis(run.created_at) <= raw.observed_at);
    const head = read('head_commit'), merge = read('merge_commit');
    need(head.sha === c.pr_head_sha && merge.sha === c.sha &&
      hash(head.commit?.tree?.sha) && head.commit.tree.sha === merge.commit?.tree?.sha);
    const reviews = read('reviews', true);
    need(reviews.every(r => plain(r) && identity(r.user) &&
      ['APPROVED', 'COMMENTED', 'CHANGES_REQUESTED', 'DISMISSED'].includes(r.state)));
    // GitHub review/comment metadata cannot, on its own, attest the separate
    // immutable MANAGER decision with exact CI + unresolved-thread binding.
    const ci = read('ci_run');
    need(ci.id === c.ci_run_id && ci.head_sha === c.pr_head_sha &&
      ci.event === 'pull_request' && ci.run_attempt === 1 && ci.status === 'completed' &&
      ci.conclusion === 'success' && ci.path === '.github/workflows/validate.yml');
    repository(ci.repository, true);repository(ci.head_repository, true);
    const jobs = read('ci_jobs', true);
    need(jobs.length === 4 && CHECKS.every(name => jobs.filter(j =>
      j.name === name && j.run_id === ci.id && j.head_sha === c.pr_head_sha &&
      j.status === 'completed' && j.conclusion === 'success').length === 1));
    need(millis(ci.updated_at) <= millis(pr.merged_at));
    const env = read('environment');
    need(integer(env.id) && env.name === 'hoben-live' && Array.isArray(env.protection_rules) &&
      env.protection_rules.length > 0 && env.protection_rules.length <= 2 &&
      env.protection_rules.every(r => ['required_reviewers', 'wait_timer'].includes(r.type)) &&
      env.protection_rules.some(r => r.type === 'required_reviewers'));
    const rr = env.protection_rules.find(r => r.type === 'required_reviewers');
    need(Array.isArray(rr.reviewers) && rr.reviewers.length > 0 && rr.reviewers.length <= 6);
    const reviewers = rr.reviewers.map(r => identity(r.reviewer));
    need(new Set(reviewers.map(r=>r.id)).size === reviewers.length &&
      reviewers.some(r => r.id !== actor.id));
    need(env.prevent_self_review === true && env.can_admins_bypass === false &&
      env.deployment_branch_policy?.protected_branches === false &&
      env.deployment_branch_policy?.custom_branch_policies === true);
    // A deployment status and a review list are not an approval linked to
    // this exact deployment, run, attempt and environment.
    const deployment = read('deployment');
    need(deployment.id === c.deployment_id && deployment.environment === 'hoben-live' &&
      deployment.sha === c.sha && deployment.ref === 'experimental');
    const approvals = read('approvals', true);
    need(approvals.length === 1);
    const approval = approvals[0];
    const approver = identity(approval.user);
    need(approval.state === 'approved' && approval.deployment_id === deployment.id &&
      approval.environment_id === env.id && approval.run_id === run.id &&
      approval.attempt === 1 && approval.sha === c.sha &&
      approver.id !== actor.id && reviewers.some(r => r.id === approver.id) &&
      millis(approval.submitted_at) >= millis(run.created_at) &&
      millis(approval.submitted_at) <= raw.observed_at);
    const wf = read('workflow');
    need(wf.path === c.workflow && hash(wf.sha) && typeof wf.content === 'string' &&
      wf.encoding === 'base64');
    const concurrent = read('concurrency', true);
    need(concurrent.every(r => plain(r) && integer(r.id)));
    // A paginated read is not an atomic claim/mutex; YAML bytes are not a
    // verified future preflight/recheck ordering. Neither is asserted here.
    const facts = {
      branch:{name:'experimental',protected:true,sha:c.sha},
      run:{id:run.id,event:run.event,attempt:run.run_attempt,sha:run.head_sha,branch:run.head_branch,
        repository:repo,head_repository:repo,actor,triggering_actor:triggered,path:run.path,created_at:millis(run.created_at)},
      prs:[{number:pr.number,head_sha:pr.head.sha,merge_sha:pr.merge_commit_sha,base_ref:pr.base.ref}],
      trees:{head_sha:head.sha,head_tree:head.commit.tree.sha,merge_sha:merge.sha,merge_tree:merge.commit.tree.sha},
      review:null,
      ci:{id:ci.id,head_sha:ci.head_sha,attempt:ci.run_attempt,checks:[...CHECKS]},
      environment:{id:env.id,name:env.name,reviewers},
      workflow:null,
      concurrency:null,
    };
    // All source material is untrusted offline fixture data. In particular,
    // NEVER promote fixture pagination to authenticated proof.complete:true.
    const proofs = Object.fromEntries(NAMES.map(name => [name,
      {status:200,complete:false,data:facts[name]}]));
    return deepFreeze({execution:'offline',admission:'NOT RUN',secrets_allowed:false,
      live_ready:false,proofs:copy(proofs)});
  } catch (_) { denied(); }
}
function requireAttested(result) {
  try {
    const v = copy(result);
    need(v.execution === 'offline' && v.admission === 'NOT RUN' &&
      v.secrets_allowed === false && v.live_ready === false);
    exact(v.proofs,NAMES);
    for (const name of NAMES) need(v.proofs[name].complete === true);
  } catch (_) { denied(); }
  // D4-B1 has no authenticated API collection, so no admission output exists.
  denied();
}
module.exports=Object.freeze({inspect,requireAttested});
