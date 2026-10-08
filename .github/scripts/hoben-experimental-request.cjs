// Trusted default-branch gate for #54. Never load this module from experimental.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const os = require('node:os');
const child = require('node:child_process');
const policy = require('../config/hoben-experimental.json');
const repository = 'Guillaume0385/ha-hoben-community';
const manager = 'Guillaume0385';
const managerId = 18246624;
const workflow = '.github/workflows/hoben-experimental-request.yml';
const marker = '<!-- hoben-experimental-decision:v1 -->\n';
const labels = {'manager-hoben-experimental-dry-run':'dry-run',
  'manager-hoben-experimental-live':'live'};
const shaPattern = /^[0-9a-f]{40}$/;
const positive = n => Number.isSafeInteger(n) && n > 0;
const digest = s => crypto.createHash('sha256').update(s).digest('hex');
const runUrl = id => 'https://github.com/' + repository + '/actions/runs/' + id;
const claimName = (phase, sha) => 'hoben-experimental-' + phase + '-h1h2-' + sha;
const statusName = phase => 'hoben-experimental/h1h2/' + phase;
const owner = u => u?.login === manager && u.id === managerId && u.type === 'User';
class Refusal extends Error {}
const requireFact = (fact, reason) => { if (!fact) throw new Refusal(reason); };

function request(context) {
  const e = context.payload;
  const phase = labels[e.label?.name];
  requireFact(context.eventName === 'issues' && e.action === 'labeled' &&
    ['dry-run','live'].includes(phase) && context.ref === 'refs/heads/main' &&
    context.actor === manager && owner(e.sender) &&
    context.repo.owner + '/' + context.repo.repo === repository &&
    e.repository?.full_name === repository && e.repository.id === 1401398724 &&
    e.repository.default_branch === 'main' && e.issue?.number === policy.tracking_issue &&
    e.issue.id === policy.tracking_issue_id && !e.issue.pull_request &&
    e.issue.state === 'open' && process.env.GITHUB_TRIGGERING_ACTOR === manager &&
    process.env.GITHUB_RUN_ATTEMPT === '1' &&
    process.env.GITHUB_WORKFLOW_REF === repository + '/' + workflow + '@refs/heads/main' &&
    process.env.GITHUB_WORKFLOW_SHA === context.sha && shaPattern.test(context.sha) &&
    positive(context.runId) && policy.schema === 1 && policy.scenario === 'h1h2' &&
    policy.environment === 'hoben-experimental', 'unauthenticated_request');
  return phase;
}

function recipient() {
  const file = path.join(__dirname, '../config/hoben-experimental-recipient.pem');
  const st = fs.lstatSync(file);
  const pem = fs.readFileSync(file, 'ascii');
  requireFact(st.isFile() && !st.isSymbolicLink() && st.size <= 16384 &&
    !pem.includes('PRIVATE KEY') &&
    (pem.match(/BEGIN CERTIFICATE/g)||[]).length === 1 &&
    (pem.match(/END CERTIFICATE/g)||[]).length === 1, 'invalid_recipient');
  const cert = new crypto.X509Certificate(pem);
  requireFact(digest(cert.raw) === policy.recipient_sha256 &&
    cert.publicKey.asymmetricKeyType === 'rsa' &&
    cert.publicKey.asymmetricKeyDetails.modulusLength >= 3072 &&
    Date.parse(cert.validFrom) <= Date.now() &&
    Date.parse(cert.validTo) >= Date.now() + 3600000, 'invalid_recipient');
  // Exercise the real CMS cipher before any admission. Only synthetic bytes;
  // the subprocess has no GitHub token, identity, shell or inherited environment.
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hoben-experimental-preflight-'));
  fs.chmodSync(dir, 0o700);
  try {
    fs.writeFileSync(path.join(dir, 'synthetic.json'), '{"purpose":"no_hoben"}',
      {mode:0o600,flag:'wx'});
    child.execFileSync('/usr/bin/openssl', ['cms','-encrypt','-binary','-aes-256-gcm',
      '-outform','DER','-in',path.join(dir,'synthetic.json'),'-out',path.join(dir,'sealed.cms'),
      '-recip',file,'-keyopt','rsa_padding_mode:oaep','-keyopt','rsa_oaep_md:sha256'],
    {env:{PATH:'/usr/bin:/bin'},stdio:['ignore','pipe','ignore'],timeout:30000});
    requireFact(fs.statSync(path.join(dir,'sealed.cms')).size > 0, 'invalid_recipient');
  } finally { fs.rmSync(dir,{recursive:true,force:true}); }
}

