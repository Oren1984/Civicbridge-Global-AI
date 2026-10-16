"""Unified cases: list, detail, timeline, tasks, messages, evidence, service requests and export."""
from __future__ import annotations

import io
import json
import uuid
import zipfile
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from app.db import utcnow
from app.deps import Ctx, get_ctx
from app.errors import AppError, bad_request
from app.models import (
    Appeal,
    Appointment,
    Case,
    CaseEvent,
    CaseParticipant,
    Decision,
    Document,
    EvidenceLink,
    InformationRequest,
    LifeEvent,
    Meeting,
    Message,
    Procedure,
    ServiceRequest,
    Task,
    Tenant,
)
from app.routers.common import iso, paginate, parse_uuid, row
from app.services import audit, notify, storage, workflow
from app.services.access import document_access, get_case, visible_case_filter
from app.services.refs import next_ref
from app.services.timeline import add_event

router = APIRouter(prefix="/api/cases", tags=["cases"])

CASE_FIELDS = ["id", "reference", "title", "case_type", "status", "summary", "created_at", "updated_at", "version"]
TASK_FIELDS = ["id", "key", "title", "description", "phase", "status", "sort_order", "depends_on", "required_evidence",
               "due_at", "deadline_basis", "requires_human_review", "procedure_code", "completed_at"]
SR_FIELDS = ["id", "reference", "title", "kind", "state", "queue", "priority", "channel", "submitted_at", "sla_due_at",
             "sla_paused_at", "sla_breached", "escalation_level", "parent_request_id", "closed_at", "version", "tenant_id"]


def _tenant_name(db, tid) -> str | None:
    t = db.get(Tenant, tid) if tid else None
    return t.name if t else None


@router.get("")
def list_cases(
    ctx: Ctx = Depends(get_ctx),
    q: str | None = Query(None, max_length=100),
    status: str | None = None,
    case_type: str | None = None,
    sort: str = "-updated_at",
    page: int = 1,
    page_size: int = 20,
) -> dict:
    stmt = select(Case).where(visible_case_filter(ctx))
    if q:
        stmt = stmt.where(or_(Case.title.ilike(f"%{q}%"), Case.reference.ilike(f"%{q}%")))
    if status:
        stmt = stmt.where(Case.status == status)
    if case_type:
        stmt = stmt.where(Case.case_type == case_type)
    col = {"updated_at": Case.updated_at, "created_at": Case.created_at, "title": Case.title}.get(sort.lstrip("-"), Case.updated_at)
    stmt = stmt.order_by(col.desc() if sort.startswith("-") else col.asc())
    items, meta = paginate(ctx.db, stmt, page, page_size)
    out = []
    for c in items:
        tasks = ctx.db.execute(select(Task.status).where(Task.case_id == c.id)).scalars().all()
        out.append({**row(c, CASE_FIELDS), "progress": {"done": sum(1 for t in tasks if t in ("done", "skipped")), "total": len(tasks)}})
    return {"items": out, "meta": meta}


