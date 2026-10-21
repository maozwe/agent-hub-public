const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../web/app.js'),'utf8');
const feedback=source.slice(source.indexOf('function feedback('),source.indexOf('async function action('));
const refresh=source.slice(source.indexOf('async function refresh('),source.indexOf("$('create-form').addEventListener"));
const nodes={feedback:{},'last-update':{},'connection-status':{}};
let offline=true;
const context=vm.createContext({$:id=>nodes[id],document:{body:{classList:{add(){},remove(){}}},activeElement:{closest:()=>null},querySelector:()=>({classList:{add(){},remove(){}}})},
  render(){}, fetch:async()=>{if(offline)throw Error('offline');return {ok:true,json:async()=>({tasks:[]})};}});
vm.runInContext("let stopped=false,previous='',state,connectionErrorShown=false;"+feedback+refresh,context);
(async()=>{
  await vm.runInContext('refresh()',context);assert.equal(nodes.feedback.className,'error');assert.ok(nodes.feedback.textContent);
  offline=false;await vm.runInContext('refresh()',context);assert.equal(nodes.feedback.textContent,'');
  vm.runInContext("feedback('Keep action error',true)",context);
  await vm.runInContext('refresh()',context);assert.equal(nodes.feedback.textContent,'Keep action error');
  console.log('PASS: recovered connection clears its stale error and preserves action feedback');
})().catch(error=>{console.error(error);process.exitCode=1;});