async function decision(github, context, phase, currentRun) {
  const comments = await github.paginate(github.rest.issues.listComments,
    {...context.repo,issue_number:policy.tracking_issue,per_page:100});
  const records = comments.filter(c => owner(c.user) && c.body?.startsWith(marker));
  const c = records.sort((a,b) => a.id-b.id).at(-1);
  requireFact(c && positive(c.id) && c.body.length <= 2048 &&
    c.created_at === c.updated_at, 'manager_decision_missing_or_changed');
  let r;
  try { r = JSON.parse(c.body.slice(marker.length)); }
  catch { throw new Refusal('manager_decision_missing_or_changed'); }
  const fields = ['schema','phase','scenario','main_sha','experimental_sha',
    'pull_request','decision','recipient_sha256'];
  requireFact(r && Object.keys(r).sort().join() === fields.sort().join() &&
    r.schema === 1 && r.phase === phase && r.scenario === 'h1h2' &&
    r.decision === 'reviewed-read-only' && r.main_sha === context.sha &&
    shaPattern.test(r.experimental_sha) && positive(r.pull_request) &&
    r.recipient_sha256 === policy.recipient_sha256,
  'manager_decision_missing_or_changed');
  const events = await github.paginate(github.rest.issues.listEvents,
    {...context.repo,issue_number:policy.tracking_issue,per_page:100});
  const labelEvent = events.filter(e => Object.hasOwn(labels,e.label?.name))
    .sort((a,b)=>a.id-b.id).at(-1);
  requireFact(labelEvent?.event === 'labeled' && labelEvent.label.name === context.payload.label.name &&
    positive(labelEvent.id) && owner(labelEvent.actor) &&
    labelEvent.created_at === context.payload.issue.updated_at &&
    Number.isFinite(Date.parse(c.created_at)) &&
    Date.parse(c.created_at) <= Date.parse(labelEvent.created_at) &&
    Date.parse(labelEvent.created_at) <= Date.parse(currentRun.created_at) &&
    Date.parse(currentRun.created_at) - Date.parse(c.created_at) <= 3600000,
  'label_or_decision_not_fresh');
  return {...r,comment_id:c.id,comment_digest:digest(c.body),
    label_event_id:labelEvent.id,decision_time:c.created_at};
}

async function claim(github, api, phase, candidate) {
  const {data:ref} = await github.rest.git.getRef({...api,
    ref:'tags/'+claimName(phase,candidate)});
  requireFact(ref.object.type === 'tag','invalid_claim');
  const {data:tag} = await github.rest.git.getTag({...api,tag_sha:ref.object.sha});
  const s = JSON.parse(tag.message);
  requireFact(s.schema === 1 && s.phase === phase && s.scenario === 'h1h2' &&
    s.candidate_sha === candidate && shaPattern.test(s.main_sha) &&
    positive(s.run_id) && positive(s.comment_id) && positive(s.label_event_id) &&
    /^[0-9a-f]{64}$/.test(s.comment_digest) &&
    tag.object.type === 'commit' && tag.object.sha === s.main_sha, 'invalid_claim');
  return s;
}

