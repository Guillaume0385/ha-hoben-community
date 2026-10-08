// Load only from the workflow's exact protected-main checkout, never PR code.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const policy = require('../config/hoben-boundary.json');
const repository = 'Guillaume0385/ha-hoben-community';
const manager = 'Guillaume0385';
const workflow = '.github/workflows/hoben-boundary-request.yml';
const labels = { 'manager-hoben-boundary-dry-run': 'dry-run',
  'manager-hoben-boundary-live': 'live' };
const phases = ['dry-run', 'live'];
const checks = ['tests', 'ha-tests', 'hacs', 'hassfest'];
const runUrl = id => `https://github.com/${repository}/actions/runs/${id}`;
const statusName = (phase, main) => `hoben-boundary-${phase}/${main}`;
const claimName = (phase, main) =>
  `hoben-boundary-${phase}-${main}-${policy.candidate_sha}`;
const refusals = new Set(['unauthenticated_request', 'unapproved_scenario',
  'invalid_recipient', 'expired_recipient', 'stale_or_unprotected_main',
  'changed_candidate_or_state', 'independent_review_missing_or_changed',
  'changes_requested', 'unresolved_review', 'unverifiable_review',
  'offline_ci_missing_or_failed', 'unverifiable_ci', 'environment_policy_unverified',
  'concurrent_live_request', 'dry_run_required', 'invalid_claim',
  'duplicate_or_unrecordable_request', 'github_or_configuration_unavailable']);
class Refusal extends Error {}
const requireFact = (fact, reason) => { if (!fact) throw new Refusal(reason); };

function request(context) {
  const event = context.payload;
  const pr = event.pull_request;
  const phase = labels[event.label?.name];
  requireFact(context.eventName === 'pull_request_target' &&
    event.action === 'labeled' && phases.includes(phase) &&
    context.ref === 'refs/heads/main' && context.actor === manager &&
    event.sender?.login === manager && event.sender?.id === 18246624 &&
    event.sender?.type === 'User' &&
    `${context.repo.owner}/${context.repo.repo}` === repository &&
    event.repository?.full_name === repository &&
    event.repository?.id === 1401398724 && event.repository?.default_branch === 'main' &&
    process.env.GITHUB_TRIGGERING_ACTOR === manager &&
    process.env.GITHUB_RUN_ATTEMPT === '1' &&
    process.env.GITHUB_WORKFLOW_REF === `${repository}/${workflow}@refs/heads/main` &&
    process.env.GITHUB_WORKFLOW_SHA === context.sha &&
    /^[0-9a-f]{40}$/.test(context.sha) && Number.isSafeInteger(context.runId) &&
    context.runId > 0 && pr?.number === 49 && pr.state === 'open' &&
    pr.draft === true && pr.head?.sha === policy.candidate_sha &&
    pr.head?.ref === 'codex/issue-48' && pr.head.repo?.full_name === repository &&
    pr.base?.ref === 'main' && pr.base.repo?.full_name === repository,
  'unauthenticated_request');
  requireFact(policy.scenario === 'h1h2' &&
    /^[0-9a-f]{40}$/.test(policy.candidate_sha), 'unapproved_scenario');
  return phase;
}

function recipient() {
  const file = path.join(__dirname, '../config/hoben-capture-recipient.pem');
  requireFact(fs.lstatSync(file).isFile() && !fs.lstatSync(file).isSymbolicLink(),
    'invalid_recipient');
  const pem = fs.readFileSync(file, 'utf8');
  requireFact(pem.length <= 16384 && !pem.includes('PRIVATE KEY') &&
    (pem.match(/BEGIN CERTIFICATE/g) || []).length === 1, 'invalid_recipient');
  const certificate = new crypto.X509Certificate(pem);
  requireFact(crypto.createHash('sha256').update(certificate.raw).digest('hex') ===
    policy.recipient_sha256 && certificate.publicKey.asymmetricKeyType === 'rsa' &&
    certificate.publicKey.asymmetricKeyDetails.modulusLength >= 3072,
  'invalid_recipient');
  requireFact(Date.parse(certificate.validFrom) <= Date.now() &&
    Date.parse(certificate.validTo) >= Date.now() + 3600000, 'expired_recipient');
}

