"""Workspace overviews (citizen, institution, professional) built only from records the context may access."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.db import utcnow
from app.deps import Ctx, get_ctx, require_workspace
from app.models import (
    Case,
    ConsentGrant,
    Delegation,
    Document,
    EmergencyNotice,
    Incident,
    InformationRequest,
    LifeEvent,
    Meeting,
    MeetingParticipant,
    Notification,
    ServiceRequest,
    Task,
    Tenant,
    Translation,
    User,
)
from app.routers.common import iso, row
from app.services.access import active_delegations, visible_case_filter

router = APIRouter(prefix="/api/overview", tags=["overview"])


def _meetings(ctx: Ctx) -> list[dict]:
    rows = ctx.db.execute(
        select(Meeting, MeetingParticipant).join(MeetingParticipant, MeetingParticipant.meeting_id == Meeting.id)
        .where(MeetingParticipant.user_id == ctx.user.id, Meeting.status.in_(("scheduled", "open")))
        .order_by(Meeting.scheduled_start).limit(5)
    ).all()
    return [{**row(m, ["id", "title", "scheduled_start", "duration_minutes", "timezone", "status"]), "my_status": p.status, "my_role": p.role} for m, p in rows]


@router.get("/citizen")
def citizen(ctx: Ctx = Depends(require_workspace("citizen"))) -> dict:
    db = ctx.db
    now = utcnow()
    my_cases = select(Case.id).where(Case.owner_user_id == ctx.user.id)
    due = db.execute(select(Task, Case).join(Case, Case.id == Task.case_id).where(Case.owner_user_id == ctx.user.id,
                     Task.status.notin_(("done", "skipped")), Task.due_at.is_not(None), Task.due_at < now + timedelta(days=45))
                     .order_by(Task.due_at).limit(8)).all()
    infos = db.execute(select(InformationRequest, ServiceRequest).join(ServiceRequest).where(ServiceRequest.case_id.in_(my_cases),
                       InformationRequest.status == "open")).all()
    pending_consents = db.execute(select(func.count()).select_from(ConsentGrant).where(ConsentGrant.owner_user_id == ctx.user.id,
                                  ConsentGrant.status == "pending")).scalar_one()
    unread = db.execute(select(func.count()).select_from(Notification).where(Notification.user_id == ctx.user.id, Notification.read_at.is_(None))).scalar_one()
    events = db.execute(select(LifeEvent, Case).join(Case, Case.id == LifeEvent.case_id).where(LifeEvent.owner_user_id == ctx.user.id)).all()
    journeys = []
    for le, c in events:
        statuses = db.execute(select(Task.status).where(Task.case_id == c.id)).scalars().all()
        journeys.append({"case_id": str(c.id), "reference": c.reference, "title": c.title, "event_type": le.event_type,
                         "target_date": iso(le.target_date), "done": sum(1 for s in statuses if s in ("done", "skipped")), "total": len(statuses)})
    open_inc = db.execute(select(Incident).where(Incident.reporter_user_id == ctx.user.id, Incident.status.notin_(("closed", "duplicate")))
                          .order_by(Incident.created_at.desc()).limit(5)).scalars().all()
    expiring = db.execute(select(Document).where(Document.owner_user_id == ctx.user.id, Document.deleted_at.is_(None),
                          Document.expires_at.is_not(None), Document.expires_at < now + timedelta(days=120)).order_by(Document.expires_at)).scalars().all()
    notices = db.execute(select(EmergencyNotice).where((EmergencyNotice.expires_at.is_(None)) | (EmergencyNotice.expires_at > now))
                         .order_by(EmergencyNotice.issued_at.desc()).limit(3)).scalars().all()
    return {
        "deadlines": [{"task_id": str(t.id), "title": t.title, "due_at": iso(t.due_at), "case_id": str(c.id), "case_reference": c.reference,
                       "overdue": t.due_at < now} for t, c in due],
        "information_requests": [{"id": str(i.id), "message": i.message, "due_at": iso(i.due_at), "request_reference": s.reference,
                                  "case_id": str(s.case_id)} for i, s in infos],
        "pending_consent_requests": pending_consents,
        "unread_notifications": unread,
        "journeys": journeys,
        "incidents": [row(i, ["id", "reference", "category", "status", "created_at"]) for i in open_inc],
        "expiring_documents": [row(d, ["id", "title", "category", "expires_at"]) for d in expiring],
        "meetings": _meetings(ctx),
        "emergency_notices": [row(n, ["id", "title", "severity", "source_label", "source_kind", "issued_at"]) for n in notices],
    }


@router.get("/institution")
def institution(ctx: Ctx = Depends(require_workspace("institution"))) -> dict:
    db = ctx.db
    cases = db.execute(select(Case).where(visible_case_filter(ctx)).order_by(Case.updated_at.desc()).limit(20)).scalars().all()
    handoffs = db.execute(select(ConsentGrant).where(ConsentGrant.recipient_tenant_id == ctx.tenant_id, ConsentGrant.handoff.is_(True))
                          .order_by(ConsentGrant.created_at.desc())).scalars().all()
    from app.routers.consent import grant_out

    return {"tenant": ctx.membership.tenant.name, "cases": [row(c, ["id", "reference", "title", "status", "updated_at"]) for c in cases],
            "handoffs": [grant_out(db, g) | {"owner": db.get(User, g.owner_user_id).display_name} for g in handoffs], "meetings": _meetings(ctx)}


@router.get("/professional")
def professional(ctx: Ctx = Depends(get_ctx)) -> dict:
    db = ctx.db
    if ctx.workspace != "professional":
        return {"delegations": [], "cases": [], "translations": [], "meetings": _meetings(ctx)}
    from app.routers.consent import deleg_out

    all_d = db.execute(select(Delegation).where(Delegation.delegate_user_id == ctx.user.id).order_by(Delegation.created_at.desc())).scalars().all()
    cases = db.execute(select(Case).where(visible_case_filter(ctx)).order_by(Case.updated_at.desc()).limit(20)).scalars().all() if ctx.role == "professional" else []
    principals = [d.principal_user_id for d in active_delegations(db, ctx.user.id, ctx.tenant_id) if "translation_review" in d.scopes]
    trs = db.execute(select(Translation).where(Translation.owner_user_id.in_(principals), Translation.status == "needs_review")).scalars().all() if principals else []
    return {"tenant": ctx.membership.tenant.name, "role": ctx.role, "delegations": [deleg_out(db, d) for d in all_d],
            "cases": [row(c, ["id", "reference", "title", "status", "updated_at"]) | {"owner": db.get(User, c.owner_user_id).display_name} for c in cases],
            "translations": [row(t, ["id", "source_lang", "target_lang", "status", "mode", "created_at"]) for t in trs], "meetings": _meetings(ctx)}


@router.get("/tenants")
def tenants(ctx: Ctx = Depends(get_ctx)) -> dict:
    rows = ctx.db.execute(select(Tenant).where(Tenant.kind.in_(("authority", "institution"))).order_by(Tenant.name)).scalars()
    return {"items": [{"id": str(t.id), "name": t.name, "kind": t.kind, "handles_incidents": bool((t.settings or {}).get("handles_incidents"))} for t in rows]}