async function environmentPolicy(github, api) {
  try {
    const {data:env} = await github.rest.repos.getEnvironment({...api,
      environment_name:policy.environment});
    requireFact(env.name === policy.environment && positive(env.id) &&
      env.deployment_branch_policy?.custom_branch_policies === true &&
      env.deployment_branch_policy.protected_branches === false,
    'environment_unverified');
    const policies = await github.paginate(github.rest.repos.listDeploymentBranchPolicies,
      {...api,environment_name:policy.environment,per_page:100});
    requireFact(policies.length === 1 && policies[0].name === 'main' &&
      positive(policies[0].id) && typeof policies[0].node_id === 'string' &&
      policies[0].node_id.length > 0, 'environment_unverified');
    let branch = policies[0];
    // Both REST schemas make type optional. Absence is never positive evidence.
    if (!Object.hasOwn(branch,'type')) {
      const {data:detail} = await github.rest.repos.getDeploymentBranchPolicy({
        ...api,environment_name:policy.environment,branch_policy_id:branch.id});
      requireFact(detail?.id === branch.id && detail.node_id === branch.node_id &&
        detail.name === branch.name, 'environment_unverified');
      branch = detail;
    }
    requireFact(branch.type === 'branch', 'environment_unverified');
    const rules = env.protection_rules;
    requireFact(Array.isArray(rules) && rules.every(r =>
      ['branch_policy','required_reviewers','wait_timer'].includes(r.type)),
    'environment_unverified');
    const required = rules.filter(r=>r.type === 'required_reviewers');
    requireFact(required.length === 1 && required[0].prevent_self_review === true &&
      positive(required[0].id) && Array.isArray(required[0].reviewers) &&
      required[0].reviewers.length > 0 && required[0].reviewers.every(r =>
        r.type === 'User' && r.reviewer?.type === 'User' &&
        positive(r.reviewer.id) && typeof r.reviewer.login === 'string'),
    'independent_environment_approval_unverified');
    // This first implementation supports named user reviewers only, not guessed
    // team membership. Same-actor and admin-bypass records cannot authorize it.
    const reviewers = required[0].reviewers.map(r=>({id:r.reviewer.id,login:r.reviewer.login}))
      .sort((a,b)=>a.id-b.id);
    requireFact(reviewers.some(r=>r.id !== managerId),
      'independent_environment_approval_unverified');
    const snapshot = {id:env.id,name:env.name,updated_at:env.updated_at,
      branch,reviewers,rules:rules.map(r=>({id:r.id,type:r.type,wait_timer:r.wait_timer,
        prevent_self_review:r.prevent_self_review})).sort((a,b)=>a.id-b.id)};
    return {id:env.id,reviewers,digest:digest(JSON.stringify(snapshot))};
  } catch (e) {
    if (e instanceof Refusal) throw e;
    throw new Refusal('environment_unverified');
  }
}

async function actualApproval(github, context, env) {
  const {data:history} = await github.request(
    'GET /repos/{owner}/{repo}/actions/runs/{run_id}/approvals',
    {...context.repo,run_id:context.runId});
  requireFact(Array.isArray(history), 'independent_environment_approval_unverified');
  const relevant = history.filter(r=>r.environments?.some(e =>
    e.id === env.id && e.name === policy.environment));
  requireFact(relevant.length > 0 && relevant.every(r=>r.state === 'approved' &&
    r.user?.type === 'User' && r.user.id !== managerId &&
    env.reviewers.some(u=>u.id === r.user.id && u.login === r.user.login)),
  'independent_environment_approval_unverified');
}

async function reviewsAndCI(github, api, pr) {
  const reviews = await github.paginate(github.rest.pulls.listReviews,
    {...api,pull_number:pr.number,per_page:100});
  const decisions = new Map();
  for (const r of reviews) {
    if (r.state === 'APPROVED' || r.state === 'CHANGES_REQUESTED') decisions.set(r.user.id,r.state);
  }
  requireFact(![...decisions.values()].includes('CHANGES_REQUESTED'),'changes_requested');
  let cursor = null;
  const seen = new Set();
  do {
    const response = await github.graphql(
      'query($owner:String!,$name:String!,$number:Int!,$cursor:String){repository(owner:$owner,name:$name){pullRequest(number:$number){reviewThreads(first:100,after:$cursor){nodes{isResolved}pageInfo{hasNextPage endCursor}}}}}',
      {owner:api.owner,name:api.repo,number:pr.number,cursor});
    const t = response.repository.pullRequest.reviewThreads;
    requireFact(t.nodes.every(n=>n.isResolved === true),'unresolved_review');
    cursor = t.pageInfo.hasNextPage ? t.pageInfo.endCursor : null;
    requireFact(!t.pageInfo.hasNextPage || typeof cursor === 'string' && cursor.length > 0 &&
      !seen.has(cursor),'unverifiable_review');
    seen.add(cursor);
  } while (cursor);
  // The experimental route requires deterministic tests, not an independent
  // CODEX REVIEW approval or the production live/HACS acceptance gate.
  const checks = await github.paginate(github.rest.checks.listForRef,
    {...api,ref:pr.head.sha,filter:'latest',per_page:100});
  const check = checks.find(r=>r.name === 'tests');
  requireFact(check?.app?.slug === 'github-actions' && check.head_sha === pr.head.sha &&
    check.status === 'completed' && check.conclusion === 'success','offline_ci_unverified');
  const match = check.details_url.match(
    /^https:\/\/github\.com\/Guillaume0385\/ha-hoben-community\/actions\/runs\/(\d+)\/job\/\d+$/);
  requireFact(match && positive(Number(match[1])),'offline_ci_unverified');
  const {data:ci} = await github.rest.actions.getWorkflowRun({...api,run_id:Number(match[1])});
  requireFact(ci.path === '.github/workflows/validate.yml' && ci.event === 'pull_request' &&
    ci.head_sha === pr.head.sha && ci.status === 'completed' && ci.conclusion === 'success',
  'offline_ci_unverified');
}

