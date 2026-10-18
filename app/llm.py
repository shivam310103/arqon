"""Thin wrapper over the Google Gen AI SDK (Gemini).

Works with either:
  - Gemini API key (AI Studio):   GEMINI_API_KEY=...
  - Vertex AI on Google Cloud:    GOOGLE_GENAI_USE_VERTEXAI=true, GOOGLE_CLOUD_PROJECT=..., GOOGLE_CLOUD_LOCATION=us-central1
If neither is configured the app runs in offline mode with deterministic fallbacks.
"""
from __future__ import annotations

import json
import os
import time

MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

_client = None
_mode = "offline"


def _init():
    global _client, _mode
    if _client is not None or _mode == "disabled":
        return
    use_vertex = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in ("1", "true", "yes")
    has_key = bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
    if not (use_vertex or has_key) or os.getenv("ARQON_OFFLINE") == "1":
        _mode = "disabled"
        return
    try:
        from google import genai
        key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if use_vertex and key and not os.getenv("GOOGLE_CLOUD_PROJECT"):
            # Vertex AI express mode: API key bound to a service account (Agent Platform API)
            _client = genai.Client(vertexai=True, api_key=key)
            _mode = "vertex_express"
        elif use_vertex:
            _client = genai.Client(vertexai=True)
            _mode = "vertex"
        else:
            _client = genai.Client(api_key=key)
            _mode = "api_key"
    except Exception as exc:  # pragma: no cover
        print(f"[llm] Gemini init failed, offline mode: {exc}")
        _mode = "disabled"


def mode() -> str:
    _init()
    return "offline" if _mode == "disabled" else _mode


def available() -> bool:
    _init()
    return _client is not None


def generate_json(system: str, prompt: str, schema: dict | None = None, temperature: float = 0.1) -> tuple[dict, dict]:
    """Return (parsed_json, meta). Raises on failure so callers can fall back."""
    _init()
    if _client is None:
        raise RuntimeError("Gemini not configured")
    from google.genai import types
    cfg = types.GenerateContentConfig(
        system_instruction=system,
        temperature=temperature,
        response_mime_type="application/json",
        response_schema=schema,
    )
    t0 = time.time()
    resp = _client.models.generate_content(model=MODEL, contents=prompt, config=cfg)
    text = resp.text or "{}"
    data = json.loads(text)
    meta = {"model": MODEL, "ms": int((time.time() - t0) * 1000)}
    try:
        u = resp.usage_metadata
        meta["tokens"] = {"in": u.prompt_token_count, "out": u.candidates_token_count}
    except Exception:
        pass
    return data, meta


def generate_text(system: str, prompt: str, temperature: float = 0.3) -> tuple[str, dict]:
    _init()
    if _client is None:
        raise RuntimeError("Gemini not configured")
    from google.genai import types
    cfg = types.GenerateContentConfig(system_instruction=system, temperature=temperature)
    t0 = time.time()
    resp = _client.models.generate_content(model=MODEL, contents=prompt, config=cfg)
    return (resp.text or "").strip(), {"model": MODEL, "ms": int((time.time() - t0) * 1000)}
