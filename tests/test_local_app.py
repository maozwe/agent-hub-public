from contextlib import closing
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from hub import Hub
from local_app import make_server


class LocalAppTests(unittest.TestCase):
    def test_manual_completion_is_atomic_idempotent_and_does_not_claim_next(self):
        from unittest.mock import patch
        with closing(Hub(self.config['database'])) as hub:
            hub.register_agent('claude',True)
            task=hub.create_task('test/local','Manual task',2)
            hub.assign(task['id'],'claude');hub.claim('claude')
            hub.transition(task['id'],'claude','working');hub.block(task['id'],'claude','timeout')
            following=hub.create_task('test/local','Next task',2);hub.assign(following['id'],'claude')
            task=hub.task(task['id'])
        task['activity']={'manual':True,'report':'CI still running'}
        self.server.controller.sync_manual_completion(task)
        self.assertEqual(task['status'],'blocked')
        task['activity']['report']=json.dumps({'state':'completed','summary':'Update finished','verification':'Tests passed; no release'})
        with patch.object(Hub,'claim',side_effect=AssertionError('Must not claim')):
            self.server.controller.sync_manual_completion(task)
            self.server.controller.sync_manual_completion(task)
        with closing(Hub(self.config['database'])) as hub:
            saved=hub.task(task['id'])
            self.assertEqual(saved['status'],'completed');self.assertIn('Tests passed',saved['verification'])
            self.assertIsNone(saved['blocked_reason']);self.assertEqual(hub.task(following['id'])['status'],'queued')

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.config = {"database": str(Path(self.directory.name) / "hub.sqlite3"),
                       "agents": ["codex"], "operator": "maoz", "repositories": {"test/local": self.directory.name}}
        self.server = make_server(self.config, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def shutdown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def post(self, data, csrf=True, origin=None):
        headers = {"Content-Type": "application/json", "Origin": origin or self.base}
        if csrf:
            headers["X-Hub-CSRF"] = self.server.controller.token
        with urlopen(Request(self.base + "/api/action", data=json.dumps(data).encode(), headers=headers)) as response:
            return json.load(response)

    def test_create_assign_answer_approval_audit_same_database(self):
        task = self.post({"action": "create", "repository": "test/local", "request": "Synthetic test", "priority": 2})
        self.post({"action": "assign", "task_id": task["id"], "agent": "codex"})
        with closing(Hub(self.config["database"])) as hub:
            hub.claim("codex")
            hub.transition(task["id"], "codex", "working")
            question = hub.ask(task["id"], "codex", "Target?", ["local"])
            approval = hub.request_approval(task["id"], "codex", "Read report", "application")
        self.post({"action": "answer", "question_id": question, "answer": "local"})
        self.post({"action": "decide", "question_id": approval, "decision": "approved"})
        with urlopen(self.base + "/api/status") as response:
            state = json.load(response)
        self.assertEqual(state["tasks"][0]["status"], "working")
        self.assertEqual(state["questions"][1]["decided_by"], "maoz")
        self.assertEqual(state["pending_questions"], [])

    def test_cross_origin_csrf_unknown_repo_and_host_are_rejected(self):
        for csrf, origin in [(False, None), (True, "https://evil.example")]:
            with self.assertRaises(HTTPError) as error:
                self.post({"action": "create"}, csrf=csrf, origin=origin)
            self.assertEqual(error.exception.code, 403)
        with self.assertRaises(HTTPError) as error:
            self.post({"action": "create", "repository": "unknown/repo", "request": "No"})
        self.assertEqual(error.exception.code, 400)
        with self.assertRaises(HTTPError) as error:
            urlopen(Request(self.base + "/api/status", headers={"Host": "evil.example"}))
        self.assertEqual(error.exception.code, 403)

    def test_html_loads_without_dynamic_unescaped_data(self):
        with urlopen(self.base) as response:
            self.assertIn('dir="rtl"', response.read().decode())
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")

    def test_stale_token_rejected_before_create_and_fresh_token_creates_once(self):
        stale = self.server.controller.token
        self.server.controller.token = "replacement-session-token"
        data = {"action": "create", "repository": "test/local", "request": "Synthetic stale session"}
        headers = {"Content-Type": "application/json", "Origin": self.base, "X-Hub-CSRF": stale}
        with self.assertRaises(HTTPError) as error:
            urlopen(Request(self.base + "/api/action", data=json.dumps(data).encode(), headers=headers))
        self.assertEqual(error.exception.code, 403)
        with urlopen(self.base + "/api/status") as response:
            self.assertEqual(json.load(response)["tasks"], [])
        with urlopen(self.base + "/") as response:
            self.assertIn(self.server.controller.token, response.read().decode())
        self.post(data)
        with urlopen(self.base + "/api/status") as response:
            self.assertEqual(len(json.load(response)["tasks"]), 1)

    def test_push_registration_requires_csrf_and_never_exposes_tokens(self):
        self.server.controller.push.settings = {"project_id": "test-project", "credentials": "not-used"}
        data = {"action": "push_register", "device": "device-test-00001", "token": "a" * 40}
        with self.assertRaises(HTTPError) as error: self.post(data, csrf=False)
        self.assertEqual(error.exception.code, 403)
        self.assertTrue(self.post(data)["enabled"])
        with urlopen(self.base + "/api/status") as response:
            self.assertNotIn("a" * 40, response.read().decode())
        self.assertFalse(self.post({**data, "token": None})["enabled"])

    def test_native_client_version_is_bounded_before_inserting_into_html(self):
        for value, expected in [("0.1.0", 'id="client-version" value="0.1.0"'),
                                ('\"><script>alert(1)</script>', 'id="client-version" value=""')]:
            with urlopen(Request(self.base, headers={"X-Agent-Hub-Client-Version": value})) as response:
                html = response.read().decode()
            self.assertIn(expected, html)
            self.assertNotIn("<script>alert", html)

    def test_create_assignment_and_participants_are_atomic_and_do_not_grant_execution(self):
        self.server.controller.config["agents"].append("reviewer")
        with closing(Hub(self.config["database"])) as hub:
            hub.register_agent("reviewer", True)
        task = self.post({"action": "create", "repository": "test/local", "request": "Review",
                          "agent": "codex", "participants": ["reviewer"]})
        self.assertEqual(task["agent"], "codex")
        self.assertEqual(task["participants"], ["reviewer"])
        with closing(Hub(self.config["database"])) as hub:
            self.assertIsNone(hub.claim("reviewer"))
            with self.assertRaises(PermissionError):
                hub.task_context(task["id"], "reviewer")
        with self.assertRaises(HTTPError):
            self.post({"action": "create", "repository": "test/local", "request": "Invalid",
                       "agent": "missing", "participants": []})
        with urlopen(self.base + "/api/status") as response:
            self.assertEqual(len(json.load(response)["tasks"]), 1)

    def test_participant_updates_preserve_active_owner_and_survive_reopening(self):
        task = self.post({"action": "create", "repository": "test/local", "request": "Read",
                          "agent": "codex"})
        with closing(Hub(self.config["database"])) as hub:
            hub.claim("codex")
            hub.transition(task["id"], "codex", "working")
        self.post({"action": "participants", "task_id": task["id"], "participants": ["codex"]})
        with closing(Hub(self.config["database"])) as hub:
            self.assertEqual(hub.task(task["id"])["participants"], ["codex"])
            self.assertEqual(hub.task(task["id"])["status"], "working")
        with self.assertRaises(HTTPError):
            self.post({"action": "participants", "task_id": task["id"], "participants": ["unknown"]})
        with self.assertRaises(HTTPError):
            self.post({"action": "assign", "task_id": task["id"], "agent": "codex"})

    def test_tailnet_proxy_requires_exact_configured_identity_and_origin(self):
        self.server.controller.config["tailnet"] = {"hostname": "test.tailnet.ts.net", "login": "owner@example.com"}
        for login in [None, "other@example.com"]:
            headers = {"Host": "test.tailnet.ts.net"}
            if login:
                headers["Tailscale-User-Login"] = login
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(self.base + "/api/status", headers=headers))
            self.assertEqual(error.exception.code, 403)
        headers = {"Host": "test.tailnet.ts.net", "Tailscale-User-Login": "owner@example.com"}
        with urlopen(Request(self.base + "/api/status", headers=headers)) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(json.load(response)["phone_url"], "https://test.tailnet.ts.net/")
        headers.update({"Origin": "https://test.tailnet.ts.net", "X-Hub-CSRF": self.server.controller.token,
                        "Content-Type": "application/json"})
        payload = json.dumps({"action": "create", "repository": "test/local", "request": "Phone test"}).encode()
        with urlopen(Request(self.base + "/api/action", data=payload, headers=headers)) as response:
            self.assertEqual(response.status, 200)
        with self.assertRaises(HTTPError) as error:
            urlopen(Request(self.base + "/api/status", headers={"X-Forwarded-For": "100.100.100.100"}))
        self.assertEqual(error.exception.code, 403)
