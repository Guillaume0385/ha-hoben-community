'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const file='../../.github/scripts/ha-live-gate-contract.cjs';
test('offline contract exists without a live admission entry point',()=>{
  const gate=require(file);
  assert.equal(gate.EXECUTION,'offline');
  assert.equal(gate.verify,undefined);
  assert.equal(gate.main,undefined);
});
const {OfflineClaims}=require(file);
const clone=v=>structuredClone(v), M='a'.repeat(40), H='b'.repeat(40), T='c'.repeat(40);
const owner={id:18246624,login:'Guillaume0385',type:'User'};
const reviewer={id:99,login:'offline-reviewer',type:'User'};
const repo={id:1401398724,full_name:'Guillaume0385/ha-hoben-community'};
const wrap=data=>({status:200,complete:true,data});
function fixture(){
  const before={execution:'offline',observed_at:1000,context:{repository:repo,sender:owner,actor:owner,
    triggering_actor:owner,event:'workflow_dispatch',ref:'refs/heads/experimental',sha:M,run_id:11,
    attempt:1,scenario:'hoben-live',workflow:'.github/workflows/hoben-ha-manual.yml'},proofs:{
    branch:wrap({name:'experimental',protected:true,sha:M}),
    run:wrap({id:11,event:'workflow_dispatch',attempt:1,sha:M,branch:'experimental',repository:repo,
      head_repository:repo,actor:owner,triggering_actor:owner,path:'.github/workflows/hoben-ha-manual.yml',created_at:900}),
    prs:wrap([{number:7,merged:true,state:'closed',draft:false,head_sha:H,head_branch:'codex/offline',
      merge_sha:M,base_ref:'experimental',base_repo:repo,head_repo:repo,merged_by:owner,merged_at:800}]),
    trees:wrap({head_sha:H,head_tree:T,merge_sha:M,merge_tree:T}),
    review:wrap({kind:'manager_decision',author:owner,decision:'APPROVED',pr:7,head_sha:H,ci_run_id:22,
      created_at:700,updated_at:700,unresolved_threads:0,changes_requested:false}),
    ci:wrap({id:22,head_sha:H,head_branch:'codex/offline',event:'pull_request',attempt:1,status:'completed',
      conclusion:'success',path:'.github/workflows/validate.yml',repository:repo,head_repository:repo,updated_at:600,
      jobs:['tests','ha-tests','hacs','hassfest'].map(name=>({name,run_id:22,head_sha:H,status:'completed',conclusion:'success'}))}),
    environment:wrap({id:9,name:'hoben-live',protected_branches:false,custom_branch_policies:true,
      branches:[{id:6,name:'experimental',type:'branch'}],reviewers:[reviewer],prevent_self_review:true,
      can_admins_bypass:false,wait_minutes:0}),
    workflow:wrap({path:'.github/workflows/hoben-ha-manual.yml',commit_sha:M,trigger:'workflow_dispatch',
      environment:'hoben-live',group:'hoben-read-only-observation',cancel_in_progress:false,
      order:['preflight','claim','environment','recheck','secrets','worker']}),
    concurrency:wrap({group:'hoben-read-only-observation',runs:[]})}};
  const after=clone(before);after.observed_at=2000;
  const approval=wrap({environment_id:9,run_id:11,attempt:1,sha:M,job:'collect',deployment_id:33,entered_at:1500,
    approvals:[{state:'approved',reviewer,environment_id:9,deployment_id:33,run_id:11,attempt:1,sha:M,at:1200}]});
  return clone({before,after,approval});
}
function complete(f=fixture(),store=new OfflineClaims()){
  const ticket=store.reserve(f.before,1000);
  return store.recheck(ticket,f.after,f.approval,2000);
}
const denied=f=>assert.throws(f,e=>e instanceof Error&&e.message==='ha_live_offline_contract_refused');
function put(value,path,data){const parts=path.split('.');const k=parts.pop();let node=value;for(const p of parts)node=node[p];node[k]=data;}
class MockGitHub {
  constructor(f){this.f=f;this.calls=[];this.error=null;}
  get(phase,key){this.calls.push([phase,key]);if(this.error===key)throw Error('PRIVATE_API_TOKEN');return clone(this.f[phase].proofs[key]);}
  collect(phase){const s=clone(this.f[phase]);for(const key of Object.keys(s.proofs)){
    try{s.proofs[key]=this.get(phase,key);}catch(_){s.proofs[key]={status:403,complete:false,data:null};}
  }return s;}
}
test('complete mock proof chain is still NOT RUN and cannot authorize a secret',()=>{
  const f=fixture(),api=new MockGitHub(f),store=new OfflineClaims();
  const ticket=store.reserve(api.collect('before'),1000);
  const r=store.recheck(ticket,api.collect('after'),f.approval,2000);
  assert.equal(r.simulation,'ACCEPTED');assert.equal(r.admission,'NOT RUN');assert.equal(r.execution,'offline');
  assert.equal(r.live_ready,false);assert.equal(r.secrets_allowed,false);assert.equal(Object.isFrozen(r),true);
  assert.match(r.binding_digest,/^[a-f0-9]{64}$/);assert.equal(api.calls.length,18);
});
const negatives=[
 ['execution','live'],['observed_at',-1],['context.event','push'],['context.ref','refs/heads/main'],
 ['context.attempt',2],['context.run_id',0],['context.sha',H],['context.scenario','all'],
 ['context.repository.id',1],['context.repository.full_name','other/repo'],['context.sender.type','Bot'],
 ['context.actor.login','someone-else'],['context.triggering_actor.id',99],
 ['context.workflow','.github/workflows/hoben-manual.yml'],
 ['proofs.branch.data.sha',H],['proofs.branch.data.protected',false],
 ['proofs.run.data.actor.id',99],['proofs.run.data.triggering_actor.login','other'],
 ['proofs.run.data.repository.id',99],['proofs.run.data.head_repository.id',99],
 ['proofs.run.data.sha',H],['proofs.run.data.attempt',2],['proofs.run.data.created_at',1001],
 ['proofs.run.data.path','.github/workflows/hoben-ha-manual.yml@refs/heads/main'],
 ['proofs.prs.data.0.merged',false],['proofs.prs.data.0.state','open'],['proofs.prs.data.0.draft',true],
 ['proofs.prs.data.0.merge_sha',H],['proofs.prs.data.0.base_ref','main'],['proofs.prs.data.0.merged_by.id',99],
 ['proofs.prs.data.0.base_repo.id',99],['proofs.prs.data.0.head_repo.id',99],['proofs.prs.data.0.merged_at',901],
 ['proofs.trees.data.head_sha',M],['proofs.trees.data.merge_tree',H],['proofs.trees.data.merge_sha',H],
 ['proofs.review.data.kind','environment_status'],['proofs.review.data.author.id',99],
 ['proofs.review.data.decision','CHANGES_REQUESTED'],['proofs.review.data.head_sha',M],
 ['proofs.review.data.pr',8],['proofs.review.data.ci_run_id',23],['proofs.review.data.updated_at',701],
 ['proofs.review.data.created_at',801],['proofs.review.data.unresolved_threads',1],['proofs.review.data.changes_requested',true],
 ['proofs.ci.data.head_sha',M],['proofs.ci.data.status','in_progress'],['proofs.ci.data.conclusion','failure'],
 ['proofs.ci.data.attempt',2],['proofs.ci.data.event','push'],['proofs.ci.data.head_branch','main'],
 ['proofs.ci.data.updated_at',701],['proofs.ci.data.path','.github/workflows/untrusted.yml'],
 ['proofs.ci.data.jobs.0.head_sha',M],['proofs.ci.data.jobs.0.run_id',23],
 ['proofs.ci.data.jobs.0.conclusion','neutral'],['proofs.ci.data.jobs.1.name','tests'],
 ['proofs.environment.data.name','hoben-experimental'],['proofs.environment.data.can_admins_bypass',true],
 ['proofs.environment.data.protected_branches',true],['proofs.environment.data.custom_branch_policies',false],
 ['proofs.environment.data.branches.0.name','main'],['proofs.environment.data.branches.0.type','tag'],
 ['proofs.environment.data.wait_minutes',-1],['proofs.environment.data.reviewers',[]],
 ['proofs.environment.data.prevent_self_review',false],
 ['proofs.environment.data.reviewers.0.id',18246624],
 ['proofs.environment.data.reviewers.0.type','Team'],
 ['proofs.workflow.data.commit_sha',H],['proofs.workflow.data.trigger','push'],
 ['proofs.workflow.data.environment','hoben-experimental'],['proofs.workflow.data.cancel_in_progress',true],
 ['proofs.workflow.data.group','unshared-mutex'],['proofs.workflow.data.order',['preflight','secrets','recheck']],
 ['proofs.concurrency.data.group','unshared-mutex'],['proofs.concurrency.data.runs',[{id:44}]],
];
for(const [path,value] of negatives)test('refuse '+path+' = '+JSON.stringify(value),()=>{
  const f=fixture();put(f.before,path,value);denied(()=>new OfflineClaims().reserve(f.before,1000));
});
for(const key of Object.keys(fixture().before.proofs)){
  for(const status of [401,403,404,429,500])test('API refusal '+key+'/'+status,()=>{
    const f=fixture();f.before.proofs[key].status=status;denied(()=>new OfflineClaims().reserve(f.before,1000));
  });
  test('missing/incomplete/API token error '+key,()=>{
    let f=fixture();delete f.before.proofs[key];denied(()=>new OfflineClaims().reserve(f.before,1000));
    f=fixture();f.before.proofs[key].complete=false;denied(()=>new OfflineClaims().reserve(f.before,1000));
    const api=new MockGitHub(f);api.error=key;f.before=api.collect('before');denied(()=>new OfflineClaims().reserve(f.before,1000));
  });
}
for(const name of ['tests','ha-tests','hacs','hassfest'])test('mandatory exact check '+name,()=>{
  const f=fixture();f.before.proofs.ci.data.jobs=f.before.proofs.ci.data.jobs.filter(j=>j.name!==name);denied(()=>new OfflineClaims().reserve(f.before,1000));
});
for(const [path,value] of [
 ['data.environment_id',8],['data.run_id',12],['data.attempt',2],['data.sha',H],['data.job','admission'],
 ['data.entered_at',999],['data.entered_at',2001],['data.deployment_id',0],
 ['data.approvals',[]],['data.approvals.0.reviewer.id',18246624],
 ['data.approvals.0.state','rejected'],['data.approvals.0.reviewer.id',99],
 ['data.approvals.0.environment_id',8],['data.approvals.0.deployment_id',34],
 ['data.approvals.0.run_id',12],['data.approvals.0.attempt',2],['data.approvals.0.sha',H],
 ['data.approvals.0.at',999],['data.approvals.0.at',1501],['status',403]
])test('attempt approval binding '+path,()=>{const f=fixture();put(f.approval,path,value);denied(()=>complete(f));});
test('environment status alone never proves approval; duplicate approval is ambiguous',()=>{
  let f=fixture();f.approval={status:200,complete:true,data:{status:'approved'}};denied(()=>complete(f));
  f=fixture();f.approval.data.approvals.push(clone(f.approval.data.approvals[0]));denied(()=>complete(f));
  f=fixture();for(const s of [f.before,f.after])s.proofs.environment.data.reviewers=[owner];
  denied(()=>complete(f));
});
test('empty reviewers and absent positive approval refuse, never ACCEPTED',()=>{
  const f=fixture();for(const s of [f.before,f.after])s.proofs.environment.data.reviewers=[];
  f.approval.data.approvals=[];denied(()=>complete(f));
});
test('configured owner cannot approve own dispatch even alongside eligible independent reviewer',()=>{
  const f=fixture();for(const s of [f.before,f.after])s.proofs.environment.data.reviewers=[owner,reviewer];
  f.approval.data.approvals[0].reviewer=owner;denied(()=>complete(f));
});
test('missing independent reviewer and non-protective self review policy refuse before claim',()=>{
  for(const change of [
    e=>{e.reviewers=[owner];},
    e=>{e.reviewers=[];},
    e=>{e.prevent_self_review=false;},
  ]){
    const f=fixture();change(f.before.proofs.environment.data);
    denied(()=>new OfflineClaims().reserve(f.before,1000));
  }
});
test('wait timer is enforced and preflight may wait without rearming recheck freshness',()=>{
  const f=fixture();for(const s of [f.before,f.after])s.proofs.environment.data.wait_minutes=1;
  denied(()=>complete(f));f.approval.data.entered_at=61000;f.after.observed_at=62000;
  const store=new OfflineClaims(),ticket=store.reserve(f.before,1000);
  assert.equal(store.recheck(ticket,f.after,f.approval,62000).admission,'NOT RUN');
});
test('recheck catches branch/policy/CI/workflow drift after approval',()=>{
  for(const path of ['proofs.branch.data.sha','proofs.ci.data.head_sha','proofs.environment.data.id','proofs.workflow.data.commit_sha']){
    const f=fixture();put(f.after,path,path.endsWith('.id')?10:T);denied(()=>complete(f));
  }
});

