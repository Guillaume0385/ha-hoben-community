'use strict';
// #207 D4-D: read-only authenticated HTTP adapter for the existing D4-B2 port.
// No network is used by tests. This is never a live admission or a claim.
const API='https://api.github.com';
const ROOT='/repos/Guillaume0385/ha-hoben-community';
const deny=()=>{throw Error('ha_live_d4_rest_refused');};
const need=v=>{if(!v)deny();};
const positive=v=>Number.isSafeInteger(v)&&v>0;
const sha=v=>typeof v==='string'&&/^[a-f0-9]{40}$/.test(v);
function allowedPaths(c){
  need(c && typeof c==='object' && positive(c.run_id) && positive(c.pr_number) &&
    positive(c.ci_run_id) && positive(c.deployment_id) && sha(c.sha) && sha(c.pr_head_sha));
  const routes=[
    `${ROOT}/branches/experimental`,
    `${ROOT}/actions/runs/${c.run_id}`,
    `${ROOT}/commits/${c.sha}/pulls`,
    `${ROOT}/commits/${c.pr_head_sha}`,
    `${ROOT}/commits/${c.sha}`,
    `${ROOT}/pulls/${c.pr_number}/reviews`,
    `${ROOT}/actions/runs/${c.ci_run_id}`,
    `${ROOT}/actions/runs/${c.ci_run_id}/jobs`,
    `${ROOT}/environments/hoben-live`,
    `${ROOT}/deployments/${c.deployment_id}`,
    `${ROOT}/actions/runs/${c.run_id}/approvals`,
    `${ROOT}/contents/.github/workflows/hoben-ha-manual.yml?ref=${c.sha}`,
    `${ROOT}/actions/runs`,
  ];
  const paged=new Set([2,5,7,10,12]);
  const result=new Set();
  routes.forEach((path,index)=>{
    if(!paged.has(index)){result.add(API+path);return;}
    for(let page=1;page<=8;page++)result.add(API+path+
      (path.includes('?')?'&':'?')+`per_page=100&page=${page}`);
  });
  return result;
}
function createPort({context,token,fetchImpl=globalThis.fetch}={}){
  need(typeof token==='string' && /^\S{10,256}$/.test(token) &&
    typeof fetchImpl==='function');
  const allowed=allowedPaths(context);
  return Object.freeze({
    async request({method,url,signal}){
      try{
        need(method==='GET' && allowed.has(url) && !(signal?.aborted));
        const reply=await fetchImpl(url,{method:'GET',redirect:'manual',signal,
          headers:{Accept:'application/vnd.github+json',
            Authorization:`Bearer ${token}`,
            'X-GitHub-Api-Version':'2022-11-28'}});
        need(reply && reply.status===200 && reply.redirected!==true);
        const h=reply.headers;
        const type=h?.get('content-type');
        need(typeof type==='string' && /^application\/json(?:;\s*charset=utf-8)?$/i.test(type));
        const date=h.get('date'),link=h.get('link');
        need(typeof date==='string' && date.length<=64 &&
          (link===null || (typeof link==='string' && link.length<=1024)));
        const size=h.get('content-length');
        need(size===null || (/^\d{1,5}$/.test(size) && Number(size)<=24576));
        const body=await reply.text();
        need(typeof body==='string' && Buffer.byteLength(body)<=24576);
        const headers={'content-type':'application/json',date};
        if(link!==null)headers.link=link;
        return {status:200,headers,body:JSON.parse(body)};
      }catch(_){deny();}
    },
  });
}
module.exports=Object.freeze({createPort});
