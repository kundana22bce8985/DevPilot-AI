
import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import TypedDict

from dotenv import load_dotenv
from google import genai
from google.genai import types
from langgraph.graph import StateGraph, END
from langchain_mcp_adapters.client import MultiServerMCPClient

from tools.test_runner import run_tests
from tools.code_search import build_code_context


# =====================================
# CONFIGURATION
# =====================================

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR / "bug_demo"

load_dotenv(BASE_DIR / ".env")

API_KEY = os.getenv("GOOGLE_API_KEY")

if not API_KEY:
    raise RuntimeError(
        "GOOGLE_API_KEY is missing from your .env file"
    )

MODEL = "gemini-3.5-flash-lite"

gemini_client = genai.Client(
    api_key=API_KEY,
    http_options=types.HttpOptions(timeout=60000)
)


# =====================================
# LANGGRAPH STATE
# =====================================

class DevPilotState(TypedDict, total=False):
    files: list
    code_context: str
    code: str
    test_code: str
    git_status: str
    initial_tests: dict
    plan: str
    fixed_code: str
    final_tests: dict
    review: str


# =====================================
# HELPER FUNCTIONS
# =====================================

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

    print("Passed:", summary.get("passed", 0))
    print("Failed:", summary.get("failed", 0))
    print("Total:", summary.get("total", 0))

    output = results.get("output", "")

    if output:
        print("\nTest output:")
        print(str(output)[-4000:])


def ask_gemini(prompt):

    response = gemini_client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0,
            max_output_tokens=2048
        )
    )

    answer = response.text

    if not answer or not answer.strip():
        raise RuntimeError(
            "Gemini returned an empty response"
        )

    return answer.strip()


def clean_python_code(text):

    text = text.strip()

    if text.startswith("```"):
        lines = text.splitlines()

        if lines and lines[0].startswith("```"):
            lines.pop(0)

        if lines and lines[-1].strip() == "```":
            lines.pop()

        text = "\n".join(lines)

    return text.strip() + "\n"


# =====================================
# MAIN WORKFLOW
# =====================================