async function claim(github, context, phase) {
  const { data: ref } = await github.rest.git.getRef({
    ...context.repo, ref: `tags/${claimName(phase, context.sha)}` });
  requireFact(ref.object.type === 'tag', 'invalid_claim');
  const { data: tag } = await github.rest.git.getTag({
    ...context.repo, tag_sha: ref.object.sha });
  const stamp = JSON.parse(tag.message);
  requireFact(tag.object.type === 'commit' && tag.object.sha === context.sha &&
    stamp.schema === 1 && stamp.scenario === 'h1h2' && stamp.phase === phase &&
    stamp.main_sha === context.sha && stamp.candidate_sha === policy.candidate_sha &&
    Number.isSafeInteger(stamp.run_id) && stamp.run_id > 0, 'invalid_claim');
  return stamp;
}

async function verify({ github, context, core, recheck = false }) {
  try {
    const phase = request(context);
    core.setOutput('recognized', 'true');
    core.setOutput('phase', phase);
    core.setOutput('sha', policy.candidate_sha);
    core.setOutput('reason', 'refused');
    recipient();
    const api = context.repo;
    const { data: repo } = await github.rest.repos.get(api);
    const { data: branch } = await github.rest.repos.getBranch({ ...api, branch: 'main' });
    requireFact(repo.default_branch === 'main' && branch.protected === true &&
      branch.commit.sha === context.sha, 'stale_or_unprotected_main');
    const { data: current } = await github.rest.pulls.get({ ...api, pull_number: 49 });
    const { data: issue } = await github.rest.issues.get({ ...api, issue_number: 48 });
    const state = issue.labels.filter(l => l.name.startsWith('state:'));
    requireFact(current.state === 'open' && current.draft === true &&
      current.head.sha === policy.candidate_sha && current.head.ref === 'codex/issue-48' &&
      current.head.repo?.full_name === repository && current.base.ref === 'main' &&
      current.base.repo?.full_name === repository &&
      current.labels.filter(l => Object.hasOwn(labels, l.name)).length === 1 &&
      current.labels.some(l => labels[l.name] === phase) &&
      issue.state === 'open' && !issue.pull_request && state.length === 1 &&
      state[0].name === 'state:blocked', 'changed_candidate_or_state');

    // Main attests the precise independent-role decision already recorded in
    // review 5452887287. COMMENTED is deliberate, not GitHub APPROVED. No text
    // parser, role claim in a comment, label or candidate file grants approval.
    const reviews = await github.paginate(github.rest.pulls.listReviews,
      { ...api, pull_number: 49, per_page: 100 });
    const review = reviews.find(r => r.id === policy.review.id);
    requireFact(review?.commit_id === policy.candidate_sha &&
      review.state === policy.review.state && review.user.login === policy.review.actor &&
      review.user.id === policy.review.actor_id &&
      crypto.createHash('sha256').update(review.body).digest('hex') ===
        policy.review.body_sha256, 'independent_review_missing_or_changed');
    // The API returns reviews chronologically. Only a submitted APPROVED or
    // CHANGES_REQUESTED decision supersedes that reviewer's active decision.
    // COMMENTED/PENDING are non-decisional. A dismissed record is inactive;
    // ignoring it removes only that record, never another blocking review.
    const effectiveReviews = new Map();
    for (const r of reviews) {
      if (r.state === 'APPROVED' || r.state === 'CHANGES_REQUESTED') {
        effectiveReviews.set(r.user.id, r.state);
      }
    }
    requireFact(![...effectiveReviews.values()].includes('CHANGES_REQUESTED'),
      'changes_requested');
    let cursor = null;
    do {
      const response = await github.graphql(`query($owner:String!, $name:String!, $cursor:String) {
        repository(owner:$owner, name:$name) { pullRequest(number:49) {
          reviewThreads(first:100, after:$cursor) {
            nodes { isResolved } pageInfo { hasNextPage endCursor }
          }
        } }
      }`, { owner: api.owner, name: api.repo, cursor });
      const threads = response.repository.pullRequest.reviewThreads;
      requireFact(threads.nodes.every(t => t.isResolved === true), 'unresolved_review');
      cursor = threads.pageInfo.hasNextPage ? threads.pageInfo.endCursor : null;
      requireFact(!threads.pageInfo.hasNextPage || typeof cursor === 'string',
        'unverifiable_review');
    } while (cursor);

    const runs = await github.paginate(github.rest.checks.listForRef,
      { ...api, ref: policy.candidate_sha, filter: 'latest', per_page: 100 });
    const selected = checks.map(name => runs.find(r => r.name === name));
    requireFact(selected.every(r => r?.app?.slug === 'github-actions' &&
      r.head_sha === policy.candidate_sha && r.status === 'completed' &&
      r.conclusion === 'success'), 'offline_ci_missing_or_failed');
    const ids = selected.map(r => r.details_url.match(
      /^https:\/\/github\.com\/Guillaume0385\/ha-hoben-community\/actions\/runs\/(\d+)\/job\/\d+$/
    )?.[1]);
    requireFact(ids.every(id => id && id === ids[0]), 'unverifiable_ci');
    const { data: ci } = await github.rest.actions.getWorkflowRun({ ...api, run_id: Number(ids[0]) });
    requireFact(ci.path === '.github/workflows/validate.yml' &&
      ci.event === 'pull_request' && ci.head_sha === policy.candidate_sha &&
      ci.status === 'completed' && ci.conclusion === 'success', 'unverifiable_ci');

    const { data: environment } = await github.rest.repos.getEnvironment({
      ...api, environment_name: 'hoben-live' });
    const branches = await github.paginate(github.rest.repos.listDeploymentBranchPolicies,
      { ...api, environment_name: 'hoben-live', per_page: 100 });
    requireFact(environment.name === 'hoben-live' &&
      environment.deployment_branch_policy?.custom_branch_policies === true &&
      environment.deployment_branch_policy.protected_branches === false &&
      branches.length === 1 && branches[0].name === 'main' && branches[0].type === 'branch',
    'environment_policy_unverified');
    const livePaths = ['opened-client-boundary.yml', 'manager-live-hoben.yml',
      'live-validation.yml', 'hoben-boundary-request.yml'];
    for (const status of ['queued', 'in_progress', 'waiting', 'pending', 'requested']) {
      const active = await github.paginate(github.rest.actions.listWorkflowRunsForRepo,
        { ...api, status, per_page: 100 });
      requireFact(!active.some(r => r.id !== context.runId &&
        livePaths.some(file => r.path === `.github/workflows/${file}`)), 'concurrent_live_request');
    }
    if (phase === 'live') {
      let stamp;
      try { stamp = await claim(github, context, 'dry-run'); }
      catch { throw new Refusal('dry_run_required'); }
      const { data: dry } = await github.rest.actions.getWorkflowRun({ ...api, run_id: stamp.run_id });
      const jobs = await github.paginate(github.rest.actions.listJobsForWorkflowRun,
        { ...api, run_id: stamp.run_id, filter: 'latest', per_page: 100 });
      requireFact(dry.path === workflow && dry.event === 'pull_request_target' &&
        dry.head_sha === context.sha && dry.run_attempt === 1 &&
        dry.actor?.login === manager && dry.triggering_actor?.login === manager &&
        dry.status === 'completed' && dry.conclusion === 'success' &&
        ['request', 'dry-run', 'publish'].every(name => jobs.some(j =>
          j.name === name && j.status === 'completed' && j.conclusion === 'success')) &&
        jobs.some(j => j.name === 'observations' && j.conclusion === 'skipped'),
      'dry_run_required');
    }
    if (recheck) {
      requireFact(phase === 'live' && (await claim(github, context, phase)).run_id ===
        context.runId, 'invalid_claim');
    } else {
      // Creating a new ref is atomic; never update/delete it or reuse a failed
      // claim. A lost API response fails closed. Main/candidate changes require
      // fresh reviewed governance and a new dry-run; labels cannot reset this.
      const name = claimName(phase, context.sha);
      const { data: tag } = await github.rest.git.createTag({ ...api, tag: name,
        message: JSON.stringify({ schema: 1, scenario: 'h1h2', phase,
          main_sha: context.sha, candidate_sha: policy.candidate_sha, run_id: context.runId }),
        object: context.sha, type: 'commit' });
      try { await github.rest.git.createRef({ ...api, ref: `refs/tags/${name}`, sha: tag.sha }); }
      catch { throw new Refusal('duplicate_or_unrecordable_request'); }
      core.setOutput('claimed', 'true');
      await github.rest.repos.createCommitStatus({ ...api, sha: policy.candidate_sha,
        state: 'pending', context: statusName(phase, context.sha),
        target_url: runUrl(context.runId), description: `H1/H2 ${phase}: accepted request` });
    }
    core.setOutput('approved', 'true');
    core.setOutput('reason', 'accepted');
  } catch (error) {
    const reason = error instanceof Refusal ? error.message : 'github_or_configuration_unavailable';
    core.setOutput('reason', reason);
    core.setFailed(`Hoben boundary request refused: ${reason}. No live permission granted.`);
  }
}

