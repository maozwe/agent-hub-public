'use strict';
const taskFilters = {
  all: {label:'הכול', matches:()=>true},
  completed: {label:'הסתיימו', matches:t=>t.status==='completed'},
  active: {label:'בביצוע', matches:t=>!!t.activity?.manual||['assigned','working','testing'].includes(t.status)},
  unassigned: {label:'לא שויכו', matches:t=>t.status==='queued'&&!t.agent},
  waiting: {label:'ממתינות', matches:t=>!t.activity?.manual&&((t.status==='queued'&&!!t.agent)||['waiting_for_user','blocked'].includes(t.status))}
};
if(typeof module!=='undefined') module.exports=taskFilters;
