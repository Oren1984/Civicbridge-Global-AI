"""Video consultation endpoints. Media flows over LiveKit; this API owns authorization and lifecycle."""
from __future__ import annotations

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo, available_timezones

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Ctx, get_ctx
from app.errors import AppError, bad_request
from app.models import Appointment, Case, Document, Meeting, MeetingParticipant, MeetingSharedDocument, User
from app.routers.common import iso, parse_uuid, row
from app.services import audit, meetings, storage
from app.services.access import case_access, document_access, receipt, require_clean

router = APIRouter(prefix="/api/meetings", tags=["meetings"])
_TZS = available_timezones()
M_FIELDS = ["id", "case_id", "title", "scheduled_start", "duration_minutes", "timezone", "status", "recording_enabled", "opened_at", "ended_at"]
P_FIELDS = ["id", "role", "display_name", "status", "invite_expires_at", "admitted_at", "removed_at", "identity"]


@router.get("")
def my_meetings(ctx: Ctx = Depends(get_ctx)) -> dict:
    rows = ctx.db.execute(select(Meeting, MeetingParticipant).join(MeetingParticipant, MeetingParticipant.meeting_id == Meeting.id)
                          .where(MeetingParticipant.user_id == ctx.user.id).order_by(Meeting.scheduled_start.desc()).limit(50)).all()
    return {"items": [row(m, M_FIELDS) | {"my_role": p.role, "my_status": p.status, "host": m.host_user_id == ctx.user.id} for m, p in rows]}


@router.get("/candidates")
def candidates(case_id: str, ctx: Ctx = Depends(get_ctx)) -> dict:
    case = ctx.db.get(Case, parse_uuid(case_id))
    if case is None or case_access(ctx, case) is None:
        raise AppError(404, "not_found", "Case not found.")
    return {"items": meetings.candidate_invitees(ctx, case)}


class Invitee(BaseModel):
    user_id: uuid.UUID
    role: str = Field(pattern=r"^(citizen|authority|institution|professional|interpreter)$")


class CreateIn(BaseModel):
    case_id: uuid.UUID
    title: str = Field(min_length=3, max_length=300)
    starts_at_local: datetime  # wall-clock time in `timezone`
    timezone: str = Field(max_length=64)
    duration_minutes: int = 30
    invitees: list[Invitee] = Field(default_factory=list, max_length=10)


