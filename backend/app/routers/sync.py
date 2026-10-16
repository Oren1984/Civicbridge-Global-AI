"""Civic Continuity: saved drafts, idempotent offline replay with conflict detection, emergency notices."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.db import utcnow
from app.deps import Ctx, get_ctx
from app.errors import AppError, bad_request
from app.models import Draft, EmergencyNotice, Jurisdiction, SyncOperation
from app.routers.common import row
from app.services import audit

router = APIRouter(prefix="/api", tags=["continuity"])
D_FIELDS = ["id", "draft_key", "kind", "title", "payload", "version", "updated_at", "created_at"]
KINDS = ("incident_report", "case_message", "case_note", "life_event_note")


@router.get("/drafts")
def drafts(ctx: Ctx = Depends(get_ctx)) -> dict:
    rows = ctx.db.execute(select(Draft).where(Draft.user_id == ctx.user.id, Draft.deleted_at.is_(None)).order_by(Draft.updated_at.desc())).scalars()
    return {"items": [row(d, D_FIELDS) for d in rows]}


class DraftIn(BaseModel):
    kind: str
    title: str = Field(default="", max_length=300)
    payload: dict = Field(default_factory=dict)
    base_version: int | None = None


def _upsert(ctx: Ctx, key: str, body: DraftIn) -> tuple[str, dict]:
    if body.kind not in KINDS:
        raise bad_request("Unknown draft kind.")
    if len(str(body.payload)) > 20000:
        raise bad_request("Draft too large.")
    d = ctx.db.execute(select(Draft).where(Draft.user_id == ctx.user.id, Draft.draft_key == key)).scalar_one_or_none()
    if d is None:
        d = Draft(user_id=ctx.user.id, draft_key=key, kind=body.kind, title=body.title, payload=body.payload, version=1)
        ctx.db.add(d)
        ctx.db.flush()
        return "applied", row(d, D_FIELDS)
    if body.base_version is not None and body.base_version != d.version:
        return "conflict", {"server": row(d, D_FIELDS), "client": body.model_dump()}
    d.title, d.payload, d.kind, d.deleted_at = body.title, body.payload, body.kind, None
    d.version += 1
    d.updated_at = utcnow()
    return "applied", row(d, D_FIELDS)


@router.put("/drafts/{key}")
def save_draft(key: str, body: DraftIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    status, res = _upsert(ctx, key[:120], body)
    ctx.db.commit()
    if status == "conflict":
        raise AppError(409, "draft_conflict", "This draft was changed on another device.", {"server": res["server"]})
    return res


@router.delete("/drafts/{key}")
def delete_draft(key: str, ctx: Ctx = Depends(get_ctx)) -> dict:
    d = ctx.db.execute(select(Draft).where(Draft.user_id == ctx.user.id, Draft.draft_key == key[:120])).scalar_one_or_none()
    if d:
        d.deleted_at = utcnow()
        d.version += 1
        ctx.db.commit()
    return {"ok": True}


class Op(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=80)
    op: str = Field(pattern=r"^(upsert_draft|delete_draft|submit_incident)$")
    draft_key: str = Field(max_length=120)
    base_version: int | None = None
    kind: str = "incident_report"
    title: str = Field(default="", max_length=300)
    payload: dict = Field(default_factory=dict)
    client_time: datetime | None = None


class ReplayIn(BaseModel):
    ops: list[Op] = Field(max_length=50)


@router.post("/sync/replay")
def replay(body: ReplayIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    """Apply queued offline operations exactly once. Re-sending the same idempotency key returns the stored result."""
    results = []
    for op in body.ops:
        prior = ctx.db.execute(select(SyncOperation).where(SyncOperation.user_id == ctx.user.id,
                                                           SyncOperation.idempotency_key == op.idempotency_key)).scalar_one_or_none()
        if prior:
            results.append({"idempotency_key": op.idempotency_key, "status": prior.status, "replayed": True, "result": prior.result})
            continue
        try:
            if op.op == "upsert_draft":
                status, res = _upsert(ctx, op.draft_key, DraftIn(kind=op.kind, title=op.title, payload=op.payload, base_version=op.base_version))
            elif op.op == "delete_draft":
                d = ctx.db.execute(select(Draft).where(Draft.user_id == ctx.user.id, Draft.draft_key == op.draft_key)).scalar_one_or_none()
                if d and op.base_version is not None and op.base_version != d.version:
                    status, res = "conflict", {"server": row(d, D_FIELDS)}
                else:
                    if d:
                        d.deleted_at = utcnow()
                        d.version += 1
                    status, res = "applied", {"deleted": True}
            else:
                from app.routers.incidents import IncidentIn, report

                p = op.payload
                inc = report(IncidentIn(tenant_id=str(p.get("tenant_id")), category=p.get("category") or None, description=str(p.get("description", "")),
                                        lat=p.get("lat"), lon=p.get("lon"), location_text=str(p.get("location_text", "")), draft_key=op.draft_key), ctx)
                d = ctx.db.execute(select(Draft).where(Draft.user_id == ctx.user.id, Draft.draft_key == op.draft_key)).scalar_one_or_none()
                if d:
                    d.deleted_at = utcnow()
                status, res = "applied", {"incident_id": inc["id"], "reference": inc["reference"]}
        except AppError as exc:
            ctx.db.rollback()
            status, res = "rejected", {"code": exc.code, "message": exc.message}
        except Exception as exc:  # noqa: BLE001  (validation errors from nested models)
            ctx.db.rollback()
            status, res = "rejected", {"code": "invalid_operation", "message": str(exc)[:200]}
        ctx.db.add(SyncOperation(user_id=ctx.user.id, idempotency_key=op.idempotency_key, op=op.op, status=status, result=res, at=utcnow()))
        ctx.db.commit()
        results.append({"idempotency_key": op.idempotency_key, "status": status, "replayed": False, "result": res})
    audit.record(ctx.db, "sync.replay", "sync", None, **audit.ctx_kw(ctx),
                 details={"ops": len(body.ops), "conflicts": sum(1 for r in results if r["status"] == "conflict")})
    ctx.db.commit()
    return {"results": results}


def notices_out(db) -> list[dict]:
    now = utcnow()
    rows = db.execute(select(EmergencyNotice).where((EmergencyNotice.expires_at.is_(None)) | (EmergencyNotice.expires_at > now))
                      .order_by(EmergencyNotice.issued_at.desc())).scalars()
    out = []
    for n in rows:
        j = db.get(Jurisdiction, n.jurisdiction_id)
        out.append(row(n, ["id", "title", "body", "severity", "source_label", "source_kind", "fallback_instructions", "issued_at", "expires_at"])
                   | {"jurisdiction": j.code, "jurisdiction_name": j.name})
    return out


@router.get("/emergency/notices")
def notices(ctx: Ctx = Depends(get_ctx)) -> dict:
    return {"items": notices_out(ctx.db), "disclaimer": "CivicBridge is not an emergency dispatch service. In danger, call your local emergency number."}


class NoticeIn(BaseModel):
    title: str = Field(min_length=5, max_length=300)
    body: str = Field(min_length=10, max_length=4000)
    severity: str = Field(pattern=r"^(info|advisory|warning|critical)$")
    fallback_instructions: str = Field(default="", max_length=2000)
    hours: int = Field(default=48, ge=1, le=720)


@router.post("/emergency/notices")
def issue_notice(body: NoticeIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    if ctx.role != "authority_supervisor":
        raise AppError(403, "role_not_permitted", "Only authority supervisors issue notices.")
    from datetime import timedelta

    t = ctx.membership.tenant
    n = EmergencyNotice(jurisdiction_id=t.jurisdiction_id, title=body.title, body=body.body, severity=body.severity,
                        source_label=f"{t.name} (synthetic demo authority inside CivicBridge — not an official alerting channel)",
                        source_kind="authority_tenant", issued_by_tenant_id=t.id, fallback_instructions=body.fallback_instructions,
                        issued_at=utcnow(), expires_at=utcnow() + timedelta(hours=body.hours))
    ctx.db.add(n)
    audit.record(ctx.db, "emergency.notice_issued", "emergency_notice", None, **audit.ctx_kw(ctx), details={"severity": body.severity})
    ctx.db.commit()
    return {"ok": True, "id": str(n.id)}


@router.get("/drafts/{key}")
def get_draft(key: str, ctx: Ctx = Depends(get_ctx)) -> dict:
    d = ctx.db.execute(select(Draft).where(Draft.user_id == ctx.user.id, Draft.draft_key == key[:120], Draft.deleted_at.is_(None))).scalar_one_or_none()
    if d is None:
        raise AppError(404, "not_found", "Draft not found.")
    return row(d, D_FIELDS)

