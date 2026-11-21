
import asyncio
import sys
from pathlib import Path

from langgraph.graph import StateGraph, END
from typing_extensions import TypedDict
from langchain_mcp_adapters.client import MultiServerMCPClient


BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR / "bug_demo"


class DevPilotState(TypedDict, total=False):
    files: list
    code: str
    git_status: str
    initial_tests: str
    plan: str
    fixed_code: str
    review: str


def result_text(result):
    """Convert an MCP tool response into readable text."""
    if isinstance(result, str):
        return result
    return str(result)


async def main():

    print("\nStarting DevPilot Integrated Workflow...\n")

    # Connect to all three MCP servers
    client = MultiServerMCPClient({
        "code_search": {
            "transport": "stdio",
            "command": sys.executable,
            "args": [
                str(BASE_DIR / "mcp_servers" / "code_search_server.py")
            ],
        },
        "git": {
            "transport": "stdio",
            "command": sys.executable,
            "args": [
                str(BASE_DIR / "mcp_servers" / "git_server.py")
            ],
        },
        "test_runner": {
            "transport": "stdio",
            "command": sys.executable,
            "args": [
                str(BASE_DIR / "mcp_servers" / "test_server.py")
            ],
        },
    })

    tools = await client.get_tools()
    tool_map = {tool.name: tool for tool in tools}

    print("Connected MCP tools:", list(tool_map.keys()))

    async def code_search(state):
        print("\n1. CODE SEARCH MCP")

        result = await tool_map["list_python_files"].ainvoke({
            "project_path": str(PROJECT_DIR)
        })

        print("Python files:", result_text(result))

        code = await tool_map["read_python_file"].ainvoke({
            "project_path": str(PROJECT_DIR),
            "relative_path": "calculator.py"
        })

        print("Source code:", result_text(code))

        return {
            "files": [result_text(result)],
            "code": result_text(code)
        }

    async def git_check(state):
        print("\n2. GIT MCP")

        result = await tool_map["git_status"].ainvoke({
            "project_path": str(PROJECT_DIR)
        })

        print("Git status:", result_text(result))

        return {"git_status": result_text(result)}

    async def test_runner(state):
        print("\n3. TEST RUNNER MCP")

        result = await tool_map["run_project_tests"].ainvoke({
            "project_path": str(PROJECT_DIR)
        })

        print("Test results:", result_text(result))

        return {"initial_tests": result_text(result)}

    def planner(state):
        print("\n4. PLANNER AGENT")

        plan = (
            "The division-by-zero test fails because divide(10, 0) "
            "raises ZeroDivisionError instead of ValueError. "
            "Add a check for b == 0 and raise ValueError."
        )

        print("Plan:", plan)
        return {"plan": plan}

    def coder(state):
        print("\n5. CODER AGENT")

        fixed_code = '''def divide(a, b):
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b
'''

        print("Proposed fix:\n", fixed_code)

        return {"fixed_code": fixed_code}

    async def reviewer(state):
        print("\n6. REVIEWER AGENT")

        # Reuse the existing local test runner for reviewing a
        # temporary project copy, without editing the original.
        import tempfile
        import shutil
        from tools.test_runner import run_tests

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_project = Path(temp_dir) / "bug_demo"
            shutil.copytree(PROJECT_DIR, temp_project)

            (temp_project / "calculator.py").write_text(
                state["fixed_code"],
                encoding="utf-8"
            )

            results = await asyncio.to_thread(
                run_tests, str(temp_project)
            )

        print("Review test results:", results)

        summary = results.get("summary", {})
        approved = (
            results.get("success") is True
            and summary.get("failed", 0) == 0
            and summary.get("total", 0) > 0
        )

        decision = "APPROVED" if approved else "REJECTED"

        print("Review decision:", decision)
        return {"review": decision}

    # Build the LangGraph workflow
    workflow = StateGraph(DevPilotState)

    workflow.add_node("code_search", code_search)
    workflow.add_node("git_check", git_check)
    workflow.add_node("test_runner", test_runner)
    workflow.add_node("planner", planner)
    workflow.add_node("coder", coder)
    workflow.add_node("reviewer", reviewer)

    workflow.set_entry_point("code_search")

    workflow.add_edge("code_search", "git_check")
    workflow.add_edge("git_check", "test_runner")
    workflow.add_edge("test_runner", "planner")
    workflow.add_edge("planner", "coder")
    workflow.add_edge("coder", "reviewer")
    workflow.add_edge("reviewer", END)

    app = workflow.compile()

    final_state = await app.ainvoke({})

    print("\n======================================")
    print("DEV PILOT FINAL OUTPUT")
    print("======================================")
    print("Plan:", final_state["plan"])
    print("Review:", final_state["review"])
    print("Original project remains unchanged.")


if __name__ == "__main__":
    asyncio.run(main())

