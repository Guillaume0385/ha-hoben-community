"use strict";
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),crypto=require('node:crypto');
const api=require('../../.github/scripts/info-manual-live-report.cjs');
const gate=require('../../.github/scripts/manual-hoben-gate.cjs');
const {setup}=require('./manual-hoben.test.cjs');
const sha='a'.repeat(40), hash=s=>crypto.createHash('sha256').update(s).digest('hex');
const clone=v=>JSON.parse(JSON.stringify(v));
function model(p,candidate=true) {
  const observation={...api.OBS,started:true,opening_accepted:true,tls_verified:true,connections:1,
    cleanup_started_ms:candidate?200:3540000,transport_close_requested:true,transport_close_completed:true,
    rx_stopped:true,operations_stopped:true,cleanup_attested:true,elapsed_ms:candidate?250:3540001};
  if(candidate)Object.assign(observation,{deliveries:1,received_bytes:1,candidate_observed:true,
    candidate_delivery_bytes:1,candidate_at_ms:100,candidate_delivery_offset:0,
    discarded_deliveries:1,tls_deliveries_since_candidate:1,tls_bytes_since_candidate:1,
    delivery_timeline:[[100,1]],candidate_segments:[{
      start_at_ms:100,observed_bytes_between_candidates:1,tls_deliveries:1,
      end_kind:'observation_end'}]});
  else observation.observation_complete=true;
  const process={...api.PROC,launch_attempted:true,spawned:true,isolated:true,child_report_bound:true,children_reaped:1,
    group_empty:true,guardian_waited:true,control_closed:true,exit_ok:true,elapsed_ms:observation.elapsed_ms+1};
  return {schema:3,scenario:'info-passive-observation',selection:'hoben-live',execution:'protected_worker',
    info_framing:'INCONCLUSIVE',boundary_proven:false,limits:{...api.LIMITS},proof:p,
    observation,process,result:'INCONCLUSIVE',
    reason:candidate?'candidate_observed_continuation_not_proven':'candidate_absent'};
}
function fixture() {
  const s=setup('hoben-live'),refs=new Map(),tags=new Map();
  s.history=[{state:'approved',created_at:'2026-10-24T12:11:00Z',
    environments:[{id:1,name:'hoben-experimental'}],user:{type:'User',id:2,login:'reviewer'}}];
  const git=s.github.rest.git;
  git.createTag=async q=>{s.writes++;const id=crypto.createHash('sha1').update(q.tag+q.message).digest('hex');
    const tag={sha:id,tag:q.tag,object:{type:'commit',sha:q.object},message:q.message};
    tags.set(id,tag);return {data:tag};};
  git.createRef=async q=>{if(refs.has(q.ref))throw Error('collision');
    refs.set(q.ref,{ref:q.ref,object:{type:'tag',sha:q.sha}});};
  git.getRef=async q=>{s.claimReads++;assert.ok(refs.has('refs/'+q.ref));return {data:refs.get('refs/'+q.ref)};};
  git.getTag=async q=>{assert.ok(tags.has(q.tag_sha));return {data:tags.get(q.tag_sha)};};
  s.refs=refs;s.tags=tags;
  const ciJobs=s.github.rest.actions.listJobsForWorkflowRun;
  s.collector={name:'collect-info',run_id:123,run_attempt:1,head_sha:sha,status:'in_progress',conclusion:null,
    steps:[{name:'Info post-approval admission',number:4,status:'completed',conclusion:'success',
      started_at:'2026-10-24T12:11:00Z',completed_at:'2026-10-24T12:11:01Z'},
    {name:'One passive Info session with independent OS guardian',number:5,status:'completed',conclusion:'success',
      started_at:'2026-10-24T12:11:01Z',completed_at:'2026-10-24T12:11:02Z'},
    {name:'Info protected export',number:6,status:'in_progress',conclusion:null,started_at:'2026-10-24T12:11:03Z'}]};
  s.github.rest.actions.listJobsForWorkflowRun=q=>q.run_id===123?[s.collector]:ciJobs(q);
  s.root=fs.mkdtempSync(path.join(os.tmpdir(),'info-protected-'));
  s.outputs={};s.failures=[];s.core={setOutput:(k,v)=>s.outputs[k]=v,setFailed:v=>s.failures.push(v)};
  s.settle=()=>{s.collector.status='completed';s.collector.conclusion='success';
    Object.assign(s.collector.steps[2],{status:'completed',conclusion:'success',completed_at:'2026-10-24T12:11:04Z'});};
  s.seal=r=>{const key=crypto.randomBytes(32),bytes=JSON.stringify(r);
    const directory=path.join(s.root,'hoben-info-private');
    fs.writeFileSync(path.join(directory,'attestation.key'),key,{mode:0o600,flag:'wx'});
    fs.writeFileSync(path.join(directory,'sealed-report.json'),JSON.stringify({report:r,
      signature:crypto.createHmac('sha256',key).update(bytes).digest('hex')}),{mode:0o600,flag:'wx'});};
  const previous={};for(const k of Object.keys(s.env)){previous[k]=process.env[k];process.env[k]=s.env[k];}
  s.close=()=>{for(const k of Object.keys(previous))if(previous[k]===undefined)delete process.env[k];else process.env[k]=previous[k];
    fs.rmSync(s.root,{recursive:true,force:true});};
  s.admit=async()=>{await gate.verify(s.options());return api.writeLaunchPermit({github:s.github,context:s.context,root:s.root});};
  return s;
}

