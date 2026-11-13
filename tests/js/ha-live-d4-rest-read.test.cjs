'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {createPort}=require('../../.github/scripts/ha-live-d4-rest-read.cjs');
const sha='a'.repeat(40);
const context={run_id:101,pr_number:23,ci_run_id:400,deployment_id:52,sha,pr_head_sha:'b'.repeat(40)};
const base='https://api.github.com/repos/Guillaume0385/ha-hoben-community';
const route=base+'/branches/experimental';
const token='synthetic-test-token-00001';
function response({status=200,contentType='application/json',body='{}',link=null,date='Fri, 13 Nov 2026 19:00:00 GMT'}={}){
  return {status,redirected:false,headers:{get(key){
    return {'content-type':contentType,'date':date,'link':link}[key] ?? null;
  }},async text(){return body;}};
}
test('GET exact allowlisted URI only; token never returned or logged',async()=>{
  const called=[];
  const p=createPort({context,token,fetchImpl:async(url,options)=>{
    called.push({url,options});return response();
  }});
  const r=await p.request({method:'GET',url:route});
  assert.deepEqual(r,{status:200,headers:{
    'content-type':'application/json',date:'Fri, 13 Nov 2026 19:00:00 GMT'},body:{}});
  assert.equal(called.length,1);assert.equal(called[0].url,route);
  assert.equal(called[0].options.redirect,'manual');
  assert.equal(called[0].options.headers.Authorization,'Bearer '+token);
  for(const url of ['https://other.example.org/',route+'/unknown',
    base+'/git/refs',route+'?foo=bar',base+'/environments/another']){
    await assert.rejects(p.request({method:'GET',url}),/ha_live_d4_rest_refused/);
  }
  await assert.rejects(p.request({method:'POST',url:route}),/ha_live_d4_rest_refused/);
  assert.equal(called.length,1);
});
test('pinned dynamic paths and only pages 1-8 are allowed',async()=>{
  const p=createPort({context,token,fetchImpl:async()=>response()});
  const list=base+'/commits/'+sha+'/pulls?per_page=100&page=';
  for(let i=1;i<=8;i++)await p.request({method:'GET',url:list+i});
  for(const bad of [list+'9',list+'0',list+'01',list+'2&mode=raw',
    base+'/commits/'+sha+'/pulls']){
    await assert.rejects(p.request({method:'GET',url:bad}),/ha_live_d4_rest_refused/);
  }
});
test('no success on 403/400, redirect, oversized, malformed, wrong media type',async()=>{
  const bad=[response({status:403}),response({status:400}),response({status:302}),
    response({contentType:'text/plain'}),response({body:'{' }),
    response({body:'x'.repeat(24577)}),response({link:'x'.repeat(1025)})];
  for(const value of bad){
    const p=createPort({context,token,fetchImpl:async()=>value});
    await assert.rejects(p.request({method:'GET',url:route}),e=>{
      assert.equal(e.message,'ha_live_d4_rest_refused');
      assert.doesNotMatch(e.message,/synthetic-test-token/);
      return true;
    });
  }
});
test('cancelled request and hostile context do not contact network',async()=>{
  let calls=0;
  const p=createPort({context,token,fetchImpl:async()=>{
    calls++;throw Error('my private stack or token');
  }});
  const controller=new AbortController();controller.abort();
  await assert.rejects(p.request({method:'GET',url:route,signal:controller.signal}),
    /ha_live_d4_rest_refused/);
  assert.equal(calls,0);
  for(const bad of [{...context,sha:'garbage'},{...context,run_id:0},
    {...context,pr_number:'1'},{...context,ci_run_id:-1}]){
    assert.throws(()=>createPort({context:bad,token,fetchImpl:async()=>response()}),
      /ha_live_d4_rest_refused/);
  }
});
