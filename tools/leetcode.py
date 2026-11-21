
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def run_leetcode_cases(project_path, module_name, function_name, cases):
    project = Path(project_path).resolve()

    if not project.is_dir():
        return {"error": "Project folder not found.", "results": []}

    # The worker imports and runs trusted project code.
    worker = r'''
import importlib
import json
import sys

project_path, module_name, function_name = sys.argv[1:4]
sys.path.insert(0, project_path)

results = []

try:
    module = importlib.import_module(module_name)
    function = getattr(module, function_name)

    for case in json.load(sys.stdin):
        args = case.get("args", [])
        expected = case.get("expected")
        expected_error = case.get("expected_error")

        try:
            actual = function(*args)
            passed = (
                expected_error is None
                and actual == expected
            )
            results.append({
                "input": args,
                "expected": expected_error or expected,
                "actual": actual,
                "passed": passed
            })
        except Exception as error:
            actual_error = type(error).__name__
            results.append({
                "input": args,
                "expected": expected_error or expected,
                "actual": actual_error,
                "passed": actual_error == expected_error
            })

except Exception as error:
    print(json.dumps({
        "error": str(error),
        "results": []
    }))
    sys.exit(0)

print(json.dumps({"results": results}, default=str))
'''

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            script = Path(temp_dir) / "worker.py"
            script.write_text(worker, encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    str(project),
                    module_name,
                    function_name
                ],
                input=json.dumps(cases),
                text=True,
                capture_output=True,
                timeout=15,
                cwd=temp_dir
            )

            if completed.returncode != 0:
                return {
                    "error": completed.stderr,
                    "results": []
                }

            return json.loads(completed.stdout)

    except subprocess.TimeoutExpired:
        return {"error": "Execution timed out.", "results": []}
    except Exception as error:
        return {"error": str(error), "results": []}
