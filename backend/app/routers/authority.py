"""Smart Authority Workspace: tenant-scoped queue, request review, server-enforced actions, evidence review."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from app.db import utcnow
from app.deps import Ctx, require_workspace
from app.errors import AppError, bad_request
from app.models import (
    CaseEvent,
    ConsentGrant,
    Decision,
    Document,
    EvidenceLink,
    InformationRequest,
    Membership,
    Message,
    Procedure,
    ServiceRequest,
    User,
)
from app.routers.cases import SR_FIELDS, _evidence_out
from app.routers.common import iso, paginate, parse_uuid, row
from app.services import audit, notify, workflow
from app.services.access import document_access
from app.services.timeline import add_event

router = APIRouter(prefix="/api/authority", tags=["authority"])
authority_ctx = require_workspace("authority")


def _officer(ctx: Ctx) -> Ctx:
    if ctx.role not in workflow.OFFICER_ROLES:
        raise AppError(403, "role_not_permitted", "Officer role required.")
    return ctx


@router.get("/queue")
def queue(
    ctx: Ctx = Depends(authority_ctx),
    state: str | None = None,
    queue_name: str | None = Query(None, alias="queue"),
    assigned: str = "all",
    sla: str | None = None,
    kind: str | None = None,
    q: str | None = Query(None, max_length=100),
    sort: str = "sla_due_at",
    page: int = 1,
    page_size: int = 20,
) -> dict:
    _officer(ctx)
    stmt = select(ServiceRequest).where(ServiceRequest.tenant_id == ctx.tenant_id, ServiceRequest.state != "draft")
    if state == "open":
        stmt = stmt.where(ServiceRequest.state.in_(tuple(workflow.OPEN_STATES)))
    elif state:
        stmt = stmt.where(ServiceRequest.state == state)
    if queue_name:
        stmt = stmt.where(ServiceRequest.queue == queue_name)
    if kind:
        stmt = stmt.where(ServiceRequest.kind == kind)
    if assigned == "me":
        stmt = stmt.where(ServiceRequest.assigned_user_id == ctx.user.id)
    elif assigned == "unassigned":
        stmt = stmt.where(ServiceRequest.assigned_user_id.is_(None))
    if sla == "breached":
        stmt = stmt.where(ServiceRequest.sla_breached.is_(True))
    elif sla == "due_soon":
        stmt = stmt.where(ServiceRequest.sla_due_at < utcnow() + timedelta(days=3), ServiceRequest.sla_breached.is_(False))
    if q:
        stmt = stmt.where(or_(ServiceRequest.reference.ilike(f"%{q}%"), ServiceRequest.title.ilike(f"%{q}%")))
    cols = {"sla_due_at": ServiceRequest.sla_due_at, "submitted_at": ServiceRequest.submitted_at, "priority": ServiceRequest.priority,
            "updated_at": ServiceRequest.updated_at}
    col = cols.get(sort.lstrip("-"), ServiceRequest.sla_due_at)
    stmt = stmt.order_by(col.desc().nulls_last() if sort.startswith("-") else col.asc().nulls_last())
    items, meta = paginate(ctx.db, stmt, page, page_size)
    out = []
    for s in items:
        assignee = ctx.db.get(User, s.assigned_user_id) if s.assigned_user_id else None
        owner = ctx.db.get(User, s.case.owner_user_id)
        out.append({**row(s, SR_FIELDS), "case_reference": s.case.reference, "applicant": owner.display_name,
                    "assignee": assignee.display_name if assignee else None})
    queues = ctx.db.execute(select(ServiceRequest.queue, func.count()).where(ServiceRequest.tenant_id == ctx.tenant_id,
                            ServiceRequest.state.in_(tuple(workflow.OPEN_STATES))).group_by(ServiceRequest.queue)).all()
    return {"items": out, "meta": meta, "queues": [{"queue": qn, "open": n} for qn, n in queues]}


@router.get("/requests/{sr_id}")
def request_detail(sr_id: str, ctx: Ctx = Depends(authority_ctx)) -> dict:
    _officer(ctx)
    sr = workflow.get_request_for(ctx, parse_uuid(sr_id))
    db = ctx.db
    case = sr.case
    owner = db.get(User, case.owner_user_id)
    decisions = db.execute(select(Decision).where(Decision.service_request_id == sr.id).order_by(Decision.version)).scalars().all()
    infos = db.execute(select(InformationRequest).where(InformationRequest.service_request_id == sr.id).order_by(InformationRequest.created_at)).scalars().all()
    links = db.execute(select(EvidenceLink).where(EvidenceLink.case_id == case.id)).scalars().all()
    events = db.execute(select(CaseEvent).where(CaseEvent.case_id == case.id, or_(CaseEvent.visibility == "all", CaseEvent.visible_tenant_id == ctx.tenant_id))
                        .order_by(CaseEvent.at.desc()).limit(100)).scalars().all()
    msgs = db.execute(select(Message).where(Message.case_id == case.id).order_by(Message.created_at)).scalars().all()
    consents = db.execute(select(ConsentGrant).where(ConsentGrant.owner_user_id == case.owner_user_id,
                                                     or_(ConsentGrant.recipient_tenant_id == ctx.tenant_id, ConsentGrant.requested_by_tenant_id == ctx.tenant_id))).scalars().all()
    proc = db.get(Procedure, sr.procedure_id) if sr.procedure_id else None
    parent = db.get(ServiceRequest, sr.parent_request_id) if sr.parent_request_id else None
    officers = db.execute(select(Membership).where(Membership.tenant_id == ctx.tenant_id, Membership.role.in_(tuple(workflow.OFFICER_ROLES)))).scalars()

    def name(uid):
        u = db.get(User, uid) if uid else None
        return u.display_name if u else None

    from app.routers.consent import grant_out

    return {
        "request": {**row(sr, SR_FIELDS), "payload": sr.payload, "assignee": name(sr.assigned_user_id),
                    "assigned_user_id": iso(sr.assigned_user_id), "procedure": {"code": proc.code, "name": proc.name, "sla_working_days": proc.service.sla_working_days} if proc else None,
                    "parent_reference": parent.reference if parent else None},
        "case": {"id": str(case.id), "reference": case.reference, "title": case.title, "applicant": owner.display_name},
        "allowed_actions": workflow.allowed_actions(ctx, sr),
        "decisions": [{**row(d, ["id", "version", "outcome", "rationale", "status", "approved_at", "appeal_deadline", "supersedes_id", "is_simulated", "rule_version_ids"]),
                       "proposed_by": name(d.proposed_by), "approved_by": name(d.approved_by), "proposed_by_me": d.proposed_by == ctx.user.id} for d in decisions],
        "information_requests": [row(i, ["id", "message", "items", "due_at", "status", "response", "responded_at", "created_at"]) for i in infos],
        "evidence": _evidence_out(ctx, links),
        "consents": [grant_out(db, g) for g in consents],
        "timeline": [row(e, ["id", "at", "kind", "actor_label", "summary", "visibility"]) for e in events],
        "messages": [row(m, ["id", "sender_label", "body", "created_at", "ai_drafted"]) for m in msgs],
        "officers": [{"user_id": str(m.user_id), "display_name": m.user.display_name, "role": m.role} for m in officers],
        "notice": "Requests arrive through CivicBridge's simulated exchange. Decisions here are demo decisions, not legally binding acts.",
    }


class ActionIn(BaseModel):
    action: str = Field(max_length=32)
    data: dict = Field(default_factory=dict)


@router.post("/requests/{sr_id}/actions")
def act(sr_id: str, body: ActionIn, ctx: Ctx = Depends(authority_ctx)) -> dict:
    _officer(ctx)
    sr = workflow.get_request_for(ctx, parse_uuid(sr_id))
    sr = workflow.transition(ctx, sr, body.action, body.data)
    return {**row(sr, SR_FIELDS), "allowed_actions": workflow.allowed_actions(ctx, sr)}


class ReviewIn(BaseModel):
    status: str = Field(pattern=r"^(accepted|rejected|needs_more)$")
    note: str = Field(default="", max_length=2000)


@router.post("/evidence/{link_id}/review")
def review_evidence(link_id: str, body: ReviewIn, ctx: Ctx = Depends(authority_ctx)) -> dict:
    _officer(ctx)
    link = ctx.db.get(EvidenceLink, parse_uuid(link_id))
    if link is None or link.service_request_id is None:
        raise AppError(404, "not_found", "Evidence not found.")
    sr = workflow.get_request_for(ctx, link.service_request_id)
    doc = ctx.db.get(Document, link.document_id)
    if document_access(ctx, doc) is None:
        raise AppError(403, "consent_required", "You need the citizen's consent for this document category before reviewing it.")
    if body.status != "accepted" and len(body.note) < 5:
        raise bad_request("Explain why the evidence is not accepted.")
    link.status = body.status
    link.review_note = body.note
    link.reviewed_by = ctx.user.id
    link.reviewed_at = utcnow()
    if body.status == "accepted":
        doc.verification_status = "reviewed_by_authority_demo"
    add_event(ctx.db, sr.case_id, "evidence.reviewed", f"Evidence '{doc.title}' marked {body.status.replace('_', ' ')}" + (f": {body.note}" if body.note else ""), ctx=ctx)
    notify.notify(ctx.db, sr.case.owner_user_id, "case_update", f"Evidence reviewed on {sr.reference}", f"{doc.title}: {body.status}", f"/cases/{sr.case_id}")
    audit.record(ctx.db, "evidence.reviewed", "document", doc.id, **audit.ctx_kw(ctx), subject_user_id=doc.owner_user_id, details={"status": body.status})
    ctx.db.commit()
    return row(link, ["id", "status", "review_note", "reviewed_at"])


@router.get("/stats")
def stats(ctx: Ctx = Depends(authority_ctx)) -> dict:
    """Operational counts for the active authority tenant only."""
    _officer(ctx)
    db = ctx.db
    base = select(func.count()).select_from(ServiceRequest).where(ServiceRequest.tenant_id == ctx.tenant_id)
    open_ = db.execute(base.where(ServiceRequest.state.in_(tuple(workflow.OPEN_STATES)))).scalar_one()
    mine = db.execute(base.where(ServiceRequest.state.in_(tuple(workflow.OPEN_STATES)), ServiceRequest.assigned_user_id == ctx.user.id)).scalar_one()
    breached = db.execute(base.where(ServiceRequest.state.in_(tuple(workflow.OPEN_STATES)), ServiceRequest.sla_breached.is_(True))).scalar_one()
    unassigned = db.execute(base.where(ServiceRequest.state.in_(tuple(workflow.OPEN_STATES)), ServiceRequest.assigned_user_id.is_(None))).scalar_one()
    pending = db.execute(base.where(ServiceRequest.state == "decision_pending")).scalar_one()
    appeals = db.execute(base.where(ServiceRequest.kind == "appeal", ServiceRequest.state.in_(tuple(workflow.OPEN_STATES)))).scalar_one()
    from app.models import Incident

    inc_open = db.execute(select(func.count()).select_from(Incident).where(Incident.tenant_id == ctx.tenant_id,
                          Incident.status.in_(("submitted", "triaged", "assigned", "in_progress")))).scalar_one()
    return {"open": open_, "assigned_to_me": mine, "sla_breached": breached, "unassigned": unassigned,
            "awaiting_approval": pending, "open_appeals": appeals, "open_incidents": inc_open,
            "tenant": ctx.membership.tenant.name, "handles_incidents": bool((ctx.membership.tenant.settings or {}).get("handles_incidents"))}
