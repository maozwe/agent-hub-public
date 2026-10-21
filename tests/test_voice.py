import io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from voice import Voice

class VoiceTests(unittest.TestCase):
    def test_bounds_and_invalid_audio(self):
        voice=Voice()
        for audio in (b'',b'x'*(5*1024*1024+1),b'invalid'):
            with self.assertRaises(Exception): voice.transcribe(audio)
        self.assertFalse(voice.lock.locked())

    def test_draft_uses_local_endpoint_selected_safe_overview(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'README.md').write_text('Safe project description')
            (root/'package.json').write_text('secret: do not send')
            with patch('voice.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='README.md\npackage.json\n.env\nprivate.key\nsrc/main.py')):
                def respond(request,timeout):
                    self.assertEqual(request.full_url,'http://127.0.0.1:11434/api/chat')
                    data=json.loads(request.data);content=data['messages'][1]['content']
                    self.assertNotIn('do not send',content);self.assertNotIn('.env',content)
                    self.assertIn('Safe project description',content)
                    return io.BytesIO(json.dumps({'message':{'content':'Draft'}}).encode())
                with patch('voice.urlopen',side_effect=respond):
                    self.assertEqual(Voice().draft('My request',tmp)['text'],'Draft')

