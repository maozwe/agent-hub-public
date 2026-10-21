'use strict';
const $ = id => document.getElementById(id);
const answerDrafts = new Map();
const labels = {queued:'בתור', assigned:'נלקחה לסוכן', working:'בעבודה', testing:'באימות', waiting_for_user:'ממתינה לתשובה', completed:'הושלמה', blocked:'חסומה'};
let state, selected = null, stopped = false, previous = '', taskFilter = 'all', connectionErrorShown = false;
function el(tag, text, className) { const node=document.createElement(tag); if(text!==undefined) node.textContent=text; if(className) node.className=className; return node; }
function feedback(message, error=false) { connectionErrorShown=false; $('feedback').textContent=message; $('feedback').className=error?'error':''; }
async function action(data) {
  const meta=document.querySelector('meta[name="hub-csrf"]'), body=JSON.stringify(data);
  const post=()=>fetch('/api/action',{method:'POST', headers:{'Content-Type':'application/json','X-Hub-CSRF':meta.content},body});
  let response=await post();
  // A 403 rejects the action before execution; never retry ambiguous network failures.
  if(response.status===403) {
    const page=await fetch('/',{cache:'no-store',redirect:'error'});
    if(page.ok) {
      const token=new DOMParser().parseFromString(await page.text(),'text/html').querySelector('meta[name="hub-csrf"]')?.content;
      if(token && token!==meta.content) {meta.content=token;response=await post();}
    }
  }
  const result=await response.json(); if(!response.ok) throw new Error(response.status===403?'היישום הופעל מחדש או שהחיבור אינו מורשה. רעננו את הדף ובדקו את החיבור.':result.error || 'הפעולה לא נשמרה'); return result;
}
async function save(data, button) {
  button.disabled=true;
  try { const result=await action(data); feedback('השינוי נשמר.'); await refresh(true); return result; }
  catch(error) { feedback('לא ניתן לשמור: '+error.message,true); if($('create-dialog').open) $('create-error').textContent=error.message; if($('answer-dialog').open) $('answer-error').textContent=error.message; }
  finally { button.disabled=false; }
}
function badge(status, taskId) {
  const tracked=state?.tasks.find(t=>t.id===taskId)?.activity;
  if(tracked?.manual) return el('span',tracked.at&&!tracked.stale?'פעילות בסשן ידני':'מעקב סשן ידני','badge working');
  const node=el(status==='waiting_for_user'?'button':'span',labels[status]||status,'badge '+status);
  if(status==='waiting_for_user') {node.type='button';node.setAttribute('aria-label','ממתינה לתשובה · משימה '+taskId);node.addEventListener('click',()=>openAnswers(taskId));}
  if(['assigned','working','testing'].includes(status) && state?.tasks.find(t=>t.id===taskId)?.activity?.at && !state.tasks.find(t=>t.id===taskId).activity.stale) {
    const activity=el('span',undefined,'task-activity');activity.setAttribute('aria-hidden','true');
    for(let i=0;i<3;i++) activity.append(el('span'));
    node.append(activity);node.title='המשימה במצב ביצוע. האנימציה אינה בדיקת התקדמות חיה של הסוכן.';
  }
  return node;
}
function openAnswers(taskId) {
  const dialog=$('answer-dialog');dialog.dataset.taskId=taskId;
  $('answer-title').textContent='שאלות ואישורים · משימה #'+taskId;
  renderInbox($('answer-content'),state.pending_questions.filter(q=>q.task_id===taskId));
  $('answer-error').textContent='';dialog.showModal();
}
async function answerQuestion(data, button) {
  const result=await save(data,button);
  if(result!==undefined && $('answer-dialog').open) {
    const remaining=state.pending_questions.filter(q=>q.task_id===Number($('answer-dialog').dataset.taskId));
    if(remaining.length) renderInbox($('answer-content'),remaining);else $('answer-dialog').close();
  }
  return result;
}
function localTime(value) { const utc=value.includes('T')?value:value.replace(' ','T')+'Z';return new Date(utc).toLocaleString('he-IL',{timeZone:'Asia/Jerusalem'}); }
function activityLine(task) {
  const activity=task.activity, root=el('div',undefined,'activity-line');
  if(activity?.manual) root.append(el('span','Claude · מעקב בלבד אחר סשן ידני; ללא הפעלה דרך Hub','muted'));
  if(!activity?.at) {root.textContent='אין דיווח פעילות חי מהסוכן';if(activity?.started_at)root.append(el('span','תחילת ההפעלה: '+localTime(activity.started_at),'muted'));return root;}
  const seconds=Math.max(0,activity.age_seconds), age=seconds<60?seconds+' שניות':Math.floor(seconds/60)+' דקות';
  root.append(el('span',activity.summary),el('span','פעילות אחרונה: לפני '+age+' · '+localTime(activity.at),'muted'));
  if(activity.stale) {root.classList.add('activity-stale');root.append(el('span','לא התקבל עדכון במשך יותר משתי דקות — ייתכן שהפעולה ממושכת או שהסוכן תקוע.'));}
  return root;
}
function meta(task) { const node=el('div',undefined,'meta'); node.append(el('span',task.repository,'repo'),el('span','#'+task.id),el('span',task.agent||'טרם שויך סוכן'),el('span','עדיפות '+task.priority)); return node; }
function assignment(task) {
  const form=el('form',undefined,'assignment'), label=el('label','שיוך סוכן'), select=el('select');
  select.setAttribute('aria-label','סוכן למשימה '+task.id);
  for(const agent of state.agents) { const option=el('option',agent.name); option.value=agent.name; select.append(option); }
  if(task.agent) select.value=task.agent;
  const button=el('button',task.agent?'עדכון שיוך':'שיוך והפעלה'); button.type='submit'; label.append(select); form.append(label,button);
  form.addEventListener('submit',event=>{event.preventDefault(); save({action:'assign',task_id:task.id,agent:select.value},button);}); return form;
}
function participantChoices(root, chosen=[]) {
  root.querySelectorAll('label').forEach(node=>node.remove());
  for(const agent of state.agents) {
    const label=el('label',undefined,'participant-choice'), input=el('input');
    input.type='checkbox';input.value=agent.name;input.checked=chosen.includes(agent.name);
    label.append(input,document.createTextNode(agent.name));root.append(label);
  }
}
function chosenParticipants(root) {return [...root.querySelectorAll('input:checked')].map(input=>input.value);}
function participantsEditor(task) {
  const form=el('form',undefined,'participants-form'), group=el('fieldset'), legend=el('legend','משתתפים נוספים');
  group.append(legend);participantChoices(group,task.participants||[]);
  const button=el('button','שמירת משתתפים','secondary');button.type='submit';
  form.append(group,el('p','משתתפים נוספים נשמרים לתיאום בלבד. הסוכן הראשי הוא המבצע היחיד.','hint'),button);
  form.addEventListener('submit',event=>{event.preventDefault();save({action:'participants',task_id:task.id,participants:chosenParticipants(group)},button);});return form;
}
function selectTask(task) {if(matchMedia('(max-width:680px)').matches)setMobileView('tasks');selected=task.id;renderDetail();$('detail').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'start'});}
function renderActive() {
  const root=$('active-tasks');root.replaceChildren();
  const active=state.tasks.filter(task=>task.activity?.manual||['assigned','working','testing'].includes(task.status));
  if(!active.length) root.append(el('p','אין משימה שרצה כרגע.','empty'));
  for(const task of active) {const row=el('div',undefined,'active-item'),button=el('button','#'+task.id+' · '+task.request.slice(0,100));button.type='button';button.addEventListener('click',()=>selectTask(task));row.append(button,el('span',task.agent||'ללא סוכן','owner'),badge(task.status,task.id));row.append(activityLine(task));root.append(row);}
}
function renderTasks() {
  const root=$('tasks'); root.replaceChildren();
  const filters=$('task-filters');filters.replaceChildren();
  for(const [key,filter] of Object.entries(taskFilters)) {
    const button=el('button',filter.label+' ('+state.tasks.filter(filter.matches).length+')','secondary');
    button.type='button';button.setAttribute('aria-pressed',String(taskFilter===key));
    button.addEventListener('click',()=>{taskFilter=key;renderTasks();filters.querySelector('[aria-pressed="true"]').focus();});filters.append(button);
  }
  const visible=state.tasks.filter(taskFilters[taskFilter].matches);
  $('filter-result').textContent='מוצגות '+visible.length+' מתוך '+state.tasks.length+' משימות';
  if(!state.tasks.length) { root.append(el('p','אין משימות עדיין. צרו משימה ואז שייכו לה סוכן.','empty')); return; }
  if(!visible.length) root.append(el('p','אין משימות בסינון שנבחר.','empty'));
  for(const task of visible) {
    const row=el('article',undefined,'task'), top=el('div',undefined,'task-top'), title=el('button',task.request.length>110?task.request.slice(0,110)+'…':task.request,'task-title');
    title.type='button'; title.addEventListener('click',()=>selectTask(task));
    if(['assigned','working','testing'].includes(task.status)) row.classList.add('active-task');
    top.append(title,badge(task.status,task.id)); row.append(top,meta(task));
    if(task.activity?.manual||['assigned','working','testing'].includes(task.status)) row.append(activityLine(task));
    if(task.participants?.length) row.append(el('div','משתתפים: '+task.participants.join(', '),'participants-label'));
    if(task.status==='queued') row.append(assignment(task));root.append(row);
  }
}
function renderInbox(root=$('inbox'), questions=state.pending_questions) {
  root.replaceChildren();
  if(!questions.length) { root.append(el('p','אין שאלות או בקשות אישור שממתינות לך.','empty')); return; }
  for(const question of questions) {
    const card=el('article',undefined,'question'); card.append(el('h3',(question.kind==='approval'?'בקשת אישור':'שאלה')+' · משימה #'+question.task_id),el('div',question.repository+' · '+question.agent,'meta'),el('p',question.question));
    if(question.kind==='approval') {
      card.append(el('p',question.scope==='provider'?'נדרש גם אישור מקורי בסביבת הסוכן. אישור כאן לא מחליף אותו.':'ההחלטה חלה על הפעולה המתוארת בלבד.','hint'));
      const actions=el('div',undefined,'actions');
      for(const [decision,text] of [['approved','אישור הבקשה'],['denied','דחיית הבקשה']]) { const button=el('button',text,decision==='denied'?'danger':''); button.type='button'; button.addEventListener('click',()=>answerQuestion({action:'decide',question_id:question.id,decision},button)); actions.append(button); } card.append(actions);
    } else {
      const form=el('form',undefined,'answer-form'), label=el('label','התשובה שלך'), input=el('textarea');
      form.noValidate=true;input.rows=3;input.required=true;input.maxLength=8000;input.setAttribute('aria-label','תשובה לשאלה '+question.id);
      input.value=answerDrafts.get(question.id)||'';label.append(input);
      const message=el('p',undefined,'hint');message.setAttribute('role','status');
      const choices=el('div',undefined,'actions answer-choices');
      function rememberAnswer() {
        answerDrafts.set(question.id,input.value);
        for(const choice of choices.children) choice.setAttribute('aria-pressed',String(choice.dataset.answer===input.value));
      }
      input.addEventListener('input',rememberAnswer);
      for(const [index,option] of question.options.entries()) {
        const choice=el('button',(index+1)+'. '+option,'secondary');choice.dataset.answer=option;choice.type='button';choice.setAttribute('aria-pressed',String(option===input.value));
        choice.addEventListener('click',()=>{input.value=option;rememberAnswer();message.textContent='האפשרות נבחרה. לחצו על שליחת תשובה.';});choices.append(choice);
      }
      const button=el('button','שליחת תשובה');button.type='submit';form.append(el('p',question.options.length?'בחרו אחת מתוך '+question.options.length+' אפשרויות, או כתבו תשובה:':'כתבו תשובה:','hint'),choices,label,button,message);
      form.addEventListener('submit',async event=>{
        event.preventDefault();if(button.disabled)return;
        if(!input.value.trim()){message.textContent='יש לבחור אפשרות או לכתוב תשובה לפני השליחה.';input.focus();return;}
        rememberAnswer();button.textContent='שולח…';message.textContent='שולח את התשובה…';
        const result=await answerQuestion({action:'answer',question_id:question.id,answer:input.value},button);
        if(result!==undefined) {answerDrafts.delete(question.id);message.textContent='התשובה נשמרה.';}
        else message.textContent=$('feedback').textContent||'השליחה לא הושלמה. התשובה נשמרה בטופס; נסו שוב.';
        button.textContent='שליחת תשובה';
      });card.append(form);
    } root.append(card);
  }
}
function renderDetail() {
  const root=$('detail'),heading=el('h2','פרטי משימה');heading.id='detail-title';root.replaceChildren(heading);
  const task=state.tasks.find(task=>task.id===selected);
  if(!task) {root.append(el('p','בחרו משימה כדי לראות את הבקשה, ההחלטות ותוצאות ההפעלה.','empty'));return;}
  root.append(meta(task),badge(task.status,task.id),el('pre',task.request),activityLine(task));
  root.append(el('h3','הסוכנים במשימה'));
  if(task.status==='queued') root.append(assignment(task));
  else root.append(el('p','סוכן ראשי: '+(task.agent||'ללא שיוך')+'. החלפת המבצע זמינה כשהמשימה בתור.','assignment-note'));
  root.append(participantsEditor(task));
  if(task.blocked_reason) root.append(el('h3',task.activity?.manual?'סיבת עצירת ההרצה הקודמת ב־Hub':'סיבת החסם'),el('pre',task.blocked_reason));
  if(task.verification) root.append(el('h3','תיעוד האימות'),el('pre',task.verification));
  for(const question of state.questions.filter(q=>q.task_id===task.id)) {
    const card=el('article',undefined,'question'); card.append(el('h3',question.kind==='approval'?'החלטת אישור':'שאלה ותשובה'),el('p',question.question));
    const answer=question.answer==='approved'?'אושר':question.answer==='denied'?'נדחה':question.answer;
    card.append(el('p',answer||'ממתינה לתשובה')); if(question.decided_by) card.append(el('div',question.decided_by+' · '+localTime(question.decided_at),'meta'));root.append(card);
  }
  for(const run of (state.runs||[]).filter(run=>run.task_id===task.id)) {
    const details=el('details'), summary=el('summary','הפעלה '+(run.turn+1)+' · '+run.state+' · '+localTime(run.started_at)); details.append(summary,el('pre',run.result||'ההפעלה נרשמה; תוצאה עדיין לא התקבלה.'));root.append(details);
  }
}
function render() {
  if(state.version){const current=$('client-version').value||state.version.version;$('current-version').textContent=current;$('server-version').textContent='גרסת שרת: '+state.version.version;$('version-changes').replaceChildren(...state.version.changes.map(change=>el('li',change)));document.querySelector('.brand small').textContent='מרכז החלטות · v'+current;}
  $('phone-link').hidden=!state.phone_url;
  if(state.phone_url) $('phone-link').href=state.phone_url;
  $('task-count').textContent=state.tasks.length; $('pending-count').textContent=state.pending_questions.length; $('active-count').textContent=state.tasks.filter(taskFilters.active.matches).length;
  $('execution-mode').textContent=state.worker.read_only?'קריאה בלבד':'כתיבה מאושרת למשימות: '+state.worker.write_tasks.join(', ');
  $('worker-status').textContent=state.worker.running?'המפעיל המקומי פועל':'המפעיל המקומי עצור'; $('worker-toggle').textContent=state.worker.running?'עצירת המפעיל':'הפעלת המפעיל'; $('worker-toggle').disabled=false;
  const repo=$('repository'); if(!repo.options.length) for(const name of Object.keys(state.repositories)) {const option=el('option',name);option.value=name;repo.append(option);}
  const newAgent=$('new-agent');if(newAgent.options.length===1) for(const agent of state.agents){const option=el('option',agent.name);option.value=agent.name;newAgent.append(option);}
  if(!$('new-participants').querySelector('input')) participantChoices($('new-participants'));
  $('agents').replaceChildren(...state.agents.map(agent=>{const node=el('div',undefined,'agent');node.dataset.initial=agent.name.slice(0,2).toUpperCase();const active=state.tasks.some(task=>task.agent===agent.name&&['working','testing','assigned'].includes(task.status));node.append(el('span',agent.name,'agent-name'),el('span',state.tasks.some(t=>t.agent===agent.name&&t.activity?.manual)?'מעקב סשן ידני':active?'בעבודה עכשיו':agent.connected?'רשום כזמין':'מנותק','muted'));return node;}));
  renderActive();renderTasks();renderInbox();renderDetail();
}
async function refresh(force=false) {
  if(stopped) return;
  try {
    const response=await fetch('/api/status'); if(!response.ok) throw new Error('חיבור לשרת');
    const next=await response.json(), signature=JSON.stringify(next);
    if(force || (signature!==previous && !document.activeElement.closest('form'))) {state=next;previous=signature;render();}
    $('last-update').textContent='עודכן '+new Date().toLocaleTimeString('he-IL',{timeZone:'Asia/Jerusalem'});
    $('connection-status').textContent='חיבור פרטי תקין';document.querySelector('.connection').classList.remove('offline');document.body.classList.remove('hub-offline');
    if(connectionErrorShown) feedback('');
  } catch(error) {$('connection-status').textContent='אין חיבור לשרת';document.querySelector('.connection').classList.add('offline');document.body.classList.add('hub-offline');feedback('אין חיבור ליישום המקומי. בדקו שהמחשב, היישום ו־Tailscale פועלים.',true);connectionErrorShown=true;}
}
$('create-form').addEventListener('submit',async event=>{
  event.preventDefault(); const button=event.submitter;
  $('create-error').textContent='';
  const task=await save({action:'create',repository:$('repository').value,request:$('request').value,priority:Number($('priority').value),agent:$('new-agent').value||null,participants:chosenParticipants($('new-participants'))},button);
  if(task) {$('request').value='';$('create-dialog').close();selectTask(task);}
});
$('new-task').addEventListener('click',()=>{$('create-error').textContent='';$('create-dialog').showModal();});
$('close-create').addEventListener('click',()=>$('create-dialog').close());
$('check-update').addEventListener('click',async event=>{
  const button=event.currentTarget;button.disabled=true;$('update-link').hidden=true;$('update-status').textContent='בודק גרסאות שפורסמו…';
  try{
    const result=await action({action:'check_update',client_version:$('client-version').value||state.version.version});
    const messages={unpublished:'טרם פורסם Release לציבור. הגרסה המקומית מוכנה לבדיקה.',unavailable:'לא ניתן לבדוק כרגע. בדקו את החיבור ונסו שוב.',current:'הגרסה שלך מעודכנת ביחס לגרסה הציבורית.'};
    $('update-status').textContent=result.available?'זמינה גרסה '+result.latest+'. '+result.notes:messages[result.status]||'לא התקבלה תוצאת עדכון.';
    if(result.available){$('update-link').href=result.release_url;$('update-link').hidden=false;}
  }catch(error){$('update-status').textContent='בדיקת העדכון נכשלה: '+error.message;}
  finally{button.disabled=false;}
});
$('refresh').addEventListener('click',()=>refresh(true));
$('refresh-page').addEventListener('click',()=>location.reload());
$('worker-toggle').addEventListener('click',event=>save({action:state.worker.running?'stop_worker':'start_worker'},event.currentTarget));
$('shutdown').addEventListener('click',async event=>{
  event.currentTarget.disabled=true;
  try {await action({action:'shutdown'});stopped=true;feedback('היישום והמפעיל נעצרים. ניתן להפעיל שוב מקיצור ההפעלה.');$('worker-status').textContent='היישום נעצר';$('worker-toggle').disabled=true;}
  catch(error){feedback(error.message,true);event.currentTarget.disabled=false;}
});
refresh(); setInterval(()=>refresh(),3000);

$('close-answer').addEventListener('click',()=>$('answer-dialog').close());

function setMobileView(view) {
  if(!['decisions','tasks','agents','connection','version'].includes(view)) return;
  document.body.dataset.mobileView=view;
  for(const button of document.querySelectorAll('.mobile-tabs button')) button.setAttribute('aria-pressed',String(button.dataset.view===view));
}
for(const button of document.querySelectorAll('.mobile-tabs button')) button.addEventListener('click',()=>setMobileView(button.dataset.view));
