'use strict';
// #207 D4-C1 cross-language regression: no external APIs, secrets or dispatch.
const test = require('node:test');
const assert = require('node:assert/strict');
const {spawnSync} = require('node:child_process');
const python = `
import json, sys
from dataclasses import asdict
sys.path.insert(0, 'tests')
from test_ha_live_workflow_static_gate_offline_207 import candidate, mock_source, mutate
from scripts.ha_live_workflow_static_gate_offline import audit_workflow
v = json.load(sys.stdin)
workflow = candidate()
for key, value in v.get('changes', []):
    mutate(workflow, key, value)
if v.get('source'):
    workflow = mock_source(workflow)
    if v.get('wrong_ref'):
        workflow['request'] += '&ref=main'
result = asdict(audit_workflow(workflow, expected_commit_sha='a' * 40))
print(json.dumps(result, separators=(',', ':')))
`;
function verdict(input) {
  const r = spawnSync('python', ['-c', python], {cwd: process.cwd(),
    input: JSON.stringify(input), encoding: 'utf8', timeout: 5000, maxBuffer: 32768});
  assert.equal(r.status, 0, 'offline Python audit must execute');
  assert.equal(r.stderr, '');
  assert.doesNotMatch(r.stdout, /VERY_PRIVATE_TOKEN/);
  return JSON.parse(r.stdout);
}
function noLive(v) {
  assert.equal(v.execution, 'offline');
  assert.equal(v.admission, 'NOT RUN');
  assert.equal(v.complete, false);
  assert.equal(v.live_ready, false);
  assert.equal(v.secrets_allowed, false);
}
test('synthetic flow can be a structural candidate but never live admission', () => {
  for (const mode of [{}, {source:true}]) {
    const v = verdict(mode);
    noLive(v);
    assert.equal(v.structure, 'CANDIDATE_ONLY');
  }
});
test('claim dependency and approval-environment protections cannot be skipped', () => {
  for (const [path, value] of [
    ['jobs.claim.needs', 'collect'],
    ['jobs.collect.if', '${{ always() }}'],
    ['jobs.collect.environment', 'unprotected'],
  ]) {
    const v = verdict({changes:[[path, value]]});
    noLive(v);
    assert.equal(v.structure, 'REFUSED');
  }
});
test('secret injection before recheck and cleanup bypass are rejected', () => {
  for (const [path, value] of [
    ['jobs.collect.steps.1.env', {CLAIM_REF:'${{ secrets.HOBEN_USER_GUID }}'}],
    ['jobs.collect.steps.2.if', '${{ always() }}'],
    ['jobs.collect.steps.3.if', '${{ success() }}'],
    ['jobs.collect.steps.2.run', 'echo VERY_PRIVATE_TOKEN ${{ secrets.HOBEN_USER_GUID }}'],
  ]) {
    const v = verdict({changes:[[path, value]]});
    noLive(v);
    assert.equal(v.structure, 'REFUSED');
  }
});
test('pin SHA/ref and concurrency cancel-in-progress cannot drift', () => {
  const wrongRef = verdict({source:true,wrong_ref:true});
  noLive(wrongRef);
  assert.equal(wrongRef.structure, 'REFUSED');
  for (const [path, value] of [
    ['jobs.collect.steps.0.with.ref', 'refs/heads/main'],
    ['jobs.collect.steps.0.uses', 'actions/checkout@v4'],
    ['concurrency.cancel-in-progress', true],
    ['permissions', {'contents':'write'}],
  ]) {
    const v = verdict({changes:[[path, value]]});
    noLive(v);
    assert.equal(v.structure, 'REFUSED');
  }
});
