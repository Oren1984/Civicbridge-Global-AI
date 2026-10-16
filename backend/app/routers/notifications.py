from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select, update

from app.db import utcnow
from app.deps import Ctx, get_ctx
from app.errors import AppError
from app.models import Notification, NotificationPreference
from app.routers.common import paginate, parse_uuid, row
from app.services.notify import CATEGORIES

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("")
def list_notifications(ctx: Ctx = Depends(get_ctx), unread: bool = False, page: int = 1, page_size: int = 20) -> dict:
    stmt = select(Notification).where(Notification.user_id == ctx.user.id)
    if unread:
        stmt = stmt.where(Notification.read_at.is_(None))
    items, meta = paginate(ctx.db, stmt.order_by(Notification.created_at.desc()), page, page_size)
    count = ctx.db.execute(select(func.count()).select_from(Notification).where(Notification.user_id == ctx.user.id, Notification.read_at.is_(None))).scalar_one()
    return {"items": [row(n, ["id", "kind", "title", "body", "link", "read_at", "created_at"]) for n in items], "meta": meta, "unread": count}


@router.post("/{nid}/read")
def mark_read(nid: str, ctx: Ctx = Depends(get_ctx)) -> dict:
    n = ctx.db.get(Notification, parse_uuid(nid))
    if n is None or n.user_id != ctx.user.id:
        raise AppError(404, "not_found", "Not found.")
    n.read_at = n.read_at or utcnow()
    ctx.db.commit()
    return {"ok": True}


@router.post("/read-all")
def read_all(ctx: Ctx = Depends(get_ctx)) -> dict:
    ctx.db.execute(update(Notification).where(Notification.user_id == ctx.user.id, Notification.read_at.is_(None)).values(read_at=utcnow()))
    ctx.db.commit()
    return {"ok": True}


@router.get("/preferences")
def prefs(ctx: Ctx = Depends(get_ctx)) -> dict:
    rows = {p.category: p for p in ctx.db.execute(select(NotificationPreference).where(NotificationPreference.user_id == ctx.user.id)).scalars()}
    return {"items": [{"category": c, "in_app": rows[c].in_app if c in rows else True, "email": rows[c].email if c in rows else c == "security",
                       "locked": c == "security"} for c in CATEGORIES]}


class PrefIn(BaseModel):
    category: str
    in_app: bool
    email: bool


@router.put("/preferences")
def set_prefs(items: list[PrefIn], ctx: Ctx = Depends(get_ctx)) -> dict:
    for p in items:
        if p.category not in CATEGORIES:
            continue
        cur = ctx.db.execute(select(NotificationPreference).where(NotificationPreference.user_id == ctx.user.id,
                                                                  NotificationPreference.category == p.category)).scalar_one_or_none()
        if cur is None:
            cur = NotificationPreference(user_id=ctx.user.id, category=p.category)
            ctx.db.add(cur)
        cur.in_app = True if p.category == "security" else p.in_app
        cur.email = p.email
    ctx.db.commit()
    return prefs(ctx)
