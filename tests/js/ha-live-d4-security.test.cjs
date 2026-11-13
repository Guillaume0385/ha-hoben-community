'use strict';
// #207 D4-D: synthetic API responses only. No GitHub requests or secrets.
const test = require('node:test');
const assert = require('node:assert/strict');
const {context,fetchPort,preflight,refusedResult} =
  require('../../.github/scripts/ha-live-d4-security.cjs');
const base = Object.freeze({repository:'Guillaume0385/ha-hoben-community',
  actor:'Guillaume0385',triggering_actor:'Guillaume0385',event:'workflow_dispatch',
  ref:'refs/heads/experimental',scenario:'hoben-live',attempt:1,run_id:123,
  sha:'a'.repeat(40),workflow:'.github/workflows/hoben-ha-manual.yml'});
const fail = /ha_live_d4_security_refused/;
const branch = {name:'experimental',protected:true,commit:{sha:base.sha}};
const protection = {required_pull_request_reviews:{required_approving_review_count:1,
  dismiss_stale_reviews:true,require_code_owner_reviews:true}};
const environment = {name:'hoben-live',prevent_self_review:true,can_admins_bypass:false,
  deployment_branch_policy:{protected_branches:false,custom_branch_policies:true},
  protection_rules:[{type:'required_reviewers',reviewers:[
    {type:'User',reviewer:{id:2,login:'independent-reviewer'}}]}]};
const rulesets = [{enforcement:'active',bypass_actors:[]}];
const copy = x => JSON.parse(JSON.stringify(x));
const paths = ['/branches/experimental','/branches/experimental/protection',
  '/environments/hoben-live','/rulesets?includes_parents=true'];
function port(values) {
  const received = [];
  const valuesByPath = Object.fromEntries(paths.map((path,index) =>
    ['/repos/Guillaume0385/ha-hoben-community'+path,values[index]]));
  return {received, async get(path) {
    received.push(path);
    if (!Object.hasOwn(valuesByPath,path)) throw Error('unexpected route');
    const result = valuesByPath[path];
    if (result instanceof Error) throw result;
    return copy(result);
  }};
}
test('strict context excludes main, reruns, other scenarios and token fields',()=>{
  assert.deepEqual(context(base),base);
  for (const change of [{ref:'refs/heads/main'},{attempt:2},
    {scenario:'all'},{actor:'outsider'},{triggering_actor:'outsider'},
    {repository:'other/repo'},{event:'push'},{sha:'a'.repeat(39)},
    {run_id:0},{workflow:'evil.yml'},{secret:'synthetic-SECRET'}]) {
    assert.throws(()=>context({...base,...change}),fail);
  }
});
test('policy never infers real approval or immutable claims from mock responses',async()=>{
  const t=port([branch,protection,environment,rulesets]);
  await assert.rejects(preflight({rawContext:base,port:t}),fail);
  assert.equal(t.received.length,4);
  assert.deepEqual(refusedResult(),{schema:1,execution:'NOT RUN',admission:'NOT RUN',
    complete:false,secrets_allowed:false,live_ready:false,reason:'evidence_unverifiable'});
});
test('403 branch protection, inaccessible environment, absent ruleset all refuse',async()=>{
  for (const [index,v] of [[1,Error('403 Authorization: fake-token')],
    [2,Error('400 unsupported endpoint')],[3,[]],
    [0,{...branch,protected:true,commit:{sha:'b'.repeat(40)}}],
    [1,{}],[2,{...environment,prevent_self_review:false}],
    [2,{...environment,protection_rules:[]}],
    [3,[{enforcement:'disabled',bypass_actors:[]}]]]) {
    const values=[branch,protection,environment,rulesets];
    values[index]=v;
    await assert.rejects(preflight({rawContext:base,port:port(values)}),e=>{
      assert.equal(e.message,'ha_live_d4_security_refused');
      assert.doesNotMatch(e.message,/fake-token|Authorization|SECRET/);
      return true;
    });
  }
});
test('native HTTP adapter is GET-only fixed-origin, no redirect or echo',async()=>{
  const token='test-only-placeholder-000001';
  const visited=[];
  const adapter=fetchPort({token,fetchImpl:async(url,options)=>{
    visited.push({url,options});
    return {status:200,redirected:false,headers:{get(name){
      return name==='content-type'?'application/json':null;
    }},async text(){return JSON.stringify(branch);}};
  }});
  const got=await adapter.get('/repos/Guillaume0385/ha-hoben-community/branches/experimental');
  assert.equal(got.name,'experimental');
  assert.equal(visited.length,1);
  assert.equal(visited[0].url,'https://api.github.com/repos/Guillaume0385/ha-hoben-community/branches/experimental');
  assert.equal(visited[0].options.method,'GET');
  assert.equal(visited[0].options.redirect,'manual');
  assert.equal(visited[0].options.headers.Authorization,'Bearer '+token);
  await assert.rejects(adapter.get('/repos/Guillaume0385/ha-hoben-community/git/refs'),fail);
  await assert.rejects(adapter.get('https://other.example.org/'),fail);
  for(const status of [301,400,401,403,404,429,500]){
    const p=fetchPort({token,fetchImpl:async()=>({status,headers:{get:()=>null}})});
    await assert.rejects(p.get('/repos/Guillaume0385/ha-hoben-community/branches/experimental'),fail);
  }
});
test('no automatic retries, cancellation, or private error output',async()=>{
  let count=0;
  const token='synthetic-private-credential';
  const p=fetchPort({token,fetchImpl:async()=>{
    count+=1; throw Error('synthetic-private-credential');
  }});
  await assert.rejects(p.get('/repos/Guillaume0385/ha-hoben-community/branches/experimental'),
    e=>e.message==='ha_live_d4_security_refused');
  assert.equal(count,1);
  const controller=new AbortController();controller.abort();
  await assert.rejects(p.get('/repos/Guillaume0385/ha-hoben-community/branches/experimental',
    {signal:controller.signal}),fail);
  assert.equal(count,1);
});
