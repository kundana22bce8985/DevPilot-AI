
import os
import re
import time
from pathlib import Path

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI


# ==========================================
# CONFIGURATION
# ==========================================

load_dotenv()

MODEL_NAME = "gemini-3.5-flash-lite"

MAX_CODE_LENGTH = 20000
MAX_RETRIES = 3


# ==========================================
# EXTRACT GEMINI RESPONSE
# ==========================================

def extract_response_text(content):

    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):

        parts = []

        for block in content:

            if isinstance(block, str):
                parts.append(block)

            elif isinstance(block, dict):

                text = block.get("text")

                if isinstance(text, str):
                    parts.append(text)

        return "\n".join(parts).strip()

    if content is None:
        return ""

    return str(content).strip()


# ==========================================
# REMOVE MARKDOWN CODE FENCES
# ==========================================

def clean_generated_code(generated_code):

    generated_code = generated_code.strip()

    if generated_code.startswith("```"):

        lines = generated_code.splitlines()

        if lines and lines[0].startswith("```"):
            lines.pop(0)

        if lines and lines[-1].strip() == "```":
            lines.pop()

        generated_code = "\n".join(lines).strip()

    return generated_code


# ==========================================
# GENERATE TESTS FROM PASTED CODE
# ==========================================

def generate_tests_from_code(
    source_code,
    module_name="sample_code"
):

    if not isinstance(source_code, str):
        return "Error: Please provide valid Python code."

    source_code = source_code.strip()

    if not source_code:
        return "Error: Please provide Python code."

    if len(source_code) > MAX_CODE_LENGTH:
        return "Error: Python code is too large."

    if not isinstance(module_name, str):
        return "Error: Invalid Python module name."

    module_name = module_name.strip()

    if not re.fullmatch(
        r"[A-Za-z_][A-Za-z0-9_]*",
        module_name
    ):
        return "Error: Invalid Python module name."

    if not os.getenv("GOOGLE_API_KEY"):
        return "Error: GOOGLE_API_KEY is missing."

    try:

        model = ChatGoogleGenerativeAI(
            model=MODEL_NAME,
            max_output_tokens=1800,
            timeout=60,
            max_retries=0
        )

    except Exception as error:

        return f"Error initializing Gemini: {error}"

    prompt = f"""
You are an expert Python software tester.

Your task is to generate pytest test cases for
the Python source code provided below.

REQUIREMENTS:

1. Return ONLY executable Python code.
2. Do not include markdown code fences.
3. Use the pytest framework.
4. Import the tested functions or classes
   from the Python module named "{module_name}".
5. Include normal test cases.
6. Include edge test cases.
7. Include error test cases where appropriate.
8. Do not invent functions that do not exist.
9. Do not modify the original source code.
10. Use clear and descriptive test names.
11. Avoid network calls and destructive operations.
12. Do not assume behavior that is not supported
    by the provided code.
13. Generate tests that are suitable for review
    before execution.

PYTHON MODULE NAME:
{module_name}

PYTHON SOURCE CODE:

{source_code}
"""

    for attempt in range(MAX_RETRIES):

        try:

            response = model.invoke(prompt)

            generated_code = extract_response_text(
                response.content
            )

            generated_code = clean_generated_code(
                generated_code
            )

            if not generated_code:
                return "Error: Gemini returned an empty response."

            return generated_code

        except Exception as error:

            message = str(error)

            temporary_error = any(
                code in message
                for code in [
                    "429",
                    "500",
                    "502",
                    "503",
                    "504",
                    "timed out",
                    "timeout"
                ]
            )

            if (
                temporary_error
                and attempt < MAX_RETRIES - 1
            ):

                time.sleep(
                    2 * (attempt + 1)
                )

                continue

            return f"Error generating tests: {error}"

    return "Error: Could not generate test cases."


# ==========================================
# GENERATE TESTS FROM PYTHON FILE
# ==========================================

def generate_tests(file_path):

    file = Path(file_path).resolve()

    if not file.is_file():

        return (
            "Error: Please select an existing "
            "Python file."
        )

    if file.suffix.lower() != ".py":

        return (
            "Error: Only Python (.py) files "
            "are supported."
        )

    try:

        source_code = file.read_text(
            encoding="utf-8"
        )

    except Exception as error:

        return f"Error reading Python file: {error}"

    if not source_code.strip():

        return "Error: Python file is empty."

    return generate_tests_from_code(
        source_code=source_code,
        module_name=file.stem
    )


# ==========================================
# COMMAND LINE TEST
# ==========================================

if __name__ == "__main__":

    print("\n===== DEVPILOT AI TEST GENERATOR =====\n")

    print("1. Generate tests from Python file")
    print("2. Generate tests from pasted code")

    choice = input(
        "\nChoose option (1 or 2): "
    ).strip()

    if choice == "1":

        file_path = input(
            "Enter Python file path: "
        ).strip().strip('"')

        print("\nGenerating test cases...\n")

        result = generate_tests(
            file_path
        )

        print(
            "===== AI GENERATED TEST CASES =====\n"
        )

        print(result)

    elif choice == "2":

        module_name = input(
            "Enter Python module name: "
        ).strip()

        print(
            "\nPaste Python code below."
        )

        print(
            "Enter END on a separate line "
            "when finished.\n"
        )

        lines = []

        while True:

            line = input()

            if line.strip() == "END":
                break

            lines.append(line)

        source_code = "\n".join(lines)

        print("\nGenerating test cases...\n")

        result = generate_tests_from_code(
            source_code,
            module_name
        )

        print(
            "===== AI GENERATED TEST CASES =====\n"
        )

        print(result)

    else:

        print("Invalid option.")
