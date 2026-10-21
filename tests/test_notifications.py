from contextlib import closing
import json
from pathlib import Path
import tempfile
import unittest
from hub import Hub
from notifications import Push, events, payload


class PushTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.database = str(Path(self.tmp.name) / 'test.sqlite3')
        self.config = {'database': self.database, 'firebase': {'project_id': 'test-project', 'credentials': 'not-used'}}
        with closing(Hub(self.database)) as hub:
            hub.register_agent('codex', True)
            self.task = hub.create_task('test/repo', 'SECRET TASK TEXT')
            hub.assign(self.task['id'], 'codex'); hub.claim('codex')
            hub.transition(self.task['id'], 'codex', 'working')
        self.sent = []
        self.push = Push(self.config, sender=lambda token: self.sent.append(payload(token)))
        self.push.register('test-device-000001', 'test-token-' + 'a' * 40)

    def test_new_question_generic_once_and_unregister(self):
        self.push.tick(); self.assertEqual(self.sent, [])
        with closing(Hub(self.database)) as hub:
            hub.ask(self.task['id'], 'codex', 'SECRET QUESTION', ['SECRET OPTION'])
        self.push.tick();self.push.tick()
        self.assertEqual(len(self.sent), 1)
        self.assertNotIn('SECRET', json.dumps(self.sent))
        self.assertNotIn('data', self.sent[0]['message'])
        self.push.register('test-device-000001', None)
        with self.push.connect() as db: self.assertEqual(db.execute('SELECT COUNT(*) FROM push_devices').fetchone()[0], 0)

    def test_validation_and_failed_send_retried(self):
        for device, token in [('x', 'a'*40), ('test-device-000001', 'bad token')]:
            with self.assertRaises(ValueError): self.push.register(device, token)
        with closing(Hub(self.database)) as hub: hub.ask(self.task['id'], 'codex', 'Q?', [])
        def fail(token): raise OSError('offline')
        self.push.sender = fail
        with self.assertRaises(OSError): self.push.tick()
        self.push.sender = lambda token: self.sent.append(payload(token))
        self.push.tick(); self.push.tick()
        self.assertEqual(len(self.sent), 1)

    def test_event_categories_and_existing_history_is_silent(self):
        with closing(Hub(self.database)) as hub: hub.ask(self.task['id'], 'codex', 'Old', [])
        new = Push(self.config, sender=lambda token: self.sent.append(token))
        new.tick(); self.assertEqual(self.sent, [])
        snapshot = {'pending_questions': [{'id': 4, 'kind': 'approval'}],
                    'tasks': [{'id': 1, 'status': 'blocked', 'blocked_reason': 'secret'}, {'id': 2, 'status': 'completed'}]}
        keys = events(snapshot)
        self.assertEqual(len(keys), 3)
        self.assertNotIn('secret', repr(keys))
