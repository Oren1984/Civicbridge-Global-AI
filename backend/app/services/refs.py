from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import utcnow


def next_ref(db: Session, prefix: str) -> str:
    """Human-readable reference from a PostgreSQL sequence (safe under concurrency)."""
    n = db.execute(text("SELECT nextval('civic_reference_seq')")).scalar_one()
    return f"{prefix}-{utcnow().year}-{n:06d}"