@router.post("")
def create(body: CreateIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    if body.timezone not in _TZS:
        raise bad_request("Unknown time zone.")
    local = body.starts_at_local.replace(tzinfo=ZoneInfo(body.timezone)) if body.starts_at_local.tzinfo is None else body.starts_at_local
    m = meetings.create(ctx, body.case_id, body.title, local.astimezone(ZoneInfo("UTC")), body.duration_minutes, body.timezone,
                        [i.model_dump(mode="json") for i in body.invitees])
    ctx.db.add(Appointment(case_id=m.case_id, title=m.title, starts_at=m.scheduled_start, duration_minutes=m.duration_minutes,
                           organizer_timezone=m.timezone, organizer_user_id=ctx.user.id, organizer_tenant_id=ctx.tenant_id, mode="video", meeting_id=m.id))
    ctx.db.commit()
    return row(m, M_FIELDS)


def _view(ctx: Ctx, m: Meeting, me: MeetingParticipant) -> dict:
    db = ctx.db
    host = m.host_user_id == ctx.user.id
    parts = db.execute(select(MeetingParticipant).where(MeetingParticipant.meeting_id == m.id).order_by(MeetingParticipant.created_at)).scalars().all()
    shared = []
    for s in db.execute(select(MeetingSharedDocument).where(MeetingSharedDocument.meeting_id == m.id, MeetingSharedDocument.active)).scalars():
        doc = db.get(Document, s.document_id)
        acc = document_access(ctx, doc) if doc else None
        shared.append({"document_id": str(s.document_id), "title": doc.title if acc else None, "category": doc.category if doc else None,
                       "can_view": acc is not None, "shared_by_me": s.shared_by == ctx.user.id,
                       "reason": None if acc else "Shared in the meeting, but no consent or delegation covers it for you."})
    case = db.get(Case, m.case_id)
    return {
        "meeting": row(m, M_FIELDS) | {"case_reference": case.reference},
        "me": row(me, P_FIELDS) | {"is_host": host},
        "participants": [row(p, P_FIELDS) for p in parts] if (host or me.status == "admitted") else [],
        "waiting": [row(p, P_FIELDS) for p in parts if p.status == "waiting"] if host else [],
        "shared_documents": shared,
        "recording": "disabled",
    }


@router.get("/{mid}")
def get_meeting(mid: str, ctx: Ctx = Depends(get_ctx)) -> dict:
    m, me = meetings.get_for(ctx, parse_uuid(mid))
    return _view(ctx, m, me)


@router.post("/{mid}/open")
def open_meeting(mid: str, ctx: Ctx = Depends(get_ctx)) -> dict:
    m, me = meetings.get_for(ctx, parse_uuid(mid))
    meetings.open_meeting(ctx, m, me)
    return _view(ctx, m, me)


@router.post("/{mid}/join")
def join(mid: str, ctx: Ctx = Depends(get_ctx)) -> dict:
    m, me = meetings.get_for(ctx, parse_uuid(mid))
    meetings.request_join(ctx, m, me)
    return _view(ctx, m, me)


@router.post("/{mid}/token")
def token(mid: str, ctx: Ctx = Depends(get_ctx)) -> dict:
    m, me = meetings.get_for(ctx, parse_uuid(mid))
    return meetings.issue_token(ctx, m, me)


@router.post("/{mid}/participants/{pid}/admit")
def admit(mid: str, pid: str, ctx: Ctx = Depends(get_ctx)) -> dict:
    m, me = meetings.get_for(ctx, parse_uuid(mid))
    meetings.admit(ctx, m, me, parse_uuid(pid))
    return _view(ctx, m, me)


@router.post("/{mid}/participants/{pid}/remove")
def remove(mid: str, pid: str, ctx: Ctx = Depends(get_ctx)) -> dict:
    m, me = meetings.get_for(ctx, parse_uuid(mid))
    meetings.remove(ctx, m, me, parse_uuid(pid))
    return _view(ctx, m, me)


@router.post("/{mid}/leave")
def leave(mid: str, ctx: Ctx = Depends(get_ctx)) -> dict:
    m, me = meetings.get_for(ctx, parse_uuid(mid))
    meetings.leave(ctx, m, me)
    return _view(ctx, m, me)


@router.post("/{mid}/end")
def end(mid: str, ctx: Ctx = Depends(get_ctx)) -> dict:
    m, me = meetings.get_for(ctx, parse_uuid(mid))
    meetings.end(ctx, m, me)
    return _view(ctx, m, me)


@router.get("/{mid}/room-check")
def room_check(mid: str, ctx: Ctx = Depends(get_ctx)) -> dict:
    """Host-only diagnostic: identities actually connected to the media server vs. admitted participants."""
    m, me = meetings.get_for(ctx, parse_uuid(mid))
    if m.host_user_id != ctx.user.id:
        raise AppError(403, "host_only", "Only the host can do this.")
    connected = meetings.room_participants(m) if m.status == "open" else []
    admitted = [p.identity for p in ctx.db.execute(select(MeetingParticipant).where(MeetingParticipant.meeting_id == m.id,
                                                                                   MeetingParticipant.status == "admitted")).scalars()]
    return {"connected": connected, "admitted": admitted, "unauthorized_connected": [i for i in connected if i not in admitted]}


class ShareIn(BaseModel):
    document_id: uuid.UUID


@router.post("/{mid}/share")
def share(mid: str, body: ShareIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    m, me = meetings.get_for(ctx, parse_uuid(mid))
    if me.status != "admitted" or m.status != "open":
        raise AppError(409, "not_in_meeting", "Join the meeting to share documents.")
    doc = ctx.db.get(Document, body.document_id)
    acc = document_access(ctx, doc) if doc else None
    if doc is None or acc is None or doc.owner_user_id != ctx.db.get(Case, m.case_id).owner_user_id:
        raise AppError(404, "not_found", "Document not found.")
    existing = ctx.db.execute(select(MeetingSharedDocument).where(MeetingSharedDocument.meeting_id == m.id,
                                                                 MeetingSharedDocument.document_id == doc.id)).scalar_one_or_none()
    if existing:
        existing.active = True
    else:
        ctx.db.add(MeetingSharedDocument(meeting_id=m.id, document_id=doc.id, shared_by=ctx.user.id))
    audit.record(ctx.db, "meeting.document_shared", "meeting", m.id, **audit.ctx_kw(ctx), subject_user_id=doc.owner_user_id,
                 details={"document": str(doc.id)})
    ctx.db.commit()
    return _view(ctx, m, me)


@router.get("/{mid}/shared/{doc_id}/preview")
def shared_preview(mid: str, doc_id: str, ctx: Ctx = Depends(get_ctx)) -> Response:
    """Each viewer is authorized individually: meeting membership never replaces consent or delegation."""
    m, me = meetings.get_for(ctx, parse_uuid(mid))
    did = parse_uuid(doc_id)
    shared = ctx.db.execute(select(MeetingSharedDocument).where(MeetingSharedDocument.meeting_id == m.id, MeetingSharedDocument.document_id == did,
                                                               MeetingSharedDocument.active)).scalar_one_or_none()
    doc = ctx.db.get(Document, did)
    acc = document_access(ctx, doc) if doc else None
    if shared is None or me.status != "admitted" or acc is None:
        audit.record_now("meeting.shared_document_denied", "meeting", m.id, actor_user_id=ctx.user.id, actor_tenant_id=ctx.tenant_id,
                         actor_role=ctx.role, outcome="denied", details={"document": str(did)})
        raise AppError(403, "document_not_authorized", "You are not authorized to view this document, even in the meeting.")
    v = next(x for x in doc.versions if x.version == doc.current_version)
    require_clean(v)
    receipt(ctx, doc, acc, "meeting_view")
    audit.record(ctx.db, "meeting.shared_document_viewed", "meeting", m.id, **audit.ctx_kw(ctx), subject_user_id=doc.owner_user_id)
    ctx.db.commit()
    mime = "text/plain; charset=utf-8" if v.object.mime == "text/plain" else v.object.mime
    return Response(storage.get(v.object.storage_key), media_type=mime,
                    headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'; img-src 'self'; sandbox",
                             "Cache-Control": "private, no-store", "Content-Disposition": "inline"})


@router.post("/livekit/webhook", include_in_schema=False)
async def webhook(request: Request, db: Session = Depends(get_db)) -> dict:
    body = (await request.body()).decode()
    try:
        return meetings.handle_webhook(db, body, request.headers.get("authorization", ""))
    except Exception as exc:  # noqa: BLE001
        raise AppError(401, "invalid_webhook", "Webhook signature invalid.") from exc