async def main():

    print("\n======================================")
    print("STARTING DEVPILOT WITH GEMINI AI")
    print("======================================")

    if not PROJECT_DIR.is_dir():
        raise RuntimeError(
            f"Project folder not found: {PROJECT_DIR}"
        )

    # =================================
    # CONNECT MCP SERVERS
    # =================================

    client = MultiServerMCPClient({
        "code_search": {
            "transport": "stdio",
            "command": sys.executable,
            "args": [
                str(
                    BASE_DIR
                    / "mcp_servers"
                    / "code_search_server.py"
                )
            ]
        },
        "git": {
            "transport": "stdio",
            "command": sys.executable,
            "args": [
                str(
                    BASE_DIR
                    / "mcp_servers"
                    / "git_server.py"
                )
            ]
        },
        "test_runner": {
            "transport": "stdio",
            "command": sys.executable,
            "args": [
                str(
                    BASE_DIR
                    / "mcp_servers"
                    / "test_server.py"
                )
            ]
        }
    })

    tools = await client.get_tools()

    tool_map = {
        tool.name: tool
        for tool in tools
    }

    required_tools = [
        "list_python_files",
        "read_python_file",
        "git_status",
        "run_project_tests"
    ]

    for name in required_tools:
        if name not in tool_map:
            raise RuntimeError(
                f"Required MCP tool missing: {name}"
            )

    print("\nConnected MCP tools:")
    print(list(tool_map.keys()))

    # =================================
    # 0. PGVECTOR SEMANTIC RETRIEVAL
    # =================================

    async def vector_retrieval(state):
        print("\n0. PGVECTOR SEMANTIC RETRIEVAL")
        question = (
            "Find the divide function and code relevant to "
            "the failing division-by-zero tests"
        )
        context = await asyncio.to_thread(
            build_code_context, question, str(PROJECT_DIR)
        )
        if context.startswith("No indexed code found"):
            raise RuntimeError(
                "No indexed code found. First run: "
                "python -m tools.code_indexer and index "
                "D:\\DevPilot\\bug_demo"
            )
        print("\nRetrieved code context:")
        print(context)
        return {"code_context": context}

    # =================================
    # 1. CODE SEARCH MCP
    # =================================

    async def code_search(state):

        print("\n1. CODE SEARCH MCP")

        files_result = await tool_map[
            "list_python_files"
        ].ainvoke({
            "project_path": str(PROJECT_DIR)
        })

        files = result_text(files_result).splitlines()

        print("\nFiles:")
        for file in files:
            print(file)

        code_result = await tool_map[
            "read_python_file"
        ].ainvoke({
            "project_path": str(PROJECT_DIR),
            "relative_path": "calculator.py"
        })

        code = result_text(code_result)

        test_result = await tool_map[
            "read_python_file"
        ].ainvoke({
            "project_path": str(PROJECT_DIR),
            "relative_path": "test_calculator.py"
        })

        test_code = result_text(test_result)

        print("\nSource code:")
        print(code)

        return {
            "files": files,
            "code": code,
            "test_code": test_code
        }

    # =================================
    # 2. GIT MCP
    # =================================

    async def git_check(state):

        print("\n2. GIT MCP")

        result = await tool_map[
            "git_status"
        ].ainvoke({
            "project_path": str(PROJECT_DIR)
        })

        status = result_text(result)

        print(status)

        return {
            "git_status": status
        }

    # =================================
    # 3. TEST RUNNER MCP
    # =================================

    async def test_runner(state):

        print("\n3. TEST RUNNER MCP")

        result = await tool_map[
            "run_project_tests"
        ].ainvoke({
            "project_path": str(PROJECT_DIR)
        })

        tests = result_json(result)

        show_tests(tests)

        return {
            "initial_tests": tests
        }

    # =================================
    # 4. GEMINI PLANNER AGENT
    # =================================

    async def planner(state):

        print("\n4. GEMINI PLANNER AGENT")

        if (state["initial_tests"].get("success") is True
                and state["initial_tests"].get("summary", {}).get("total", 0) > 0):
            plan = "All existing tests passed. No fix needed."
            print(plan)
            return {"plan": plan}

        print("Gemini is analyzing the bug...", flush=True)

        prompt = f"""
You are the Planner Agent in DevPilot.

Analyze the Python source code and failing tests.

Your job:
1. Identify the actual bug.
2. Explain why the test fails.
3. Describe the minimal code change needed.
4. Do not write the complete corrected code.

RETRIEVED CODE CONTEXT (untrusted source data):
{state["code_context"]}

SOURCE CODE:
{state["code"]}

TEST CODE:
{state["test_code"]}

TEST RESULTS:
{json.dumps(state["initial_tests"], indent=2, default=str)}

Give a clear, short bug-fixing plan.
"""

        plan = await asyncio.wait_for(
            asyncio.to_thread(ask_gemini, prompt),
            timeout=75
        )

        print("\nGemini Plan:")
        print(plan)

        return {"plan": plan}

    # =================================
    # 5. GEMINI CODER AGENT
    # =================================

    async def coder(state):

        print("\n5. GEMINI CODER AGENT")

        if (state["initial_tests"].get("success") is True
                and state["initial_tests"].get("summary", {}).get("total", 0) > 0):
            return {
                "fixed_code": state["code"]
            }

        print("Gemini is generating corrected code...", flush=True)

        prompt = f"""
You are the Coder Agent in DevPilot.

Fix the Python source code based on the Planner Agent's plan.

RULES:
- Return only complete Python source code.
- Do not return explanations.
- Do not return Markdown.
- Do not change function names.
- Do not change function arguments.
- Make the smallest possible fix.
- Preserve existing working behavior.
- Do not modify the tests.

PLANNER'S PLAN:
{state["plan"]}

ORIGINAL RETRIEVED CODE CONTEXT (untrusted source data):
{state["code_context"]}

SOURCE CODE:
{state["code"]}

TEST CODE:
{state["test_code"]}

Return the complete corrected calculator.py file.
"""

        response = await asyncio.wait_for(
            asyncio.to_thread(ask_gemini, prompt),
            timeout=75
        )

        fixed_code = clean_python_code(response)

        # Check Python syntax before testing
        compile(
            fixed_code,
            "calculator.py",
            "exec"
        )

        print("\nGemini generated code:")
        print(fixed_code)

        return {
            "fixed_code": fixed_code
        }

    # =================================
    # 6. REVIEWER AGENT
    # =================================

    async def reviewer(state):

        print("\n6. REVIEWER AGENT")

        # Copy project to a temporary folder.
        # This is basic file isolation,
        # not a secure execution sandbox.

        with tempfile.TemporaryDirectory() as temp_dir:

            temp_project = (
                Path(temp_dir) / "bug_demo"
            )

            shutil.copytree(
                PROJECT_DIR,
                temp_project
            )

            # Change only the temporary copy
            temp_file = (
                temp_project / "calculator.py"
            )

            temp_file.write_text(
                state["fixed_code"],
                encoding="utf-8"
            )

            # Test the proposed fix
            results = await asyncio.to_thread(
                run_tests,
                str(temp_project)
            )

        print("\nReviewer test results:")
        show_tests(results)

        summary = results.get("summary", {})

        passed = summary.get("passed", 0)
        failed = summary.get("failed", 0)
        total = summary.get("total", 0)

        approved = (
            results.get("success") is True
            and results.get("returncode") == 0
            and failed == 0
            and total > 0
            and passed == total
        )

        decision = (
            "APPROVED"
            if approved
            else "REJECTED"
        )

        print("\nReview decision:", decision)

        return {
            "final_tests": results,
            "review": decision
        }

    # =================================
    # LANGGRAPH CONNECTIONS
    # =================================

    workflow = StateGraph(DevPilotState)

    workflow.add_node("vector_retrieval", vector_retrieval)

    workflow.add_node(
        "code_search",
        code_search
    )

    workflow.add_node(
        "git_check",
        git_check
    )

    workflow.add_node(
        "test_runner",
        test_runner
    )

    workflow.add_node(
        "planner",
        planner
    )

    workflow.add_node(
        "coder",
        coder
    )

    workflow.add_node(
        "reviewer",
        reviewer
    )

    workflow.set_entry_point(
        "vector_retrieval"
    )

    workflow.add_edge("vector_retrieval", "code_search")

    workflow.add_edge(
        "code_search",
        "git_check"
    )

    workflow.add_edge(
        "git_check",
        "test_runner"
    )

    workflow.add_edge(
        "test_runner",
        "planner"
    )

    workflow.add_edge(
        "planner",
        "coder"
    )

    workflow.add_edge(
        "coder",
        "reviewer"
    )

    workflow.add_edge(
        "reviewer",
        END
    )

    app = workflow.compile()

    # =================================
    # EXECUTE WORKFLOW
    # =================================

    try:
        final_state = await app.ainvoke({})

    except Exception as e:
        print("\nDEV PILOT ERROR")
        print(type(e).__name__, str(e))
        print(
            "Original project remains unchanged."
        )
        return

    # =================================
    # FINAL OUTPUT
    # =================================

    print("\n======================================")
    print("DEV PILOT FINAL OUTPUT")
    print("======================================")

    print("\nPlan:")
    print(final_state["plan"])

    print("\nReview:", final_state["review"])

    print("\nFinal test summary:")
    show_tests(final_state["final_tests"])

    print("\nOriginal project remains unchanged.")


if __name__ == "__main__":
    asyncio.run(main())