test('complete passive route reserves, approves, binds, authenticates and publishes INCONCLUSIVE',async()=>{
  const s=fixture();try{
    const p=await s.admit(),r=model(p);
    assert.equal(api.validateStructure(r,p),r);
    const permit=JSON.parse(fs.readFileSync(path.join(s.root,'hoben-info-private/permit.json')));
    assert.equal(permit.schema,2);assert.deepEqual(permit.proof,p);
    const tag=s.tags.get(p.launch_tag_sha);assert.equal(JSON.parse(tag.message).nonce_digest,hash(permit.nonce));
    assert.ok(!tag.message.includes(permit.nonce));
    s.seal(r);await api.prepare({github:s.github,context:s.context,core:s.core,proof:p,root:s.root});
    assert.deepEqual(s.failures,[]);assert.ok(s.outputs.report_b64&&s.outputs.receipt_sha);
    assert.ok(!fs.existsSync(path.join(s.root,'hoben-info-private/attestation.key')));
    s.settle();const writes=s.writes;
    assert.equal(await api.validateForLivePublication({github:s.github,context:s.context,
      report:r,proof:p,receiptSha:s.outputs.receipt_sha}),r);
    await api.publish({github:s.github,context:s.context,core:s.core,proof:p,
      text:s.outputs.report_b64,receiptSha:s.outputs.receipt_sha,root:s.root});
    assert.equal(s.outputs.report,'true');assert.equal(s.writes,writes);
    assert.deepEqual(api.read(path.join(s.root,'hoben-info-published/report.json'),p),r);
    await assert.rejects(()=>s.admit()); // Atomic claims/launches cannot be replayed.
  }finally{s.close();}
});
for(const candidate of [false,true])test('no fabricated functional SUCCESS, candidate='+candidate,async()=>{
  const s=fixture();try{const p=await s.admit(),r=model(p,candidate);
    assert.equal(api.validateStructure(r,p).result,'INCONCLUSIVE');
    for(const mutate of [r=>r.result='SUCCESS',r=>r.execution='offline',r=>r.mode='live',
      r=>r.boundary_proven=true,r=>r.observation.continuation='proven',
      r=>r.observation.post_candidate_reads=1,r=>r.process.children_reaped=0,
      r=>r.private='PRIVATE_DATA',r=>r.observation.pid=123,r=>r.info_framing='PROVEN']){
      const bad=clone(r);mutate(bad);assert.throws(()=>api.validateStructure(bad,p));
    }
    for(const key of Object.keys(r)){const bad=clone(r);delete bad[key];assert.throws(()=>api.validateStructure(bad,p));}
    const old=require('../../.github/scripts/info-delivery-manual-report.cjs');
    assert.throws(()=>old.validateForLivePublication(r));
  }finally{s.close();}
});
test('D8 delivery counts, omitted items and fixed-FFFF non-correlation fail closed',async()=>{
  const s=fixture();try{
    const p=await s.admit(),r=model(p);
    Object.assign(r.observation,{
      deliveries:4,received_bytes:12,post_candidate_reads:3,
      tls_deliveries_since_candidate:4,tls_bytes_since_candidate:12,
      delivery_timeline:[[100,1],[120,3],[130,4],[140,4]],
      candidate_leads_unproven:1,response_leads_unproven:1,ping_leads_unproven:1,
      candidate_segments:[{
        start_at_ms:100,observed_bytes_between_candidates:8,tls_deliveries:3,
        end_kind:'delivery_lead_unproven'},{
        start_at_ms:140,observed_bytes_between_candidates:4,tls_deliveries:1,
        end_kind:'observation_end'}],
      read_requests:3,unconfirmed_read_requests:3,
    });
    assert.equal(api.validateStructure(r,p),r);
    for(const modify of [
      o=>o.tls_bytes_since_candidate=13,
      o=>o.tls_deliveries_since_candidate=5,
      o=>o.delivery_timeline_omitted=1,
      o=>o.delivery_timeline[0][1]=2,
      o=>o.candidate_segments[0].observed_bytes_between_candidates=-1,
      o=>o.candidate_segments[1].end_kind='Info_complete',
      o=>o.verified_reads=1,
      o=>o.unconfirmed_read_requests=4,
      o=>o.first_post_info_valid_v4_at_ms=150,
      o=>o.recovery_stability_elapsed_ms=300000,
      o=>o.delivery_timeline[1].push('private'),
      o=>o.delivery_timeline.push([9999999,1]),
      o=>o.private_bytes='secret',
    ]){const t=clone(r);modify(t.observation);assert.throws(()=>api.validateStructure(t,p));}
  }finally{s.close();}
});
for(const mutation of ['signature','key','extra','clock','mode','missing','symlink'])
 test('collector refuses tampered private report: '+mutation,async()=>{
  const s=fixture();try{const p=await s.admit(),r=model(p);s.seal(r);
    const directory=path.join(s.root,'hoben-info-private'),file=path.join(directory,'sealed-report.json');
    if(mutation==='signature'){const e=JSON.parse(fs.readFileSync(file));e.signature='0'.repeat(64);fs.writeFileSync(file,JSON.stringify(e));}
    if(mutation==='key')fs.writeFileSync(path.join(directory,'attestation.key'),crypto.randomBytes(32));
    if(mutation==='extra'){const e=JSON.parse(fs.readFileSync(file));e.raw='PRIVATE';fs.writeFileSync(file,JSON.stringify(e));}
    if(mutation==='clock')s.collector.steps[1].completed_at='2026-10-24T12:11:01Z';
    if(mutation==='mode'){const e=JSON.parse(fs.readFileSync(file));e.report.execution='offline';fs.writeFileSync(file,JSON.stringify(e));}
    if(mutation==='missing')fs.unlinkSync(file);
    if(mutation==='symlink'){fs.renameSync(file,file+'.private');fs.symlinkSync(file+'.private',file);}
    // clock uses the long observation report to expose false elapsed evidence.
    if(mutation==='clock'){fs.unlinkSync(path.join(directory,'attestation.key'));fs.unlinkSync(file);s.seal(model(p,false));}
    await api.prepare({github:s.github,context:s.context,core:s.core,proof:p,root:s.root});
    assert.equal(s.outputs.report_b64,undefined);assert.equal(s.outputs.receipt_sha,undefined);
    assert.equal(s.failures.length,1);assert.ok(!s.failures[0].includes('PRIVATE'));
    assert.ok(!fs.existsSync(path.join(directory,'attestation.key')));
  }finally{s.close();}
});
for(const mutation of ['hash','receipt','launch','actor','head','approval','job','capture','order','attempt'])
 test('publication requires actual gate, job and immutable receipt: '+mutation,async()=>{
  const s=fixture();try{const p=await s.admit(),r=model(p);s.seal(r);
    await api.prepare({github:s.github,context:s.context,core:s.core,proof:p,root:s.root});
    assert.deepEqual(s.failures,[]);s.settle();let receipt=s.outputs.receipt_sha;
    if(mutation==='hash'){const t=s.tags.get(receipt),m=JSON.parse(t.message);m.report_sha256='0'.repeat(64);t.message=JSON.stringify(m);}
    if(mutation==='receipt')receipt='0'.repeat(40);
    if(mutation==='launch')s.refs.delete('refs/tags/hoben-info-start-123-attempt1');
    if(mutation==='actor')s.context.actor='other';
    if(mutation==='head')s.branch.commit.sha='f'.repeat(40);
    if(mutation==='approval')s.history=[];
    if(mutation==='job')s.collector.name='collect-ha';
    if(mutation==='capture')s.collector.steps[1].conclusion='cancelled';
    if(mutation==='order')s.collector.steps[0].number=9;
    if(mutation==='attempt')s.collector.run_attempt=2;
    await assert.rejects(()=>api.validateForLivePublication({github:s.github,context:s.context,report:r,proof:p,receiptSha:receipt}));
  }finally{s.close();}
});
test('launch capability requires post-approval API recheck, not a caller decision',async()=>{
  const s=fixture();try{await gate.verify(s.options());s.history=[];const writes=s.writes;
    await assert.rejects(()=>api.writeLaunchPermit({github:s.github,context:s.context,root:s.root,
      decision:{selection:'hoben-live',status:'PENDING APPROVAL'}}));
    assert.equal(s.writes,writes);assert.ok(!fs.existsSync(path.join(s.root,'hoben-info-private')));
  }finally{s.close();}
});
test('b64 bounds and offline schema never reach live publication',()=>{
  assert.throws(()=>api.decode('A'.repeat(10925),{}));
  assert.throws(()=>api.decode(Buffer.from('{"mode":"offline","result":"SUCCESS"}').toString('base64'),{}));
});

