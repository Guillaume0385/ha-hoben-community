"use strict";
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs');
const gate=require('../../.github/scripts/manual-hoben-gate.cjs');
const api=require('../../.github/scripts/manual-hoben-report.cjs');
const repo='Guillaume0385/ha-hoben-community',file='.github/workflows/hoben-manual.yml';
const sha='a'.repeat(40),candidate='b'.repeat(40),tree='c'.repeat(40);
const user={login:'Guillaume0385',id:18246624,type:'User'};
const repository={full_name:repo,id:1401398724};
function setup(selection='all') {
  const s={writes:0,claimReads:0,environmentReads:[],reads:new Set(),history:[],reviews:[],threads:[],jobs:['tests','ha-tests','hacs','hassfest'].map(name=>
    ({name,head_sha:candidate,status:'completed',conclusion:'success'}))};
  s.context={eventName:'workflow_dispatch',actor:user.login,ref:'refs/heads/experimental',sha,runId:123,
    repo:{owner:user.login,repo:'ha-hoben-community'},
    payload:{repository,sender:user,inputs:{scenario:selection}}};
  s.env={GITHUB_ACTIONS:'true',GITHUB_EVENT_NAME:'workflow_dispatch',GITHUB_ACTOR:user.login,
    GITHUB_TRIGGERING_ACTOR:user.login,GITHUB_REPOSITORY:repo,GITHUB_REF:s.context.ref,
    GITHUB_SHA:sha,GITHUB_WORKFLOW_SHA:sha,GITHUB_WORKFLOW_REF:repo+'/'+file+'@'+s.context.ref,
    GITHUB_RUN_ATTEMPT:'1',GITHUB_RUN_ID:'123'};
  s.branch={protected:true,commit:{sha}};
  s.run={id:123,event:'workflow_dispatch',run_attempt:1,head_sha:sha,head_branch:'experimental',
    repository,head_repository:repository,actor:user,triggering_actor:user,path:file,created_at:'2026-10-24T12:10:00Z'};
  s.pr={number:121,state:'closed',merged:true,draft:false,merge_commit_sha:sha,merged_by:user,
    merged_at:'2026-10-24T12:05:00Z',base:{ref:'experimental',repo:repository},head:{sha:candidate,ref:'work',repo:repository}};
  s.ci={id:9,head_sha:candidate,head_branch:'work',event:'pull_request',run_attempt:1,
    status:'completed',conclusion:'success',repository,head_repository:repository,
    path:'.github/workflows/validate.yml',updated_at:'2026-10-24T12:00:00Z',pull_requests:[]};
  s.environment={id:1,name:'hoben-experimental',deployment_branch_policy:{protected_branches:false,
    custom_branch_policies:true},protection_rules:[{type:'branch_policy',id:2}]};
  if(selection==='hoben-live')s.environment.protection_rules.push({id:3,type:'required_reviewers',prevent_self_review:true,
    reviewers:[{type:'User',reviewer:{type:'User',id:2,login:'reviewer'}}]});
  s.policies=[{id:2,node_id:'branch',name:'experimental',type:'branch'}];
  s.tree=tree;s.active=[];
  const actions={getWorkflowRun:async q=>{s.reads.add(q.run_id===9?'ci':'run');return {data:q.run_id===9?s.ci:s.run};},
    listWorkflowRunsForRepo:q=>q.head_sha?[s.ci]:s.active,
    listJobsForWorkflowRun:()=>{s.reads.add('jobs');return s.jobs;}};
  const git={getCommit:async q=>{s.reads.add('tree');return {data:{sha:q.commit_sha,tree:{sha:q.commit_sha===sha?s.tree:tree}}};},
    createTag:async q=>{s.writes++;s.tag={tag:q.tag,object:{type:'commit',sha:q.object},message:q.message};
      return {data:{sha:'d'.repeat(40)}};},
    createRef:async q=>{if(s.ref)throw Error('collision');s.ref={ref:q.ref,object:{type:'tag',sha:q.sha}};},
    getRef:async()=>{s.claimReads++;return {data:s.ref};},getTag:async()=>({data:s.tag})};
  s.github={rest:{repos:{getBranch:async()=>{s.reads.add('branch');return {data:s.branch};},
      listPullRequestsAssociatedWithCommit:()=>{s.reads.add('pr');return [s.pr];},getEnvironment:async q=>{
        s.environmentReads.push(q.environment_name);
        if(s.apiDenied)throw Error('PRIVATE_API');return {data:s.environment};},
      listDeploymentBranchPolicies:()=>s.policies,
      getContent:async q=>{assert.equal(q.ref,sha);
        const text=fs.readFileSync(q.path,'utf8');return {data:{type:'file',path:q.path,
          encoding:'base64',size:Buffer.byteLength(text),content:Buffer.from(text).toString('base64')}};}},
    pulls:{get:async()=>({data:s.pr}),listReviews:()=>{s.reads.add('review');return s.reviews;}},actions,git},
    paginate:async(fn,args)=>fn(args),
    graphql:async()=>({repository:{pullRequest:{reviewThreads:{nodes:s.threads,pageInfo:{hasNextPage:false}}}}}),
    request:async()=>({data:s.history})};
  s.options=()=>({github:s.github,context:s.context,env:s.env});
  return s;
}
// #186-D7 retains the fail-closed Info admission; D3 superseded the former HA acceptance of this one literal selection.
// Other scenarios retain their exact reservation/approval/recheck behavior.
const runnable=['h1h2','session-300','session-reconnect','all'];
for(const choice of runnable)test('manual reserve/recheck '+choice,async()=>{
  const s=setup(choice);
  const decision=await gate.verify(s.options());
  assert.equal(decision.selection,choice);assert.equal(decision.pr,121);
  assert.equal(s.ref.ref,'refs/tags/hoben-manual-123-attempt1');
  assert.equal(JSON.parse(s.tag.message).ci_run_id,9);
  assert.ok(!s.tag.message.includes('decision_id'));
  assert.equal((await gate.verify({...s.options(),recheck:true})).selection,choice);
  await assert.rejects(()=>gate.verify(s.options())); // Consumed even after failure/cancellation.
});
const mutations={main:s=>{s.context.ref=s.env.GITHUB_REF='refs/heads/main';},
  push:s=>{s.context.eventName='push';},actor:s=>{s.env.GITHUB_ACTOR='other';},
  rerun:s=>{s.env.GITHUB_RUN_ATTEMPT='2';},sha:s=>{s.env.GITHUB_WORKFLOW_SHA=candidate;},
  extra:s=>{s.context.payload.inputs.extra='PRIVATE';},choice:s=>{s.context.payload.inputs.scenario='other';},
  stale:s=>{s.branch.commit.sha=candidate;},unprotected:s=>{s.branch.protected=false;},
  tree:s=>{s.tree='e'.repeat(40);},changes:s=>{s.reviews=[{state:'CHANGES_REQUESTED',user:{id:2}}];},
  thread:s=>{s.threads=[{isResolved:false}];},ci:s=>{s.jobs[0].conclusion='failure';},
  ciDate:s=>{s.ci.updated_at='2026-10-24T12:11:00Z';},environment:s=>{s.policies[0].name='main';},
  api:s=>{s.apiDenied=true;},overlap:s=>{s.active=[{id:99,path:'.github/workflows/hoben-session-300.yml'}];}};
