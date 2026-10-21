const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../web/app.js'),'utf8');
const action=source.slice(source.indexOf('async function authenticatedPost('),source.indexOf('async function save('));
async function scenario(statuses,token='fresh',pageOK=true,voice=false) {
  const calls=[],meta={content:'old'};
  const context=vm.createContext({document:{querySelector:()=>meta},
    DOMParser:class {parseFromString(){return {querySelector:()=>token?{content:token}:null};}},
    fetch:async(url,options)=>{
      calls.push({url,...options,headers:{...options.headers}});
      if(url==='/')return {ok:pageOK,text:async()=>'<html></html>'};
      const status=statuses.shift();if(status==='network')throw Error('network');
      return {status,ok:status===200,json:async()=>status===200?{id:1}:{error:'denied'}};
    }});
  vm.runInContext(action,context);
  let result,error;try{result=await vm.runInContext(voice?"authenticatedPost('/api/transcribe','recorded-audio')":"action({action:'create',request:'draft',agent:'claude'})",context);}catch(e){error=e;}
  return {calls,result,error};
}
(async()=>{
  const recovered=await scenario([403,200]);assert.equal(recovered.result.id,1);
  assert.deepEqual(recovered.calls.map(c=>c.url),['/api/action','/','/api/action']);
  assert.equal(recovered.calls[0].body,recovered.calls[2].body);
  assert.equal(recovered.calls[2].headers['X-Hub-CSRF'],'fresh');
  for(const [statuses,token,pageOK,posts] of [
    [[403,403],'fresh',true,2],[[403],'old',true,1],[[403],null,true,1],
    [[403],'fresh',false,1],[[500],'fresh',true,1],[['network'],'fresh',true,1]]) {
    const r=await scenario(statuses,token,pageOK);assert.ok(r.error);
    assert.equal(r.calls.filter(c=>c.url==='/api/action').length,posts);
  }
  assert.equal((await scenario([200])).calls.length,1);
  const voice=await scenario([403,200],'fresh',true,true);
  assert.equal(voice.result.id,1);
  assert.deepEqual(voice.calls.map(c=>c.url),['/api/transcribe','/','/api/transcribe']);
  assert.equal(voice.calls[0].body,voice.calls[2].body);
  assert.equal(voice.calls[2].headers['X-Hub-CSRF'],'fresh');
  const failedVoice=await scenario([500],'fresh',true,true);
  assert.ok(failedVoice.error);assert.equal(failedVoice.calls.length,1);
  console.log('PASS: refresh stale CSRF once, preserve payload, never retry ambiguous failures');
})().catch(error=>{console.error(error);process.exitCode=1;});
