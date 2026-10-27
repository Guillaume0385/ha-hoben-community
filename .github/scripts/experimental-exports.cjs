"use strict";
// Run only from the reviewed export boundary, never from the collector.
const fs = require('node:fs');
const path = require('node:path');
const fsSafe = require('./experimental-report-file.cjs');
const timeline = require('./experimental-timeline.cjs');
const requireFact = fact => { if (!fact) throw Error('invalid_public_report'); };
function readReport(file, context) {
  const r = JSON.parse(fsSafe.snapshot(file,2097152).toString('utf8'));
  return validate(r,context);
}
function validate(r, context) {
  const phase = 'live';
  requireFact(r.schema === 1 && r.scenario === 'h1h2' && r.phase === phase &&
    r.experimental_sha === context.sha && r.merge_sha === context.sha &&
    r.candidate_sha === context.sha &&
    r.run_id === context.runId &&
    Number.isSafeInteger(context.runAttempt) &&
    context.runAttempt >= 1 && context.runAttempt <= 50 &&
    Number.isSafeInteger(context.prNumber) && context.prNumber > 0 &&
    r.run_attempt === context.runAttempt &&
    r.pr_number === context.prNumber &&
    r.boundary_proven === false, 'invalid_public_report');
  const exact = (o, keys) => o && Object.keys(o).sort().join() === keys.sort().join();
  const common = ['schema','scenario','phase','experimental_sha','merge_sha','candidate_sha','run_id',
    'run_attempt','pr_number',
    'boundary_proven','result','reason','executed_sessions'];
  requireFact(exact(r, common.concat(
    ['observation_seconds','planned_sessions','eligible_sessions','sessions'])),
    'invalid_public_report');
  requireFact((['inconclusive','failure'].includes(r.result)) && r.reason === (r.result === 'inconclusive' ? 'hypotheses_unproven' : 'collection_interrupted') &&
    r.observation_seconds === 90 && r.planned_sessions === 12 &&
    Array.isArray(r.sessions) && r.sessions.length <= 12 &&
    (r.result !== 'inconclusive' || r.sessions.length === 12) &&
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
      'h1_status','h2_status','comparison'].concat(s.timing_observations === undefined ? [] : ['timing_observations'])) &&
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
    if (s.timing_observations !== undefined) {
      timeline.validate(s.timing_observations, s.rx_bytes, s.read_calls);
    }
    return `| ${index + 1} | ${s.mode} | ${s.stop} | ${s.opening_context.status} | ` +
      `${s.h1_status} | ${s.h2_status} | ${s.comparison} | ${s.v4_requests}/${s.correlated_responses} |`;
  });
  requireFact(r.eligible_sessions === r.sessions.filter(s => s.opening_context.eligible).length,
    'invalid_public_report');
  return {report:r,result:r.result,text:`Anonymized report: ${r.executed_sessions}/12 sessions; ` +
    `${r.eligible_sessions} eligible.\n\n` +
    '| Session | Mode | Stop | Opening context | H1 | H2 | Comparison | V4 sent/correlated |\n' +
    '| --- | --- | --- | --- | --- | --- | --- | --- |\n' + rows.join('\n')};
}

// Job outputs are capped by GitHub (1 MiB in UTF-16 per job). Fail closed if
// a validated report cannot fit in the cross-runner handoff.
const MAX_REPORT_BYTES = 340 * 1024;
function encode(report) {
  const json = JSON.stringify(report);
  if (Buffer.byteLength(json, 'utf8') > MAX_REPORT_BYTES) throw Error('report_too_large');
  return Buffer.from(json, 'utf8').toString('base64');
}

function prepare({context,core}) {
  try {
    const source = path.join(process.env.RUNNER_TEMP,'hoben-experimental-exports/report.json');
    const {report} = readReport(source,context);
    // Only a fixed-schema validated JSON value crosses to a different runner;
    // never upload any file from the runner that executed candidate Python.
    core.setOutput('report_b64',encode(report));
    core.setOutput('report','true');
  } catch (_) { core.setFailed('Public report refused before upload.'); }
}

function publish({core,context,encoded}) {
  let file;
  try {
    if (typeof encoded !== 'string' || encoded.length > 465000 ||
        !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(encoded)) {
      throw Error('invalid_transfer');
    }
    const bytes = Buffer.from(encoded,'base64');
    if (bytes.toString('base64') !== encoded || bytes.length > MAX_REPORT_BYTES) {
      throw Error('invalid_transfer');
    }
    const parent = process.env.RUNNER_TEMP;
    if (typeof parent !== 'string' || !path.isAbsolute(parent)) throw Error('invalid_path');
    const dir = path.join(parent,'hoben-experimental-public');
    fs.mkdirSync(dir,{mode:0o700});
    file = path.join(dir,'report.json');
    fs.writeFileSync(file,bytes,{mode:0o600,flag:'wx'});
    // Independently validate exact bytes in a fresh job with no Hoben secrets
    // and no process, checkout or filesystem from the collection runner.
    readReport(file,context);
    core.setOutput('report','true');
  } catch (_) {
    // Never leave a rejected candidate JSON at the publication path.
    if (file) { try { fs.unlinkSync(file); } catch (_) {} }
    core.setFailed('NOT RUN: isolated public report rejected.');
  }
}
module.exports = {readReport,validate,prepare,publish};
