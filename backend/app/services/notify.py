"""In-app notifications with per-category preferences; e-mail delivery goes through the job queue to the local mail sink."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Notification, NotificationPreference
from app.services import jobs

CATEGORIES = ("case", "message", "deadline", "meeting", "incident", "security", "emergency")
_KIND_CATEGORY = {
    "message": "message",
    "task_due": "deadline",
    "info_request": "case",
    "decision": "case",
    "case_update": "case",
    "appeal": "case",
    "meeting_invite": "meeting",
    "meeting_update": "meeting",
    "incident_update": "incident",
    "security": "security",
    "emergency": "emergency",
    "delegation": "case",
    "consent": "case",
    "privacy": "case",
    "escalation": "case",
    "assignment": "case",
}
# Security notices cannot be switched off in-app.
_MANDATORY = {"security"}


def category_for(kind: str) -> str:
    return _KIND_CATEGORY.get(kind, "case")


def notify(
    db: Session,
    user_id: uuid.UUID,
    kind: str,
    title: str,
    body: str = "",
    link: str = "",
    tenant_id: uuid.UUID | None = None,
) -> Notification | None:
    cat = category_for(kind)
    pref = db.execute(
        select(NotificationPreference).where(NotificationPreference.user_id == user_id, NotificationPreference.category == cat)
    ).scalar_one_or_none()
    in_app = True if pref is None or cat in _MANDATORY else pref.in_app
    email = pref.email if pref is not None else cat in ("security",)
    n = None
    if in_app:
        n = Notification(user_id=user_id, tenant_id=tenant_id, kind=kind, title=title[:300], body=body, link=link)
        db.add(n)
        db.flush()
    if email:
        jobs.enqueue(db, "send_email", {"user_id": str(user_id), "subject": title[:200], "body": body, "link": link})
    return n
