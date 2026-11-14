'use strict';
// #207 D4-D: read-only preflight entrypoint, safe refusal when policy is missing.
// This script may be run by a protected future manual Actions job, NEVER by CI.
const fs = require('node:fs');
const {fetchPort,preflight} = require('../.github/scripts/ha-live-d4-security.cjs');
async function main(env=process.env) {
  try {
    const required=['GITHUB_REPOSITORY','GITHUB_ACTOR','GITHUB_TRIGGERING_ACTOR',
      'GITHUB_EVENT_NAME','GITHUB_REF','GITHUB_SHA','GITHUB_RUN_ID',
      'GITHUB_RUN_ATTEMPT','GITHUB_EVENT_PATH'];
    if (required.some(key=>!env[key])) throw Error('context');
    const path=env.GITHUB_EVENT_PATH;
    const stat=fs.lstatSync(path);
    if (!stat.isFile() || stat.isSymbolicLink() || stat.size > 65536) throw Error('event');
    const event=JSON.parse(fs.readFileSync(path,'utf8'));
    if (!event || !event.inputs || Object.keys(event.inputs).join('|')!=='scenario')
      throw Error('selection');
    const rawContext={repository:env.GITHUB_REPOSITORY,actor:env.GITHUB_ACTOR,
      triggering_actor:env.GITHUB_TRIGGERING_ACTOR,event:env.GITHUB_EVENT_NAME,
      ref:env.GITHUB_REF,sha:env.GITHUB_SHA,run_id:Number(env.GITHUB_RUN_ID),
      attempt:Number(env.GITHUB_RUN_ATTEMPT),scenario:event.inputs.scenario,
      workflow:'.github/workflows/hoben-ha-manual.yml'};
    // A default Actions token typically lacks Administration:read. A 403
    // is expected and MUST remain NOT RUN until independently resolved.
    await preflight({rawContext,port:fetchPort({token:env.GITHUB_TOKEN})});
  } catch (_) {
    process.stderr.write('::error::ha_live_d4_preflight_NOT_RUN\n');
    return 1;
  }
  // No operational permit or claim implementation exists: never report READY.
  process.stderr.write('::error::ha_live_d4_claim_not_attested_NOT_RUN\n');
  return 1;
}
if (require.main === module) {
  main().then(code => {process.exitCode=code;},()=>{
    process.stderr.write('::error::ha_live_d4_preflight_NOT_RUN\n');
    process.exitCode=1;
  });
}
module.exports = Object.freeze({main});