class CaseIn(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    summary: str = Field(default="", max_length=4000)
    case_type: str = Field(default="general", pattern=r"^(general|rights|incident)$")


@router.post("")
def create_case(body: CaseIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    if ctx.workspace != "citizen":
        raise AppError(403, "role_not_permitted", "Only citizens create their own cases.")
    c = Case(reference=next_ref(ctx.db, "CB"), owner_user_id=ctx.user.id, title=body.title, summary=body.summary, case_type=body.case_type)
    ctx.db.add(c)
    ctx.db.flush()
    add_event(ctx.db, c.id, "case.created", f"Case created: {c.title}", ctx=ctx)
    audit.record(ctx.db, "case.created", "case", c.id, **audit.ctx_kw(ctx), subject_user_id=ctx.user.id)
    ctx.db.commit()
    return row(c, CASE_FIELDS)


def _evidence_out(ctx: Ctx, links: list[EvidenceLink]) -> list[dict]:
    out = []
    for e in links:
        doc = ctx.db.get(Document, e.document_id)
        acc = document_access(ctx, doc) if doc else None
        cur = next((v for v in doc.versions if v.version == doc.current_version), None) if doc else None
        out.append({
            **row(e, ["id", "task_id", "service_request_id", "evidence_key", "status", "review_note", "reviewed_at"]),
            "document": {
                "id": str(doc.id), "title": doc.title, "category": doc.category, "expires_at": iso(doc.expires_at),
                "verification_status": doc.verification_status, "scan_status": cur.object.scan_status if cur else None,
                "current_version": doc.current_version,
            } if doc and acc else {"id": str(e.document_id), "restricted": True, "category": doc.category if doc else None,
                                   "note": "No active consent covers this document for your organisation."},
        })
    return out


@router.get("/{case_id}")
def case_detail(case_id: str, ctx: Ctx = Depends(get_ctx)) -> dict:
    case, acc = get_case(ctx, parse_uuid(case_id), "view_case")
    db = ctx.db
    tasks = db.execute(select(Task).where(Task.case_id == case.id).order_by(Task.sort_order)).scalars().all()
    srs = db.execute(select(ServiceRequest).where(ServiceRequest.case_id == case.id).order_by(ServiceRequest.created_at)).scalars().all()
    if acc.level in ("authority", "institution"):
        srs = [s for s in srs if s.tenant_id == ctx.tenant_id] if acc.level == "authority" else []
    req_out = []
    for s in srs:
        decisions = db.execute(select(Decision).where(Decision.service_request_id == s.id).order_by(Decision.version)).scalars().all()
        visible = [d for d in decisions if d.status in ("approved", "superseded") or acc.level == "authority"]
        infos = db.execute(select(InformationRequest).where(InformationRequest.service_request_id == s.id)).scalars().all()
        proc = db.get(Procedure, s.procedure_id) if s.procedure_id else None
        req_out.append({
            **row(s, SR_FIELDS),
            "authority": _tenant_name(db, s.tenant_id),
            "procedure": {"code": proc.code, "name": proc.name} if proc else None,
            "allowed_actions": workflow.allowed_actions(ctx, s),
            "decisions": [row(d, ["id", "version", "outcome", "rationale", "status", "approved_at", "appeal_deadline", "supersedes_id", "is_simulated"]) for d in visible],
            "information_requests": [row(i, ["id", "message", "items", "due_at", "status", "response", "responded_at"]) for i in infos],
        })
    links = db.execute(select(EvidenceLink).where(EvidenceLink.case_id == case.id)).scalars().all()
    participants = db.execute(select(CaseParticipant).where(CaseParticipant.case_id == case.id)).scalars().all()
    le = db.execute(select(LifeEvent).where(LifeEvent.case_id == case.id)).scalar_one_or_none()
    appts = db.execute(select(Appointment).where(Appointment.case_id == case.id).order_by(Appointment.starts_at)).scalars().all()
    meetings = db.execute(select(Meeting).where(Meeting.case_id == case.id).order_by(Meeting.scheduled_start)).scalars().all()
    appeals = db.execute(select(Appeal).where(Appeal.case_id == case.id)).scalars().all()
    return {
        "case": row(case, CASE_FIELDS),
        "access": {"level": acc.level, "scopes": sorted(acc.scopes)},
        "life_event": row(le, ["id", "template_code", "event_type", "target_date", "status"]) if le else None,
        "participants": [
            {**row(p, ["id", "role", "granted_via", "status", "created_at", "ended_at"]), "tenant": _tenant_name(db, p.tenant_id)}
            for p in participants
        ],
        "tasks": [row(t, TASK_FIELDS) | {"jurisdiction_id": iso(t.jurisdiction_id)} for t in tasks],
        "requests": req_out,
        "evidence": _evidence_out(ctx, links),
        "appointments": [row(a, ["id", "title", "starts_at", "duration_minutes", "organizer_timezone", "mode", "status", "meeting_id"]) for a in appts],
        "meetings": [row(m, ["id", "title", "scheduled_start", "duration_minutes", "timezone", "status"]) for m in meetings],
        "appeals": [row(a, ["id", "decision_id", "follow_up_request_id", "grounds", "status", "created_at", "resolution_decision_id"]) for a in appeals],
    }


@router.get("/{case_id}/timeline")
def timeline(case_id: str, ctx: Ctx = Depends(get_ctx), page: int = 1, page_size: int = 50) -> dict:
    case, _acc = get_case(ctx, parse_uuid(case_id), "view_case")
    stmt = select(CaseEvent).where(CaseEvent.case_id == case.id)
    if ctx.workspace == "authority":
        stmt = stmt.where(or_(CaseEvent.visibility == "all", CaseEvent.visible_tenant_id == ctx.tenant_id))
    else:
        stmt = stmt.where(CaseEvent.visibility == "all")
    items, meta = paginate(ctx.db, stmt.order_by(CaseEvent.at.desc()), page, page_size)
    return {"items": [row(e, ["id", "at", "kind", "actor_label", "summary", "data", "visibility"]) for e in items], "meta": meta}


class TaskUpdate(BaseModel):
    status: str = Field(pattern=r"^(todo|in_progress|blocked|done|skipped)$")
    expected_updated_at: datetime | None = None


@router.patch("/{case_id}/tasks/{task_id}")
def update_task(case_id: str, task_id: str, body: TaskUpdate, ctx: Ctx = Depends(get_ctx)) -> dict:
    case, acc = get_case(ctx, parse_uuid(case_id), "respond_info_requests")
    t = ctx.db.get(Task, parse_uuid(task_id))
    if t is None or t.case_id != case.id:
        raise AppError(404, "not_found", "Task not found.")
    if body.status == "done":
        tasks = {x.key: x for x in ctx.db.execute(select(Task).where(Task.case_id == case.id)).scalars()}
        blockers = [tasks[d].title for d in t.depends_on if d in tasks and tasks[d].status not in ("done", "skipped")]
        if blockers:
            raise AppError(409, "task_blocked", "Complete these first: " + "; ".join(blockers), {"blocked_by": blockers})
        t.completed_at = utcnow()
        t.completed_by = ctx.user.id
    prev = t.status
    t.status = body.status
    case.updated_at = utcnow()
    add_event(ctx.db, case.id, "task.updated", f"Task '{t.title}': {prev} → {t.status}", ctx=ctx, data={"task_id": str(t.id)})
    audit.record(ctx.db, "task.updated", "task", t.id, **audit.ctx_kw(ctx), subject_user_id=case.owner_user_id,
                 details={"from": prev, "to": t.status, "via": acc.level})
    ctx.db.commit()
    return row(t, TASK_FIELDS)


class TaskIn(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    description: str = Field(default="", max_length=2000)
    due_at: datetime | None = None


@router.post("/{case_id}/tasks")
def add_task(case_id: str, body: TaskIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    case, acc = get_case(ctx, parse_uuid(case_id))
    if acc.level != "owner":
        raise AppError(403, "role_not_permitted", "Only the case owner adds personal tasks.")
    n = len(ctx.db.execute(select(Task.id).where(Task.case_id == case.id)).all())
    t = Task(case_id=case.id, key=f"custom-{uuid.uuid4().hex[:6]}", title=body.title, description=body.description,
             due_at=body.due_at, sort_order=1000 + n, phase="personal")
    ctx.db.add(t)
    add_event(ctx.db, case.id, "task.added", f"Personal task added: {t.title}", ctx=ctx)
    ctx.db.commit()
    return row(t, TASK_FIELDS)


@router.get("/{case_id}/messages")
def messages(case_id: str, ctx: Ctx = Depends(get_ctx)) -> dict:
    case, _acc = get_case(ctx, parse_uuid(case_id), "view_case")
    rows = ctx.db.execute(select(Message).where(Message.case_id == case.id).order_by(Message.created_at)).scalars().all()
    return {"items": [row(m, ["id", "sender_label", "body", "created_at", "ai_drafted", "on_behalf_of_user_id"]) | {"mine": m.sender_user_id == ctx.user.id} for m in rows]}


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=4000)
    ai_drafted: bool = False


def post_message(ctx: Ctx, case: Case, acc, body: str, ai_drafted: bool) -> Message:
    db = ctx.db
    label = ctx.user.display_name
    if acc.level in ("authority", "institution"):
        label = f"{ctx.user.display_name} · {ctx.membership.tenant.name}"
    elif acc.level == "professional":
        label = f"{ctx.user.display_name} (authorized representative)"
    m = Message(case_id=case.id, sender_user_id=ctx.user.id, sender_tenant_id=ctx.tenant_id, sender_label=label, body=body,
                ai_drafted=ai_drafted, on_behalf_of_user_id=case.owner_user_id if acc.level == "professional" else None)
    db.add(m)
    db.flush()
    recipients = set()
    if case.owner_user_id != ctx.user.id:
        recipients.add(case.owner_user_id)
    for sr in db.execute(select(ServiceRequest).where(ServiceRequest.case_id == case.id)).scalars():
        if sr.assigned_user_id and sr.assigned_user_id != ctx.user.id and (acc.level != "authority" or sr.tenant_id == ctx.tenant_id):
            recipients.add(sr.assigned_user_id)
    for uid in recipients:
        notify.notify(db, uid, "message", f"New message on {case.reference}", body[:140], f"/cases/{case.id}")
    add_event(db, case.id, "message.sent", f"Message from {label}", ctx=ctx, actor_label=label)
    audit.record(db, "message.sent", "case", case.id, **audit.ctx_kw(ctx), subject_user_id=case.owner_user_id, details={"via": acc.level})
    return m


@router.post("/{case_id}/messages")
def send_message(case_id: str, body: MessageIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    case, acc = get_case(ctx, parse_uuid(case_id), "send_messages")
    m = post_message(ctx, case, acc, body.body, body.ai_drafted)
    ctx.db.commit()
    return row(m, ["id", "sender_label", "body", "created_at", "ai_drafted"])


class EvidenceIn(BaseModel):
    document_id: uuid.UUID
    task_id: uuid.UUID | None = None
    service_request_id: uuid.UUID | None = None
    evidence_key: str = Field(default="", max_length=64)


@router.post("/{case_id}/evidence")
def link_evidence(case_id: str, body: EvidenceIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    case, acc = get_case(ctx, parse_uuid(case_id), "upload_documents")
    doc = ctx.db.get(Document, body.document_id)
    if doc is None or doc.owner_user_id != case.owner_user_id or document_access(ctx, doc) is None:
        raise AppError(404, "not_found", "Document not found.")
    if body.task_id:
        t = ctx.db.get(Task, body.task_id)
        if t is None or t.case_id != case.id:
            raise bad_request("Task does not belong to this case.")
    if body.service_request_id:
        sr = ctx.db.get(ServiceRequest, body.service_request_id)
        if sr is None or sr.case_id != case.id:
            raise bad_request("Request does not belong to this case.")
    link = EvidenceLink(document_id=doc.id, case_id=case.id, task_id=body.task_id, service_request_id=body.service_request_id,
                        evidence_key=body.evidence_key, status="submitted" if body.service_request_id else "attached", linked_by=ctx.user.id)
    ctx.db.add(link)
    add_event(ctx.db, case.id, "evidence.linked", f"Document '{doc.title}' attached as evidence", ctx=ctx)
    audit.record(ctx.db, "evidence.linked", "document", doc.id, **audit.ctx_kw(ctx), subject_user_id=case.owner_user_id)
    ctx.db.commit()
    return row(link, ["id", "status", "evidence_key"])


class RequestIn(BaseModel):
    procedure_code: str = Field(max_length=64)
    title: str | None = Field(default=None, max_length=300)


@router.post("/{case_id}/requests")
def create_service_request(case_id: str, body: RequestIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    case, acc = get_case(ctx, parse_uuid(case_id))
    if acc.level not in ("owner", "professional") or not acc.can("send_messages"):
        raise AppError(403, "role_not_permitted", "Only the citizen or an authorized representative prepares requests.")
    proc = ctx.db.execute(select(Procedure).where(Procedure.code == body.procedure_code)).scalar_one_or_none()
    if proc is None or proc.service.authority.tenant_id is None:
        raise bad_request("Unknown procedure or the authority has no CivicBridge workspace.")
    sr = workflow.create_request(ctx, case, proc.service.authority.tenant_id, body.title or proc.name, proc.id,
                                 payload={"queue": proc.service.code})
    ctx.db.commit()
    return row(sr, SR_FIELDS)


class ActionIn(BaseModel):
    action: str = Field(max_length=32)
    data: dict = Field(default_factory=dict)


@router.post("/{case_id}/requests/{sr_id}/actions")
def citizen_action(case_id: str, sr_id: str, body: ActionIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    case, _acc = get_case(ctx, parse_uuid(case_id), "view_case")
    sr = workflow.get_request_for(ctx, parse_uuid(sr_id))
    if sr.case_id != case.id:
        raise AppError(404, "not_found", "Not found.")
    sr = workflow.transition(ctx, sr, body.action, body.data)
    return row(sr, SR_FIELDS) | {"allowed_actions": workflow.allowed_actions(ctx, sr)}


@router.get("/{case_id}/export")
def export_case(case_id: str, ctx: Ctx = Depends(get_ctx)) -> StreamingResponse:
    """Citizen export package: case record (JSON) plus clean document originals. Owner only."""
    case, acc = get_case(ctx, parse_uuid(case_id))
    if acc.level != "owner":
        raise AppError(403, "role_not_permitted", "Only the case owner can export the case package.")
    detail = case_detail(case_id, ctx)
    events = ctx.db.execute(select(CaseEvent).where(CaseEvent.case_id == case.id, CaseEvent.visibility == "all").order_by(CaseEvent.at)).scalars().all()
    msgs = ctx.db.execute(select(Message).where(Message.case_id == case.id).order_by(Message.created_at)).scalars().all()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.txt", "CivicBridge case export (synthetic demo data).\nThis package is a personal record, not an official document.\n"
                   "Documents are included only if they passed malware scanning.\n")
        z.writestr("case.json", json.dumps(detail, indent=2, default=str, ensure_ascii=False))
        z.writestr("timeline.json", json.dumps([row(e, ["at", "kind", "actor_label", "summary"]) for e in events], indent=2, ensure_ascii=False))
        z.writestr("messages.json", json.dumps([row(m, ["created_at", "sender_label", "body"]) for m in msgs], indent=2, ensure_ascii=False))
        for e in detail["evidence"]:
            d = e["document"]
            if d.get("restricted"):
                continue
            doc = ctx.db.get(Document, uuid.UUID(d["id"]))
            v = next((x for x in doc.versions if x.version == doc.current_version), None)
            if v and v.object.scan_status == "clean":
                z.writestr(f"documents/{doc.id}_{v.object.safe_filename}", storage.get(v.object.storage_key))
    audit.record(ctx.db, "case.exported", "case", case.id, **audit.ctx_kw(ctx), subject_user_id=case.owner_user_id)
    ctx.db.commit()
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="{case.reference}.zip"'})