test('Info no-reviewer environment still requires full launch, cleanup and receipt proofs',async()=>{
  const s=fixture();try{
    s.environment.protection_rules=s.environment.protection_rules.filter(r=>r.type!=='required_reviewers');
    s.history=[];
    let approvalApiCalls=0;
    s.github.request=async()=>{approvalApiCalls++;throw Error('unexpected_approval_request');};
    const p=await s.admit(),r=model(p);
    assert.equal(approvalApiCalls,0);
    assert.equal(s.refs.has('refs/tags/hoben-manual-123-attempt1'),true);
    assert.equal(s.refs.has('refs/tags/hoben-info-start-123-attempt1'),true);
    s.seal(r);
    await api.prepare({github:s.github,context:s.context,core:s.core,proof:p,root:s.root});
    assert.deepEqual(s.failures,[]);
    s.settle();
    await api.publish({github:s.github,context:s.context,core:s.core,proof:p,
      text:s.outputs.report_b64,receiptSha:s.outputs.receipt_sha,root:s.root});
    assert.equal(s.outputs.report,'true');
    assert.equal(approvalApiCalls,0);
    // Any later addition of required reviewers invalidates the reserved
    // policy digest. An old claim cannot authorize the changed environment.
    s.environment.protection_rules.push({id:3,type:'required_reviewers',prevent_self_review:true,
      reviewers:[{type:'User',reviewer:{type:'User',id:2,login:'reviewer'}}]});
    await assert.rejects(()=>api.validateForLivePublication({github:s.github,context:s.context,
      report:r,proof:p,receiptSha:s.outputs.receipt_sha}));
  }finally{s.close();}
});
