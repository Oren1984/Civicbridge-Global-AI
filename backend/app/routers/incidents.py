"""Incident reporting and municipal resolution."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from app.ai.tools import classify_text
from app.deps import Ctx, get_ctx
from app.errors import AppError, bad_request
from app.models import Incident, IncidentMedia, IncidentUpdate, Membership, StoredObject, Tenant, User
from app.routers.common import iso, paginate, parse_uuid, row
from app.services import audit, files, incidents, storage

router = APIRouter(prefix="/api/incidents", tags=["incidents"])
FIELDS = ["id", "reference", "category", "category_source", "description", "lat_approx", "lon_approx", "location_text",
          "location_precision", "status", "priority", "queue", "duplicate_of_id", "sla_due_at", "sla_breached", "resolved_at",
          "closed_at", "feedback_rating", "feedback_comment", "created_at", "updated_at"]
_FIXTURES = Path(__file__).resolve().parents[2] / "packs" / "fixtures.json"


def _fixture_transcripts() -> dict:
    try:
        return json.loads(_FIXTURES.read_text(encoding="utf-8")).get("audio_transcripts", {})
    except FileNotFoundError:
        return {}


@router.get("/municipalities")
def municipalities(ctx: Ctx = Depends(get_ctx)) -> dict:
    return {"items": [{"id": str(t.id), "name": t.name} for t in incidents.municipal_tenants(ctx.db)],
            "categories": list(incidents.QUEUES.keys())}


class ClassifyIn(BaseModel):
    description: str = Field(min_length=3, max_length=4000)


@router.post("/classify")
def classify(body: ClassifyIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    return classify_text(body.description)


class IncidentIn(BaseModel):
    tenant_id: str
    category: str | None = None
    description: str = Field(min_length=10, max_length=4000)
    lat: float | None = None
    lon: float | None = None
    location_text: str = Field(default="", max_length=300)
    draft_key: str | None = Field(default=None, max_length=120)


@router.post("")
def report(body: IncidentIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    if ctx.workspace != "citizen":
        raise AppError(403, "role_not_permitted", "Reports are submitted from the citizen workspace.")
    source = "reporter"
    category = body.category
    if not category:
        category = classify_text(body.description)["category"]
        source = "rules_suggestion"
    inc = incidents.create(ctx, tenant_id=parse_uuid(body.tenant_id, "tenant_id"), category=category, description=body.description,
                           lat=body.lat, lon=body.lon, location_text=body.location_text, category_source=source, draft_key=body.draft_key)
    ctx.db.commit()
    return row(inc, FIELDS)


@router.post("/{incident_id}/media")
async def add_media(incident_id: str, file: UploadFile = File(...), role: str = Form("report"), ctx: Ctx = Depends(get_ctx)) -> dict:
    inc = incidents.get_incident_for(ctx, parse_uuid(incident_id))
    is_reporter = ctx.workspace == "citizen"
    if role == "report" and not is_reporter:
        raise AppError(403, "role_not_permitted", "Only the reporter adds report media.")
    if role == "resolution_evidence" and (is_reporter or inc.assigned_user_id != ctx.user.id):
        raise AppError(403, "role_not_permitted", "Only the assigned officer adds resolution evidence.")
    if role not in ("report", "resolution_evidence"):
        raise bad_request("Unknown media role.")
    data = await file.read(16 * 1024 * 1024 + 1)
    purpose = "incident_media" if role == "report" else "resolution_evidence"
    obj = files.store_upload(ctx.db, owner_user_id=ctx.user.id, tenant_id=inc.tenant_id, purpose=purpose, filename=file.filename or "media", data=data)
    kind = "audio" if obj.mime.startswith("audio/") else ("image" if obj.mime.startswith("image/") else "document")
    m = IncidentMedia(incident_id=inc.id, object_id=obj.id, kind=kind, role=role)
    if kind == "audio":
        fx = _fixture_transcripts().get(hashlib.sha256(data).hexdigest())
        if fx:
            m.transcription_status = "fixture"
            m.transcription_text = fx
            m.analysis_note = "Demo fixture transcript matched by file hash. No speech recognition was performed."
        else:
            m.transcription_status = "unavailable"
            m.analysis_note = "Transcription is not available in this installation. The original audio is kept for staff to listen to."
    elif kind == "image":
        m.analysis_note = "Image stored as evidence. Images are not automatically analysed."
    ctx.db.add(m)
    audit.record(ctx.db, "incident.media_added", "incident", inc.id, **audit.ctx_kw(ctx), details={"kind": kind, "role": role})
    ctx.db.commit()
    return _media_out(ctx.db, m)


def _media_out(db, m: IncidentMedia) -> dict:
    o = db.get(StoredObject, m.object_id)
    return {**row(m, ["id", "kind", "role", "transcription_status", "transcription_text", "analysis_note", "created_at"]),
            "mime": o.mime, "size": o.size, "scan_status": o.scan_status, "available": o.scan_status == "clean"}


@router.get("")
def list_incidents(ctx: Ctx = Depends(get_ctx), status: str | None = None, category: str | None = None, assigned: str = "all",
                   q: str | None = None, sort: str = "-created_at", page: int = 1, page_size: int = 20) -> dict:
    if ctx.workspace == "citizen":
        stmt = select(Incident).where(Incident.reporter_user_id == ctx.user.id)
    elif ctx.workspace == "authority" and ctx.role in incidents.OFFICER_ROLES:
        stmt = select(Incident).where(Incident.tenant_id == ctx.tenant_id)
    else:
        return {"items": [], "meta": {"page": 1, "page_size": page_size, "total": 0, "pages": 1}}
    if status == "open":
        stmt = stmt.where(Incident.status.in_(("submitted", "triaged", "assigned", "in_progress")))
    elif status:
        stmt = stmt.where(Incident.status == status)
    if category:
        stmt = stmt.where(Incident.category == category)
    if assigned == "me":
        stmt = stmt.where(Incident.assigned_user_id == ctx.user.id)
    elif assigned == "unassigned":
        stmt = stmt.where(Incident.assigned_user_id.is_(None))
    if q:
        stmt = stmt.where(or_(Incident.reference.ilike(f"%{q[:60]}%"), Incident.description.ilike(f"%{q[:60]}%")))
    col = {"created_at": Incident.created_at, "sla_due_at": Incident.sla_due_at, "priority": Incident.priority}.get(sort.lstrip("-"), Incident.created_at)
    stmt = stmt.order_by(col.desc() if sort.startswith("-") else col.asc())
    items, meta = paginate(ctx.db, stmt, page, page_size)
    return {"items": [row(i, FIELDS) | {"municipality": ctx.db.get(Tenant, i.tenant_id).name} for i in items], "meta": meta}


@router.get("/{incident_id}")
def detail(incident_id: str, ctx: Ctx = Depends(get_ctx)) -> dict:
    inc = incidents.get_incident_for(ctx, parse_uuid(incident_id))
    db = ctx.db
    officer = ctx.workspace == "authority"
    ups = db.execute(select(IncidentUpdate).where(IncidentUpdate.incident_id == inc.id).order_by(IncidentUpdate.created_at)).scalars().all()
    if not officer:
        ups = [u for u in ups if u.public]
    media = db.execute(select(IncidentMedia).where(IncidentMedia.incident_id == inc.id)).scalars().all()
    out = {
        "incident": row(inc, FIELDS) | {"municipality": db.get(Tenant, inc.tenant_id).name},
        "updates": [row(u, ["id", "kind", "body", "public", "created_at", "data"]) | {"author": db.get(User, u.author_user_id).display_name if officer else None} for u in ups],
        "media": [_media_out(db, m) for m in media],
        "allowed_actions": [a for a, (froms, _to, actor) in incidents.TRANSITIONS.items() if inc.status in froms and (
            (actor in ("officer", "reporter_or_officer") and officer) or (actor == "assignee" and officer and inc.assigned_user_id == ctx.user.id)
            or (actor in ("reporter", "reporter_or_officer") and not officer))],
    }
    if officer:
        assignee = db.get(User, inc.assigned_user_id) if inc.assigned_user_id else None
        out["incident"]["assignee"] = assignee.display_name if assignee else None
        out["duplicates"] = incidents.duplicate_candidates(db, inc)
        out["officers"] = [{"user_id": str(m.user_id), "display_name": m.user.display_name} for m in db.execute(
            select(Membership).where(Membership.tenant_id == inc.tenant_id, Membership.role.in_(incidents.OFFICER_ROLES))).scalars()]
    return out


class ActionIn(BaseModel):
    action: str = Field(max_length=32)
    data: dict = Field(default_factory=dict)


@router.post("/{incident_id}/actions")
def action(incident_id: str, body: ActionIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    inc = incidents.get_incident_for(ctx, parse_uuid(incident_id))
    inc = incidents.transition(ctx, inc, body.action, body.data)
    return row(inc, FIELDS)


@router.get("/{incident_id}/media/{media_id}")
def media(incident_id: str, media_id: str, ctx: Ctx = Depends(get_ctx)) -> Response:
    inc = incidents.get_incident_for(ctx, parse_uuid(incident_id))
    m = ctx.db.get(IncidentMedia, parse_uuid(media_id))
    if m is None or m.incident_id != inc.id:
        raise AppError(404, "not_found", "Not found.")
    o = ctx.db.get(StoredObject, m.object_id)
    if o.scan_status != "clean":
        raise AppError(423, "file_not_available", f"This file is not available (scan status: {o.scan_status}).")
    audit.record(ctx.db, "incident.media_viewed", "incident", inc.id, **audit.ctx_kw(ctx))
    ctx.db.commit()
    return Response(storage.get(o.storage_key), media_type=o.mime,
                    headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'; sandbox",
                             "Cache-Control": "private, no-store", "Content-Disposition": "inline"})
