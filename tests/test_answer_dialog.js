const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/app.js','utf8');
const code=source.slice(source.indexOf('async function answerQuestion('),source.indexOf('function localTime('));
(async()=>{
 for(const [result,pending,closed] of [[undefined,[],false],[{},[],true],[{},[{task_id:6}],false],[{},[{task_id:7}],true]]) {
  const dialog={open:true,dataset:{taskId:'6'},close(){this.open=false;}};
  let rendered=null;
  const ctx=vm.createContext({$:()=>dialog,save:async()=>result,state:{pending_questions:pending},renderInbox:(root,items)=>rendered=items});
  vm.runInContext(code,ctx);await vm.runInContext('answerQuestion({}, {})',ctx);
  assert.equal(!dialog.open,closed);
  if(result && pending.some(q=>q.task_id===6))assert.equal(rendered.length,1);
 }
 console.log('PASS: failed save keeps dialog; remaining questions stay; answered task closes');
})().catch(e=>{console.error(e);process.exitCode=1;});
