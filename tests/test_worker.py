from contextlib import closing
import tempfile
from pathlib import Path
import unittest
from hub import Hub
from worker import Worker


class WorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_manual_assignment_launch_wait_answer_continue_and_no_duplicate(self):
        with tempfile.TemporaryDirectory() as directory, closing(Hub(str(Path(directory) / "hub.sqlite3"))) as hub:
            database = str(Path(directory) / "hub.sqlite3")
            hub.register_agent("codex", True)
            task = hub.create_task("owner/repo", "Summarize")
            calls = []

            async def delegate(agent, workspace, context):
                calls.append(context)
                if len(calls) == 1:
                    return {"state": "question", "question": "Which scope?", "options": ["all"]}
                return {"state": "completed", "verification": "Read all source", "summary": "Done"}

            first = Worker(database, {"owner/repo": directory}, delegate)
            second = Worker(database, {"owner/repo": directory}, delegate)
            self.assertIsNone(await first.tick("codex"))
            hub.assign(task["id"], "codex")
            hub.register_agent("codex", False)
            self.assertIsNone(await first.tick("codex"))
            self.assertEqual(calls, [])
            hub.register_agent("codex", True)
            await first.tick("codex")
            self.assertEqual(hub.task(task["id"])["status"], "waiting_for_user")
            self.assertIsNone(await second.tick("codex"))
            question = hub.status()["pending_questions"][0]
            hub.answer(question["id"], "all", "maoz")
            await second.tick("codex")
            self.assertEqual(calls[1]["questions"][0]["answer"], "all")
            self.assertEqual(hub.task(task["id"])["status"], "completed")
            self.assertIsNone(await first.tick("codex"))
            self.assertEqual(len(calls), 2)

    async def test_uncertain_failure_is_not_retried(self):
        with tempfile.TemporaryDirectory() as directory, closing(Hub(str(Path(directory) / "hub.sqlite3"))) as hub:
            database = str(Path(directory) / "hub.sqlite3")
            hub.register_agent("codex", True)
            task = hub.create_task("owner/repo", "Read")
            hub.assign(task["id"], "codex")
            calls = []

            async def delegate(*args):
                calls.append(1)
                raise TimeoutError("Outcome unknown")

            worker = Worker(database, {"owner/repo": directory}, delegate)
            await worker.tick("codex")
            await worker.tick("codex")
            self.assertEqual(len(calls), 1)
            self.assertEqual(hub.task(task["id"])["status"], "blocked")

    async def test_two_workers_cannot_launch_the_same_turn(self):
        import asyncio
        with tempfile.TemporaryDirectory() as directory, closing(Hub(str(Path(directory) / "hub.sqlite3"))) as hub:
            database = str(Path(directory) / "hub.sqlite3")
            hub.register_agent("codex", True)
            task = hub.create_task("owner/repo", "Read")
            hub.assign(task["id"], "codex")
            entered, release = asyncio.Event(), asyncio.Event()
            calls = []

            async def delegate(*args):
                calls.append(1)
                entered.set()
                await release.wait()
                return {"state": "blocked", "summary": "Needs operator"}

            first = Worker(database, {"owner/repo": directory}, delegate)
            second = Worker(database, {"owner/repo": directory}, delegate)
            running = asyncio.create_task(first.tick("codex"))
            await entered.wait()
            self.assertIsNone(await second.tick("codex"))
            release.set()
            await running
            self.assertEqual(len(calls), 1)
