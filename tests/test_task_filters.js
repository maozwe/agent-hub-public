const assert=require('node:assert/strict');
const filters=require('../web/task-filters.js');
const cases=[['queued',null,'unassigned'],['queued','codex','waiting'],['assigned','codex','active'],
  ['working','codex','active'],['testing','codex','active'],['waiting_for_user','codex','waiting'],
  ['blocked','codex','waiting'],['completed','codex','completed']];
for(const [status,agent,expected] of cases){
  const task={status,agent};
  assert.equal(filters.all.matches(task),true);
  assert.deepEqual(Object.entries(filters).filter(([key,f])=>key!=='all'&&f.matches(task)).map(([key])=>key),[expected]);
}
console.log('PASS: all eight task/assignment cases map to exactly one status filter');

const manual={status:'blocked',agent:'claude',activity:{manual:true}};
assert.equal(filters.active.matches(manual),true);
assert.equal(filters.waiting.matches(manual),false);
