"""Shared router helpers: pagination, serialisation, rate limiting."""
from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque
from datetime import date, datetime
from typing import Any

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import AppError


def iso(v: Any) -> Any:
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, uuid.UUID):
        return str(v)
    return v


def row(obj: Any, fields: list[str]) -> dict[str, Any]:
    return {f: iso(getattr(obj, f)) for f in fields}


def paginate(db: Session, stmt, page: int, page_size: int) -> tuple[list, dict]:
    page = max(1, page)
    page_size = min(100, max(1, page_size))
    total = db.execute(select(func.count()).select_from(stmt.order_by(None).subquery())).scalar_one()
    items = db.execute(stmt.limit(page_size).offset((page - 1) * page_size)).scalars().unique().all()
    return list(items), {"page": page, "page_size": page_size, "total": total, "pages": max(1, -(-total // page_size))}


class RateLimiter:
    """In-process sliding-window limiter (single backend process; documented limitation for scale-out)."""

    def __init__(self) -> None:
        self.hits: dict[str, deque] = defaultdict(deque)

    def check(self, key: str, limit: int, window_s: int) -> None:
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > window_s:
            q.popleft()
        if len(q) >= limit:
            raise AppError(429, "rate_limited", "Too many attempts. Please wait a moment and try again.")
        q.append(now)


limiter = RateLimiter()


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown"))[:64]


def parse_uuid(v: Any, field: str = "id") -> uuid.UUID:
    try:
        return uuid.UUID(str(v))
    except (ValueError, TypeError) as exc:
        raise AppError(400, "invalid_request", f"Invalid {field}.") from exc