async function verify({github,context,core,recheck=false}) {
  try {
    const phase = request(context);
    core.setOutput('recognized','true');
    core.setOutput('phase',phase);
    recipient();
    const api = context.repo;
    const [{data:repo},{data:main},{data:run},{data:issue}] = await Promise.all([
      github.rest.repos.get(api),github.rest.repos.getBranch({...api,branch:'main'}),
      github.rest.actions.getWorkflowRun({...api,run_id:context.runId}),
      github.rest.issues.get({...api,issue_number:policy.tracking_issue})]);
    requireFact(repo.full_name === repository && repo.id === 1401398724 &&
      repo.default_branch === 'main' && main.protected === true &&
      main.commit.sha === context.sha, 'stale_or_unprotected_main');
    requireFact(run.id === context.runId && run.path === workflow && run.event === 'issues' &&
      run.head_branch === 'main' && run.head_sha === context.sha && run.run_attempt === 1 &&
      owner(run.actor) && owner(run.triggering_actor), 'unauthenticated_request');
    const states = issue.labels.filter(l=>l.name.startsWith('state:'));
    requireFact(issue.id === policy.tracking_issue_id && issue.state === 'open' &&
      !issue.pull_request && states.length === 1 &&
      ['state:review','state:blocked'].includes(states[0].name) &&
      issue.labels.filter(l=>Object.hasOwn(labels,l.name)).length === 1 &&
      issue.labels.some(l=>labels[l.name] === phase), 'tracking_issue_or_label_changed');
    const r = await decision(github,context,phase,run);
    core.setOutput('sha',r.experimental_sha);
    core.setOutput('pr',String(r.pull_request));
    const [{data:experimental},{data:pr}] = await Promise.all([
      github.rest.repos.getBranch({...api,branch:'experimental'}),
      github.rest.pulls.get({...api,pull_number:r.pull_request})]);
    requireFact(experimental.commit.sha === r.experimental_sha && pr.number === r.pull_request &&
      pr.state === 'closed' && pr.merged === true && pr.draft === false &&
      pr.merge_commit_sha === r.experimental_sha && pr.base.ref === 'experimental' &&
      pr.base.repo?.full_name === repository && pr.head.repo?.full_name === repository &&
      owner(pr.merged_by) && shaPattern.test(pr.head.sha) &&
      Number.isFinite(Date.parse(pr.merged_at)) && Date.parse(pr.merged_at) <= Date.parse(r.decision_time),
    'experimental_head_or_review_changed');
    await reviewsAndCI(github,api,pr);
    let env = null;
    if (phase === 'live') env = await environmentPolicy(github,api);
    for (const status of ['queued','in_progress','waiting','pending','requested']) {
      const runs = await github.paginate(github.rest.actions.listWorkflowRunsForRepo,
        {...api,status,per_page:100});
      requireFact(runs.length < 1000 && !runs.some(x=>x.id !== context.runId &&
        ['opened-client-boundary.yml','manager-live-hoben.yml','live-validation.yml',
          'hoben-boundary-request.yml','hoben-experimental-request.yml']
          .some(f=>x.path === '.github/workflows/'+f)), 'concurrent_hoben_run');
    }
    if (phase === 'live') {
      try {
        const dry = await claim(github,api,'dry-run',r.experimental_sha);
        const {data:completed} = await github.rest.actions.getWorkflowRun({...api,run_id:dry.run_id});
        const jobs = await github.paginate(github.rest.actions.listJobsForWorkflowRun,
          {...api,run_id:dry.run_id,filter:'latest',per_page:100});
        const artifacts = await github.paginate(github.rest.actions.listWorkflowRunArtifacts,
          {...api,run_id:dry.run_id,per_page:100});
        const {data:status} = await github.rest.repos.getCombinedStatusForRef({...api,ref:r.experimental_sha});
        requireFact(dry.main_sha === context.sha && dry.pull_request === r.pull_request &&
          completed.id === dry.run_id && completed.path === workflow &&
          completed.event === 'issues' && completed.head_sha === context.sha &&
          completed.head_branch === 'main' &&
          completed.run_attempt === 1 && owner(completed.actor) && owner(completed.triggering_actor) &&
          completed.status === 'completed' && completed.conclusion === 'success' &&
          ['request','dry-run','publish'].every(name=>jobs.some(j=>j.name === name &&
            j.status === 'completed' && j.conclusion === 'success')) &&
          !jobs.some(j=>j.name === 'observations' && j.conclusion !== 'skipped') &&
          artifacts.some(a=>a.name === 'experimental-report-'+r.experimental_sha+'-'+dry.run_id &&
            positive(a.id) && a.expired === false && a.workflow_run?.id === dry.run_id &&
            a.workflow_run.head_sha === context.sha) &&
          status.statuses.find(s=>s.context === statusName('dry-run'))?.state === 'success' &&
          status.statuses.find(s=>s.context === statusName('dry-run')).target_url === runUrl(dry.run_id),
        'dry_run_required');
      } catch { throw new Refusal('dry_run_required'); }
    }
    if (recheck) {
      const s = await claim(github,api,phase,r.experimental_sha);
      requireFact(phase === 'live' && s.run_id === context.runId &&
        s.main_sha === context.sha && s.comment_id === r.comment_id &&
        s.comment_digest === r.comment_digest && s.label_event_id === r.label_event_id &&
        s.environment_digest === env.digest, 'request_changed_after_wait');
      await actualApproval(github,context,env);
    } else {
      const name = claimName(phase,r.experimental_sha);
      const stamp = {schema:1,scenario:'h1h2',phase,main_sha:context.sha,
        candidate_sha:r.experimental_sha,pull_request:r.pull_request,run_id:context.runId,
        comment_id:r.comment_id,comment_digest:r.comment_digest,label_event_id:r.label_event_id,
        environment_digest:env?.digest || null};
      const {data:tag} = await github.rest.git.createTag({...api,tag:name,
        message:JSON.stringify(stamp),object:context.sha,type:'commit'});
      try { await github.rest.git.createRef({...api,ref:'refs/tags/'+name,sha:tag.sha}); }
      catch { throw new Refusal('duplicate_or_unrecordable_request'); }
      core.setOutput('claimed','true');
      await github.rest.repos.createCommitStatus({...api,sha:r.experimental_sha,
        state:'pending',context:statusName(phase),target_url:runUrl(context.runId),
        description:'H1/H2 '+phase+': accepted request'});
    }
    core.setOutput('approved','true');
    core.setOutput('reason','accepted');
  } catch (e) {
    const reason = e instanceof Refusal ? e.message : 'github_or_configuration_unavailable';
    core.setOutput('reason',reason);
    core.setFailed('Hoben experimental request: NOT RUN ('+reason+').');
  }
}

