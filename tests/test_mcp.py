import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class MCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_identity_questions_approvals_and_next_task(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "hub.sqlite3")

            async def connect(role, identity, scenario):
                params = StdioServerParameters(command=sys.executable, args=[
                    str(Path(__file__).resolve().parents[1] / "hub_mcp.py"),
                    "--database", database, "--role", role, "--identity", identity])
                async with stdio_client(params) as streams:
                    async with ClientSession(*streams) as session:
                        await session.initialize()
                        await scenario(session)

            async def call(session, tool_name, **args):
                result = await session.call_tool(tool_name, args)
                self.assertFalse(result.isError, result)
                return json.loads(result.content[0].text)

            async def operator(session):
                tools = {t.name for t in (await session.list_tools()).tools}
                self.assertNotIn("complete_task", tools)
                await call(session, "register_agent", name="codex", connected=True)
                for name in ["First", "Second"]:
                    task = await call(session, "create_task", repository="owner/repo", request=name)
                    await call(session, "assign_task", task_id=task["id"], agent="codex")

            async def agent(session):
                identity = await call(session, "hub_identity")
                self.assertEqual(identity["identity"], "codex")
                self.assertEqual(identity["execution_mode"], "direct_mcp")
                assigned = await call(session, "assigned_tasks")
                self.assertEqual(len(assigned["tasks"]), 2)
                tools = {t.name for t in (await session.list_tools()).tools}
                self.assertNotIn("decide_approval", tools)
                self.assertNotIn("assign_task", tools)
                task = (await call(session, "next_task"))["task"]
                await call(session, "set_status", task_id=task["id"], status="working")
                question = await call(session, "ask_question", task_id=task["id"],
                                      question="Which target?", options=["staging"])
                approval = await call(session, "request_approval", task_id=task["id"],
                                      action="Publish exact build abc to staging", scope="application")

                async def answer(operator_session):
                    await call(operator_session, "answer_question", question_id=question["question_id"], answer="staging")
                    await call(operator_session, "decide_approval", question_id=approval["question_id"], decision="approved")

                await connect("operator", "maoz", answer)
                context = await call(session, "task_context", task_id=task["id"])
                self.assertEqual(context["task"]["status"], "working")
                self.assertEqual(context["questions"][1]["decided_by"], "maoz")
                await call(session, "set_status", task_id=task["id"], status="testing")
                result = await call(session, "complete_task", task_id=task["id"], verification="integration test")
                self.assertEqual(result["next_task"]["request"], "Second")

            await connect("operator", "maoz", operator)
            await connect("agent", "codex", agent)

            async def other_agent(session):
                assigned = await call(session, "assigned_tasks")
                self.assertEqual(assigned["tasks"], [])
                result = await session.call_tool("task_context", {"task_id": 1})
                self.assertTrue(result.isError)

            await connect("agent", "cursor", other_agent)
