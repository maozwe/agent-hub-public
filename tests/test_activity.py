import json,tempfile,unittest
from pathlib import Path
from activity import ActivityReader,event_summary,timestamp
class ActivityTests(unittest.TestCase):
 def test_manual_session_is_exact_read_only_binding(self):
  with tempfile.TemporaryDirectory() as tmp:
   folder=Path(tmp)/'workspace';folder.mkdir()
   sid='645a4f60-2d68-4e05-87dc-0ed03242c04d'
   record={'type':'assistant','sessionId':sid,'cwd':'workspace','timestamp':'2026-10-21T17:10:00Z','message':{'content':[{'type':'tool_use','name':'Edit'}]}}
   path=folder/(sid+'.jsonl');path.write_text(json.dumps(record),encoding='utf-8')
   task={'id':6,'agent':'claude','repository':'test/repo','status':'blocked'}
   binding={'session_id':sid,'repository':'test/repo','since':'2026-10-21T17:00:00Z'}
   reader=ActivityReader(tmp)
   result=reader.read(task,None,'workspace',timestamp('2026-10-21T17:10:10Z'),manual=binding)
   self.assertEqual(result['summary'],'עריכת קובץ');self.assertTrue(result['manual']);self.assertFalse(result['stale'])
   self.assertEqual(task['status'],'blocked');self.assertEqual(path.read_text(encoding='utf-8'),json.dumps(record))
   self.assertTrue(reader.read(task,None,'workspace',timestamp('2026-10-21T17:13:00Z'),manual=binding)['stale'])
   for changed in [{'repository':'other/repo'},{'session_id':'../escape'}]:
    self.assertIsNone(reader.read(task,None,'workspace',manual={**binding,**changed})['at'])
   path.write_text(json.dumps({**record,'cwd':'other'}),encoding='utf-8')
   self.assertIsNone(reader.read(task,None,'workspace',manual=binding)['at'])
   final={**record,'message':{'stop_reason':'end_turn','content':[{'type':'text','text':'CI still running'}]}}
   path.write_text(json.dumps(final),encoding='utf-8')
   self.assertEqual(reader.read(task,None,'workspace',manual=binding)['report'],'CI still running')
   path.write_text(json.dumps(final)+'\n'+json.dumps(record),encoding='utf-8')
   self.assertNotIn('report',reader.read(task,None,'workspace',manual=binding))
 def test_real_events_and_stale_without_poll_heartbeat(self):
  with tempfile.TemporaryDirectory() as tmp:
   folder=Path(tmp)/'workspace';folder.mkdir()
   context={'task':{'id':6}}
   prompt='This is the WORKER execution route, test. All questions and decisions from earlier turns are included below.\n'+json.dumps(context)
   records=[{'type':'user','cwd':'workspace','timestamp':'2026-10-21T17:00:01Z','message':{'content':prompt}},
    {'type':'assistant','timestamp':'2026-10-21T17:00:02Z','message':{'content':[{'type':'tool_use','name':'Bash','input':{'command':'cargo test'}}]}},
    {'type':'assistant','timestamp':'2026-10-21T17:03:00Z','message':{'content':[{'type':'thinking','thinking':'private'}]}}]
   (folder/'s.jsonl').write_text('\n'.join(json.dumps(r) for r in records),encoding='utf-8')
   reader=ActivityReader(tmp);task={'id':6,'agent':'claude','status':'working'};run={'started_at':'2026-10-21 17:00:00'}
   r=reader.read(task,run,'workspace',timestamp('2026-10-21T17:04:00Z'))
   self.assertEqual(r['summary'],'הרצת בדיקות Rust');self.assertEqual(r['age_seconds'],238);self.assertTrue(r['stale'])
   self.assertIsNone(reader.read({**task,'id':7},run,'workspace')['at'])
   self.assertIsNone(reader.read({**task,'agent':'codex'},run,'workspace')['at'])
 def test_no_thinking_or_command_contents_exposed(self):
  self.assertIsNone(event_summary({'type':'assistant','message':{'content':[{'type':'thinking','thinking':'secret'}]}}))
  self.assertEqual(event_summary({'message':{'content':[{'type':'tool_use','name':'Bash','input':{'command':'echo secret'}}]}}),'הרצת פקודה')
