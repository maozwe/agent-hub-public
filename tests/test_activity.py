import json,tempfile,unittest
from pathlib import Path
from activity import ActivityReader,event_summary,timestamp
class ActivityTests(unittest.TestCase):
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
