
import os
import sys
import json
import shutil
import subprocess
import tempfile
from pathlib import Path


TEST_TIMEOUT = 30

EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    ".pytest_cache",
    "build",
    "dist",
}


def ignore_files(directory, names):
    return [
        name
        for name in names
        if name in EXCLUDED_DIRS
    ]


def empty_result(message, returncode=None):
    return {
        "success": False,
        "output": message,
        "returncode": returncode,
        "tests": [],
        "summary": {},
    }


def run_tests(project_path):

    project = Path(project_path).resolve()

    if not project.is_dir():
        return empty_result(
            "Project folder does not exist."
        )

    test_files = (
        list(project.rglob("test_*.py"))
        + list(project.rglob("*_test.py"))
    )

    test_files = [
        path
        for path in test_files
        if not any(
            part in EXCLUDED_DIRS
            for part in path.relative_to(project).parts
        )
    ]

    if not test_files:
        return empty_result(
            "No Python test files found."
        )

    with tempfile.TemporaryDirectory() as temp_dir:

        workspace = Path(temp_dir) / "project"

        shutil.copytree(
            project,
            workspace,
            ignore=ignore_files,
        )

        report_path = workspace / "test_report.json"

        environment = os.environ.copy()

        environment["PYTHONDONTWRITEBYTECODE"] = "1"

        # Disable automatic loading of external pytest plugins
        environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"

        # Remove inherited pytest options
        environment.pop("PYTEST_ADDOPTS", None)

        command = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "-p",
            "pytest_jsonreport.plugin",
            "--json-report",
            f"--json-report-file={report_path}",
            ".",
        ]

        try:
            result = subprocess.run(
                command,
                cwd=str(workspace),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=TEST_TIMEOUT,
                shell=False,
                env=environment,
            )

            output = (
                result.stdout + "\n" + result.stderr
            ).strip()

            report = {}

            if report_path.exists():
                report = json.loads(
                    report_path.read_text(
                        encoding="utf-8"
                    )
                )

            tests = []

            for item in report.get("tests", []):

                outcome = item.get(
                    "outcome",
                    "unknown"
                )

                call = item.get("call") or {}
                setup = item.get("setup") or {}
                teardown = item.get("teardown") or {}

                error = (
                    call.get("longrepr")
                    or setup.get("longrepr")
                    or teardown.get("longrepr")
                    or ""
                )

                tests.append({
                    "name": item.get("nodeid", ""),
                    "status": outcome,
                    "error": str(error),
                    "duration": call.get(
                        "duration",
                        0
                    ),
                })

            return {
                "success": result.returncode == 0,
                "output": output,
                "returncode": result.returncode,
                "tests": tests,
                "summary": report.get(
                    "summary",
                    {}
                ),
            }

        except subprocess.TimeoutExpired as error:

            stdout = error.stdout or b""
            stderr = error.stderr or b""

            if isinstance(stdout, bytes):
                stdout = stdout.decode(
                    errors="replace"
                )

            if isinstance(stderr, bytes):
                stderr = stderr.decode(
                    errors="replace"
                )

            return empty_result(
                f"Test execution timed out after "
                f"{TEST_TIMEOUT} seconds.\n"
                f"{stdout}\n{stderr}"
            )

        except Exception as error:

            return empty_result(
                f"Test runner error: {error}"
            )


if __name__ == "__main__":

    project_path = input(
        "Enter project folder path: "
    ).strip().strip('"')

    result = run_tests(project_path)

    print("\n===== TEST RESULTS =====\n")
    print(result["output"])

    print("\n===== INDIVIDUAL TESTS =====\n")

    for test in result["tests"]:
        print(
            test["name"],
            "->",
            test["status"].upper()
        )

    print("\nSuccess:", result["success"])