async function publish({ github, context, core }) {
  try {
    const phase = request(context);
    const success = process.env.BOUNDARY_JOB_RESULT === 'success';
    // Fresh runner, trusted main only: no candidate code, capture artifact or
    // Hoben secret. Revalidate the separate public JSON before any write token
    // publishes counts; never quote arbitrary strings, exceptions or raw data.
    let observation = '';
    let verified = false;
    if (success && process.env.BOUNDARY_APPROVED === 'true') {
      try { observation = publicReport(context, phase); verified = true; }
      catch { /* Failed/missing report cannot produce a successful status. */ }
    }
    const result = process.env.BOUNDARY_APPROVED === 'true'
      ? (success && verified ? (phase === 'dry-run' ? 'dry_run_pass' : 'inconclusive') : 'failure')
      : 'refused';
    const reason = result === 'inconclusive' ? 'hypotheses_unproven'
      : result === 'dry_run_pass' ? 'no_hoben_connection'
      : result === 'failure' ? 'job_or_report_failed_or_incomplete'
      : refusals.has(process.env.BOUNDARY_GATE_REASON) ? process.env.BOUNDARY_GATE_REASON : 'gate_refused';
    if (process.env.BOUNDARY_CLAIMED === 'true') {
      requireFact((await claim(github, context, phase)).run_id === context.runId, 'invalid_claim');
      await github.rest.repos.createCommitStatus({ ...context.repo, sha: policy.candidate_sha,
        state: success && verified && process.env.BOUNDARY_APPROVED === 'true' ? 'success' : 'failure',
        context: statusName(phase, context.sha), target_url: runUrl(context.runId),
        description: `H1/H2 ${phase}: ${result}; ${reason}` });
    }
    const body = `H1/H2 MANAGER request: ${phase}; result: ${result}; reason: ${reason}.\n` +
        `Scenario: h1h2; candidate: ${policy.candidate_sha}; main: ${context.sha}.\n` +
        `Run: ${runUrl(context.runId)}\n${observation}\n` +
        'Refs #48. Boundary remains unproven; no merge approval.';
    await github.rest.issues.createComment({ ...context.repo, issue_number: 49, body });
    if (core.summary) await core.summary.addRaw(body).write();
    core.info(`H1/H2 ${phase}: ${result}; ${runUrl(context.runId)}`);
    requireFact(!success || verified || process.env.BOUNDARY_APPROVED !== 'true',
      'invalid_public_report');
  } catch { core.setFailed('Unable to publish verified boundary request result.'); }
}