test('policy drift between preflight and recheck burns the ticket even on valid restoration',()=>{
  const policyChanges=[
    ['proofs.environment.data.reviewers',[]],
    ['proofs.environment.data.reviewers',[owner]],
    ['proofs.environment.data.reviewers',[owner,reviewer]],
    ['proofs.environment.data.prevent_self_review',false],
    ['proofs.environment.data.id',10],
    ['proofs.environment.data.name','other-environment'],
    ['proofs.environment.data.branches.0.id',7],
    ['proofs.environment.data.wait_minutes',1],
    ['proofs.environment.data.can_admins_bypass',true],
    ['proofs.environment.data.reviewers.0.login','changed-reviewer'],
    ['context.sha',H],
    ['context.attempt',2],
    ['proofs.run.data.id',12],
    ['proofs.workflow.data.commit_sha',H],
  ];
  for(const [path,value] of policyChanges){
    const f=fixture(),store=new OfflineClaims(),ticket=store.reserve(f.before,1000);
    const changed=clone(f.after);put(changed,path,value);
    denied(()=>store.recheck(ticket,changed,f.approval,2000));
    denied(()=>store.recheck(ticket,f.after,f.approval,2000));
    denied(()=>store.reserve(f.before,2000));
  }
});
test('missing or changed deployment-specific approval burns claim before any replay',()=>{
  for(const mutate of [
    a=>{a.data.approvals=[];},
    a=>{a.data.approvals[0].deployment_id=34;},
    a=>{a.data.approvals[0].run_id=12;},
    a=>{a.data.approvals[0].sha=H;},
    a=>{a.data.approvals[0].attempt=2;},
    a=>{a.data.approvals[0].reviewer=owner;},
  ]){
    const f=fixture(),store=new OfflineClaims(),ticket=store.reserve(f.before,1000);
    const changed=clone(f.approval);mutate(changed);
    denied(()=>store.recheck(ticket,f.after,changed,2000));
    denied(()=>store.recheck(ticket,f.after,f.approval,2000));
  }
});
test('stale and future observations and clock rollback refuse',()=>{
  const f=fixture(),store=new OfflineClaims();denied(()=>new OfflineClaims().reserve(f.before,31001));
  const ticket=store.reserve(f.before,31000); // 30-second boundary is inclusive.
  denied(()=>store.recheck(ticket,f.after,f.approval,2000));
  denied(()=>new OfflineClaims().reserve(f.before,999));
});
test('claim compare-and-insert has one winner for simultaneous runs and cannot replay',async()=>{
  const store=new OfflineClaims();const attempts=await Promise.allSettled(Array.from({length:20},(_,i)=>Promise.resolve().then(()=>{
    const f=fixture();f.before.context.run_id=100+i;f.before.proofs.run.data.id=100+i;
    return store.reserve(f.before,1000);
  })));
  assert.equal(attempts.filter(r=>r.status==='fulfilled').length,1);
  assert.equal(attempts.filter(r=>r.status==='rejected').length,19);
  denied(()=>store.reserve(fixture().before,1000));
});
test('ticket is private to this ledger and snapshot; failed recheck burns the simulation',()=>{
  const f=fixture(),store=new OfflineClaims(),ticket=store.reserve(f.before,1000);
  denied(()=>new OfflineClaims().recheck(ticket,f.after,f.approval,2000));
  denied(()=>store.recheck(clone(ticket),f.after,f.approval,2000));
  const bad=clone(f.after);bad.proofs.run.status=403;
  denied(()=>store.recheck(ticket,bad,f.approval,2000));
  denied(()=>store.recheck(ticket,f.after,f.approval,2000));
});
test('successful simulation is one use and cannot be relabelled into live',()=>{
  const f=fixture(),store=new OfflineClaims(),ticket=store.reserve(f.before,1000);
  const result=store.recheck(ticket,f.after,f.approval,2000);
  denied(()=>store.recheck(ticket,f.after,f.approval,2000));
  assert.throws(()=>{result.admission='APPROVED';},TypeError);
  f.before.execution='live';denied(()=>new OfflineClaims().reserve(f.before,2000));
});
test('unknown fields, prototypes, getters, cycles, oversize and free errors never escape',()=>{
  for(const corrupt of [
    f=>{f.before.extra='PRIVATE_API_TOKEN';},
    f=>{f.before.proofs.run.data.extra='PRIVATE_API_TOKEN';},
    f=>{Object.defineProperty(f.before,'extra',{get(){throw Error('PRIVATE_API_TOKEN');},enumerable:true});},
    f=>{f.before.context.actor=Object.create({login:'Guillaume0385'});},
    f=>{f.before.extra=f.before;},f=>{f.before.context.sha='x'.repeat(65537);},
  ]){const f=fixture();corrupt(f);denied(()=>complete(f));}
});
test('copy protects reserved facts from mutation and property order is immaterial',()=>{
  const f=fixture(),store=new OfflineClaims(),ticket=store.reserve(f.before,1000);
  f.before.context.sha=H;
  f.after.context.repository={full_name:repo.full_name,id:repo.id};
  assert.equal(store.recheck(ticket,f.after,f.approval,2000).simulation,'ACCEPTED');
});

