"""Read real provider events; never use polling time as an agent heartbeat."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re


def timestamp(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00').replace(' ', 'T')).replace(tzinfo=timezone.utc).timestamp()


def event_summary(record):
    message = record.get('message', {})
    blocks = message.get('content', []) if isinstance(message, dict) else []
    if not isinstance(blocks, list): return None
    for block in reversed(blocks):
        if not isinstance(block, dict): continue
        kind = block.get('type')
        if kind == 'tool_use':
            name = block.get('name', '')
            if name == 'Bash':
                command = block.get('input', {}).get('command', '')
                for pattern, label in [(r'\bcargo\s+(test|nextest)\b', 'הרצת בדיקות Rust'),
                                       (r'\bcargo\s+(build|check|clippy)\b', 'בנייה או בדיקת קוד Rust'),
                                       (r'\bgit\s+merge\b', 'מיזוג Git'), (r'\bgit\b', 'פעולת Git')]:
                    if re.search(pattern, command): return label
                return 'הרצת פקודה'
            return {'Read':'קריאת קובץ','Edit':'עריכת קובץ','Write':'כתיבת קובץ',
                    'Grep':'חיפוש בקוד','Glob':'איתור קבצים'}.get(name, 'הפעלת כלי')
        if kind == 'tool_result': return 'התקבלה תוצאת כלי'
        if kind == 'text' and record.get('type') == 'assistant': return 'התקבל דיווח מהסוכן'
    return None


class ActivityReader:
    def __init__(self, projects=None):
        self.projects = Path(projects) if projects else Path.home()/'.claude'/'projects'
        self.sessions = {}

    def read(self, task, run, workspace, now=None):
        now = datetime.now(timezone.utc).timestamp() if now is None else now
        result = {'source':'none','summary':'אין דיווח פעילות זמין מהסוכן','at':None,'age_seconds':None,'stale':False}
        if not run: return result
        result['started_at'] = run['started_at']
        if task['agent'] != 'claude': return result
        key = (task['id'], run['started_at'], workspace)
        path = self.sessions.get(key)
        try:
            if path is None:
                folder = self.projects/re.sub(r'[^a-zA-Z0-9]', '-', workspace)
                candidates = sorted(folder.glob('*.jsonl'), key=lambda p:p.stat().st_mtime, reverse=True)[:64]
                for candidate in candidates:
                    if candidate.stat().st_mtime < timestamp(run['started_at']): continue
                    with candidate.open('r', encoding='utf-8') as stream: head = stream.read(262144)
                    for line in head.splitlines():
                        try: record = json.loads(line)
                        except ValueError: continue
                        if record.get('type') != 'user' or os.path.normcase(record.get('cwd','')) != os.path.normcase(workspace): continue
                        content = record.get('message',{}).get('content',[])
                        texts = [content] if isinstance(content,str) else [b.get('text','') for b in content if isinstance(b,dict) and b.get('type')=='text']
                        for text in texts:
                            if not text.startswith('This is the WORKER execution route,'): continue
                            try: context=json.loads(text.split('All questions and decisions from earlier turns are included below.\n',1)[1])
                            except (ValueError,IndexError): continue
                            if context.get('task',{}).get('id')==task['id'] and timestamp(record['timestamp'])>=timestamp(run['started_at']):
                                path=candidate;self.sessions[key]=path;break
                        if path: break
                    if path: break
            if path:
                with path.open('rb') as stream:
                    stream.seek(max(0,path.stat().st_size-2097152));lines=stream.read().decode('utf-8',errors='replace').splitlines()
                latest = None
                for line in lines:
                    try:
                        record=json.loads(line);summary=event_summary(record)
                        if summary and record.get('timestamp'):
                            at=timestamp(record['timestamp'])
                            if at>=timestamp(run['started_at']) and (latest is None or at>latest[0]): latest=(at,record['timestamp'],summary)
                    except (ValueError,TypeError,KeyError): continue
                if latest:
                    age=max(0,int(now-latest[0]));result.update(source='claude',summary=latest[2],at=latest[1],age_seconds=age,
                        stale=task['status'] in {'working','testing','assigned'} and age>=120)
        except (OSError,ValueError,TypeError): pass
        return result
