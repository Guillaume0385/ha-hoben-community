"use strict";
// D7: source integrity is necessary, never sufficient for live admission.
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const API = Object.freeze({owner: 'Guillaume0385', repo: 'ha-hoben-community'});
const MANIFEST = '.github/info-manual-route.json';
const FILES = Object.freeze([
  '.github/workflows/hoben-manual.yml',
  '.github/workflows/hoben-ha-manual.yml',
  '.github/scripts/manual-hoben-gate.cjs',
  '.github/scripts/info-manual-route.cjs',
  '.github/scripts/info-manual-report.cjs',
  '.github/scripts/info-manual-live-report.cjs',
  '.github/scripts/experimental-report-file.cjs',
  '.github/scripts/experimental-lab-gate.cjs',
  '.github/scripts/experimental-push-preflight.cjs',
  '.github/scripts/experimental-native-rerun.cjs',
  '.github/config/hoben-experimental.json',
  'scripts/manual_hoben_context.py',
  'scripts/launch_info_manual.py',
  'scripts/info_manual_contract.py',
  'scripts/info_manual_process.py',
  'scripts/info_manual_worker.py',
  'scripts/info_delivery_memory.py',
  'scripts/info_delivery_process_guard.py',
  'scripts/info_delivery_scenario.py',
  'scripts/info_delivery_supervisor.py',
  'scripts/info_delivery_tls_adapter.py',
  'custom_components/hoben/__init__.py',
  'custom_components/hoben/binary_sensor.py',
  'custom_components/hoben/client.py',
  'custom_components/hoben/close_diagnostic.py',
  'custom_components/hoben/config_flow.py',
  'custom_components/hoben/const.py',
  'custom_components/hoben/coordinator.py',
  'custom_components/hoben/data_updated_recovery.py',
  'custom_components/hoben/diagnostics.py',
  'custom_components/hoben/entity.py',
  'custom_components/hoben/error_phases.py',
  'custom_components/hoben/exceptions.py',
  'custom_components/hoben/frame_diagnostic.py',
  'custom_components/hoben/helpers.py',
  'custom_components/hoben/malformed.py',
  'custom_components/hoben/modbus.py',
  'custom_components/hoben/myhoben.py',
  'custom_components/hoben/profiles.py',
  'custom_components/hoben/safe_reports.py',
  'custom_components/hoben/sensor.py',
  'custom_components/hoben/session.py',
  'custom_components/hoben/session_monitor.py',
  'custom_components/hoben/session_observation.py',
  'custom_components/hoben/session_sensor.py',
  'custom_components/hoben/transport.py',
  'custom_components/hoben/v4_eof_quarantine.py',
  'custom_components/hoben/v4_experiment.py',
  'custom_components/hoben/v4_lifecycle.py',
  'custom_components/hoben/v4_no_pong.py',
  'custom_components/hoben/v4_read.py',
  'custom_components/hoben/v4_session.py',
  'custom_components/hoben/v4_state.py',
]);
const LIMITS = Object.freeze({observation_ms: 3540000, cleanup_ms: 60000, total_ms: 3600000});
const POLICY = Object.freeze({observation: 'passive_candidate_stop', continuation: 'never_force',
  info_framing: 'INCONCLUSIVE', boundary_proven: false});
const BLOCKERS = Object.freeze(['manual_info_route_not_connected']);
const bad = () => { throw Error('manual_info_route_not_connected'); };
const need = value => { if (!value) bad(); };
const keys = (v, expected) => v && typeof v === 'object' && !Array.isArray(v) &&
  Object.keys(v).sort().join() === [...expected].sort().join();
const equal = (a, b) => keys(a, Object.keys(b)) &&
  Object.entries(b).every(([k, v]) => a[k] === v);
const digest = data => crypto.createHash('sha256').update(data).digest('hex');

