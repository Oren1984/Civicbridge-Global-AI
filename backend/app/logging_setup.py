"""Structured JSON logs with redaction of e-mail addresses, tokens and secrets."""
from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone

_PATTERNS = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[email]"),
    (re.compile(r"(?i)(token|password|secret|authorization|cookie)=([^&\s]+)"), r"\1=[redacted]"),
    (re.compile(r"eyJ[\w-]+\.[\w-]+\.[\w-]+"), "[jwt]"),
    (re.compile(r"(?i)bearer\s+[\w.-]+"), "Bearer [redacted]"),
]


def redact(text: str) -> str:
    for pat, repl in _PATTERNS:
        text = pat.sub(repl, text)
    return text


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        for key in ("method", "path", "status", "duration_ms", "request_id", "job", "job_id"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["error"] = redact(self.formatException(record.exc_info))[-2000:]
        return json.dumps(payload, ensure_ascii=False)


def setup(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    for noisy in ("uvicorn.access", "botocore", "urllib3", "httpx", "livekit"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
