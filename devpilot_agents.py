
import os
import json
import shutil
import tempfile
import difflib
import ast
from pathlib import Path
from typing import TypedDict

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, START, END

from tools.test_runner import run_tests


# ==========================================
# 1. CONFIGURATION
# ==========================================

BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")

PROJECT = BASE_DIR / "bug_demo"

SOURCE_FILE = "calculator.py"
TEST_FILE = "test_calculator.py"

if not os.getenv("GOOGLE_API_KEY"):
    raise RuntimeError(
        "GOOGLE_API_KEY not found. "
        "Add it to your .env file."
    )


# Gemini model
llm = ChatGoogleGenerativeAI(
    model="gemini-3.8-flash",
    temperature=0,
    max_retries=2,
)


# ==========================================
# 2. LANGGRAPH STATE
# ==========================================

class AgentState(TypedDict):
    project_path: str
    original_tests: dict
    plan: str
    proposed_code: str
    review_results: dict
    approved: bool


# ==========================================
# 3. HELPER FUNCTIONS
# ==========================================

def get_response_text(response):
    content = response.content

    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        parts = []

        for item in content:
            if isinstance(item, str):
                parts.append(item)

            elif isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(item.get("text", ""))

        return "\n".join(parts).strip()

    return str(content).strip()


def clean_python_code(code):

    code = code.strip()

    if code.startswith("```"):
        lines = code.splitlines()

        lines = lines[1:]

        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]

        code = "\n".join(lines)

    code = code.strip() + "\n"

    # Check Python syntax
    ast.parse(code)

    return code


def read_project_file(project, filename):

    file_path = project / filename

    if not file_path.is_file():
        raise FileNotFoundError(
            f"File not found: {file_path}"
        )

    return file_path.read_text(
        encoding="utf-8"
    )


# ==========================================
# 4. AI PLANNER AGENT
# ==========================================

def planner_agent(state: AgentState):

    print("\n" + "=" * 50)
    print("AI PLANNER AGENT")
    print("=" * 50)

    project = Path(state["project_path"])

    source_code = read_project_file(
        project,
        SOURCE_FILE
    )

    test_code = read_project_file(
        project,
        TEST_FILE
    )

    # Run original tests
    results = run_tests(str(project))

    print("\nOriginal test summary:")
    print(
        json.dumps(
            results["summary"],
            indent=2
        )
    )

    if not results["tests"]:
        raise RuntimeError(
            "Test runner did not return test results:\n"
            + results["output"]
        )

    prompt = f"""
You are the Planner Agent in DevPilot,
an AI-powered codebase debugging assistant.

Your responsibility is to analyze Python
source code and identify bugs.

SOURCE CODE:
{source_code}

TEST CODE:
{test_code}

PYTEST RESULTS:
{results["output"]}

TASK:

1. Identify the exact bug.
2. Explain why the test failed.
3. Explain what should be changed.
4. Suggest the smallest possible correction.

IMPORTANT RULES:
- Do not generate full Python code.
- Do not modify files.
- Do not invent unrelated problems.
- Focus only on the failing tests.

Return a clear debugging plan.
"""

    print("\nGemini is analyzing the bug...\n")

    response = llm.invoke(prompt)

    plan = get_response_text(response)

    if not plan:
        raise RuntimeError(
            "Gemini returned an empty debugging plan."
        )

    print("DEBUGGING PLAN:\n")
    print(plan)

    return {
        "original_tests": results,
        "plan": plan
    }


# ==========================================
# 5. AI CODER AGENT
# ==========================================

def coder_agent(state: AgentState):

    print("\n" + "=" * 50)
    print("AI CODER AGENT")
    print("=" * 50)

    project = Path(state["project_path"])

    original_code = read_project_file(
        project,
        SOURCE_FILE
    )

    test_code = read_project_file(
        project,
        TEST_FILE
    )

    prompt = f"""
You are the Coder Agent in DevPilot.

You are an expert Python software engineer.

Your task is to fix bugs identified by
the Planner Agent.

ORIGINAL SOURCE CODE:
{original_code}

TEST CODE:
{test_code}

DEBUGGING PLAN:
{state["plan"]}

TASK:

Generate the complete corrected
{SOURCE_FILE} source code.

RULES:

1. Return only valid Python code.
2. Do not include explanations.
3. Do not include Markdown formatting.
4. Do not include ```python.
5. Preserve existing functions.
6. Make the smallest possible correction.
7. Do not modify test files.
8. Ensure the correction satisfies the tests.
"""

    print("\nGemini is generating corrected code...\n")

    response = llm.invoke(prompt)

    proposed_code = clean_python_code(
        get_response_text(response)
    )

    print("PROPOSED CORRECTED CODE:\n")
    print(proposed_code)

    return {
        "proposed_code": proposed_code
    }


