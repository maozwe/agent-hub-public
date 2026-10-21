'use strict';
let voiceBusy=false;
function voiceControls(input, context) {
  const root=el('div'),record=el('button','🎙 הקלטה'),draft=el('button','סידור לטיוטה מקומית'),message=el('p',undefined,'hint');
  record.type=draft.type='button';message.setAttribute('role','status');root.append(record,draft,message);
  let recorder,stream,timer,chunks=[];
  const update=text=>{input.value=text.slice(0,input.maxLength>0?input.maxLength:8000);input.dispatchEvent(new Event('input',{bubbles:true}));};
  const stop=()=>{clearTimeout(timer);if(recorder?.state==='recording')recorder.stop();stream?.getTracks().forEach(t=>t.stop());};
  record.addEventListener('click',async()=>{
    if(recorder?.state==='recording'){stop();return;}
    if(voiceBusy){message.textContent='הקלטה או תמלול אחר עדיין פעילים.';return;}
    voiceBusy=true;record.disabled=true;
    try {
      if(!navigator.mediaDevices?.getUserMedia||!window.MediaRecorder)throw Error('ההקלטה אינה זמינה כאן; השתמש בדפדפן תומך או באפליקציה מעודכנת.');
      stream=await navigator.mediaDevices.getUserMedia({audio:true});chunks=[];recorder=new MediaRecorder(stream);
      recorder.ondataavailable=e=>{if(e.data.size)chunks.push(e.data);};
      recorder.onstop=async()=>{
        record.disabled=true;draft.disabled=true;message.textContent='מתמלל במחשב שלך…';
        try {
          const blob=new Blob(chunks,{type:recorder.mimeType});
          if(blob.size>5*1024*1024)throw Error('ההקלטה גדולה מדי. נסה הקלטה קצרה יותר.');
          const response=await fetch('/api/transcribe',{method:'POST',headers:{'X-Hub-CSRF':document.querySelector('meta[name="hub-csrf"]').content},body:blob});
          const result=await response.json();if(!response.ok)throw Error(result.error||'התמלול נכשל. רענן ונסה שוב.');
          if(!result.text.trim())throw Error('לא זוהה דיבור.');
          update([input.value,result.text].filter(Boolean).join('\n'));message.textContent='התמלול נוסף. אפשר לערוך או לסדר לטיוטה לפני השליחה.';
        } catch(e){message.textContent=e.message;} finally {chunks=[];record.textContent='🎙 הקלטה';record.disabled=draft.disabled=false;voiceBusy=false;}
      };
      recorder.start();record.disabled=false;record.textContent='עצירה ותמלול';message.textContent='מקליט — עד 90 שניות. האודיו מועבר רק למחשב שלך.';timer=setTimeout(stop,90000);
    } catch(e){stop();voiceBusy=false;record.disabled=false;message.textContent=e.name==='NotAllowedError'?'יש לאשר גישה למיקרופון כדי להקליט.':e.name==='NotReadableError'?'לא ניתן לפתוח את המיקרופון. ודא שהאפליקציה מעודכנת ושאין שיחה או הקלטה אחרת פעילה, ונסה שוב.':e.message;}
  });
  draft.addEventListener('click',async()=>{
    if(voiceBusy)return;
    if(!input.value.trim()){message.textContent='הקלט או כתוב טקסט תחילה.';return;}
    voiceBusy=true;draft.disabled=record.disabled=true;const original=input.value;input.readOnly=true;message.textContent='מכין טיוטה עם ההקשר של הפרויקט במחשב שלך…';
    try {const result=await action({action:'voice_draft',text:original,...context()});update(result.text);message.textContent='טיוטה מוכנה. בדוק וערוך לפני השליחה.';}
    catch(e){message.textContent='הטיוטה לא נוצרה; הטקסט נשמר. '+e.message;}
    finally{input.readOnly=false;voiceBusy=false;draft.disabled=record.disabled=false;}
  });
  window.addEventListener('pagehide',stop,{once:true});
  return root;
}
