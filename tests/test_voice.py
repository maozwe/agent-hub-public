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
