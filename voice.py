"""Local-only transcription and draft preparation. Never executes model output."""
import io
import json
from pathlib import Path
import re
import subprocess
import threading
from urllib.request import Request, urlopen

class Voice:
    def __init__(self):
        self.lock=threading.Lock()
        self.model=None

    def transcribe(self, audio):
        if not audio or len(audio)>5*1024*1024: raise ValueError('הקלטה ריקה או גדולה מדי')
        if not self.lock.acquire(blocking=False): raise ValueError('התמלול עסוק; נסה שוב בעוד רגע')
        try:
            from faster_whisper import WhisperModel
            import av
            import numpy as np
            frames=[]; count=0
            with av.open(io.BytesIO(audio)) as container:
                resampler=av.AudioResampler(format='s16',layout='mono',rate=16000)
                for frame in container.decode(audio=0):
                    for converted in resampler.resample(frame):
                        values=converted.to_ndarray().flatten();count+=len(values)
                        if count>16000*95: raise ValueError('ההקלטה מוגבלת ל־90 שניות')
                        frames.append(values)
            if not frames: raise ValueError('אין דגימות אודיו')
            samples=np.concatenate(frames).astype(np.float32)/32768.0
            if self.model is None:
                self.model=WhisperModel('small',device='cpu',compute_type='int8',cpu_threads=4,local_files_only=True)
            segments,_=self.model.transcribe(samples,language='he',vad_filter=True,beam_size=3)
            return {'text':' '.join(s.text.strip() for s in segments).strip()}
        finally: self.lock.release()
