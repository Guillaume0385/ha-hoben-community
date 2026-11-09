"use strict";
// This is a readiness/NOT RUN report, not a new live-proof validator.
// D1's independent live-publication refusal remains in force.
const fs = require('node:fs');
const path = require('node:path');
const route = require('./info-manual-route.cjs');
const MAX_BYTES = 8192;
const need = value => { if (!value) throw Error('invalid_info_readiness_report'); };
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
function notRun() {
  return {
    schema: 1, scenario: 'info-delivery-observation', selection: 'hoben-live',
    mode: 'readiness', result: 'NOT RUN', readiness: 'NOT READY',
    observation_started: false, connection_started: false,
    live_provenance: 'not_proven', process_reap: 'not_proven',
    cleanup_attested: false, info_framing: 'INCONCLUSIVE', boundary_proven: false,
    limits: {...route.LIMITS}, blockers: [...route.BLOCKERS],
  };
}
function validate(value) {
  // Compare canonical, closed fields; neither free text nor user counters are
  // accepted. Every claim of connection/cleanup/live SUCCESS is rejected.
  need(value && typeof value === 'object' && !Array.isArray(value));
  const expected = notRun();
  need(Object.keys(value).sort().join() === Object.keys(expected).sort().join());
  for (const key of Object.keys(expected)) need(same(value[key], expected[key]));
  need(Buffer.byteLength(JSON.stringify(value)) <= MAX_BYTES);
  return expected;
}
function decode(text) {
  need(typeof text === 'string' && Buffer.byteLength(text) <= MAX_BYTES);
  return validate(JSON.parse(text));
}
function writeNotRun(root) {
  // The publisher has no Hoben identity/environment. A private output folder
  // is created once under the runner temp directory, never a supplied path.
  need(typeof root === 'string' && path.isAbsolute(root));
  const parent = fs.realpathSync(root);
  const folder = path.join(parent, 'hoben-info-readiness');
  fs.mkdirSync(folder, {mode: 0o700});
  const report = validate(notRun());
  fs.writeFileSync(path.join(folder, 'report.json'), JSON.stringify(report) + '\n',
    {mode: 0o600, flag: 'wx'});
  return report;
}
async function summarize({core, report}) {
  const r = validate(report);
  await core.summary.addHeading('Info 0x0C — NON PRÊT / NOT RUN')
    .addTable([[{data: 'Scénario', header: true}, {data: 'État', header: true}],
      ['hoben-live / Info #186', r.result], ['Framing Info', r.info_framing],
      ...r.blockers.map(b => [b, 'NOT PROVEN'])])
    .addRaw('Aucune observation ni preuve live fournie par ce rapport de préparation. ' +
      'boundary_proven=false ; cleanup réel #192 non résolu. ' +
      'Un job publié correctement ne constitue jamais un SUCCESS fonctionnel.').write();
  core.setFailed('NOT RUN: manual_info_route_not_connected');
}
module.exports = {notRun, validate, decode, writeNotRun, summarize, MAX_BYTES};
