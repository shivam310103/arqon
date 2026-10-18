"""Diagnose Gemini access. Run:  .\\.venv\\Scripts\\python.exe scripts\\check_gemini.py
Prints which Flash models your key can use and the exact error if a call fails. Never prints your key."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import app  # noqa: F401,E402  (loads .env)
from app import llm  # noqa: E402

model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
print(f"Key loaded: {'yes' if key else 'NO'} (length {len(key)})   Model in .env: {model}")

llm._init()
client = llm._client
print("Client mode:", llm.mode())
if client is None:
    sys.exit("Gemini client not configured - check .env")
try:
    names = [m.name.replace("models/", "") for m in client.models.list()]
    flash = [n for n in names if "flash" in n]
    print("Flash models available to this key:")
    for n in flash:
        print("   ", n)
except Exception as e:
    print("Could not list models:", repr(e)[:600])

try:
    r = client.models.generate_content(model=model, contents="Reply with the single word OK.")
    print("Test call result:", (r.text or "").strip())
except Exception as e:
    print("TEST CALL FAILED:", repr(e)[:900])
