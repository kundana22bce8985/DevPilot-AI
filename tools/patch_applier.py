
import ast
import shutil
import tempfile
from pathlib import Path

from tools.test_runner import run_tests


def apply_and_verify(project_path, relative_file_path, corrected_code):
    """
    Apply corrected code to a temporary project copy
    and run pytest to verify the fix.
    Original files remain unchanged.
    """

    project = Path(project_path).resolve()
    relative = Path(relative_file_path)

    if not project.is_dir():
        return {"success": False, "message": "Project folder not found."}

    if relative.is_absolute() or ".." in relative.parts or relative.suffix != ".py":
        return {"success": False, "message": "Invalid Python file path."}

    target = project / relative

    if not target.is_file() or target.is_symlink():
        return {"success": False, "message": "Target Python file not found or unsafe."}

    if not target.resolve().is_relative_to(project):
        return {"success": False, "message": "Target path is outside the project."}

    try:
        ast.parse(corrected_code)
    except SyntaxError as error:
        return {"success": False, "message": f"Invalid Python syntax: {error}"}

    with tempfile.TemporaryDirectory() as temp:
        working_project = Path(temp) / "project"

        shutil.copytree(
            project,
            working_project,
            ignore=shutil.ignore_patterns(
                ".git", ".venv", "venv",
                "__pycache__", ".pytest_cache",
                "node_modules", ".env", ".env.*"
            )
        )

        working_target = working_project / relative

        if not working_target.is_file() or working_target.is_symlink():
            return {"success": False, "message": "Unsafe or missing file in working copy."}

        working_target.write_text(corrected_code, encoding="utf-8")

        test_result = run_tests(str(working_project))

        return {
            "success": bool(test_result.get("success")),
            "message": (
                "Fix verified: tests passed."
                if test_result.get("success")
                else "Fix not verified: tests failed."
            ),
            "test_result": test_result,
            "original_unchanged": True
        }
