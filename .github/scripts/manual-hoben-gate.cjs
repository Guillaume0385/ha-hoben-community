"use strict";
// Owner dispatch replaces the old PR comment. Every technical proof is reread.
const crypto=require('node:crypto');
const technical=require('./experimental-lab-gate.cjs');
const infoRoute=require('./info-manual-route.cjs');
const API={owner:'Guillaume0385',repo:'ha-hoben-community'};
const REPO=API.owner+'/'+API.repo, REPO_ID=1401398724, OWNER_ID=18246624;
const FILE='.github/workflows/hoben-manual.yml';
const CHOICES=Object.freeze(['h1h2','session-300','session-reconnect','all','hoben-live']);
const need=(v)=>{if(!v)throw Error('manual_proof_unverified');};
const sha=v=>typeof v==='string'&&/^[a-f0-9]{40}$/.test(v);
const positive=v=>Number.isSafeInteger(v)&&v>0;
const sameRepo=r=>r?.id===REPO_ID&&r.full_name===REPO;
const owner=u=>u?.login===API.owner&&u.id===OWNER_ID&&u.type==='User';
const digest=o=>crypto.createHash('sha256').update(JSON.stringify(o)).digest('hex');
// Public diagnostic phases are fixed, never derived from GitHub API responses,
// exception messages or private Hoben evidence. The run still fails closed.
const PUBLIC_PHASES=Object.freeze(['provenance','merged_pr','ci','review','environment_policy',
  'environment_api','environment_approval','concurrent_run','claim','route_contract']);
const refusalPhases=new WeakMap();
function mark(error,category) {
  const safe=error instanceof Error?error:Error('manual_proof_unverified');
  if(!refusalPhases.has(safe))refusalPhases.set(safe,category);
  return safe;
}
async function inPhase(category,operation) {
  try{return await operation();}catch(error){throw mark(error,category);}
}
function publicFailureCategory(error) {
  const category=error instanceof Error?refusalPhases.get(error):undefined;
  return PUBLIC_PHASES.includes(category)?category:'unknown';
}

async function provenance({github,context,env=process.env}) {
  need(context.eventName==='workflow_dispatch'&&context.ref==='refs/heads/experimental'&&
    context.actor===API.owner&&sameRepo(context.payload.repository)&&owner(context.payload.sender)&&
    positive(context.runId)&&sha(context.sha)&&env.GITHUB_ACTIONS==='true'&&
    env.GITHUB_EVENT_NAME===context.eventName&&env.GITHUB_REF===context.ref&&
    env.GITHUB_REPOSITORY===REPO&&env.GITHUB_SHA===context.sha&&
    env.GITHUB_WORKFLOW_SHA===context.sha&&env.GITHUB_RUN_ID===String(context.runId)&&
    env.GITHUB_ACTOR===API.owner&&env.GITHUB_TRIGGERING_ACTOR===API.owner&&
    env.GITHUB_RUN_ATTEMPT==='1'&&env.GITHUB_WORKFLOW_REF===REPO+'/'+FILE+'@'+context.ref);
  const inputs=context.payload.inputs;
  need(inputs&&Object.keys(inputs).join()==='scenario'&&CHOICES.includes(inputs.scenario));
  const {data:branch}=await github.rest.repos.getBranch({...API,branch:'experimental'});
  const {data:run}=await github.rest.actions.getWorkflowRun({...API,run_id:context.runId});
  need(branch.protected===true&&branch.commit?.sha===context.sha&&run.id===context.runId&&
    run.event==='workflow_dispatch'&&run.run_attempt===1&&run.head_sha===context.sha&&
    run.head_branch==='experimental'&&sameRepo(run.repository)&&sameRepo(run.head_repository)&&
    owner(run.actor)&&owner(run.triggering_actor)&&
    technical.workflowPath(run.path,FILE,['refs/heads/experimental'])&&
    Number.isFinite(Date.parse(run.created_at)));
  return {selection:inputs.scenario,beganAt:Date.parse(run.created_at)};
}

async function reviewedCommit(github,context,proof) {
  const associated=await github.paginate(github.rest.repos.listPullRequestsAssociatedWithCommit,
    {...API,commit_sha:context.sha,per_page:100});
  const matches=associated.filter(p=>p.merge_commit_sha===context.sha&&p.base?.ref==='experimental'&&
    sameRepo(p.base.repo)&&sameRepo(p.head.repo)&&p.state==='closed'&&p.merged_at);
  need(matches.length===1&&positive(matches[0].number));
  const {data:pr}=await github.rest.pulls.get({...API,pull_number:matches[0].number});
  need(pr.number===matches[0].number&&pr.merged===true&&pr.state==='closed'&&!pr.draft&&
    owner(pr.merged_by)&&pr.merge_commit_sha===context.sha&&pr.base?.ref==='experimental'&&
    sameRepo(pr.base.repo)&&sameRepo(pr.head.repo)&&sha(pr.head.sha)&&
    Number.isFinite(Date.parse(pr.merged_at))&&Date.parse(pr.merged_at)<=proof.beganAt);
  const [{data:candidate},{data:merged}]=await Promise.all([
    github.rest.git.getCommit({...API,commit_sha:pr.head.sha}),
    github.rest.git.getCommit({...API,commit_sha:context.sha})]);
  need(candidate.sha===pr.head.sha&&merged.sha===context.sha&&sha(candidate.tree?.sha)&&
    candidate.tree.sha===merged.tree?.sha);
  const candidates=await inPhase('ci',async()=>{
    const runs=await github.paginate(github.rest.actions.listWorkflowRunsForRepo,
      {...API,head_sha:pr.head.sha,event:'pull_request',per_page:100});
    const found=runs.filter(r=>r.head_sha===pr.head.sha&&r.head_branch===pr.head.ref&&
      r.event==='pull_request'&&r.run_attempt===1&&r.status==='completed'&&r.conclusion==='success'&&
      technical.workflowPath(r.path,'.github/workflows/validate.yml',
        ['refs/pull/'+pr.number+'/merge',pr.head.ref,'refs/heads/'+pr.head.ref])&&
      Number.isFinite(Date.parse(r.updated_at))&&Date.parse(r.updated_at)<=proof.beganAt);
    need(found.length>0);
    return found.sort((a,b)=>b.id-a.id);
  });
  // Review and CI are distinct public failure phases, but no raw API errors escape.
  try {
    await technical.reviewedCI(github,pr,{ciRunId:candidates[0].id,
      notAfter:new Date(proof.beganAt).toISOString()});
  } catch(error) {
    throw mark(error,error instanceof Error&&error.message==='review_unverified'?'review':'ci');
  }
  return {pr:pr.number,candidate_sha:pr.head.sha,ci_run_id:candidates[0].id};
}

