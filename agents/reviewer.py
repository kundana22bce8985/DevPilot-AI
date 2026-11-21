
import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import TypedDict

from langgraph.graph import StateGraph, END
from langchain_mcp_adapters.client import MultiServerMCPClient

from tools.test_runner import run_tests


BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR / "bug_demo"


class DevPilotState(TypedDict, total=False):
    files: list
    code: str
    git_status: str
    initial_tests: dict
    plan: str
    fixed_code: str
    final_tests: dict
    review: str


# Convert MCP response into readable text
def result_text(result):

    if isinstance(result, str):
        return result

    if isinstance(result, list):
        parts = []

        for item in result:
            if isinstance(item, dict):
                parts.append(item.get("text", str(item)))
            elif hasattr(item, "text"):
                parts.append(item.text)
            else:
                parts.append(str(item))

        return "\n".join(parts)

    return str(result)


# Convert MCP test response into Python dictionary
def result_json(result):

    content = result_text(result)

    try:
        data = json.loads(content)

        if isinstance(data, dict):
            return data

    except (json.JSONDecodeError, TypeError):
        pass

    return {
        "success": False,
        "output": content,
        "summary": {}
    }


def show_tests(results):

    summary = results.get("summary", {})

    passed = summary.get("passed", 0)
    failed = summary.get("failed", 0)
    total = summary.get("total", 0)

    print("Passed:", passed)
    print("Failed:", failed)
    print("Total:", total)

    for test in results.get("tests", []):
        print(
            test.get("name", "Unknown"),
            "-",
            test.get("status", "Unknown")
        )


async def main():

    print("\n====================================")
    print("STARTING DEVPILOT")
    print("====================================")

    if not PROJECT_DIR.is_dir():
        print("Project folder not found:", PROJECT_DIR)
        return

    # CONNECT MCP SERVERS

    client = MultiServerMCPClient({
        "code_search": {
            "transport": "stdio",
            "command": sys.executable,
            "args": [
                str(BASE_DIR / "mcp_servers" /
                    "code_search_server.py")
            ]
        },
        "git": {
            "transport": "stdio",
            "command": sys.executable,
            "args": [
                str(BASE_DIR / "mcp_servers" /
                    "git_server.py")
            ]
        },
        "test_runner": {
            "transport": "stdio",
            "command": sys.executable,
            "args": [
                str(BASE_DIR / "mcp_servers" /
                    "test_server.py")
            ]
        }
    })

    tools = await client.get_tools()

    tool_map = {
        tool.name: tool for tool in tools
    }

    required = [
        "list_python_files",
        "read_python_file",
        "git_status",
        "run_project_tests"
    ]

    for name in required:
        if name not in tool_map:
            raise RuntimeError(
                f"MCP tool missing: {name}"
            )

    print("\nMCP servers connected successfully!")

    # 1. CODE SEARCH MCP

    async def code_search(state):

        print("\n1. CODE SEARCH MCP")

        files_result = await tool_map[
            "list_python_files"
        ].ainvoke({
            "project_path": str(PROJECT_DIR)
        })

        files = result_text(files_result).splitlines()

        print("Python files:")
        for file in files:
            print("-", file)

        code_result = await tool_map[
            "read_python_file"
        ].ainvoke({
            "project_path": str(PROJECT_DIR),
            "relative_path": "calculator.py"
        })

        code = result_text(code_result)

        print("\nOriginal code:")
        print(code)

        return {
            "files": files,
            "code": code
        }

    # 2. GIT MCP

    async def git_check(state):

        print("\n2. GIT MCP")

        result = await tool_map[
            "git_status"
        ].ainvoke({
            "project_path": str(PROJECT_DIR)
        })

        status = result_text(result)

        print("Git status:", status)

        return {
            "git_status": status
        }

    # 3. TEST RUNNER MCP

    async def test_runner(state):

        print("\n3. TEST RUNNER MCP")

        result = await tool_map[
            "run_project_tests"
        ].ainvoke({
            "project_path": str(PROJECT_DIR)
        })

        tests = result_json(result)

        print("\nOriginal test results:")
        show_tests(tests)

        return {
            "initial_tests": tests
        }

    # 4. PLANNER AGENT

    def planner(state):

        print("\n4. PLANNER AGENT")

        tests = state["initial_tests"]
        summary = tests.get("summary", {})

        if tests.get("success") is True:
            plan = "All tests passed. No fix needed."

        elif summary.get("failed", 0) > 0:
            plan = (
                "Division by zero raises ZeroDivisionError, "
                "but the test expects ValueError. "
                "Add a check for b == 0."
            )

        else:
            raise RuntimeError(
                "Test execution failed without a "
                "recognized failing test."
            )

        print("Plan:", plan)

        return {"plan": plan}

    # 5. CODER AGENT

    def coder(state):

        print("\n5. CODER AGENT")

        if state["initial_tests"].get("success") is True:
            fixed_code = state["code"]

        else:
            fixed_code = '''def divide(a, b):
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b
'''

        print("\nProposed fix:")
        print(fixed_code)

        return {"fixed_code": fixed_code}

    # 6. REVIEWER AGENT

    async def reviewer(state):

        print("\n6. REVIEWER AGENT")

        # Create temporary copy of project
        with tempfile.TemporaryDirectory() as temp_dir:

            temp_project = Path(temp_dir) / "bug_demo"

            shutil.copytree(
                PROJECT_DIR,
                temp_project
            )

            # Modify only the temporary copy
            temp_file = temp_project / "calculator.py"

            temp_file.write_text(
                state["fixed_code"],
                encoding="utf-8"
            )

            # Run tests on temporary project
            results = await asyncio.to_thread(
                run_tests,
                str(temp_project)
            )

        print("\nFinal test results:")
        show_tests(results)

        summary = results.get("summary", {})

        passed = summary.get("passed", 0)
        failed = summary.get("failed", 0)
        total = summary.get("total", 0)

        # CORRECTED APPROVAL CONDITION
        approved = (
            results.get("success") is True
            and results.get("returncode") == 0
            and failed == 0
            and total > 0
            and passed == total
        )

        decision = (
            "APPROVED" if approved else "REJECTED"
        )

        print("\nReview decision:", decision)

        return {
            "final_tests": results,
            "review": decision
        }

    # LANGGRAPH WORKFLOW

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

    # FINAL OUTPUT

    print("\n====================================")
    print("DEVPILOT FINAL OUTPUT")
    print("====================================")

    print("\nPlanner:", final_state["plan"])
    print("Review:", final_state["review"])

    print("\nFinal test summary:")
    show_tests(final_state["final_tests"])

    print("\nOriginal project remains unchanged.")
    print("Workflow completed!")


if __name__ == "__main__":
    asyncio.run(main())