function publicReport(context, phase) {
  const file = path.join(process.env.GITHUB_WORKSPACE, 'public-report/report.json');
  const stat = fs.lstatSync(file);
  requireFact(stat.isFile() && !stat.isSymbolicLink() && stat.size <= 65536,
    'invalid_public_report');
  const r = JSON.parse(fs.readFileSync(file, 'utf8'));
  requireFact(r.schema === 1 && r.scenario === 'h1h2' && r.phase === phase &&
    r.main_sha === context.sha && r.candidate_sha === policy.candidate_sha &&
    r.run_id === context.runId && r.boundary_proven === false, 'invalid_public_report');
  if (phase === 'dry-run') {
    requireFact(r.result === 'dry_run_pass' && r.reason === 'no_hoben_connection' &&
      r.executed_sessions === 0, 'invalid_public_report');
    return 'Anonymized report: synthetic encryption passed; Hoben sessions: 0.';
  }
  requireFact(r.result === 'inconclusive' && r.reason === 'hypotheses_unproven' &&
    r.observation_seconds === 90 && r.planned_sessions === 12 &&
    Array.isArray(r.sessions) && r.sessions.length <= 12 &&
    r.executed_sessions === r.sessions.length, 'invalid_public_report');
  const integer = (n, max) => Number.isInteger(n) && n >= 0 && n <= max;
  const stops = new Set(['observation_budget', 'peer_eof', 'pending_response_eof',
    'response_timeout', 'opening_timeout', 'rx_limit', 'authorization_required',
    'opening_rejected', 'unexpected_opening_type', 'unsupported_opening',
    'invalid_opening_prefix', 'unusable_pending_session', 'modbus_exception',
    'invalid_correlation', 'cancelled', 'transport_or_capture_error']);
  const opening = new Set(['missing_opening', 'invalid_opening_offset',
    'incomplete_opening_prefix', 'unsupported_opening', 'unaccepted_opening_prefix',
    'accepted_v4_prefix', 'invalid_opening_prefix']);
  const comparisons = new Set(['compatible_with_both', 'h2_contradicted',
    'neither_model_supported', 'h2_compatible_h1_inconclusive', 'insufficient_data']);
  requireFact(integer(r.eligible_sessions, r.executed_sessions), 'invalid_public_report');
  const rows = r.sessions.map((s, index) => {
    requireFact(s.mode === (index < 6 ? 'H1' : 'H2') &&
      s.pause_seconds === [0, 0.1, 1][Math.floor((index % 6) / 2)] &&
      s.repetition === index % 2 + 1 && stops.has(s.stop) &&
      typeof s.partial === 'boolean' && typeof s.opening_context?.eligible === 'boolean' &&
      opening.has(s.opening_context.status) &&
      s.opening_context.eligible === (s.opening_context.status === 'accepted_v4_prefix') &&
      ['compatible', 'inconclusive'].includes(s.h1_status) &&
      ['compatible', 'contradicted', 'inconclusive'].includes(s.h2_status) &&
      comparisons.has(s.comparison) && integer(s.rx_bytes, 1048576) &&
      integer(s.v4_requests, s.mode === 'H1' ? 0 : 2) &&
      integer(s.correlated_responses, s.v4_requests), 'invalid_public_report');
    return `| ${index + 1} | ${s.mode} | ${s.stop} | ${s.opening_context.status} | ` +
      `${s.h1_status} | ${s.h2_status} | ${s.comparison} | ${s.v4_requests}/${s.correlated_responses} |`;
  });
  requireFact(r.eligible_sessions === r.sessions.filter(s => s.opening_context.eligible).length,
    'invalid_public_report');
  return `Anonymized report: ${r.executed_sessions}/12 sessions; ` +
    `${r.eligible_sessions} eligible.\n\n` +
    '| Session | Mode | Stop | Opening context | H1 | H2 | Comparison | V4 sent/correlated |\n' +
    '| --- | --- | --- | --- | --- | --- | --- | --- |\n' + rows.join('\n');
}
module.exports = { verify, publish };
