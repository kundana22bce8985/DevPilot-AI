
import json
import re
from pathlib import Path

from main import app
from tools.test_runner import run_tests


def read_project_files(project_path, max_files=20, max_chars=30000):
    """
    Read Python source files for bug analysis.
    Skip virtual environments, caches and tests.
    """
    root = Path(project_path).resolve()

    if not root.is_dir():
        raise ValueError("Project folder does not exist.")

    excluded = {
        ".venv", "venv", "__pycache__", ".git",
        "node_modules", ".pytest_cache"
    }

    source_parts = []
    total_chars = 0
    file_count = 0

    for file_path in sorted(root.rglob("*.py")):
        relative_path = file_path.relative_to(root)

        if any(part in excluded for part in relative_path.parts):
            continue

        if file_path.is_symlink():
            continue

        if file_path.name.startswith("test_"):
            continue

        if file_path.name.endswith("_test.py"):
            continue

        try:
            code = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue

        remaining = max_chars - total_chars

        if remaining <= 0 or file_count >= max_files:
            break

        code = code[:remaining]

        source_parts.append(
            f"\nFILE: {relative_path}\n"
            f"```python\n{code}\n```\n"
        )

        total_chars += len(code)
        file_count += 1

    return "\n".join(source_parts)


def extract_failed_tests(test_result):
    """
    Extract failed tests from pytest JSON results.
    """
    failed_tests = []

    for test in test_result.get("tests", []):
        status = str(test.get("status", "")).lower()

        if status in ("failed", "error"):
            failed_tests.append({
                "name": test.get("name", "Unknown test"),
                "error": test.get("error", "No error details")
            })

    return failed_tests


def detect_bugs(project_path):
    """
    Run tests and detect failures.
    """
    project = Path(project_path).resolve()

    if not project.is_dir():
        return {
            "success": False,
            "message": "Project folder not found.",
            "test_result": {},
            "failed_tests": []
        }

    test_result = run_tests(str(project))
    failed_tests = extract_failed_tests(test_result)

    summary = test_result.get("summary", {})

    failed_count = summary.get(
        "failed", len(failed_tests)
    )

    if test_result.get("success") and failed_count == 0:
        return {
            "success": True,
            "message": "All discovered tests passed.",
            "test_result": test_result,
            "failed_tests": []
        }

    return {
        "success": False,
        "message": "Tests failed or test execution was unsuccessful.",
        "test_result": test_result,
        "failed_tests": failed_tests
    }


def generate_bug_fix(project_path, detection_result):
    """
    Ask the existing LangGraph agents to analyze
    test failures and propose a fix.
    """
    if detection_result.get("success"):
        return {
            "success": True,
            "message": "No failing tests detected.",
            "plan": "",
            "solution": "",
            "review": ""
        }

    source_code = read_project_files(project_path)

    if not source_code.strip():
        return {
            "success": False,
            "message": "No readable Python source files found.",
            "plan": "",
            "solution": "",
            "review": ""
        }

    test_output = detection_result.get(
        "test_result", {}
    ).get("output", "")

    failed_tests = detection_result.get(
        "failed_tests", []
    )

    issue = f"""
Analyze this Python project and identify the bugs.

TEST FAILURES:
{json.dumps(failed_tests, indent=2, default=str)}

PYTEST OUTPUT:
{str(test_output)[-12000:]}

SOURCE CODE:
{source_code}

INSTRUCTIONS:
1. Identify the root cause of each relevant failure.
2. Explain which file and function need correction.
3. Generate corrected Python code.
4. Preserve existing functionality.
5. Do not invent test results.
6. Do not execute shell commands.
7. Do not modify files directly.
8. Clearly identify any uncertainty.

Return a clear proposed fix.
"""

    initial_state = {
        "issue": issue,
        "project_path": str(Path(project_path).resolve()),
        "code_context": "",
        "plan": "",
        "solution": "",
        "review": ""
    }

    try:
        result = app.invoke(initial_state)

        return {
            "success": True,
            "message": "AI bug analysis completed.",
            "plan": str(result.get("plan", "")),
            "solution": str(result.get("solution", "")),
            "review": str(result.get("review", ""))
        }

    except Exception as error:
        return {
            "success": False,
            "message": f"AI analysis failed: {error}",
            "plan": "",
            "solution": "",
            "review": ""
        }


def auto_fix_bugs(project_path):
    """
    Main entry point.

    1. Run tests
    2. Detect failures
    3. Analyze with LangGraph agents
    4. Return proposed correction

    Does not modify original files.
    """
    detection = detect_bugs(project_path)

    if detection["success"]:
        return {
            "status": "passed",
            "message": detection["message"],
            "detection": detection,
            "fix": None
        }

    test_result = detection.get("test_result", {})
    output = str(test_result.get("output", ""))

    # Avoid asking AI to fix a project when pytest
    # could not run or no tests were collected.
    if not detection["failed_tests"]:
        return {
            "status": "needs_attention",
            "message": (
                "No individual failing tests were reported. "
                "Check pytest output for collection errors, "
                "missing dependencies or execution problems."
            ),
            "detection": detection,
            "fix": None
        }

    fix = generate_bug_fix(project_path, detection)

    return {
        "status": (
            "fix_proposed"
            if fix["success"]
            else "analysis_failed"
        ),
        "message": fix["message"],
        "detection": detection,
        "fix": fix
    }


if __name__ == "__main__":
    project_path = input(
        "Enter Python project folder path: "
    ).strip().strip('"')

    result = auto_fix_bugs(project_path)

    print("\nSTATUS:", result["status"])
    print("MESSAGE:", result["message"])

    if result.get("fix"):
        fix = result["fix"]

        print("\n===== PLANNER =====")
        print(fix.get("plan", ""))

        print("\n===== CODER =====")
        print(fix.get("solution", ""))

        print("\n===== REVIEWER =====")
        print(fix.get("review", ""))
