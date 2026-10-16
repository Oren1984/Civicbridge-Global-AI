"""AI mode resolution and the optional local Ollama client.

Modes:
* rules  - deterministic logic only; no generated text.
* mock   - deterministic, clearly labelled fixture/template outputs (default; no downloads, no keys).
* ollama - optional local model via the `ollama` compose profile. Falls back to mock if unreachable.
"""
from __future__ import annotations

import re

import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.services import policies

INJECTION_PATTERNS = re.compile(
    r"(ignore (all |any )?(previous|prior|above) (instructions|rules)|disregard (the )?(system|previous)|"
    r"you are now|system prompt|developer message|<\s*tool|call the tool|function_call|"
    r"release (all )?(personal )?records|approve (this|the) (decision|application)|"
    r"submit (the )?official application|dispatch (an )?emergency)",
    re.I,
)


def looks_like_injection(text: str) -> bool:
    return bool(INJECTION_PATTERNS.search(text or ""))


def mode(db: Session) -> str:
    m = str(policies.get(db, "ai_mode") or "mock")
    return m if m in ("rules", "mock", "ollama") else "mock"


def ollama_status() -> dict:
    s = get_settings()
    try:
        r = httpx.get(f"{s.ollama_url}/api/tags", timeout=2.0)
        r.raise_for_status()
        models = [m.get("name") for m in r.json().get("models", [])]
        return {"reachable": True, "model_available": s.ollama_model in models, "models": models[:10]}
    except Exception as exc:  # noqa: BLE001
        return {"reachable": False, "model_available": False, "error": type(exc).__name__}


def ollama_generate(system: str, prompt: str, timeout_s: float) -> str:
    s = get_settings()
    r = httpx.post(
        f"{s.ollama_url}/api/generate",
        json={"model": s.ollama_model, "system": system, "prompt": prompt, "stream": False, "options": {"temperature": 0}},
        timeout=timeout_s,
    )
    r.raise_for_status()
    return str(r.json().get("response", ""))[:8000]
