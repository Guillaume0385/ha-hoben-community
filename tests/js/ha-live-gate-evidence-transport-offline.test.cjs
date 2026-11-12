'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {collect} = require('../../.github/scripts/ha-live-gate-evidence-transport-offline.cjs');
const {inspect,requireAttested} = require('../../.github/scripts/ha-live-gate-evidence-offline.cjs');
const API = 'https://api.github.com';
const root = '/repos/Guillaume0385/ha-hoben-community';
const M = 'a'.repeat(40), H = 'b'.repeat(40), T = 'c'.repeat(40);
const owner = {id:18246624, login:'Guillaume0385', type:'User'};
const other = {id:98, login:'independent', type:'User'};
const repo = {id:1401398724, full_name:'Guillaume0385/ha-hoben-community', owner};
const time = '2026-11-12T19:00:00Z';
const now = Date.parse(time) + 1000;
const c = {repository:{id:repo.id,full_name:repo.full_name},sender:owner,actor:owner,
  triggering_actor:owner,event:'workflow_dispatch',ref:'refs/heads/experimental',sha:M,
  run_id:11,attempt:1,scenario:'hoben-live',workflow:'.github/workflows/hoben-ha-manual.yml',
  pr_number:7,pr_head_sha:H,ci_run_id:22,deployment_id:33};
