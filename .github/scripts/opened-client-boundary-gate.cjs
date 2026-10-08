// Trusted main-only dispatch gate. Never load this module from the candidate.
module.exports = async function verify({ github, context, core }) {
  const repository = 'Guillaume0385/ha-hoben-community';
  const manager = 'Guillaume0385';
  const inputs = context.payload.inputs;
  const sha = inputs?.reviewed_sha;
  const certificate = inputs?.recipient_sha256;
  const seconds = inputs?.observation_seconds;
  const mode = inputs?.mode;
  if (context.eventName !== 'workflow_dispatch' ||
      context.ref !== 'refs/heads/main' || context.actor !== manager ||
      context.payload.sender?.login !== manager ||
      `${context.repo.owner}/${context.repo.repo}` !== repository ||
      process.env.GITHUB_TRIGGERING_ACTOR !== manager ||
      process.env.GITHUB_RUN_ATTEMPT !== '1' ||
      process.env.GITHUB_WORKFLOW_REF !==
        `${repository}/.github/workflows/opened-client-boundary.yml@refs/heads/main` ||
      typeof sha !== 'string' || !/^[0-9a-f]{40}$/.test(sha) ||
      typeof certificate !== 'string' || !/^[0-9a-f]{64}$/.test(certificate) ||
      !['H1', 'H2', 'both'].includes(mode) ||
      typeof seconds !== 'string' || !/^(?:[3-8][0-9]|90)$/.test(seconds)) {
    core.setFailed('Exact MANAGER main dispatch and bounded inputs required.');
    return;
  }
  try {
    const { data: branch } = await github.rest.repos.getBranch({
      ...context.repo, branch: 'main'
    });
    const { data: pr } = await github.rest.pulls.get({
      ...context.repo, pull_number: 49
    });
    if (branch.protected !== true || branch.commit.sha !== context.sha ||
        pr.state !== 'open' || pr.head.sha !== sha ||
        pr.head.ref !== 'codex/issue-48' ||
        pr.head.repo?.full_name !== repository ||
        pr.base.ref !== 'main' || pr.base.repo.full_name !== repository) {
      core.setFailed('Unprotected/stale main or changed #49 candidate; dispatch again after review.');
      return;
    }
    core.setOutput('approved', 'true');
    core.setOutput('sha', sha);
    core.setOutput('mode', mode);
    core.setOutput('seconds', seconds);
    core.setOutput('recipient', certificate);
    core.info(`Exploratory candidate SHA: ${sha}; no merge approval or protocol proof.`);
  } catch {
    core.setFailed('Unable to verify trusted main and exact exploratory candidate.');
  }
};