for(const [name,mutate] of Object.entries(mutations))test('refusal before claim '+name,async()=>{
  const s=setup();mutate(s);await assert.rejects(()=>gate.verify(s.options()));assert.equal(s.writes,0);
});
for(const choice of runnable)test('fresh independent environment approval is mandatory: '+choice,async()=>{
  const s=setup(choice);s.environment.protection_rules.push({id:3,type:'required_reviewers',prevent_self_review:true,
    reviewers:[{type:'User',reviewer:{type:'User',id:2,login:'reviewer'}}]});
  assert.equal((await gate.verify(s.options())).status,'PENDING APPROVAL');
  await assert.rejects(()=>gate.verify({...s.options(),recheck:true}));
  const approval={state:'approved',created_at:'2026-10-24T12:09:00Z',environments:[{id:1,name:'hoben-experimental'}],
    user:{type:'User',id:2,login:'reviewer'}};
  s.history=[approval];await assert.rejects(()=>gate.verify({...s.options(),recheck:true}));
  approval.created_at='2026-10-24T12:11:00Z';
  await gate.verify({...s.options(),recheck:true});
  s.environment.protection_rules[0].id=99;
  await assert.rejects(()=>gate.verify({...s.options(),recheck:true}));
});
test('changed selection and claim cannot be reused',async()=>{
  const s=setup();await gate.verify(s.options());s.context.payload.inputs.scenario='h1h2';
  await assert.rejects(()=>gate.verify({...s.options(),recheck:true}));
});
test('bundle states are closed and no missing report can be successful',()=>{
  const proof={merge_sha:sha,candidate_sha:candidate,run_id:123,run_attempt:1,pr_number:121,selection:'all'};
  const r={schema:1,selection:'all',proof:{...proof},started:[],process_ok:false,h1h2:null,session:null};
  delete r.proof.selection;
  assert.deepEqual(api.states(api.validate(r,proof)),{h1h2:'NOT RUN','session-300':'NOT RUN','session-reconnect':'NOT RUN'});
  assert.equal(api.completed(r,proof),false);
  r.started=['h1h2'];assert.equal(api.states(api.validate(r,proof)).h1h2,'FAILURE');
  for(const bad of [{...r,private:'PRIVATE'},{...r,started:['session-reconnect']},
    {...r,selection:'other'},{...r,proof:{...r.proof,run_attempt:2}}])assert.throws(()=>api.validate(bad,proof));
});
test('publication refuses oversized or incomplete environment parts before filesystem access',()=>{
  for(const parts of [['A'],Array(4).fill('A'.repeat(120001))]) {
    const failures=[];
    api.publish({core:{setFailed:x=>failures.push(x)},proof:{},parts});
    assert.deepEqual(failures,['NOT RUN: manual publication refused.']);
  }
});

