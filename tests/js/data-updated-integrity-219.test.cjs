'use strict';
// #219-A: the new runtime dependency must remain covered by the existing gate.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const route = require('../../.github/scripts/info-manual-route.cjs');
const parser = 'custom_components/hoben/data_updated_parser.py';
const manifest = JSON.parse(fs.readFileSync(route.MANIFEST, 'utf8'));
const sources = Object.fromEntries(route.FILES.map(p => [p, fs.readFileSync(p, 'utf8')]));

test('#219 parser and existing RX sources are in the closed integrity set', () => {
  for (const file of [parser, 'custom_components/hoben/v4_session.py',
    'custom_components/hoben/v4_experiment.py', 'custom_components/hoben/frame_diagnostic.py']) {
    assert.ok(route.FILES.includes(file), file);
    assert.ok(Object.hasOwn(manifest.files, file), file);
  }
  assert.equal(route.assess(manifest, sources).ready, true);
});

test('#219 parser mutation fails closed without a reviewed repin', () => {
  assert.ok(Object.hasOwn(sources, parser));
  assert.equal(route.assess(manifest, sources).ready, true);
  assert.throws(() => route.assess(manifest, {...sources,
    [parser]: sources[parser] + '\n# offline synthetic integrity mutation\n',
  }), {message: 'manual_info_route_not_connected'});
});
