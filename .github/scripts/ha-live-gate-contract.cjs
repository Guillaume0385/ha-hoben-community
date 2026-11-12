'use strict';
// #207 D4-A: data-only contract/simulator. No GitHub client, secret or live grant.
const {createHash}=require('node:crypto');
const {workflowPath}=require('./experimental-lab-gate.cjs'); // pure helper only
const EXECUTION='offline', REPO='Guillaume0385/ha-hoben-community';
const FILE='.github/workflows/hoben-ha-manual.yml', REF='refs/heads/experimental';
const GROUP='hoben-read-only-observation', CONTRACT='hoben-207-ha-live-admission-v1';
const CHECKS=Object.freeze(['tests','ha-tests','hacs','hassfest']);
const PROOFS=Object.freeze(['branch','run','prs','trees','review','ci','environment','workflow','concurrency']);
const ORDER=Object.freeze(['preflight','claim','environment','recheck','secrets','worker']);
const refused=()=>{throw Error('ha_live_offline_contract_refused');};
const need=v=>{if(!v)refused();};
const positive=v=>Number.isSafeInteger(v)&&v>0;
const instant=v=>Number.isSafeInteger(v)&&v>=0;
const sha=v=>typeof v==='string'&&/^[a-f0-9]{40}$/.test(v);
const keys=(v,k)=>{
  need(v!==null&&typeof v==='object'&&!Array.isArray(v));
  need(Object.keys(v).sort().join() === [...k].sort().join());
};
const canonical=v=>v!==null&&typeof v==='object'
  ?(Array.isArray(v)?v.map(canonical):Object.fromEntries(Object.keys(v).sort().map(k=>[k,canonical(v[k])]))):v;