const routeBlocked='manual_info_route_not_connected';
function unconnected(s) {
  const original=s.github.rest.repos.getContent;
  s.github.rest.repos.getContent=async q=>{
    const r=await original(q);if(q.path==='.github/info-manual-route.json'){
      const m=JSON.parse(Buffer.from(r.data.content,'base64'));m.schema=1;
      const t=JSON.stringify(m);r.data.content=Buffer.from(t).toString('base64');r.data.size=Buffer.byteLength(t);
    }return r;
  };return s;
}
function legacy(s) {
  s.branch.name='experimental';
  s.environment.name='hoben-live';s.environment.can_admins_bypass=true;
  s.environment.deployment_branch_policy={protected_branches:true,custom_branch_policies:false};
  return s;
}
test('the dispatch choices are unchanged and all does not select hoben-live',()=>{
  assert.deepEqual(gate.CHOICES,[...runnable,'hoben-live']);
  assert.deepEqual(runnable,['h1h2','session-300','session-reconnect','all']);
});
for(const recheck of [false,true])test('Unconnected Info route stays blocked after technical checks, recheck='+recheck,async()=>{
  const s=unconnected(setup('hoben-live'));
  await assert.rejects(()=>gate.verify({...s.options(),recheck}),{message:routeBlocked});
  assert.deepEqual(s.environmentReads,['hoben-experimental']);
  for(const read of ['branch','run','pr','tree','review','ci','jobs'])assert.ok(s.reads.has(read),read);
  assert.equal(s.writes,0);assert.equal(s.claimReads,0);assert.equal(s.ref,undefined);
});
for(const recheck of [false,true])test('old HA environment cannot admit Info, recheck='+recheck,async()=>{
  const s=legacy(setup('hoben-live'));
  await assert.rejects(()=>gate.verify({...s.options(),recheck}),{message:'environment_branch_invalid'});
  assert.deepEqual(s.environmentReads,['hoben-experimental']);assert.equal(s.writes,0);
});
const infoMutations={...mutations,
  sender:s=>{s.context.payload.sender={...user,id:99};},
  repository:s=>{s.context.payload.repository={...repository,id:99};},
  runHead:s=>{s.run.head_sha=candidate;},
  prDraft:s=>{s.pr.draft=true;},prMerge:s=>{s.pr.merged=false;},
  prOwner:s=>{s.pr.merged_by={...user,id:99};},
  ciHead:s=>{s.ci.head_sha=sha;},ciAttempt:s=>{s.ci.run_attempt=2;},
  ciJobHead:s=>{s.jobs[0].head_sha=sha;},ciMissing:s=>{s.jobs.pop();},
  wrongEnvironment:s=>{s.environment.name='hoben-live';},
  unknownRule:s=>{s.environment.protection_rules.push({id:3,type:'custom_protection'});}};