test('independent configured reviewer satisfies prevent-self-review',()=>{
  const f=fixture();
  for(const s of [f.before,f.after]){
    s.proofs.environment.data.reviewers=[owner,reviewer];
    s.proofs.environment.data.prevent_self_review=true;
  }
  f.approval.data.approvals[0].reviewer=reviewer;
  assert.equal(complete(f).admission,'NOT RUN');
});
test('ambiguous PR, checks, branches, policy rules and numeric types refuse',()=>{
  for(const mutate of [
    s=>s.proofs.prs.data.push(clone(s.proofs.prs.data[0])),
    s=>s.proofs.ci.data.jobs.push(clone(s.proofs.ci.data.jobs[0])),
    s=>s.proofs.environment.data.branches.push({id:7,name:'main',type:'branch'}),
    s=>{s.proofs.environment.data.unknown_rule={enabled:true};},
    s=>{s.proofs.ci.data.jobs[0].status='in_progress';},
    s=>{s.proofs.ci.data.jobs[0].conclusion='skipped';},
    s=>{s.context.attempt='1';},s=>{s.context.run_id=Number.MAX_SAFE_INTEGER+1;},
    s=>{s.observed_at=NaN;},s=>{s.observed_at=Infinity;},s=>{s.observed_at=1000.1;},
    s=>{s.proofs.environment.data.reviewers.push(clone(owner));},
  ]){const f=fixture();mutate(f.before);denied(()=>new OfflineClaims().reserve(f.before,1000));}
});
test('all post-approval endpoints are required and fresh, including mutex',()=>{
  for(const key of Object.keys(fixture().after.proofs)){
    const f=fixture();f.after.proofs[key].status=503;denied(()=>complete(f));
  }
  const f=fixture(),store=new OfflineClaims(),ticket=store.reserve(f.before,1000);
  denied(()=>store.recheck(ticket,f.after,f.approval,32001));
});
test('freshness endpoint is inclusive and ledger capacity never evicts a claim',()=>{
  const f=fixture(),store=new OfflineClaims();
  for(let i=0;i<64;i++){
    const s=clone(f.before),m=i.toString(16).padStart(40,'0');
    s.context.sha=m;s.proofs.branch.data.sha=m;s.proofs.run.data.sha=m;
    s.proofs.prs.data[0].merge_sha=m;s.proofs.trees.data.merge_sha=m;
    s.proofs.workflow.data.commit_sha=m;
    store.reserve(s,31000);
  }
  denied(()=>store.reserve(f.before,31000));
});