function validateManifest(m) {
  need(keys(m, ['schema', 'selection', 'environment', 'limits', 'policy', 'files']));
  need(m.schema === 2 && m.selection === 'hoben-live' && m.environment === 'hoben-experimental');
  need(equal(m.limits, LIMITS) && equal(m.policy, POLICY));
  need(keys(m.files, FILES) && Object.values(m.files).every(v =>
    typeof v === 'string' && /^[a-f0-9]{64}$/.test(v)));
  return m;
}
function job(source, name) {
  const start = source.indexOf('  '+name+':\n');
  need(start >= 0);
  const rest = source.slice(start+name.length+4), end = rest.search(/^  [a-z][a-z-]*:\n/m);
  return rest.slice(0, end < 0 ? rest.length : end);
}
function wired(sources) {
  const source = sources['.github/workflows/hoben-manual.yml'];
  need(source.includes('name: Tests Hoben manuels\n') &&
    source.includes('group: hoben-read-only-observation\n') &&
    source.includes('cancel-in-progress: false\n'));
  need(!/^  (collect-ha|publish-ha|result-ha):/m.test(source));
  const collect = job(source,'collect-info'), publish = job(source,'publish-info'),
    result = job(source,'result-info');
  need(/environment: hoben-experimental\n/.test(collect) &&
    /timeout-minutes: 75\n/.test(collect));
  need(collect.includes("needs.preflight.outputs.selection == 'hoben-live'") &&
    collect.includes('github.run_attempt == 1') && collect.includes("refs/heads/experimental"));
  const recheck = collect.indexOf('- id: recheck'), capture = collect.indexOf('- id: capture'),
    exports = collect.indexOf('- id: exports');
  need(recheck >= 0 && capture > recheck && exports > capture);
  need(!collect.slice(0,capture).includes('secrets.'));
  need(!collect.includes('continue-on-error') &&
    collect.includes("if: steps.recheck.outputs.approved == 'true'") &&
    collect.includes('run: python -I trusted/scripts/launch_info_manual.py'));
  need(collect.slice(recheck,capture).includes('writeLaunchPermit({github,context,root:process.env.RUNNER_TEMP})'));
  // #186-011: Info has one Hoben secret. A repinned manifest must not
  // permit another secret to be injected into its protected capture step.
  const protectedCapture = collect.slice(capture,exports);
  need(protectedCapture.includes('HOBEN_USER_GUID: ${{ secrets.HOBEN_USER_GUID }}') &&
    (protectedCapture.match(/secrets\./g)||[]).length === 1);
  need(collect.slice(exports).includes('info-manual-live-report.cjs') &&
    collect.slice(exports).includes('await api.prepare('));
  need(publish.includes('await api.publish(') && result.includes('validateForLivePublication'));
  need(!publish.includes('secrets.') && !result.includes('secrets.') &&
    !/environment:/.test(publish+result));
  need(job(source,'collect').includes('timeout-minutes: 50\n') &&
    job(source,'collect').includes("selection != 'hoben-live'"));
  // The dedicated HA workflow is outside this task, even when hashing sources.
  need(digest(sources['.github/workflows/hoben-ha-manual.yml']) ===
    'f1f27e60304f2f3b44c08e9b88e13064e5e0f80de40f3396d57a84c2f7b02eff');
}
function assess(m, sources) {
  validateManifest(m); need(keys(sources, FILES));
  for (const file of FILES) {
    need(typeof sources[file] === 'string' && Buffer.byteLength(sources[file]) <= 262144);
    need(digest(sources[file]) === m.files[file]);
  }
  wired(sources);
  return Object.freeze({ready: true, status: 'CONNECTED FOR PASSIVE OBSERVATION',
    contract_digest: digest(JSON.stringify(m)), limits: {...LIMITS}, policy: {...POLICY}});
}

async function remoteFile(github, sha, file) {
  try {
    const {data} = await github.rest.repos.getContent({...API, path: file, ref: sha});
    need(data?.type === 'file' && data.path === file && data.encoding === 'base64' &&
      Number.isSafeInteger(data.size) && data.size > 0 && data.size <= 262144 &&
      typeof data.content === 'string' && data.content.length <= 360000);
    const encoded = data.content.replace(/\n/g, '');
    need(/^[A-Za-z0-9+/]*={0,2}$/.test(encoded));
    const bytes = Buffer.from(encoded, 'base64');
    need(bytes.length === data.size && bytes.toString('base64') === encoded);
    const text = new TextDecoder('utf-8', {fatal: true}).decode(bytes);
    need(Buffer.byteLength(text) === data.size);
    return text;
  } catch (_) { return bad(); }
}

async function inspect({github, context}) {
  need(context.ref === 'refs/heads/experimental' && /^[a-f0-9]{40}$/.test(context.sha || ''));
  const m = validateManifest(JSON.parse(await remoteFile(github, context.sha, MANIFEST)));
  const sources = {};
  // All paths are fixed here, not taken from the manifest or dispatch input.
  for (const file of FILES) sources[file] = await remoteFile(github, context.sha, file);
  return assess(m, sources);
}

async function requireConnected(options) {
  try {
    const assessment = await inspect(options);
    need(assessment.ready);
    return assessment;
  } catch (_) { bad(); }
}

function local(root) {
  // Read-only, fixed files. Does not create a runtime, identity consumer or CLI.
  const read = file => {
    const full = path.join(root, file), stat = fs.lstatSync(full);
    need(stat.isFile() && !stat.isSymbolicLink() && stat.size <= 262144);
    return fs.readFileSync(full, 'utf8');
  };
  const m = JSON.parse(read(MANIFEST)), sources = {};
  for (const file of FILES) sources[file] = read(file);
  return assess(m, sources);
}
module.exports = Object.freeze({FILES, MANIFEST, LIMITS, POLICY, BLOCKERS, assess, inspect, requireConnected, local});
