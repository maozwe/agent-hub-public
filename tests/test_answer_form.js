const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const s=fs.readFileSync('web/app.js','utf8');
function el(tag,text){return {tag,textContent:text,children:[],events:{},attrs:{},dataset:{},append(...n){this.children.push(...n)},replaceChildren(){this.children=[]},setAttribute(k,v){this.attrs[k]=v},addEventListener(k,v){this.events[k]=v},focus(){}};}
const root=el('root'),drafts=new Map();let sent=[],fail=false;
const ctx=vm.createContext({el,answerDrafts:drafts,$:()=>({textContent:'Connection error'}),answerQuestion:async(data)=>{sent.push(data);return fail?undefined:{};}});
vm.runInContext(s.slice(s.indexOf('function renderInbox('),s.indexOf('function renderDetail(')),ctx);
const q={id:10,task_id:6,kind:'question',question:'Q',options:['First','Second']};
function render(){ctx.root=root;ctx.q=q;vm.runInContext('renderInbox(root,[q])',ctx);return root.children[0].children.at(-1);}
(async()=>{
 let form=render();await form.events.submit({preventDefault(){}});assert.equal(sent.length,0);
 form.children[1].children[1].events.click();assert.equal(drafts.get(10),'Second');assert.equal(form.children[1].children[1].attrs['aria-pressed'],'true');
 form=render();assert.equal(form.children[2].children[0].value,'Second');
 fail=true;await form.events.submit({preventDefault(){}});assert.equal(drafts.get(10),'Second');assert.equal(form.children[4].textContent,'Connection error');
 fail=false;await form.events.submit({preventDefault(){}});assert.equal(sent.at(-1).answer,'Second');assert.equal(drafts.has(10),false);
 console.log('PASS: selection survives render, failed save retains draft, successful save sends selection');
})().catch(e=>{console.error(e);process.exitCode=1;});
