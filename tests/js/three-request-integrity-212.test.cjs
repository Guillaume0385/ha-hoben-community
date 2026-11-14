'use strict';
// Offline scope evidence: mutate copies only, never the protected manifest.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const route = require('../../.github/scripts/info-manual-route.cjs');
const files = Object.fromEntries(route.FILES.map(file => [file, fs.readFileSync(file, 'utf8')]));
const manifest = JSON.parse(fs.readFileSync(route.MANIFEST, 'utf8'));

test('#212 base passes existing Info integrity checks', () => {
  assert.equal(route.assess(manifest, files).ready, true);
});

for (const file of ['v4_session.py', 'v4_lifecycle.py', 'client.py', 'coordinator.py']) {
  const target = 'custom_components/hoben/' + file;
  test('#212 runtime change requires reviewed manifest update: ' + target, () => {
    assert.ok(Object.hasOwn(manifest.files, target));
    assert.throws(() => route.assess(manifest, {
      ...files,
      [target]: files[target] + '\n# synthetic offline integrity mutation\n',
    }), {message: 'manual_info_route_not_connected'});
  });
}
