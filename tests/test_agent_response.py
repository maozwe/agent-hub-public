import unittest
from worker import parse_agent_response, task_write_scope
class ResponseTests(unittest.TestCase):
 def test_commentary_question(self):
  text='Read-only inspection. '+ '{"state":"question","question":"Which version?","options":["new repo"]}'
  self.assertEqual(parse_agent_response(text)['state'],'question')
 def test_fenced(self):
  self.assertEqual(parse_agent_response('```json\n{"state":"blocked","summary":"Need input"}\n```')['state'],'blocked')
 def test_reject_ambiguous_invalid(self):
  for text in ['', '{}', '{"state":"completed"}', '{"state":"question","question":"Q","options":"x"}', '{"state":"blocked","summary":"a"}{"state":"blocked","summary":"b"}', '{"state":"blocked","summary":"a"} trailing']:
   with self.assertRaises(ValueError): parse_agent_response(text)
 def test_grant_exact_scope(self):
  task={'id':6,'agent':'claude','repository':'test/repo','request':'Update'}
  config={'task_write_grants':{'6':{**task,'scope':'Update software'}}}
  self.assertEqual(task_write_scope(config,{'task':task}),'Update software')
  for key,value in [('id',7),('agent','codex'),('repository','other/repo'),('request','Other')]:
   self.assertFalse(task_write_scope(config,{'task':{**task,key:value}}))
  self.assertFalse(task_write_scope({}, {'task':task}))

class DelegateTests(unittest.IsolatedAsyncioTestCase):
 async def test_scope_controls_provider_mode(self):
  from unittest.mock import patch
  from types import SimpleNamespace
  from worker import rutherford_delegate
  class Session:
   async def call_tool(self,name,args):
    self.args=args
    return SimpleNamespace(isError=False,structuredContent={'result':'envelope'})
  session=Session()
  with patch('worker.decode',return_value={'ok':True,'text':'Explanation {"state":"question","question":"Source?","options":[]}','session_id':'test'}):
   for scope,mode in [('', 'read_only'),('Update task 6 only','write')]:
    result=await rutherford_delegate(session,'claude','test',{'task':{'id':6}},scope)
    self.assertEqual(result['state'],'question')
    self.assertEqual(session.args['safety_mode'],mode)
    self.assertEqual(session.args['trust_workspace'],bool(scope))
    self.assertEqual(session.args['fallback'],[])
    self.assertEqual(session.args['direct_workspace_mutation'],bool(scope))
