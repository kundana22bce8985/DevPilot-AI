
import os
import time
import random

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI

load_dotenv()

api_key = os.getenv("GOOGLE_API_KEY")

if not api_key:
    raise ValueError("GOOGLE_API_KEY not found in .env")


# ==========================================
# GEMINI CONFIGURATION
# ==========================================

llm = ChatGoogleGenerativeAI(
    model="gemini-3.5-flash-lite",
    google_api_key=api_key,
    temperature=0,
    timeout=60,
    max_retries=0,
    max_output_tokens=400
)


# ==========================================
# TEMPORARY ERROR DETECTION
# ==========================================

def is_retryable_error(error):

    # Check the exception and its original cause
    current = error

    while current is not None:

        status_code = getattr(
            current, "status_code", None
        )

        if status_code is None:
            status_code = getattr(
                current, "code", None
            )

        if callable(status_code):
            try:
                status_code = status_code()
            except Exception:
                status_code = None

        if status_code is not None:

            status_text = str(status_code).upper()

            if any(value in status_text for value in [
                "429",
                "500",
                "502",
                "503",
                "504",
                "RESOURCE_EXHAUSTED",
                "UNAVAILABLE",
                "DEADLINE_EXCEEDED"
            ]):
                return True

        message = str(current).upper()

        if any(value in message for value in [
            "429",
            "500 INTERNAL",
            "502 BAD GATEWAY",
            "503",
            "504",
            "DEADLINE_EXCEEDED",
            "RESOURCE_EXHAUSTED",
            "SERVICE_UNAVAILABLE",
            "UNAVAILABLE",
            "TIMED OUT",
            "TIMEOUT"
        ]):
            return True

        current = (
            current.__cause__
            or current.__context__
        )

    return False


# ==========================================
# GEMINI CALL WITH RETRIES
# ==========================================

def invoke_with_retry(prompt, max_attempts=3):

    for attempt in range(1, max_attempts + 1):

        try:

            print(
                f"Planner Agent: Gemini attempt "
                f"{attempt}/{max_attempts}"
            )

            return llm.invoke(prompt)

        except Exception as error:

            if not is_retryable_error(error):
                raise

            if attempt == max_attempts:
                raise

            # Exponential backoff with jitter
            wait_seconds = (
                min(2 ** attempt, 15)
                + random.uniform(0, 1)
            )

            print(
                "Temporary Gemini error: "
                f"{type(error).__name__}"
            )

            print(
                f"Retrying in "
                f"{wait_seconds:.1f} seconds..."
            )

            time.sleep(wait_seconds)


# ==========================================
# PLANNER AGENT
# ==========================================

def planner_agent(issue):

    if not issue or not issue.strip():
        raise ValueError(
            "No coding problem provided."
        )

    print("Connecting Planner Agent to Gemini AI...")

    prompt = f"""
You are the Planner Agent of DevPilot.

Coding Problem:
{issue}

Analyze the problem and provide:

1. Problem Description
2. Possible Root Causes
3. Files to Investigate
4. Steps to Fix
5. Tests to Verify

Keep your answer short and simple.
Maximum 150 words.

Use the provided repository context when available.
Do not claim to have inspected files that were not provided.
Do not invent bugs or test results.
"""

    try:

        response = invoke_with_retry(
            prompt,
            max_attempts=3
        )

        if isinstance(response.content, str):
            return response.content

        if isinstance(response.content, list):

            return "\n".join(
                block.get("text", "")
                for block in response.content
                if isinstance(block, dict)
                and block.get("type") == "text"
            )

        return str(response.content)

    except Exception as error:

        raise RuntimeError(
            f"Planner Agent failed after retry handling: {error}"
        ) from error
