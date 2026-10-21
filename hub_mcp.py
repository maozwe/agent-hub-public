"""Local stdio MCP boundary; identity comes from trusted host configuration."""
import argparse
from contextlib import closing
from mcp.server.fastmcp import FastMCP
from hub import Hub


def build_server(database, identity, role):
    identity = Hub.text(identity)
    if role not in {"operator", "agent"}:
        raise ValueError("Unknown role")
    server = FastMCP("Agent Hub", instructions=(
        "Use only explicitly assigned tasks. Read task_context after user responses. "
        "Route questions and application approval requests here. Provider permissions still "
        "require the provider's native approval. On completion call complete_task, then "
        "inspect next_task. MCP cannot wake an idle agent."))

    def call(method, *args):
        with closing(Hub(database)) as hub:
            return getattr(hub, method)(*args)

    @server.tool()
    def hub_identity() -> dict:
        """Read this connection's bound identity and role; does not claim work."""
        return {"identity": identity, "role": role, "execution_mode": "direct_mcp"}

    if role == "operator":
        @server.tool()
        def register_agent(name: str, connected: bool = False) -> dict:
            """Register an agent; connected is an operator assertion, not a live probe."""
            call("register_agent", name, connected)
            return {"name": name, "connected": connected}

        @server.tool()
        def create_task(repository: str, request: str, priority: int | None = None) -> dict:
            """Create user-requested work; remains unassigned until assign_task."""
            return call("create_task", repository, request, priority)

        @server.tool()
        def assign_task(task_id: int, agent: str) -> dict:
            """Explicitly assign queued work to one registered agent."""
            return call("assign", task_id, agent)

        @server.tool()
        def hub_status() -> dict:
            """Read all tasks and pending user questions/approvals."""
            return call("status")

        @server.tool()
        def answer_question(question_id: int, answer: str) -> dict:
            """Record the user's answer. Unsafe to retry without checking context."""
            call("answer", question_id, answer, identity)
            return {"recorded": True}

        @server.tool()
        def decide_approval(question_id: int, decision: str) -> dict:
            """Record approved/denied; never grants native provider permissions."""
            call("decide", question_id, decision, identity)
            return {"recorded": True}
    else:
        @server.tool()
        def assigned_tasks() -> dict:
            """Read only tasks explicitly assigned to this connection, without claiming."""
            return {"tasks": [task for task in call("status")["tasks"] if task["agent"] == identity]}

        @server.tool()
        def next_task() -> dict:
            """Reserve the next task already assigned to this identity, if free."""
            return {"task": call("claim", identity)}

        @server.tool()
        def task_context(task_id: int) -> dict:
            """Read owned task, questions, answers and approval audit history."""
            return call("task_context", task_id, identity)

        @server.tool()
        def set_status(task_id: int, status: str, reason: str | None = None) -> dict:
            """Report working/testing/blocked/queued; use complete_task to finish."""
            if status == "completed":
                raise ValueError("Use complete_task with verification")
            if status == "blocked":
                return call("block", task_id, identity, reason)
            return call("transition", task_id, identity, status)

        @server.tool()
        def ask_question(task_id: int, question: str, options: list[str]) -> dict:
            """Pause owned task and ask the user with optional answer choices."""
            return {"question_id": call("ask", task_id, identity, question, options)}

        @server.tool()
        def request_approval(task_id: int, action: str, scope: str) -> dict:
            """Pause for an exact action; scope is application or provider."""
            return {"question_id": call("request_approval", task_id, identity, action, scope)}

        @server.tool()
        def complete_task(task_id: int, verification: str) -> dict:
            """Record verification and reserve next assigned work atomically; read next_task."""
            return call("complete_and_next", task_id, identity, verification)
    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--identity", required=True)
    parser.add_argument("--role", choices=["operator", "agent"], required=True)
    args = parser.parse_args()
    build_server(args.database, args.identity, args.role).run(transport="stdio")
