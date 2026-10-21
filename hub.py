"""Agent Hub domain foundation. No external provider execution is implied."""
import json
import re
import sqlite3
from typing import Protocol
from contextlib import contextmanager


class AgentAdapter(Protocol):
    def submit(self, task: dict) -> str:
        """Submit an execution brief; return the provider run reference."""
        ...


class Hub:
    def __init__(self, database=":memory:"):
        self.db = sqlite3.connect(database, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS tasks(
          id INTEGER PRIMARY KEY, repository TEXT NOT NULL, request TEXT NOT NULL,
          prompt TEXT NOT NULL, priority INTEGER NOT NULL,
          priority_source TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
          agent TEXT, verification TEXT);
        CREATE TABLE IF NOT EXISTS agents(
          name TEXT PRIMARY KEY, connected INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS questions(
          id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id),
          agent TEXT NOT NULL, question TEXT NOT NULL, options TEXT NOT NULL,
          answer TEXT);
        """)
        # Upgrade existing foundation databases without discarding task history.
        with self.transaction():
            task_columns = {r[1] for r in self.db.execute("PRAGMA table_info(tasks)")}
            if "blocked_reason" not in task_columns:
                self.db.execute("ALTER TABLE tasks ADD COLUMN blocked_reason TEXT")
            if "participants" not in task_columns:
                self.db.execute("ALTER TABLE tasks ADD COLUMN participants TEXT NOT NULL DEFAULT '[]'")
            columns = {r[1] for r in self.db.execute("PRAGMA table_info(questions)")}
            for name, definition in {
                "kind": "TEXT NOT NULL DEFAULT 'question'",
                "scope": "TEXT", "decided_by": "TEXT", "decided_at": "TEXT",
                "resume_status": "TEXT NOT NULL DEFAULT 'working'"
            }.items():
                if name not in columns:
                    self.db.execute(f"ALTER TABLE questions ADD COLUMN {name} {definition}")

    @contextmanager
    def transaction(self):
        if self.db.in_transaction:
            yield
            return
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def close(self):
        self.db.close()

    @staticmethod
    def text(value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("A non-empty string is required")
        return value.strip()

    def create_task(self, repository, request, priority=None):
        repository, request = self.text(repository), self.text(request)
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("Use owner/repository")
        if priority is not None and (type(priority) is not int or not 0 <= priority <= 4):
            raise ValueError("Priority must be 0 (highest) through 4")
        prompt = (f"Repository: {repository}\nUser request:\n{request}\n\n"
                  "Scope: implement the user request in this repository.\n"
                  "Report blockers as task questions with answer options.\n"
                  "Record verification results before requesting completion.")
        cursor = self.db.execute(
            "INSERT INTO tasks(repository,request,prompt,priority,priority_source) VALUES(?,?,?,?,?)",
            (repository, request, prompt, 2 if priority is None else priority,
             "automatic" if priority is None else "user"))
        return self.task(cursor.lastrowid)

    def task(self, task_id):
        row = self.db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise KeyError("Task does not exist")
        task = dict(row)
        task["participants"] = json.loads(task["participants"])
        return task

    def set_participants(self, task_id, names):
        """Operator coordination metadata; never grants claim or context permissions."""
        if not isinstance(names, list) or len(names) > 16 or any(not isinstance(n, str) for n in names):
            raise ValueError("Expected at most 16 registered participant names")
        names = list(dict.fromkeys(names))
        with self.transaction():
            self.task(task_id)
            for name in names:
                if self.db.execute("SELECT 1 FROM agents WHERE name=?", (name,)).fetchone() is None:
                    raise ValueError("Unknown participant")
            self.db.execute("UPDATE tasks SET participants=? WHERE id=?", (json.dumps(names), task_id))
            return self.task(task_id)

    def register_agent(self, name, connected=False):
        name = self.text(name)
        self.db.execute(
            "INSERT INTO agents(name,connected) VALUES(?,?) "
            "ON CONFLICT(name) DO UPDATE SET connected=excluded.connected",
            (name, int(bool(connected))))

    def assign(self, task_id, agent):
        """Operator-only operation: explicitly choose an agent for a queued task."""
        with self.transaction():
            if self.task(task_id)["status"] != "queued":
                raise ValueError("Only queued tasks can be assigned or reassigned")
            if self.db.execute("SELECT 1 FROM agents WHERE name=?", (agent,)).fetchone() is None:
                raise ValueError("Unknown agent")
            self.db.execute("UPDATE tasks SET agent=? WHERE id=?", (agent, task_id))
            return self.task(task_id)

    def claim(self, agent):
        """Reserve only explicitly assigned work; never choose an agent."""
        with self.transaction():
            row = self.db.execute("SELECT connected FROM agents WHERE name=?", (agent,)).fetchone()
            if row is None or not row["connected"]:
                raise ValueError("Agent is not connected")
            busy = self.db.execute(
                "SELECT 1 FROM tasks WHERE agent=? AND status IN "
                "('assigned','working','waiting_for_user','testing','blocked')", (agent,)).fetchone()
            row = None if busy else self.db.execute(
                "SELECT id FROM tasks WHERE status='queued' AND agent=? "
                "ORDER BY priority,id LIMIT 1", (agent,)).fetchone()
            if row:
                self.db.execute("UPDATE tasks SET agent=?,status='assigned' WHERE id=?",
                                (agent, row["id"]))
            return self.task(row["id"]) if row else None

    def transition(self, task_id, agent, status, verification=None):
        with self.transaction():
            return self._transition(task_id, agent, status, verification)

    def _transition(self, task_id, agent, status, verification=None):
        allowed = {"assigned": {"working", "queued"},
                   "working": {"testing", "blocked"},
                   "blocked": {"working", "queued"},
                   "testing": {"completed", "working", "blocked"}}
        task = self.task(task_id)
        if task["agent"] != agent or status not in allowed.get(task["status"], set()):
            raise ValueError("Invalid task transition or agent")
        if self.db.execute("SELECT 1 FROM questions WHERE task_id=? AND kind='approval' "
                           "AND answer='denied'", (task_id,)).fetchone():
            raise ValueError("Denied approval blocks this task; operator must create revised work")
        if status == "completed":
            verification = self.text(verification)
        self.db.execute(
            "UPDATE tasks SET status=?,verification=?,agent=? WHERE id=?",
            (status, verification, agent, task_id))
        return self.task(task_id)

    def complete_and_next(self, task_id, agent, verification):
        with self.transaction():
            completed = self.transition(task_id, agent, "completed", verification)
            return {"completed": completed, "next_task": self.claim(agent)}

    def block(self, task_id, agent, reason):
        reason = self.text(reason)
        with self.transaction():
            self.transition(task_id, agent, "blocked")
            self.db.execute("UPDATE tasks SET blocked_reason=? WHERE id=?", (reason, task_id))
            return self.task(task_id)

    def task_context(self, task_id, agent):
        task = self.task(task_id)
        if task["agent"] != agent:
            raise PermissionError("Task belongs to another agent")
        questions = [dict(r) for r in self.db.execute(
            "SELECT * FROM questions WHERE task_id=? ORDER BY id", (task_id,))]
        for question in questions:
            question["options"] = json.loads(question["options"])
        return {"task": task, "questions": questions}

    def ask(self, task_id, agent, question, options):
        with self.transaction():
            return self._ask(task_id, agent, question, options)

    def _ask(self, task_id, agent, question, options, kind="question", scope=None):
        question = self.text(question)
        if not isinstance(options, list) or any(not isinstance(o, str) or not o.strip() for o in options):
            raise ValueError("Options must be a list of non-empty strings")
        task = self.task(task_id)
        if task["agent"] != agent or task["status"] not in {"working", "testing", "waiting_for_user"}:
            raise ValueError("Only the working agent may ask")
        resume_status = task["status"]
        if resume_status == "waiting_for_user":
            resume_status = self.db.execute(
                "SELECT resume_status FROM questions WHERE task_id=? AND answer IS NULL ORDER BY id LIMIT 1",
                (task_id,)).fetchone()[0]
        cursor = self.db.execute(
            "INSERT INTO questions(task_id,agent,question,options,kind,scope,resume_status) VALUES(?,?,?,?,?,?,?)",
            (task_id, agent, question, json.dumps(options), kind, scope, resume_status))
        self.db.execute("UPDATE tasks SET status='waiting_for_user' WHERE id=?", (task_id,))
        return cursor.lastrowid

    def request_approval(self, task_id, agent, action, scope):
        if scope not in {"application", "provider"}:
            raise ValueError("Scope must be application or provider")
        with self.transaction():
            return self._ask(task_id, agent, action, ["approved", "denied"], "approval", scope)

    def answer(self, question_id, answer, actor="operator"):
        return self._resolve(question_id, answer, actor, "question")

    def decide(self, question_id, decision, actor):
        if decision not in {"approved", "denied"}:
            raise ValueError("Decision must be approved or denied")
        return self._resolve(question_id, decision, actor, "approval")

    def _resolve(self, question_id, answer, actor, kind):
        answer = self.text(answer)
        actor = self.text(actor)
        with self.transaction():
            question = self.db.execute("SELECT * FROM questions WHERE id=?", (question_id,)).fetchone()
            if question is None:
                raise KeyError("Question does not exist")
            if question["answer"] is not None:
                raise ValueError("Question already answered")
            if question["kind"] != kind:
                raise ValueError("Use the matching answer or approval operation")
            self.db.execute("UPDATE questions SET answer=?,decided_by=?,decided_at="
                            "strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                            (answer, actor, question_id))
            denied = self.db.execute(
                "SELECT 1 FROM questions WHERE task_id=? AND kind='approval' AND answer='denied'",
                (question["task_id"],)).fetchone()
            pending = self.db.execute(
                "SELECT 1 FROM questions WHERE task_id=? AND answer IS NULL",
                (question["task_id"],)).fetchone()
            if denied:
                self.db.execute("UPDATE tasks SET status='blocked' WHERE id=?", (question["task_id"],))
            elif not pending:
                self.db.execute("UPDATE tasks SET status=? WHERE id=? AND status='waiting_for_user'",
                                (question["resume_status"], question["task_id"]))

    def status(self):
        tasks = [dict(r) for r in self.db.execute("SELECT * FROM tasks ORDER BY priority,id")]
        for task in tasks:
            task["participants"] = json.loads(task["participants"])
        questions = []
        for row in self.db.execute(
            "SELECT q.*,t.repository,t.request FROM questions q JOIN tasks t ON t.id=q.task_id "
            "ORDER BY t.priority,q.id"):
            item = dict(row)
            item["options"] = json.loads(item["options"])
            questions.append(item)
        result = {"tasks": tasks, "questions": questions,
                  "pending_questions": [q for q in questions if q["answer"] is None]}
        if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='runs'").fetchone():
            result["runs"] = [dict(r) for r in self.db.execute("SELECT * FROM runs ORDER BY task_id,turn")]
        return result
