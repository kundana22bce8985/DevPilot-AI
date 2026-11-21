
import ast
import re
from pathlib import Path

from tools.auto_bug_fixer import auto_fix_bugs
from tools.patch_applier import apply_and_verify


def extract_python_code(text):
    """Extract Python code from the Coder Agent's response."""
    blocks = re.findall(
        r"```(?:python|py)\s*\n(.*?)```",
        text,
        flags=re.DOTALL | re.IGNORECASE
    )

    for block in blocks:
        candidate = block.strip()

        try:
            ast.parse(candidate)
            return candidate
        except SyntaxError:
            continue

    # Also support responses containing only Python code.
    candidate = text.strip()

    try:
        ast.parse(candidate)
        return candidate
    except SyntaxError:
        return None


def reviewer_approved(review):
    """Require an explicit approval from the Reviewer Agent."""
    return bool(
        re.search(
            r"(?:final verdict\s*:\s*|verdict\s*:\s*)"
            r"(?:\*\*)?APPROVED\b",
            review,
            flags=re.IGNORECASE
        )
    )


def automatically_fix_project(project_path, file_name):
    """
    Detect failing tests, generate a fix,
    and verify it in a temporary project copy.

    Original files are not modified.
    """

    project = Path(project_path).resolve()
    target = project / file_name

    if not project.is_dir():
        return {
            "success": False,
            "message": "Project folder not found."
        }

    if not target.is_file():
        return {
            "success": False,
            "message": "Target Python file not found."
        }

    print("\n[1/5] Running tests and detecting bugs...")

    analysis = auto_fix_bugs(str(project))

    if analysis["status"] == "passed":
        return {
            "success": True,
            "message": "All tests already passed. No fix needed."
        }

    if analysis["status"] != "fix_proposed":
        return {
            "success": False,
            "message": analysis["message"]
        }

    fix = analysis["fix"]

    print("[2/5] Planner identified the problem.")
    print("[3/5] Coder generated a proposed correction.")

    review = fix.get("review", "")

    if not reviewer_approved(review):
        return {
            "success": False,
            "message": "Reviewer did not explicitly approve the fix.",
            "review": review
        }

    print("[4/5] Reviewer approved the correction.")

    corrected_code = extract_python_code(
        fix.get("solution", "")
    )

    if not corrected_code:
        return {
            "success": False,
            "message": (
                "Could not extract valid Python code "
                "from the Coder Agent's response."
            )
        }

    # Require a complete replacement module, not a snippet.
    try:
        original_ast = ast.parse(
            target.read_text(encoding="utf-8")
        )
        corrected_ast = ast.parse(corrected_code)

        original_functions = {
            node.name
            for node in original_ast.body
            if isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef)
            )
        }

        corrected_functions = {
            node.name
            for node in corrected_ast.body
            if isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef)
            )
        }

        if not original_functions.issubset(corrected_functions):
            return {
                "success": False,
                "message": (
                    "The proposed code is missing existing "
                    "top-level functions. Manual review required."
                )
            }

    except (OSError, SyntaxError) as error:
        return {
            "success": False,
            "message": str(error)
        }

    print("[5/5] Applying correction to a copy and rerunning tests...")

    verification = apply_and_verify(
        project_path=str(project),
        relative_file_path=file_name,
        corrected_code=corrected_code
    )

    return {
        "success": verification.get("success", False),
        "message": verification.get("message", "Verification failed."),
        "corrected_code": corrected_code,
        "review": review,
        "test_result": verification.get("test_result", {}),
        "original_unchanged": True
    }


if __name__ == "__main__":
    project_path = input(
        "Enter project folder: "
    ).strip().strip('"')

    file_name = input(
        "Enter buggy file name: "
    ).strip().strip('"')

    result = automatically_fix_project(
        project_path,
        file_name
    )

    print("\n========== FINAL RESULT ==========")
    print("SUCCESS:", result["success"])
    print("MESSAGE:", result["message"])

    if result.get("corrected_code"):
        print("\n===== CORRECTED CODE =====")
        print(result["corrected_code"])

    if result.get("test_result"):
        print("\n===== TEST RESULTS =====")
        print(result["test_result"].get("output", ""))

    print("\nOriginal project files were not modified.")