# ==========================================
# 6. REVIEWER AGENT
# ==========================================

def reviewer_agent(state: AgentState):

    print("\n" + "=" * 50)
    print("REVIEWER AGENT")
    print("=" * 50)

    project = Path(state["project_path"])

    # Create a temporary copy of the project.
    # The original project will not be modified.

    with tempfile.TemporaryDirectory() as temp_dir:

        review_project = (
            Path(temp_dir) / "review_project"
        )

        shutil.copytree(
            project,
            review_project,
            ignore=shutil.ignore_patterns(
                ".git",
                ".venv",
                "venv",
                "__pycache__",
                ".pytest_cache",
                "node_modules"
            )
        )

        target_file = (
            review_project / SOURCE_FILE
        )

        target_file.write_text(
            state["proposed_code"],
            encoding="utf-8"
        )

        print("\nRunning tests on proposed correction...\n")

        results = run_tests(
            str(review_project)
        )

    summary = results.get("summary", {})

    approved = (
        results.get("success", False)
        and summary.get("total", 0) > 0
        and summary.get("failed", 0) == 0
    )

    print("TEST SUMMARY:\n")
    print(
        json.dumps(
            summary,
            indent=2
        )
    )

    if approved:
        print("\nREVIEW DECISION: APPROVED")
    else:
        print("\nREVIEW DECISION: REJECTED")
        print("\nTEST OUTPUT:\n")
        print(results.get("output", ""))

    return {
        "review_results": results,
        "approved": approved
    }


# ==========================================
# 7. CREATE LANGGRAPH WORKFLOW
# ==========================================

def build_workflow():

    workflow = StateGraph(AgentState)

    workflow.add_node(
        "planner",
        planner_agent
    )

    workflow.add_node(
        "coder",
        coder_agent
    )

    workflow.add_node(
        "reviewer",
        reviewer_agent
    )

    workflow.add_edge(
        START,
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

    return workflow.compile()


# ==========================================
# 8. MAIN FUNCTION
# ==========================================

def main():

    print("\n" + "=" * 55)
    print("DEVPILOT - AI CODEBASE ASSISTANT")
    print("=" * 55)

    if not PROJECT.is_dir():
        raise FileNotFoundError(
            f"Project not found: {PROJECT}"
        )

    app = build_workflow()

    initial_state = {
        "project_path": str(PROJECT),
        "original_tests": {},
        "plan": "",
        "proposed_code": "",
        "review_results": {},
        "approved": False
    }

    result = app.invoke(
        initial_state
    )

    print("\n" + "=" * 55)
    print("FINAL RESULT")
    print("=" * 55)

    print(
        "\nPatch approved:",
        result["approved"]
    )

    original_code = read_project_file(
        PROJECT,
        SOURCE_FILE
    )

    proposed_code = result["proposed_code"]

    # Display the proposed changes
    diff = difflib.unified_diff(
        original_code.splitlines(
            keepends=True
        ),
        proposed_code.splitlines(
            keepends=True
        ),
        fromfile=f"{SOURCE_FILE} (original)",
        tofile=f"{SOURCE_FILE} (proposed)"
    )

    print("\n===== PROPOSED PATCH =====\n")

    patch = "".join(diff)

    if patch:
        print(patch)
    else:
        print("No changes proposed.")

    print("\n===== FINAL TEST RESULTS =====\n")

    print(
        json.dumps(
            result["review_results"]["summary"],
            indent=2
        )
    )

    if result["approved"]:

        print(
            "\nSUCCESS: All review tests passed!"
        )

        print(
            "\nThe original calculator.py "
            "has NOT been modified."
        )

    else:

        print(
            "\nFAILED: The proposed correction "
            "did not pass all tests."
        )

        print(
            "\nThe original calculator.py "
            "has NOT been modified."
        )


if __name__ == "__main__":
    main()
