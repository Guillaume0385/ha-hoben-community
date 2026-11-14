'use strict';
// #207 D4-D: no GitHub reference write without independent durability proof.
// A tag createRef and successful readback are NOT an immutable anti-replay ledger.
function main() {
  process.stderr.write('::error::ha_live_d4_durable_claim_NOT_RUN\n');
  return 1;
}
if (require.main === module) process.exitCode = main();
module.exports = Object.freeze({main});
