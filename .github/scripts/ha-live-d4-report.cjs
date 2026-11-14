'use strict';
// #207 D4-D: independent, closed report validation on a new runner.
const fs=require('node:fs'), path=require('node:path');
const deny=()=>{throw Error('ha_live_d4_public_refused');};
const need=v=>{if(!v)deny();};
const integer=(v,a,b)=>Number.isSafeInteger(v)&&v>=a&&v<=b;
const KEYS=['schema','scenario','sha','run_id','attempt','observation','elapsed_ms',
  'drop_at_ms','correlated_at_ms','tls_generation','unknown_drops','info_candidates',
  'correlated_after_drop','pings','pongs','cleanup_attested','boundary_proven'];
function validate(v,env){
  need(v&&typeof v==='object'&&!Array.isArray(v)&&
    Object.keys(v).sort().join('|')===KEYS.slice().sort().join('|'));
  need(v.schema===1&&v.scenario==='hoben-live'&&
    typeof v.sha==='string'&&/^[a-f0-9]{40}$/.test(v.sha)&&
    v.sha===env.GITHUB_SHA&&integer(v.run_id,1,Number.MAX_SAFE_INTEGER)&&
    String(v.run_id)===env.GITHUB_RUN_ID&&v.attempt===1&&
    env.GITHUB_RUN_ATTEMPT==='1'&&
    ['SUCCESS','INCONCLUSIVE','FAILED'].includes(v.observation)&&
    typeof v.cleanup_attested==='boolean'&&v.boundary_proven===false);
  for(const k of ['elapsed_ms','unknown_drops','info_candidates','correlated_after_drop','pings','pongs'])
    need(integer(v[k],0,900000));
  for(const k of ['drop_at_ms','correlated_at_ms'])
    need(integer(v[k],-1,900000));
  need(v.tls_generation===null||integer(v.tls_generation,1,2147483647));
  need(v.observation!=='SUCCESS'||(v.cleanup_attested&&v.drop_at_ms>=0&&
    v.correlated_at_ms>v.drop_at_ms&&v.elapsed_ms-v.correlated_at_ms>=300000&&
    v.correlated_after_drop>=1));
  return v;
}
function main(mode, env=process.env){
  try{
    need(['prepare','publish'].includes(mode)&&typeof env.RUNNER_TEMP==='string');
    let raw;
    if(mode==='prepare'){
      const file=path.join(env.RUNNER_TEMP,'hoben-d4-public','report.json');
      const stat=fs.lstatSync(file);
      need(stat.isFile()&&!stat.isSymbolicLink()&&stat.size<=4096);
      raw=fs.readFileSync(file);
    }else{
      need(env.COLLECT_RESULT==='success'&&typeof env.PUBLIC_REPORT_B64==='string'&&
        /^[A-Za-z0-9+/]*={0,2}$/.test(env.PUBLIC_REPORT_B64)&&
        env.PUBLIC_REPORT_B64.length<=6000);
      raw=Buffer.from(env.PUBLIC_REPORT_B64,'base64');
      need(raw.toString('base64')===env.PUBLIC_REPORT_B64);
    }
    need(raw.length>0&&raw.length<=4096);
    const data=validate(JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(raw)),env);
    const encoded=Buffer.from(JSON.stringify(data));
    need(encoded.equals(raw));
    if(mode==='prepare'){
      fs.appendFileSync(env.GITHUB_OUTPUT,'report_b64='+encoded.toString('base64')+'\n');
    }else{
      const folder=path.join(env.RUNNER_TEMP,'hoben-campaign-published');
      fs.mkdirSync(folder,{mode:0o700,recursive:false});
      fs.writeFileSync(path.join(folder,'report.json'),encoded,{flag:'wx',mode:0o600});
      fs.appendFileSync(env.GITHUB_OUTPUT,'report=true\n');
      fs.appendFileSync(env.GITHUB_STEP_SUMMARY,'## D4-D Live HA — '+data.observation+'\n');
      if(data.observation!=='SUCCESS')process.exitCode=1;
    }
    return true;
  }catch(_){
    process.stderr.write('::error::ha_live_d4_public_refused\n');
    process.exitCode=1;
    return false;
  }
}
if(require.main===module)main(process.argv[2]);
module.exports=Object.freeze({validate,main});