for(const [name,mutate] of Object.entries(infoMutations))test('Info technical refusal is not masked by route block: '+name,async()=>{
  const s=setup('hoben-live');mutate(s);
  await assert.rejects(()=>gate.verify(s.options()),error=>error.message!==routeBlocked);
  assert.equal(s.writes,0);
});
test('legacy claimed/approved HA evidence and caller flags cannot resurrect the route',async()=>{
  for(const environment of ['hoben-live','hoben-experimental']) {
    const s=unconnected(setup('hoben-live'));
    if(environment==='hoben-live')legacy(s);
    s.ref={ref:'refs/tags/hoben-manual-123-attempt1',object:{type:'tag',sha:'d'.repeat(40)}};
    s.tag={tag:'hoben-manual-123-attempt1',object:{type:'commit',sha},message:JSON.stringify({schema:1,selection:'hoben-live'})};
    s.history=[{state:'approved',created_at:'2026-10-24T12:11:00Z',environments:[{id:1,name:environment}],
      user:{type:'User',id:2,login:'reviewer'}}];
    await assert.rejects(()=>gate.verify({...s.options(),recheck:true,infoRouteConnected:true,allowLive:true}));
    assert.equal(s.writes,0);assert.equal(s.claimReads,0);
  }
});
test('configured technical approval cannot authorize the unconnected Info route',async()=>{
  const s=unconnected(setup('hoben-live'));
  for(const history of [[],[{state:'approved',created_at:'2026-10-24T12:11:00Z',environments:[{id:1,name:'hoben-experimental'}],
    user:{type:'User',id:2,login:'reviewer'}}]]) {
    s.history=history;
    await assert.rejects(()=>gate.verify({...s.options(),recheck:true}),{message:routeBlocked});
    assert.equal(s.claimReads,0);assert.equal(s.writes,0);
  }
});
test('actual preflight action never emits approved for the unproven Info route',async()=>{
  const workflow=fs.readFileSync('.github/workflows/hoben-manual.yml','utf8');
  const block=workflow.split('    - id: gate\n')[1]?.split('\n    outputs:')[0];
  assert.ok(block);
  const lines=block.split('        script: |\n')[1]?.trimEnd().split('\n');
  assert.ok(lines&&lines.length>0&&lines.every(line=>line.startsWith('          ')));
  const script=lines.map(line=>line.slice(10)).join('\n');
  const AsyncFunction=Object.getPrototypeOf(async function(){}).constructor;
  const action=new AsyncFunction('require','github','context','core',script);
  for(const setupEnvironment of [s=>s,legacy]) {
    const s=setupEnvironment(unconnected(setup('hoben-live'))),outputs={},failures=[];
    let summaries=0;
    const core={setOutput:(key,value)=>{outputs[key]=value;},setFailed:value=>failures.push(value),
      summary:{addRaw(){summaries++;return this;},async write(){}}};
    await action(name=>{assert.equal(name,'./.github/scripts/manual-hoben-gate.cjs');
      return {verify:options=>gate.verify({...options,env:s.env})};},s.github,s.context,core);
    assert.equal(outputs.approved,undefined);assert.deepEqual(outputs,{});
    assert.equal(failures.length,1);assert.equal(summaries,0);assert.equal(s.writes,0);
  }
});

test('Info requires configured approval even though source route remains blocked',async()=>{
  const s=setup('hoben-live');s.environment.protection_rules=s.environment.protection_rules.filter(r=>r.type!=='required_reviewers');
  await assert.rejects(()=>gate.verify(s.options()),{message:'manual_info_environment_approval_required'});
  assert.equal(s.writes,0);assert.equal(s.claimReads,0);
});

module.exports={setup};