function dryReport(context) {
  requireFact(request(context) === 'dry-run','unauthenticated_request');
  const candidate = process.env.EXPERIMENTAL_APPROVED_SHA;
  requireFact(shaPattern.test(candidate),'invalid_claim');
  recipient();
  const dir = path.join(process.env.RUNNER_TEMP,'hoben-experimental-exports');
  fs.mkdirSync(dir,{mode:0o700});
  fs.writeFileSync(path.join(dir,'report.json'),JSON.stringify({
    schema:1,scenario:'h1h2',phase:'dry-run',main_sha:context.sha,candidate_sha:candidate,
    run_id:context.runId,boundary_proven:false,result:'dry_run_pass',
    reason:'no_hoben_connection',executed_sessions:0}),{mode:0o600,flag:'wx'});
}

function publicReport(context, phase) {
  const file = path.join(process.env.GITHUB_WORKSPACE, 'public-report/report.json');
  const stat = fs.lstatSync(file);
  requireFact(stat.isFile() && !stat.isSymbolicLink() && stat.size <= 65536,
    'invalid_public_report');
  const r = JSON.parse(fs.readFileSync(file, 'utf8'));
  requireFact(r.schema === 1 && r.scenario === 'h1h2' && r.phase === phase &&
    r.main_sha === context.sha && r.candidate_sha === process.env.EXPERIMENTAL_APPROVED_SHA &&
    r.run_id === context.runId && r.boundary_proven === false, 'invalid_public_report');
  const exact = (o, keys) => o && Object.keys(o).sort().join() === keys.sort().join();
  const common = ['schema','scenario','phase','main_sha','candidate_sha','run_id',
    'boundary_proven','result','reason','executed_sessions'];
  requireFact(exact(r, phase === 'dry-run' ? common : common.concat(
    ['observation_seconds','planned_sessions','eligible_sessions','sessions'])),
  'invalid_public_report');
  if (phase === 'dry-run') {
    requireFact(r.result === 'dry_run_pass' && r.reason === 'no_hoben_connection' &&
      r.executed_sessions === 0, 'invalid_public_report');
    return {result:r.result,
      text:'Dry-run: trusted admission and CMS preflight passed; Hoben sessions: 0.'};
  }
  requireFact((['inconclusive','failure'].includes(r.result)) && r.reason === (r.result === 'inconclusive' ? 'hypotheses_unproven' : 'collection_interrupted') &&
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
    requireFact(exact(s, ['mode','pause_seconds','repetition','partial','prefix_complete',
      'rx_bytes','read_calls','pongs_before_open','pongs_under_h2','v4_requests',
      'correlated_responses','exception_responses','stop','emission_stop','opening_context',
      'h1_status','h2_status','comparison']) &&
      exact(s.opening_context,['eligible','status']) &&
      typeof s.prefix_complete === 'boolean' &&
      [null,'terminal_close_h2','invalid_mbap_h2','unsupported_type_h2','invalid_correlation'].includes(s.emission_stop) &&
      ['read_calls','pongs_before_open','pongs_under_h2'].every(k=>integer(s[k],1048576)) &&
      integer(s.exception_responses,s.v4_requests) &&
      s.correlated_responses + s.exception_responses <= s.v4_requests &&
      (s.mode !== 'H1' || s.pongs_under_h2 === 0) &&
      s.mode === (index < 6 ? 'H1' : 'H2') &&
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
  return {result:r.result,text:`Anonymized report: ${r.executed_sessions}/12 sessions; ` +
    `${r.eligible_sessions} eligible.\n\n` +
    '| Session | Mode | Stop | Opening context | H1 | H2 | Comparison | V4 sent/correlated |\n' +
    '| --- | --- | --- | --- | --- | --- | --- | --- |\n' + rows.join('\n')};
}

const reasons = new Set(['unauthenticated_request','invalid_recipient',
  'manager_decision_missing_or_changed','label_or_decision_not_fresh','invalid_claim',
  'environment_unverified','independent_environment_approval_unverified',
  'stale_or_unprotected_main','tracking_issue_or_label_changed','experimental_head_or_review_changed',
  'changes_requested','unresolved_review','unverifiable_review','offline_ci_unverified',
  'concurrent_hoben_run','dry_run_required','request_changed_after_wait',
  'duplicate_or_unrecordable_request','github_or_configuration_unavailable']);
async function publish({github,context,core}) {
  try {
    const phase = request(context);
    const candidate = process.env.EXPERIMENTAL_APPROVED_SHA;
    const claimed = process.env.EXPERIMENTAL_CLAIMED === 'true';
    let observation = '';
    let reportResult = null;
    let reportVerified = false;
    if (claimed) {
      const stamp = await claim(github,context.repo,phase,candidate);
      requireFact(stamp.run_id === context.runId && stamp.main_sha === context.sha,
        'invalid_claim');
      try {
        const report = publicReport(context,phase);
        observation = report.text; reportResult = report.result; reportVerified = true;
      }
      catch { /* Missing/unsafe report never grants success. */ }
    }
    const job = process.env.EXPERIMENTAL_JOB_RESULT;
    const accepted = process.env.EXPERIMENTAL_APPROVED === 'true';
    const result = !accepted ? 'NOT RUN' : job === 'cancelled' ? 'cancelled' :
      phase === 'live' && process.env.EXPERIMENTAL_COLLECT_RESULT === 'skipped' ? 'NOT RUN' :
      job === 'success' && reportVerified && reportResult !== 'failure' ?
        (phase === 'dry-run' ? 'dry_run_pass' : 'inconclusive') :
      'failure';
    const gateReason = process.env.EXPERIMENTAL_GATE_REASON;
    const reason = result === 'NOT RUN' ? (reasons.has(gateReason) ? gateReason : 'gate_or_approval_refused') :
      result === 'dry_run_pass' ? 'no_hoben_connection' :
      result === 'inconclusive' ? 'hypotheses_unproven' :
      result === 'cancelled' ? 'run_cancelled' : 'job_or_report_failed_or_incomplete';
    if (claimed) await github.rest.repos.createCommitStatus({...context.repo,sha:candidate,
      state:['dry_run_pass','inconclusive'].includes(result) ? 'success' : 'failure',
      context:statusName(phase),target_url:runUrl(context.runId),
      description:'H1/H2 '+phase+': '+result});
    // Refused unclaimed requests do not modify a previous claim/status and do
    // not repeat notifications. Only the fixed gate category enters the log.
    const body = 'Experimental H1/H2 '+phase+': '+result+'; reason: '+reason+'.\n'+
      'Scenario: h1h2; experimental SHA: '+candidate+'; main gate SHA: '+context.sha+'.\n'+
      'Run ID: '+context.runId+'; URL: '+runUrl(context.runId)+'\n'+observation+
      '\nBoundary unproven; no production or merge approval. Refs #48 / #51.';
    if (claimed) {
      const message = '<!-- hoben-experimental-result:'+phase+':'+candidate+':'+context.runId+' -->\n';
      const comments = await github.paginate(github.rest.issues.listComments,{
        ...context.repo,issue_number:policy.tracking_issue,per_page:100});
      if (!comments.some(c=>c.user?.login === 'github-actions[bot]' &&
        c.user.type === 'Bot' && c.body === message+body)) await github.rest.issues.createComment({
        ...context.repo,issue_number:policy.tracking_issue,body:message+body});
    }
    if (core.summary) await core.summary.addRaw(body).write();
    core.info('Experimental H1/H2 '+phase+': '+result+'; '+reason);
    requireFact(job !== 'success' || reportVerified || !accepted,'invalid_public_report');
  } catch { core.setFailed('Unable to publish verified experimental result.'); }
}

async function discover({github,repo,phase,candidate}) {
  requireFact(repo.owner+'/'+repo.repo === repository &&
    ['dry-run','live'].includes(phase) && shaPattern.test(candidate),'invalid_claim');
  const stamp = await claim(github,repo,phase,candidate);
  const {data:run} = await github.rest.actions.getWorkflowRun({...repo,run_id:stamp.run_id});
  requireFact(run.id === stamp.run_id && run.path === workflow && run.event === 'issues' &&
    run.head_sha === stamp.main_sha && run.head_branch === 'main' && run.run_attempt === 1 &&
    owner(run.actor) && owner(run.triggering_actor),'invalid_claim');
  const jobs = await github.paginate(github.rest.actions.listJobsForWorkflowRun,
    {...repo,run_id:stamp.run_id,filter:'latest',per_page:100});
  const artifacts = await github.paginate(github.rest.actions.listWorkflowRunArtifacts,
    {...repo,run_id:stamp.run_id,per_page:100});
  const name = 'experimental-report-'+candidate+'-'+stamp.run_id;
  const report = artifacts.find(a=>a.name === name && a.expired === false);
  const {data:combined} = await github.rest.repos.getCombinedStatusForRef({...repo,ref:candidate});
  const status = combined.statuses.find(s=>s.context === statusName(phase));
  requireFact(!status || status.target_url === runUrl(stamp.run_id),'invalid_claim');
  const gate = jobs.find(j=>j.name === 'request');
  const collect = jobs.find(j=>j.name === 'observations');
  const notRun = phase === 'live' && run.status === 'completed' &&
    (gate?.conclusion !== 'success' || collect?.conclusion === 'skipped');
  return {scenario:'h1h2',phase,sha:candidate,main_sha:stamp.main_sha,
    run_id:stamp.run_id,url:runUrl(stamp.run_id),
    state:notRun ? 'NOT RUN' : run.status === 'completed' ? run.conclusion :
      ['queued','requested','pending','waiting'].includes(run.status) ? 'queued' : 'running',
    report_artifact_id:report && positive(report.id) ? report.id : null,
    report_name:name,boundary_proven:false};
}
module.exports = {verify,publish,dryReport,discover};
