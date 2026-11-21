
import os
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

api_key = os.getenv("GOOGLE_API_KEY")

if not api_key:
    print("Google API key is missing!")
    raise SystemExit(1)

client = genai.Client(
    api_key=api_key,
    http_options=types.HttpOptions(timeout=60000)
)

print("Connecting to Gemini...", flush=True)

try:
    response = client.models.generate_content(
        model="gemini-3.5-flash-lite",
        contents="Reply with only OK"
    )

    print("Gemini response:", response.text)

except Exception as e:
    print("Gemini API failed:")
    print(type(e).__name__, str(e))
