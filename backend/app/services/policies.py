"""Governance-configurable policies with safe defaults. Locked policies cannot be changed from the UI."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import utcnow
from app.models import Policy

DEFAULTS: dict[str, tuple[Any, str, bool]] = {
    "session_idle_minutes": (None, "Idle session timeout in minutes.", False),
    "session_absolute_hours": (None, "Absolute session lifetime in hours.", False),
    "max_upload_mb": (None, "Maximum upload size per file (MB).", False),
    "user_quota_mb": (200, "Total storage quota per citizen (MB).", False),
    "small_group_threshold": (5, "Aggregates with fewer records than this are suppressed in public/aggregate views.", False),
    "ai_mode": (None, "AI assistance mode: rules (deterministic only), mock (labelled fixtures) or ollama (optional local model).", False),
    "ai_budget_per_hour": (60, "Maximum AI tool calls per user per hour.", False),
    "ai_tool_timeout_s": (8, "Maximum seconds for a single AI tool call.", False),
    "meeting_recording": (False, "Meeting recording is disabled. A consent/retention/deletion workflow would be required first.", True),
    "incident_sla_working_days": (5, "Default incident SLA in working days.", False),
    "appeal_window_days": (30, "Synthetic default appeal window (days) for demo decisions.", False),
    "breach_notification_hours": (72, "Target hours to notify regulators after a personal-data breach is confirmed (assessment input).", False),
    "consent_max_days": (365, "Maximum duration of a consent grant in days.", False),
    "delegation_max_days": (180, "Maximum duration of a delegation in days.", False),
}


def _runtime_default(key: str) -> Any:
    s = get_settings()
    return {
        "session_idle_minutes": s.session_idle_minutes,
        "session_absolute_hours": s.session_absolute_hours,
        "max_upload_mb": s.max_upload_mb,
        "ai_mode": s.ai_mode,
    }.get(key, DEFAULTS[key][0])


def get(db: Session, key: str) -> Any:
    row = db.get(Policy, key)
    if row is not None:
        return row.value.get("v")
    return _runtime_default(key)


def all_policies(db: Session) -> list[dict[str, Any]]:
    out = []
    for key, (_default, desc, locked) in DEFAULTS.items():
        row = db.get(Policy, key)
        out.append(
            {
                "key": key,
                "value": row.value.get("v") if row else _runtime_default(key),
                "description": desc,
                "locked": locked,
                "updated_at": row.updated_at.isoformat() if row else None,
            }
        )
    return out


def set_policy(db: Session, key: str, value: Any, user_id) -> Policy:
    row = db.get(Policy, key)
    if row is None:
        row = Policy(key=key, value={"v": value}, description=DEFAULTS[key][1], locked=DEFAULTS[key][2], updated_at=utcnow())
        db.add(row)
    row.value = {"v": value}
    row.updated_by = user_id
    row.updated_at = utcnow()
    return row