const singleton = (path, body) => ({path, body});
const list = (path, body) => ({path:`${path}?per_page=100&page=1`, body});
function replies() {
  return {
    branch:singleton(`${root}/branches/experimental`,{name:'experimental',protected:true,commit:{sha:M}}),
    run:singleton(`${root}/actions/runs/11`,{id:11,run_attempt:1,event:'workflow_dispatch',head_sha:M,
      head_branch:'experimental',path:c.workflow,repository:repo,head_repository:repo,actor:owner,
      triggering_actor:owner,created_at:time}),
    prs:list(`${root}/commits/${M}/pulls`,[{number:7,merged:true,state:'closed',draft:false,
      head:{sha:H,repo},base:{ref:'experimental',repo},merged_by:owner,merge_commit_sha:M,
      merged_at:'2026-11-12T18:55:00Z'}]),
    head_commit:singleton(`${root}/commits/${H}`,{sha:H,commit:{tree:{sha:T}}}),
    merge_commit:singleton(`${root}/commits/${M}`,{sha:M,commit:{tree:{sha:T}}}),
    reviews:list(`${root}/pulls/7/reviews`,[{id:15,user:other,state:'APPROVED'}]),
    ci_run:singleton(`${root}/actions/runs/22`,{id:22,head_sha:H,event:'pull_request',run_attempt:1,
      status:'completed',conclusion:'success',path:'.github/workflows/validate.yml',
      repository:repo,head_repository:repo,updated_at:'2026-11-12T18:50:00Z'}),
    ci_jobs:list(`${root}/actions/runs/22/jobs`,['tests','ha-tests','hacs','hassfest'].map(
      (name,i)=>({id:100+i,name,run_id:22,head_sha:H,status:'completed',conclusion:'success'}))),
    environment:singleton(`${root}/environments/hoben-live`,{id:9,name:'hoben-live',
      prevent_self_review:true,can_admins_bypass:false,
      deployment_branch_policy:{protected_branches:false,custom_branch_policies:true},
      protection_rules:[{type:'required_reviewers',reviewers:[{reviewer:other}]}]}),
    deployment:singleton(`${root}/deployments/33`,{id:33,environment:'hoben-live',sha:M,ref:'experimental'}),
    approvals:list(`${root}/actions/runs/11/approvals`,[{id:91,user:other,state:'approved',
      deployment_id:33,environment_id:9,run_id:11,attempt:1,sha:M,submitted_at:time}]),
    workflow:singleton(`${root}/contents/.github/workflows/hoben-ha-manual.yml?ref=${M}`,
      {path:c.workflow,sha:'d'.repeat(40),encoding:'base64',content:'c3ludGhldGlj'}),
    concurrency:list(`${root}/actions/runs`,[{id:11,head_sha:M}]),
  };
}
function fake(options = {}) {
  const entries = replies();
  const paths = new Map(Object.values(entries).map(v => [API+v.path,v.body]));
  const calls = [];
  const transport = {request:async ({method,url,signal}) => {
    calls.push({method,url});
    if (options.pending === url) return new Promise(() => {});
    if (options.abort === url) return new Promise((resolve,reject) => {
      signal.addEventListener('abort',()=>reject(Error('private_abort_detail')),{once:true});
    });
    if (!paths.has(url)) throw Error('PRIVATE_ROUTE');
    const headers = {'content-type':'application/json',date:new Date(now).toUTCString()};
    const response = {status:200,headers,body:structuredClone(paths.get(url))};
    if (options.override) options.override(response,url,paths);
    return response;
  }};
  return {transport,calls,paths};
}
const denied = async p => assert.rejects(p,e=>e.message==='ha_live_offline_transport_refused');
test('GREEN: exactly thirteen mock GETs build D4-B1 input, all nine proofs incomplete',async()=>{
  const {transport,calls}=fake();
  const result=await collect({mockTransport:transport,context:structuredClone(c),now});
  assert.equal(calls.length,13);
  assert.ok(calls.every(v=>v.method==='GET'&&v.url.startsWith(`${API}${root}/`)));
  assert.deepEqual(Object.keys(result.fixture.sources).sort(),Object.keys(replies()).sort());
  assert.deepEqual(inspect(result.fixture,now),result.evidence);
  assert.equal(result.execution,'offline');assert.equal(result.admission,'NOT RUN');
  assert.equal(result.secrets_allowed,false);assert.equal(result.live_ready,false);
  assert.ok(Object.values(result.evidence.proofs).every(p=>p.complete===false));
  assert.equal(Object.isFrozen(result.fixture),true);
  assert.throws(()=>requireAttested(result.evidence),/ha_live_offline_evidence_refused/);
});
test('RED/GREEN: all HTTP failures and redirects refuse without response data',async()=>{
  for(const status of [301,302,307,308,401,403,404,429,500,503]){
    const {transport}=fake({override:r=>{r.status=status;}});
    await denied(collect({mockTransport:transport,context:c,now}));
  }
});
test('only GET fixed routes and safe context before first simulated call',async()=>{
  for (const mutation of [v=>{v.sha='../../private';},v=>{v.run_id=0;},
    v=>{v.ref='refs/heads/main';},v=>{v.repository.id=12;},v=>{v.actor.login='else';}]) {
    const {transport,calls}=fake();const context=structuredClone(c);mutation(context);
    await denied(collect({mockTransport:transport,context,now}));
    assert.equal(calls.length,0);
  }
  const {transport,calls}=fake();
  await denied(collect({mockTransport:transport,context:c,now,signal:AbortSignal.abort()}));
  assert.equal(calls.length,0);
});
test('headers, bad Link targets and leaked context fields always refuse',async()=>{
  for(const override of [
    r=>{r.headers.location='https://evil.example/';},
    r=>{r.headers.link='<https://evil.example/private>; rel="next"';},
    r=>{r.headers.link='<https://api.github.com/other>; rel="next"';},
    r=>{r.headers.link='garbage';},
    r=>{r.headers.date='Mon, 10 Nov 2025 19:00:00 GMT';},
    r=>{r.headers.date='Fri, 13 Nov 2026 19:00:00 GMT';},
    r=>{r.headers['content-type']='text/html';},
    r=>{r.body={token:'VERY_PRIVATE_TOKEN'};},
    r=>{r.body={unexpected:'x'.repeat(70000)};},
    r=>{r.status=200;r.extra='surprise';},
  ]) {
    const {transport}=fake({override});
    await denied(collect({mockTransport:transport,context:c,now}));
  }
});
test('pages are monotonic, bounded, nonduplicated, cannot omit signalled next',async()=>{
  const start = `${API}${root}/actions/runs/22/jobs?per_page=100&page=1`;
  const page2 = `${API}${root}/actions/runs/22/jobs?per_page=100&page=2`;
  const {transport,calls,paths}=fake();
  const original=transport.request;
  paths.set(page2,structuredClone(paths.get(start)).slice(2));
  paths.set(start,structuredClone(paths.get(start)).slice(0,2));
  transport.request=async data=>{
    const r=await original(data);
    if(data.url===start)r.headers.link=`<${page2}>; rel="next"`;
    return r;
  };
  const outcome=await collect({mockTransport:transport,context:c,now});
  assert.deepEqual(outcome.evidence.proofs.ci.data.checks,['tests','ha-tests','hacs','hassfest']);
  assert.equal(calls.filter(v=>v.url.includes('/jobs')).length,2);
  const duplicate=fake();const first=duplicate.paths.get(start);
  duplicate.paths.set(start,first.slice(0,2));duplicate.paths.set(page2,[first[0],first[2],first[3]]);
  const orig=duplicate.transport.request;
  duplicate.transport.request=async data=>{const r=await orig(data);
    if(data.url===start)r.headers.link=`<${page2}>; rel="next"`;return r;};
  await denied(collect({mockTransport:duplicate.transport,context:c,now}));
  const missing=fake();missing.paths.set(start,missing.paths.get(start).slice(0,2));
  const originalMissing=missing.transport.request;
  missing.transport.request=async data=>{const r=await originalMissing(data);
    if(data.url===start)r.headers.link=`<${page2}>; rel="next"`;return r;};
  await denied(collect({mockTransport:missing.transport,context:c,now}));
});
test('unexpected redirects, empty and oversized pages never become partial success',async()=>{
  for(const override of [
    r=>{r.body=[];},r=>{r.body={id:1,payload:'x'.repeat(25000)};},
    r=>{r.headers.link='<https://api.github.com/repos/Guillaume0385/ha-hoben-community/actions/runs?page=2>; rel="last"';},
  ]){
    const {transport}=fake({override});await denied(collect({mockTransport:transport,context:c,now}));
  }
});
test('incomplete, inconsistent run SHA, freshness and CI are refused',async()=>{
  const {transport}=fake({override:(r,url)=>{
    if(url.includes('/branches/experimental'))r.body.commit.sha=H;
  }});
  await denied(collect({mockTransport:transport,context:c,now}));
  await denied(collect({mockTransport:fake().transport,context:c,now:now+30001}));
  const f=fake({override:(r,url)=>{
    if(url.includes('/jobs?'))r.body[0].conclusion='failure';
  }});
  await denied(collect({mockTransport:f.transport,context:c,now}));
});
test('timeout, rejected transport and cancellation have generic public errors',async()=>{
  const runUrl = `${API}${root}/branches/experimental`;
  for(const options of [{pending:runUrl},{abort:runUrl}]){
    await denied(collect({mockTransport:fake(options).transport,context:c,now}));
  }
  const t={request:()=>Promise.reject(Error('TOKEN_SECRET_PRIVATE'))};
  await denied(collect({mockTransport:t,context:c,now}));
  const ac=new AbortController();
  const pending=collect({mockTransport:fake({pending:runUrl}).transport,context:c,now,signal:ac.signal});
  ac.abort(); await denied(pending);
});
