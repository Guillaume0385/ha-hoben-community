"use strict";
// Only fixed suite entry points. No caller-selected scenario/profile/budget.
// Not wired into any workflow in this structural, locked installation slice.
const shared = require("./session-300-gate.cjs");
const contract = require("./session-suite-contract.cjs");
module.exports = Object.freeze({
  dryRun: shared.suiteDryRun,
  verify: shared.suiteVerify,
  refusalCategory: shared.refusalCategory,
  WORKFLOW: shared.WORKFLOW,
  MARKER: contract.MARKER,
  CONTRACT: contract.CONTRACT,
});