const encode=v=>JSON.stringify(canonical(v));
const same=(a,b)=>encode(a)===encode(b);
function copy(value){
  let nodes=0;
  const seen=new Set();
  function visit(v,depth){
    need(++nodes<=4096&&depth<=12);
    if(v===null||typeof v==='boolean')return;
    if(typeof v==='number'){need(Number.isSafeInteger(v));return;}
    if(typeof v==='string'){need(v.length<=1024);return;}
    need(typeof v==='object'&&!seen.has(v)); seen.add(v);
    need(Array.isArray(v)||[Object.prototype,null].includes(Object.getPrototypeOf(v)));
    need(Object.getOwnPropertySymbols(v).length===0);
    for(const [k,d] of Object.entries(Object.getOwnPropertyDescriptors(v))){
      need(!['__proto__','constructor','prototype'].includes(k)&&Object.hasOwn(d,'value'));
      visit(d.value,depth+1);
    }
    seen.delete(v);
  }
  visit(value,0);
  const text=JSON.stringify(value);need(Buffer.byteLength(text)<=65536);
  return JSON.parse(text);
}
function repository(r){keys(r,['id','full_name']);need(r.id===1401398724&&r.full_name===REPO);}
function user(u){
  keys(u,['id','login','type']);
  need(positive(u.id)&&typeof u.login==='string'&&/^[A-Za-z0-9-]{1,39}$/.test(u.login)&&u.type==='User');
}
function owner(u){user(u);need(u.id===18246624&&u.login==='Guillaume0385');}
function proof(p){keys(p,['status','complete','data']);need(p.status===200&&p.complete===true);return p.data;}
function snapshot(raw,now){
  const s=copy(raw);keys(s,['execution','observed_at','context','proofs']);
  need(s.execution===EXECUTION&&instant(now)&&instant(s.observed_at)&&
    s.observed_at<=now&&now-s.observed_at<=30000);
  const c=s.context;
  keys(c,['repository','sender','actor','triggering_actor','event','ref','sha','run_id','attempt','scenario','workflow']);
  repository(c.repository);owner(c.sender);owner(c.actor);owner(c.triggering_actor);
  need(c.event==='workflow_dispatch'&&c.ref===REF&&sha(c.sha)&&positive(c.run_id)&&
    c.attempt===1&&c.scenario==='hoben-live'&&c.workflow===FILE);
  keys(s.proofs,PROOFS);
  const facts=Object.fromEntries(PROOFS.map(k=>[k,proof(s.proofs[k])]));
  const {branch,run,prs,trees,review,ci,environment:e,workflow:w,concurrency}=facts;
  keys(branch,['name','protected','sha']);
  need(branch.name==='experimental'&&branch.protected===true&&branch.sha===c.sha);
  keys(run,['id','event','attempt','sha','branch','repository','head_repository','actor','triggering_actor','path','created_at']);
  repository(run.repository);repository(run.head_repository);owner(run.actor);owner(run.triggering_actor);
  need(run.id===c.run_id&&run.event===c.event&&run.attempt===1&&run.sha===c.sha&&
    run.branch==='experimental'&&workflowPath(run.path,FILE,[REF])&&
    instant(run.created_at)&&run.created_at<=s.observed_at);
  need(Array.isArray(prs)&&prs.length===1);const pr=prs[0];
  keys(pr,['number','merged','state','draft','head_sha','head_branch','merge_sha','base_ref','base_repo','head_repo','merged_by','merged_at']);
  repository(pr.base_repo);repository(pr.head_repo);owner(pr.merged_by);
  need(positive(pr.number)&&pr.merged===true&&pr.state==='closed'&&pr.draft===false&&
    sha(pr.head_sha)&&typeof pr.head_branch==='string'&&pr.head_branch.length>0&&
    pr.merge_sha===c.sha&&pr.base_ref==='experimental'&&instant(pr.merged_at)&&pr.merged_at<=run.created_at);
  keys(trees,['head_sha','head_tree','merge_sha','merge_tree']);
  need(trees.head_sha===pr.head_sha&&trees.merge_sha===c.sha&&sha(trees.head_tree)&&trees.head_tree===trees.merge_tree);
  keys(review,['kind','author','decision','pr','head_sha','ci_run_id','created_at','updated_at','unresolved_threads','changes_requested']);
  owner(review.author);
  need(review.kind==='manager_decision'&&review.decision==='APPROVED'&&review.pr===pr.number&&
    review.head_sha===pr.head_sha&&positive(review.ci_run_id)&&instant(review.created_at)&&
    review.updated_at===review.created_at&&review.created_at<=pr.merged_at&&
    review.unresolved_threads===0&&review.changes_requested===false);
  keys(ci,['id','head_sha','head_branch','event','attempt','status','conclusion','path','repository','head_repository','updated_at','jobs']);
  repository(ci.repository);repository(ci.head_repository);
  need(ci.id===review.ci_run_id&&ci.head_sha===pr.head_sha&&ci.head_branch===pr.head_branch&&
    ci.event==='pull_request'&&ci.attempt===1&&ci.status==='completed'&&ci.conclusion==='success'&&
    workflowPath(ci.path,'.github/workflows/validate.yml',['refs/pull/'+pr.number+'/merge',pr.head_branch,'refs/heads/'+pr.head_branch])&&
    instant(ci.updated_at)&&ci.updated_at<=review.created_at&&Array.isArray(ci.jobs)&&ci.jobs.length===4);
  for(const name of CHECKS){
    const matches=ci.jobs.filter(j=>j.name===name);need(matches.length===1);
    const j=matches[0];keys(j,['name','run_id','head_sha','status','conclusion']);
    need(j.run_id===ci.id&&j.head_sha===pr.head_sha&&j.status==='completed'&&j.conclusion==='success');
  }
  keys(e,['id','name','protected_branches','custom_branch_policies','branches','reviewers','prevent_self_review','can_admins_bypass','wait_minutes']);
  need(positive(e.id)&&e.name==='hoben-live'&&e.protected_branches===false&&e.custom_branch_policies===true&&
    e.can_admins_bypass===false&&e.prevent_self_review===true&&
    Number.isSafeInteger(e.wait_minutes)&&e.wait_minutes>=0&&e.wait_minutes<=43200&&
    Array.isArray(e.branches)&&e.branches.length===1&&Array.isArray(e.reviewers)&&
    e.reviewers.length>0&&e.reviewers.length<=6);
  keys(e.branches[0],['id','name','type']);
  need(positive(e.branches[0].id)&&e.branches[0].name==='experimental'&&e.branches[0].type==='branch');
  e.reviewers.forEach(user);
  need(new Set(e.reviewers.map(u=>u.id)).size===e.reviewers.length&&
    e.reviewers.some(u=>u.id!==c.actor.id)); // A protected gate requires an eligible independent reviewer.
  keys(w,['path','commit_sha','trigger','environment','group','cancel_in_progress','order']);
  need(w.path===FILE&&w.commit_sha===c.sha&&w.trigger==='workflow_dispatch'&&w.environment==='hoben-live'&&
    w.group===GROUP&&w.cancel_in_progress===false&&same(w.order,ORDER));
  keys(concurrency,['group','runs']);need(concurrency.group===GROUP&&Array.isArray(concurrency.runs)&&concurrency.runs.length===0);
  // Dynamic approval and collection timestamps are checked separately. Everything
  // else is bound to the immutable preflight; post-approval drift denies.
  return {snapshot:s,c,run,pr,environment:e,binding:encode([c,...PROOFS.filter(k=>k!=='concurrency').map(k=>facts[k])])};
}
function approved(raw,before,after){
  const a=proof(copy(raw));keys(a,['environment_id','run_id','attempt','sha','job','deployment_id','entered_at','approvals']);
  need(a.environment_id===after.environment.id&&a.run_id===after.c.run_id&&a.attempt===1&&
    a.sha===after.c.sha&&a.job==='collect'&&positive(a.deployment_id)&&instant(a.entered_at)&&
    a.entered_at>=before.snapshot.observed_at+after.environment.wait_minutes*60000&&a.entered_at<=after.snapshot.observed_at&&Array.isArray(a.approvals));
  // No policy may substitute missing human approval with a successful simulation.
  need(a.approvals.length===1);const v=a.approvals[0];
  keys(v,['state','reviewer','environment_id','deployment_id','run_id','attempt','sha','at']);user(v.reviewer);
  need(v.state==='approved'&&v.environment_id===a.environment_id&&v.deployment_id===a.deployment_id&&
    v.run_id===a.run_id&&v.attempt===1&&v.sha===a.sha&&instant(v.at)&&
    v.at>=before.snapshot.observed_at&&v.at<=a.entered_at&&
    after.environment.reviewers.some(u=>same(u,v.reviewer))&&
    v.reviewer.id!==after.c.actor.id);
}
class OfflineClaims {
  #claims=new Map(); #tickets=new WeakMap(); #last=0;
  #clock(now){need(instant(now)&&now>=this.#last);this.#last=now;}
  reserve(raw,now){
    try{
      this.#clock(now);const before=snapshot(raw,now);
      const key=CONTRACT+':'+before.c.sha;
      need(this.#claims.size<64&&!this.#claims.has(key));
      const ticket=Object.freeze({execution:EXECUTION,admission:'NOT RUN',secrets_allowed:false});
      const entry={before,key,state:'reserved'};
      // Synchronous check+insert models create-if-absent; never a real git ref.
      this.#claims.set(key,entry);this.#tickets.set(ticket,entry);return ticket;
    }catch(_){refused();}
  }
  recheck(ticket,raw,approval,now){
    const entry=this.#tickets.get(ticket);
    try{
      this.#clock(now);need(entry&&entry.state==='reserved'&&this.#claims.get(entry.key)===entry);
      const after=snapshot(raw,now);need(after.binding===entry.before.binding&&after.snapshot.observed_at>=entry.before.snapshot.observed_at);
      approved(approval,entry.before,after);
      entry.state='consumed';
      return Object.freeze({schema:1,execution:EXECUTION,contract:CONTRACT,simulation:'ACCEPTED',
        admission:'NOT RUN',secrets_allowed:false,live_ready:false,
        binding_digest:createHash('sha256').update(after.binding).digest('hex')});
    }catch(_){if(entry)entry.state='failed';refused();}
  }
}
module.exports=Object.freeze({OfflineClaims,EXECUTION});
