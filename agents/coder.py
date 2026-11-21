
import os
import time
import random

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI


# ==========================================
# STEP 1: LOAD API KEY
# ==========================================

load_dotenv()

API_KEY = os.getenv("GOOGLE_API_KEY")

if not API_KEY:
    raise ValueError(
        "GOOGLE_API_KEY is missing from the .env file"
    )


# ==========================================
# STEP 2: CONFIGURE GEMINI
# ==========================================

llm = ChatGoogleGenerativeAI(
    model="gemini-3.5-flash-lite",
    google_api_key=API_KEY,
    temperature=0,
    timeout=60,
    max_retries=0,
    max_output_tokens=1800
)


# ==========================================
# STEP 3: EXTRACT RESPONSE TEXT
# ==========================================

def extract_text(response):

    content = response.content

    if isinstance(content, str):
        return content

    if isinstance(content, list):

        text_parts = []

        for block in content:

            if isinstance(block, dict):
                if block.get("type") == "text":
                    text_parts.append(
                        block.get("text", "")
                    )

        return "\n".join(text_parts)

    return str(content)


# ==========================================
# STEP 4: IDENTIFY TEMPORARY ERRORS
# ==========================================

def is_temporary_error(error):

    message = str(error).upper()

    retryable_errors = [
        "429",
        "RESOURCE_EXHAUSTED",
        "500 INTERNAL",
        "502 BAD GATEWAY",
        "503",
        "SERVICE_UNAVAILABLE",
        "504",
        "DEADLINE_EXCEEDED",
        "TIMED OUT",
        "TIMEOUT"
    ]

    return any(
        value in message
        for value in retryable_errors
    )


# ==========================================
# STEP 5: GEMINI RETRY FUNCTION
# ==========================================

def invoke_with_retry(prompt, max_attempts=3):

    for attempt in range(1, max_attempts + 1):

        try:

            print(
                f"Coder Agent: Gemini attempt "
                f"{attempt}/{max_attempts}"
            )

            response = llm.invoke(prompt)

            result = extract_text(response)

            if not result.strip():
                raise RuntimeError(
                    "Gemini returned an empty response."
                )

            return result

        except Exception as error:

            if not is_temporary_error(error):
                raise

            if attempt == max_attempts:
                raise

            wait_seconds = (
                min(2 ** attempt, 15)
                + random.uniform(0, 1)
            )

            print(
                f"Temporary Gemini error. "
                f"Retrying in {wait_seconds:.1f} seconds..."
            )

            time.sleep(wait_seconds)


# ==========================================
# STEP 6: CODER AGENT
# ==========================================

def coder_agent(issue, plan):

    if not issue or not issue.strip():
        raise ValueError(
            "Coding problem cannot be empty."
        )

    if not plan or not plan.strip():
        raise ValueError(
            "Planner Agent plan cannot be empty."
        )

    prompt = f"""
You are the Coder Agent of DevPilot.

Your task is to propose safe Python code changes
based on the Planner Agent's analysis.

CODING PROBLEM AND AVAILABLE CODE CONTEXT:
{issue}

PLANNER AGENT PLAN:
{plan}

INSTRUCTIONS:

1. Understand the problem and available code.
2. Identify the relevant Python function or file.
3. Explain the likely cause of the problem.
4. Propose a minimal code change.
5. Provide replacement Python code when enough
   source code is available.
6. Explain why the change is useful.
7. Suggest tests to verify the change.

OUTPUT FORMAT:

### Problem
Explain the problem briefly.

### Target File
Identify the file that needs modification.
If unknown, say "Not identified".

### Proposed Change
Explain the modification.

### Updated Code
Provide the proposed Python code in a
Markdown Python code block.

### Explanation
Explain how the change works.

### Suggested Tests
Describe tests that should be run.

IMPORTANT RULES:

- Never claim that files have been edited.
- Never claim that tests have been executed.
- Do not invent missing source code.
- If the supplied context is incomplete,
  request the missing code instead of
  producing an unsafe replacement.
- Preserve existing function names and
  interfaces unless a change is necessary.
- Never reveal API keys or passwords.
- Do not suggest destructive shell commands.
- Keep changes focused and minimal.
"""

    try:

        result = invoke_with_retry(
            prompt,
            max_attempts=3
        )

        print(
            "Coder Agent completed successfully."
        )

        return result

    except Exception as error:

        raise RuntimeError(
            f"Coder Agent failed: {error}"
        ) from error


# ==========================================
# STEP 7: TEST CODER AGENT
# ==========================================

if __name__ == "__main__":

    print("\n================================")
    print("       DEVPILOT CODER AGENT")
    print("================================")

    issue = input(
        "\nEnter your coding problem: "
    )

    sample_plan = """
1. Identify the problem.
2. Investigate the relevant Python code.
3. Suggest a minimal correction.
4. Explain the proposed change.
5. Recommend tests.
"""

    try:

        result = coder_agent(
            issue,
            sample_plan
        )

        print("\n================================")
        print("       CODER AGENT OUTPUT")
        print("================================\n")

        print(result)

    except Exception as error:

        print("\nError:", error)
