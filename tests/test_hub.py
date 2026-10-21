import os
import tempfile
import unittest
from hub import Hub


class HubTests(unittest.TestCase):
    def setUp(self):
        self.hub = Hub()
        self.hub.register_agent("codex", connected=True)

    def tearDown(self):
        self.hub.close()

    def test_priority_capacity_and_completion(self):
        self.hub.create_task("owner/one", "Normal")
        urgent = self.hub.create_task("owner/two", "Urgent", priority=0)
        for task in self.hub.status()["tasks"]:
            self.hub.assign(task["id"], "codex")
        self.assertEqual(self.hub.claim("codex")["id"], urgent["id"])
        self.assertIsNone(self.hub.claim("codex"))
        with self.assertRaises(ValueError):
            self.hub.transition(urgent["id"], "codex", "completed")
        self.hub.transition(urgent["id"], "codex", "working")
        self.hub.transition(urgent["id"], "codex", "testing")
        with self.assertRaises(ValueError):
            self.hub.transition(urgent["id"], "codex", "completed", "")
        self.hub.transition(urgent["id"], "codex", "completed", "Validation passed")
        self.assertIsNotNone(self.hub.claim("codex"))

    def test_questions_keep_context_and_wait_for_all_answers(self):
        task = self.hub.create_task("owner/repo", "Build task")
        self.hub.assign(task["id"], "codex")
        self.hub.claim("codex")
        self.hub.transition(task["id"], "codex", "working")
        first = self.hub.ask(task["id"], "codex", "Which database?", ["SQLite", "Postgres"])
        second = self.hub.ask(task["id"], "codex", "Which environment?", [])
        question = self.hub.status()["pending_questions"][0]
        self.assertEqual(question["repository"], "owner/repo")
        self.assertEqual(question["agent"], "codex")
        self.assertEqual(question["options"], ["SQLite", "Postgres"])
        self.hub.answer(first, "SQLite")
        self.assertEqual(self.hub.task(task["id"])["status"], "waiting_for_user")
        self.hub.answer(second, "Local")
        self.assertEqual(self.hub.task(task["id"])["status"], "working")
        with self.assertRaises(ValueError):
            self.hub.answer(first, "Changed")

    def test_disconnected_agent_and_wrong_agent(self):
        self.hub.register_agent("claude")
        task = self.hub.create_task("owner/repo", "Task")
        self.hub.assign(task["id"], "codex")
        with self.assertRaises(ValueError):
            self.hub.claim("claude")
        self.hub.claim("codex")
        with self.assertRaises(ValueError):
            self.hub.transition(task["id"], "claude", "working")

    def test_durable_atomic_claims(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "hub.sqlite3")
            first, second = Hub(path), Hub(path)
            try:
                first.register_agent("one", True)
                second.register_agent("two", True)
                task = first.create_task("owner/repo", "Persistent", 1)
                first.assign(task["id"], "one")
                self.assertEqual(first.claim("one")["id"], task["id"])
                self.assertIsNone(second.claim("two"))
                self.assertEqual(second.task(task["id"])["priority_source"], "user")
            finally:
                first.close()
                second.close()

    def test_validation(self):
        for priority in [-1, 5, True, "high"]:
            with self.assertRaises(ValueError):
                self.hub.create_task("owner/repo", "Task", priority)
        with self.assertRaises(ValueError):
            self.hub.create_task("repo", "Task")

    def test_only_explicit_assignments_and_next_after_completion(self):
        unassigned = self.hub.create_task("owner/repo", "Unassigned", 0)
        self.hub.register_agent("other", True)
        other = self.hub.create_task("owner/repo", "Other", 0)
        self.hub.assign(other["id"], "other")
        self.assertIsNone(self.hub.claim("codex"))
        first = self.hub.create_task("owner/repo", "First")
        second = self.hub.create_task("owner/repo", "Second")
        self.hub.assign(first["id"], "codex")
        self.hub.assign(second["id"], "codex")
        self.hub.claim("codex")
        with self.assertRaises(ValueError):
            self.hub.assign(first["id"], "other")
        self.hub.transition(first["id"], "codex", "working")
        self.hub.transition(first["id"], "codex", "testing")
        result = self.hub.complete_and_next(first["id"], "codex", "unit tests passed")
        self.assertEqual(result["completed"]["status"], "completed")
        self.assertEqual(result["next_task"]["id"], second["id"])
        self.assertEqual(self.hub.task(unassigned["id"])["status"], "queued")

    def test_approval_decisions_are_audited_and_denial_blocks_completion(self):
        task = self.hub.create_task("owner/repo", "Deploy")
        self.hub.assign(task["id"], "codex")
        self.hub.claim("codex")
        self.hub.transition(task["id"], "codex", "working")
        request = self.hub.request_approval(task["id"], "codex", "Deploy build abc", "provider")
        with self.assertRaises(ValueError):
            self.hub.answer(request, "yes")
        with self.assertRaises(ValueError):
            self.hub.decide(request, "maybe", "maoz")
        self.hub.decide(request, "denied", "maoz")
        context = self.hub.task_context(task["id"], "codex")
        decision = context["questions"][0]
        self.assertEqual(decision["answer"], "denied")
        self.assertEqual(decision["decided_by"], "maoz")
        self.assertTrue(decision["decided_at"])
        self.assertEqual(context["task"]["status"], "blocked")
        with self.assertRaises(ValueError):
            self.hub.transition(task["id"], "codex", "working")
        with self.assertRaises(ValueError):
            self.hub.decide(request, "approved", "maoz")
        with self.assertRaises(PermissionError):
            self.hub.task_context(task["id"], "other")

    def test_questions_and_approvals_wait_for_all_responses(self):
        task = self.hub.create_task("owner/repo", "Build")
        self.hub.assign(task["id"], "codex")
        self.hub.claim("codex")
        self.hub.transition(task["id"], "codex", "working")
        question = self.hub.ask(task["id"], "codex", "Which target?", ["staging"])
        approval = self.hub.request_approval(task["id"], "codex", "Publish build abc", "application")
        self.hub.decide(approval, "approved", "maoz")
        self.assertEqual(self.hub.task(task["id"])["status"], "waiting_for_user")
        self.hub.answer(question, "staging", "maoz")
        self.assertEqual(self.hub.task(task["id"])["status"], "working")

    def test_testing_approval_resumes_testing(self):
        task = self.hub.create_task("owner/repo", "Test")
        self.hub.assign(task["id"], "codex")
        self.hub.claim("codex")
        self.hub.transition(task["id"], "codex", "working")
        self.hub.transition(task["id"], "codex", "testing")
        approval = self.hub.request_approval(task["id"], "codex", "Run integration test", "application")
        self.hub.decide(approval, "approved", "maoz")
        self.assertEqual(self.hub.task(task["id"])["status"], "testing")

    def test_old_database_migration_preserves_answers(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "old.sqlite3")
            db = sqlite3.connect(path)
            db.execute("CREATE TABLE questions(id INTEGER PRIMARY KEY, task_id INTEGER, "
                       "agent TEXT, question TEXT, options TEXT, answer TEXT)")
            db.execute("INSERT INTO questions VALUES(1,1,'codex','Target?','[]','local')")
            db.commit()
            db.close()
            migrated = Hub(path)
            try:
                row = dict(migrated.db.execute("SELECT * FROM questions").fetchone())
                self.assertEqual(row["answer"], "local")
                self.assertEqual(row["kind"], "question")
                self.assertIsNone(row["decided_by"])
            finally:
                migrated.close()

    def test_blocker_reason_is_preserved_in_task_context(self):
        task = self.hub.create_task("owner/repo", "Read")
        self.hub.assign(task["id"], "codex")
        self.hub.claim("codex")
        self.hub.transition(task["id"], "codex", "working")
        self.hub.block(task["id"], "codex", "Missing local input file")
        context = self.hub.task_context(task["id"], "codex")
        self.assertEqual(context["task"]["blocked_reason"], "Missing local input file")


if __name__ == "__main__":
    unittest.main()
