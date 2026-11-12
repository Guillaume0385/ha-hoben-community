'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {inspect,requireAttested} = require('../../.github/scripts/ha-live-gate-evidence-offline.cjs');
const repoName = 'Guillaume0385/ha-hoben-community';
const root = `/repos/${repoName}`, M = 'a'.repeat(40), H = 'b'.repeat(40), T = 'c'.repeat(40);
const owner = {id:18246624, login:'Guillaume0385', type:'User'};
const other = {id:98, login:'independent', type:'User'};
const repo = {id:1401398724, full_name:repoName, owner};
const context = {repository:{id:repo.id,full_name:repoName},sender:owner,actor:owner,
  triggering_actor:owner,event:'workflow_dispatch',ref:'refs/heads/experimental',sha:M,
  run_id:11,attempt:1,scenario:'hoben-live',workflow:'.github/workflows/hoben-ha-manual.yml',
  pr_number:7,pr_head_sha:H,ci_run_id:22,deployment_id:33};
const ts = '2026-11-12T19:00:00Z', mergedAt='2026-11-12T18:55:00Z', ciAt='2026-11-12T18:50:00Z';
const observed = Date.parse(ts)+1000;
const single = (route, item) => ({pages:[{request:route,status:200,items:[item],next:null}]});
const paged = (route,items) => ({pages:[{request:`${route}?per_page=100&page=1`,status:200,items,next:null}]});
function fixture(){
  const c=structuredClone(context);
  const sources={
    branch:single(`${root}/branches/experimental`,{name:'experimental',protected:true,commit:{sha:M}}),
    run:single(`${root}/actions/runs/11`,{id:11,run_attempt:1,event:'workflow_dispatch',head_sha:M,
      head_branch:'experimental',path:c.workflow,repository:repo,head_repository:repo,actor:owner,
      triggering_actor:owner,created_at:ts}),
    prs:paged(`${root}/commits/${M}/pulls`,[{number:7,merged:true,state:'closed',draft:false,
      head:{sha:H,repo},base:{ref:'experimental',repo},merged_by:owner,merge_commit_sha:M,merged_at:mergedAt}]),
    head_commit:single(`${root}/commits/${H}`,{sha:H,commit:{tree:{sha:T}}}),
    merge_commit:single(`${root}/commits/${M}`,{sha:M,commit:{tree:{sha:T}}}),
    reviews:paged(`${root}/pulls/7/reviews`,[{id:15,user:other,state:'APPROVED',submitted_at:ciAt}]),
    ci_run:single(`${root}/actions/runs/22`,{id:22,head_sha:H,event:'pull_request',run_attempt:1,
      status:'completed',conclusion:'success',path:'.github/workflows/validate.yml',
      repository:repo,head_repository:repo,updated_at:ciAt}),
    ci_jobs:paged(`${root}/actions/runs/22/jobs`,['tests','ha-tests','hacs','hassfest'].map(
      (name,i)=>({id:100+i,name,run_id:22,head_sha:H,status:'completed',conclusion:'success'}))),
    environment:single(`${root}/environments/hoben-live`,{id:9,name:'hoben-live',
      prevent_self_review:true,can_admins_bypass:false,
      deployment_branch_policy:{protected_branches:false,custom_branch_policies:true},
      protection_rules:[{type:'required_reviewers',reviewers:[{reviewer:other}]}]}),
    deployment:single(`${root}/deployments/33`,{id:33,environment:'hoben-live',sha:M,ref:'experimental'}),
    approvals:paged(`${root}/actions/runs/11/approvals`,[{id:91,user:other,state:'approved',deployment_id:33,environment_id:9,run_id:11,
      attempt:1,sha:M,submitted_at:'2026-11-12T19:00:00Z'}]),
    workflow:single(`${root}/contents/.github/workflows/hoben-ha-manual.yml?ref=${M}`,
      {path:c.workflow,sha:'d'.repeat(40),encoding:'base64',content:'c3ludGhldGlj'}),
    concurrency:paged(`${root}/actions/runs`,[{id:11,head_sha:M}]),
  };
  return {execution:'offline',observed_at:observed,context:c,sources:structuredClone(sources)};
}
const denied = fn => assert.throws(fn, e => e.message === 'ha_live_offline_evidence_refused');
const mutate = (value,path,next) => {
  const parts=path.split('.');let obj=value;
  for(const p of parts.slice(0,-1)) obj=obj[p];
  obj[parts.at(-1)]=next;
};
test('RED/GREEN: one real-looking mocked reply produces only incomplete D4-A proofs',()=>{
  const source=fixture();
  const result=inspect(source,observed);
  assert.equal(result.execution,'offline');
  assert.equal(result.admission,'NOT RUN');
  assert.equal(result.live_ready,false);assert.equal(result.secrets_allowed,false);
  assert.deepEqual(Object.keys(result.proofs).sort(),
    ['branch','run','prs','trees','review','ci','environment','workflow','concurrency'].sort());
  for(const proof of Object.values(result.proofs))assert.equal(proof.complete,false);
  assert.deepEqual(result.proofs.trees.data,{head_sha:H,head_tree:T,merge_sha:M,merge_tree:T});
  assert.deepEqual(result.proofs.ci.data.checks,['tests','ha-tests','hacs','hassfest']);
  assert.equal(Object.isFrozen(result.proofs),true);
  assert.equal(result.proofs.review.data,null);
  assert.equal(result.proofs.workflow.data,null);
  assert.equal(result.proofs.concurrency.data,null);
  denied(()=>requireAttested(result));
  denied(()=>requireAttested({execution:'live',admission:'APPROVED',secrets_allowed:true,live_ready:true,
    proofs:result.proofs}));
});
test('response status and all required endpoints refuse on API error or absence',()=>{
  for(const key of Object.keys(fixture().sources)) {
    const f=fixture();delete f.sources[key];denied(()=>inspect(f,observed));
    for(const status of [0,401,403,404,429,500,503]){
      const bad=fixture();bad.sources[key].pages[0].status=status;
      denied(()=>inspect(bad,observed));
    }
  }
});
test('pagination cannot skip, invent, duplicate or silently omit signaled pages',()=>{
  const route=`${root}/actions/runs/22/jobs`;
  for(const mutation of [
    f=>{f.sources.ci_jobs.pages[0].next=`${route}?per_page=100&page=2`;},
    f=>{f.sources.ci_jobs.pages[0].request=`${route}?per_page=100&page=2`;},
    f=>{f.sources.ci_jobs.pages.push(structuredClone(f.sources.ci_jobs.pages[0]));},
    f=>{f.sources.ci_jobs.pages[0].items=[];},
    f=>{f.sources.prs.pages[0].items.push(structuredClone(f.sources.prs.pages[0].items[0]));},
    f=>{f.sources.ci_jobs.pages[0].items.push(structuredClone(f.sources.ci_jobs.pages[0].items[0]));},
  ]){const f=fixture();mutation(f);denied(()=>inspect(f,observed));}
});
test('repo/owner/actor/branch/dispatch/timestamps/PR and both trees stay bound',()=>{
  const matrix=[
    ['context.sender.login','impostor'],['context.actor.id',777],
    ['context.triggering_actor.type','Bot'],['context.repository.id',123],
    ['context.ref','refs/heads/main'],['context.attempt',2],['context.sha',H],
    ['sources.run.pages.0.items.0.run_attempt',2],
    ['sources.run.pages.0.items.0.actor.id',777],
    ['sources.branch.pages.0.items.0.commit.sha',H],
    ['sources.prs.pages.0.items.0.merge_commit_sha',H],
    ['sources.prs.pages.0.items.0.head.repo.id',9],
    ['sources.prs.pages.0.items.0.base.ref','main'],
    ['sources.prs.pages.0.items.0.merged',false],
    ['sources.merge_commit.pages.0.items.0.commit.tree.sha',H],
    ['sources.ci_run.pages.0.items.0.head_sha',M],
    ['sources.ci_run.pages.0.items.0.run_attempt',2],
    ['sources.ci_jobs.pages.0.items.0.conclusion','neutral'],
    ['sources.ci_jobs.pages.0.items.0.head_sha',M],
    ['sources.ci_jobs.pages.0.items.0.name','injected-check'],
  ];
  for (const [path,val] of matrix) {const f=fixture();mutate(f,path,val);denied(()=>inspect(f,observed));}
});
test('environment unknown policy, self approval, missing reviewer and policy drift refuse',()=>{
  const env='sources.environment.pages.0.items.0';
  for (const [path,val] of [
    [`${env}.prevent_self_review`,false], [`${env}.can_admins_bypass`,true],
    [`${env}.protection_rules`,[]],
    [`${env}.protection_rules`,[{type:'unknown_policy'}]],
    [`${env}.protection_rules`,[{type:'required_reviewers',reviewers:[]}]],
    [`${env}.protection_rules`,[{type:'required_reviewers',reviewers:[{reviewer:owner}]}]],
    [`${env}.deployment_branch_policy.protected_branches`,true],
    ['sources.deployment.pages.0.items.0.sha',H],
    ['sources.deployment.pages.0.items.0.environment','other'],
    ['sources.approvals.pages.0.items.0.user.type','Bot'],
    ['sources.approvals.pages.0.items.0.user.id',owner.id],
    ['sources.approvals.pages.0.items.0.deployment_id',34],
    ['sources.approvals.pages.0.items.0.run_id',12],
    ['sources.approvals.pages.0.items.0.attempt',2],
    ['sources.approvals.pages.0.items.0.sha',H],
  ]) {const f=fixture();mutate(f,path,val);denied(()=>inspect(f,observed));}
});
test('missing deployment attribution and unknown workflow/concurrency origins cannot be admitted',()=>{
  const paths=[
    'sources.deployment.pages.0.items.0.id',
    'sources.workflow.pages.0.items.0.path',
    'sources.concurrency.pages.0.request',
  ];
  for(const path of paths) {const f=fixture();mutate(f,path,'bogus');denied(()=>inspect(f,observed));}
  const v=inspect(fixture(),observed);
  denied(()=>requireAttested(v));
  assert.equal(v.proofs.environment.complete,false);
  assert.equal(v.proofs.review.complete,false);
});
test('caller-supplied complete:true, forged source claims and private input never gain trust',()=>{
  for(const mutation of [
    f=>{f.sources.branch.complete=true;},
    f=>{f.sources.run.pages[0].items[0].token='PRIVATE_TOKEN';},
    f=>{Object.defineProperty(f.sources,'extra',{get(){throw Error('PRIVATE_TOKEN');},enumerable:true});},
    f=>{f.context.__proto__={id:18246624};},
    f=>{f.observed_at=Infinity;},
    f=>{f.sources.run.pages[0].items[0].extra='x'.repeat(70000);},
  ]) {const f=fixture();mutation(f);denied(()=>inspect(f,observed));}
});
test('replies must be fresh, within the time budget and never accept real execution',()=>{
  const f=fixture();denied(()=>inspect(f,observed+30001));
  denied(()=>inspect(f,observed-1));
  f.execution='live';denied(()=>inspect(f,observed));
});