async function verify(options) {
  const {github,context,recheck=false}=options;
  const proof=await inPhase('provenance',()=>provenance(options));
  const reviewed=await inPhase('merged_pr',()=>reviewedCommit(github,context,proof));
  // #186 reassigns the existing literal hoben-live choice to Info research.
  // Its future route must satisfy the hoben-experimental technical policy;
  // the former HA environment/approval cannot authorize this selection.
  let environment;
  try {
    environment=await technical.environmentPolicy(github,context);
  } catch(error) {
    throw mark(error,error instanceof Error&&error.message==='environment_api_inaccessible'
      ?'environment_api':'environment_policy');
  }
  await inPhase('concurrent_run',async()=>{
    await technical.noOtherObservation(github,context);
    // Also reject runs created from the retired experimental entry points.
    for(const status of ['requested','queued','pending','waiting','in_progress']) {
      const runs=await github.paginate(github.rest.actions.listWorkflowRunsForRepo,{...API,status,per_page:100});
      need(Array.isArray(runs)&&!runs.some(r=>r.id!==context.runId&&
        (!positive(r.id)||typeof r.path!=='string'||
         ['hoben-experimental.yml','hoben-live-experimental.yml','hoben-session-300.yml',
           ...(proof.selection==='hoben-live'?['hoben-manual.yml','hoben-ha-manual.yml',
             'hoben-protocol-manual.yml']:[])]
           .includes(r.path.split('@')[0].split('/').pop()))));
    }
  });
  let circuit;
  if(proof.selection==='hoben-live') {
    // Owner 09/11: the supported passive strategy may end INCONCLUSIVE
    // after an opaque candidate, without claiming a frame/continuation.
    // Only the reviewed, complete worker/guardian/receipt route can admit it.
    if(!environment.approvalRequired)
      throw mark(Error('manual_info_environment_approval_required'),'environment_approval');
    circuit=await inPhase('route_contract',()=>infoRoute.requireConnected({github,context}));
  }
  const name='hoben-manual-'+context.runId+'-attempt1';
  const claim={schema:circuit?2:1,selection:proof.selection,sha:context.sha,run_id:context.runId,
    run_attempt:1,...reviewed,environment_digest:environment.digest,
    ...(circuit?{contract_digest:circuit.contract_digest}:{})};
  let claimSha;
  await inPhase('claim',async()=>{
  if(recheck) {
    const {data:ref}=await github.rest.git.getRef({...API,ref:'tags/'+name});
    need(ref.ref==='refs/tags/'+name&&ref.object?.type==='tag'&&sha(ref.object.sha));
    claimSha=ref.object.sha;
    const {data:tag}=await github.rest.git.getTag({...API,tag_sha:ref.object.sha});
    need(tag.tag===name&&tag.object?.type==='commit'&&tag.object.sha===context.sha&&
      digest(JSON.parse(tag.message))===digest(claim));
    if(environment.approvalRequired) await inPhase('environment_approval',
      ()=>technical.actualApproval(github,context,environment,
        {number:1,beganAt:proof.beganAt},true));
  } else {
    const {data:tag}=await github.rest.git.createTag({...API,tag:name,message:JSON.stringify(claim),
      object:context.sha,type:'commit'});
    need(sha(tag.sha));
    await github.rest.git.createRef({...API,ref:'refs/tags/'+name,sha:tag.sha});
    const {data:created}=await github.rest.git.getRef({...API,ref:'tags/'+name});
    need(created.ref==='refs/tags/'+name&&created.object?.type==='tag'&&created.object.sha===tag.sha);
    claimSha=tag.sha;
  }
  });
  return {...reviewed,...(circuit?{contract_digest:circuit.contract_digest}:{}),selection:proof.selection,claim_sha:claimSha,
    environment_id:environment.id,environment_digest:environment.digest,
    status:environment.approvalRequired?'PENDING APPROVAL':'READY FOR ENVIRONMENT'};
}
module.exports={provenance,verify,CHOICES,publicFailureCategory,PUBLIC_PHASES};
