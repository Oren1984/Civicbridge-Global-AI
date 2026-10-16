"""Purpose-bound consent (incl. authority/institution consent requests used for interagency handoff) and delegation."""
from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from app.db import utcnow
from app.deps import Ctx, get_ctx
from app.errors import AppError, bad_request, conflict
from app.models import Case, CaseParticipant, ConsentGrant, Delegation, Document, Membership, Tenant, User
from app.routers.common import parse_uuid, row
from app.services import audit, jobs, notify, policies
from app.services.access import DELEGATION_SCOPES, case_access, ensure_participant
from app.services.timeline import add_event

router = APIRouter(prefix="/api", tags=["consent", "delegation"])
CATEGORIES = ("identity", "civil_status", "employment", "education", "financial", "housing", "health", "other")
GRANT_FIELDS = ["id", "purpose", "data_categories", "document_ids", "valid_from", "valid_until", "status", "revoked_at",
                "revoke_reason", "created_at", "case_id", "handoff", "valid_days"]


def _effective_status(g: ConsentGrant) -> str:
    if g.status == "active" and g.valid_until <= utcnow():
        return "expired"
    return g.status


def grant_out(db, g: ConsentGrant) -> dict:
    t = db.get(Tenant, g.recipient_tenant_id)
    req_t = db.get(Tenant, g.requested_by_tenant_id) if g.requested_by_tenant_id else None
    case = db.get(Case, g.case_id) if g.case_id else None
    return {**row(g, GRANT_FIELDS), "status": _effective_status(g), "recipient": {"id": str(t.id), "name": t.name, "kind": t.kind},
            "requested_by": req_t.name if req_t else None, "case_reference": case.reference if case else None}


@router.get("/consents/recipients")
def recipients(ctx: Ctx = Depends(get_ctx)) -> dict:
    rows = ctx.db.execute(select(Tenant).where(Tenant.kind.in_(("authority", "institution"))).order_by(Tenant.name)).scalars()
    return {"items": [{"id": str(t.id), "name": t.name, "kind": t.kind} for t in rows], "categories": CATEGORIES}


@router.get("/consents")
def list_consents(ctx: Ctx = Depends(get_ctx)) -> dict:
    db = ctx.db
    if ctx.workspace == "citizen":
        rows = db.execute(select(ConsentGrant).where(ConsentGrant.owner_user_id == ctx.user.id).order_by(ConsentGrant.created_at.desc())).scalars()
    elif ctx.workspace in ("authority", "institution"):
        rows = db.execute(select(ConsentGrant).where(or_(ConsentGrant.recipient_tenant_id == ctx.tenant_id,
                                                         ConsentGrant.requested_by_tenant_id == ctx.tenant_id))
                          .order_by(ConsentGrant.created_at.desc())).scalars()
    else:
        return {"items": []}
    items = []
    for g in rows:
        item = grant_out(db, g)
        if ctx.workspace != "citizen":
            owner = db.get(User, g.owner_user_id)
            item["owner"] = owner.display_name
        items.append(item)
    return {"items": items}


class ConsentIn(BaseModel):
    recipient_tenant_id: uuid.UUID
    purpose: str = Field(min_length=5, max_length=300)
    data_categories: list[str] = Field(min_length=1, max_length=8)
    document_ids: list[uuid.UUID] | None = None
    case_id: uuid.UUID | None = None
    valid_days: int = Field(ge=1, le=3650)


def _validate_grant(ctx: Ctx, body_cats: list[str], doc_ids, case_id, days: int) -> None:
    if any(c not in CATEGORIES for c in body_cats):
        raise bad_request("Unknown data category.")
    if days > int(policies.get(ctx.db, "consent_max_days")):
        raise bad_request("Consent duration exceeds the maximum allowed by policy.")
    for did in doc_ids or []:
        d = ctx.db.get(Document, did)
        if d is None or d.owner_user_id != ctx.user.id:
            raise bad_request("You can only share your own documents.")
        if d.category not in body_cats:
            raise bad_request(f"Document '{d.title}' is not in the selected categories.")
    if case_id:
        c = ctx.db.get(Case, case_id)
        if c is None or c.owner_user_id != ctx.user.id:
            raise bad_request("Unknown case.")


@router.post("/consents")
def create_consent(body: ConsentIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    if ctx.workspace != "citizen":
        raise AppError(403, "role_not_permitted", "Only the data owner grants consent.")
    t = ctx.db.get(Tenant, body.recipient_tenant_id)
    if t is None or t.kind not in ("authority", "institution"):
        raise bad_request("Choose a recipient organisation.")
    _validate_grant(ctx, body.data_categories, body.document_ids, body.case_id, body.valid_days)
    now = utcnow()
    g = ConsentGrant(owner_user_id=ctx.user.id, recipient_tenant_id=t.id, case_id=body.case_id, purpose=body.purpose,
                     data_categories=body.data_categories, document_ids=[str(d) for d in body.document_ids] if body.document_ids else None,
                     valid_from=now, valid_until=now + timedelta(days=body.valid_days), status="active", valid_days=body.valid_days)
    ctx.db.add(g)
    ctx.db.flush()
    if body.case_id:
        add_event(ctx.db, body.case_id, "consent.granted", f"Consent granted to {t.name}: {body.purpose} ({', '.join(body.data_categories)})", ctx=ctx)
    audit.record(ctx.db, "consent.granted", "consent_grant", g.id, **audit.ctx_kw(ctx), subject_user_id=ctx.user.id,
                 details={"recipient": t.slug, "categories": body.data_categories, "days": body.valid_days})
    ctx.db.commit()
    return grant_out(ctx.db, g)


class RevokeIn(BaseModel):
    reason: str = Field(default="", max_length=300)


@router.post("/consents/{grant_id}/revoke")
def revoke_consent(grant_id: str, body: RevokeIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    g = ctx.db.get(ConsentGrant, parse_uuid(grant_id))
    if g is None or g.owner_user_id != ctx.user.id or ctx.workspace != "citizen":
        raise AppError(404, "not_found", "Consent not found.")
    if g.status not in ("active", "pending"):
        raise conflict("This consent is not active.")
    g.status = "revoked"
    g.revoked_at = utcnow()
    g.revoke_reason = body.reason
    # Participation that relied on this consent (e.g. an institution handoff) ends with it.
    for p in ctx.db.execute(select(CaseParticipant).where(CaseParticipant.consent_grant_id == g.id, CaseParticipant.status == "active")).scalars():
        p.status = "ended"
        p.ended_at = utcnow()
    t = ctx.db.get(Tenant, g.recipient_tenant_id)
    if g.case_id:
        add_event(ctx.db, g.case_id, "consent.revoked", f"Consent to {t.name} revoked. Future access stops now; earlier disclosures cannot be recalled.", ctx=ctx)
    for m in ctx.db.execute(select(Membership).where(Membership.tenant_id == g.recipient_tenant_id)).scalars():
        notify.notify(ctx.db, m.user_id, "consent", "A consent grant was revoked", g.purpose, "", g.recipient_tenant_id)
    audit.record(ctx.db, "consent.revoked", "consent_grant", g.id, **audit.ctx_kw(ctx), subject_user_id=ctx.user.id, details={"recipient": t.slug})
    ctx.db.commit()
    return grant_out(ctx.db, g)


class ConsentRequestIn(BaseModel):
    case_id: uuid.UUID
    recipient_tenant_id: uuid.UUID | None = None  # default: the requesting tenant itself; set to an institution for a handoff
    purpose: str = Field(min_length=5, max_length=300)
    data_categories: list[str] = Field(min_length=1, max_length=8)
    valid_days: int = Field(default=30, ge=1, le=365)


@router.post("/consents/requests")
def request_consent(body: ConsentRequestIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    """An authority/institution asks the citizen for consent. For a handoff the recipient is another tenant.
    Nothing is shared until the citizen approves."""
    if ctx.workspace not in ("authority", "institution"):
        raise AppError(403, "role_not_permitted", "Only authorities and institutions request consent.")
    case = ctx.db.get(Case, body.case_id)
    if case is None or case_access(ctx, case) is None:
        raise AppError(404, "not_found", "Case not found.")
    if any(c not in CATEGORIES for c in body.data_categories):
        raise bad_request("Unknown data category.")
    recipient = ctx.db.get(Tenant, body.recipient_tenant_id or ctx.tenant_id)
    if recipient is None or recipient.kind not in ("authority", "institution"):
        raise bad_request("Unknown recipient organisation.")
    handoff = recipient.id != ctx.tenant_id
    now = utcnow()
    g = ConsentGrant(owner_user_id=case.owner_user_id, recipient_tenant_id=recipient.id, case_id=case.id, purpose=body.purpose,
                     data_categories=body.data_categories, valid_from=now, valid_until=now + timedelta(days=body.valid_days),
                     status="pending", requested_by_user_id=ctx.user.id, requested_by_tenant_id=ctx.tenant_id, handoff=handoff,
                     valid_days=body.valid_days)
    ctx.db.add(g)
    ctx.db.flush()
    kind = "handoff to " + recipient.name if handoff else "access by " + recipient.name
    add_event(ctx.db, case.id, "consent.requested", f"{ctx.membership.tenant.name} requested your consent for {kind}: {body.purpose}", ctx=ctx)
    notify.notify(ctx.db, case.owner_user_id, "consent", f"Consent requested: {kind}", body.purpose, "/consent")
    audit.record(ctx.db, "consent.requested", "consent_grant", g.id, **audit.ctx_kw(ctx), subject_user_id=case.owner_user_id,
                 details={"recipient": recipient.slug, "handoff": handoff})
    ctx.db.commit()
    return grant_out(ctx.db, g)


@router.post("/consents/{grant_id}/approve")
def approve_consent(grant_id: str, ctx: Ctx = Depends(get_ctx)) -> dict:
    g = ctx.db.get(ConsentGrant, parse_uuid(grant_id))
    if g is None or g.owner_user_id != ctx.user.id or ctx.workspace != "citizen":
        raise AppError(404, "not_found", "Consent request not found.")
    if g.status != "pending":
        raise conflict("This request is no longer pending.")
    now = utcnow()
    g.status = "active"
    g.valid_from = now
    g.valid_until = now + timedelta(days=g.valid_days)
    t = ctx.db.get(Tenant, g.recipient_tenant_id)
    if g.case_id and g.handoff:
        case = ctx.db.get(Case, g.case_id)
        ensure_participant(ctx.db, case, t.id, t.kind if t.kind in ("authority", "institution") else "institution", "handoff", consent_grant_id=g.id)
        add_event(ctx.db, case.id, "handoff.approved", f"You approved the handoff to {t.name}. They can now see this case and the consented document categories.", ctx=ctx)
    elif g.case_id:
        add_event(ctx.db, g.case_id, "consent.granted", f"Consent granted to {t.name}: {g.purpose}", ctx=ctx)
    for m in ctx.db.execute(select(Membership).where(Membership.tenant_id.in_([g.recipient_tenant_id, g.requested_by_tenant_id]))).scalars():
        notify.notify(ctx.db, m.user_id, "consent", "Consent approved by the citizen", g.purpose, f"/cases/{g.case_id}" if g.case_id else "", m.tenant_id)
    audit.record(ctx.db, "consent.approved", "consent_grant", g.id, **audit.ctx_kw(ctx), subject_user_id=ctx.user.id,
                 details={"recipient": t.slug, "handoff": g.handoff})
    ctx.db.commit()
    return grant_out(ctx.db, g)


@router.post("/consents/{grant_id}/decline")
def decline_consent(grant_id: str, ctx: Ctx = Depends(get_ctx)) -> dict:
    g = ctx.db.get(ConsentGrant, parse_uuid(grant_id))
    if g is None or g.owner_user_id != ctx.user.id or ctx.workspace != "citizen" or g.status != "pending":
        raise AppError(404, "not_found", "Consent request not found.")
    g.status = "declined"
    if g.case_id:
        add_event(ctx.db, g.case_id, "consent.declined", "You declined a consent request.", ctx=ctx)
    audit.record(ctx.db, "consent.declined", "consent_grant", g.id, **audit.ctx_kw(ctx), subject_user_id=ctx.user.id)
    ctx.db.commit()
    return grant_out(ctx.db, g)


# ------------------------------------------------------------------ delegation

DELEG_FIELDS = ["id", "scopes", "document_categories", "purpose", "valid_from", "valid_until", "status", "revoked_at", "case_id", "created_at"]


def _deleg_status(d: Delegation) -> str:
    return "expired" if d.status == "active" and d.valid_until <= utcnow() else d.status


def deleg_out(db, d: Delegation) -> dict:
    principal, delegate = db.get(User, d.principal_user_id), db.get(User, d.delegate_user_id)
    t = db.get(Tenant, d.delegate_tenant_id)
    case = db.get(Case, d.case_id) if d.case_id else None
    return {**row(d, DELEG_FIELDS), "status": _deleg_status(d), "principal": {"id": str(principal.id), "display_name": principal.display_name},
            "delegate": {"id": str(delegate.id), "display_name": delegate.display_name}, "organisation": t.name,
            "case_reference": case.reference if case else None}


@router.get("/delegations/professionals")
def professionals(ctx: Ctx = Depends(get_ctx)) -> dict:
    rows = ctx.db.execute(select(Membership).where(Membership.role == "professional", Membership.is_active)).scalars()
    return {"items": [{"user_id": str(m.user_id), "tenant_id": str(m.tenant_id), "display_name": m.user.display_name,
                       "organisation": m.tenant.name} for m in rows], "scopes": DELEGATION_SCOPES, "categories": CATEGORIES}


@router.get("/delegations")
def list_delegations(ctx: Ctx = Depends(get_ctx)) -> dict:
    if ctx.workspace == "citizen":
        q = select(Delegation).where(Delegation.principal_user_id == ctx.user.id)
    elif ctx.workspace == "professional":
        q = select(Delegation).where(Delegation.delegate_user_id == ctx.user.id, Delegation.delegate_tenant_id == ctx.tenant_id)
    else:
        return {"items": []}
    return {"items": [deleg_out(ctx.db, d) for d in ctx.db.execute(q.order_by(Delegation.created_at.desc())).scalars()]}


class DelegationIn(BaseModel):
    delegate_user_id: uuid.UUID
    delegate_tenant_id: uuid.UUID
    case_id: uuid.UUID | None = None
    scopes: list[str] = Field(min_length=1, max_length=len(DELEGATION_SCOPES))
    document_categories: list[str] = Field(default_factory=list, max_length=8)
    purpose: str = Field(min_length=5, max_length=300)
    valid_days: int = Field(ge=1, le=3650)


@router.post("/delegations")
def create_delegation(body: DelegationIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    if ctx.workspace != "citizen":
        raise AppError(403, "role_not_permitted", "Only citizens delegate access to their own records.")
    if any(s not in DELEGATION_SCOPES for s in body.scopes) or any(c not in CATEGORIES for c in body.document_categories):
        raise bad_request("Unknown scope or category.")
    if "view_case" not in body.scopes:
        raise bad_request("A delegation must include 'view_case'.")
    if body.valid_days > int(policies.get(ctx.db, "delegation_max_days")):
        raise bad_request("Delegation duration exceeds the maximum allowed by policy.")
    m = ctx.db.execute(select(Membership).where(Membership.user_id == body.delegate_user_id, Membership.tenant_id == body.delegate_tenant_id,
                                                Membership.role == "professional")).scalar_one_or_none()
    if m is None:
        raise bad_request("The delegate must be a registered professional in that organisation.")
    if body.case_id:
        c = ctx.db.get(Case, body.case_id)
        if c is None or c.owner_user_id != ctx.user.id:
            raise bad_request("Unknown case.")
    now = utcnow()
    d = Delegation(principal_user_id=ctx.user.id, delegate_user_id=m.user_id, delegate_tenant_id=m.tenant_id, case_id=body.case_id,
                   scopes=body.scopes, document_categories=body.document_categories, purpose=body.purpose, valid_from=now,
                   valid_until=now + timedelta(days=body.valid_days), status="active")
    ctx.db.add(d)
    ctx.db.flush()
    if body.case_id:
        add_event(ctx.db, body.case_id, "delegation.granted", f"Delegated access granted to {m.user.display_name} ({m.tenant.name}) until "
                  f"{d.valid_until.date().isoformat()}: {', '.join(body.scopes)}", ctx=ctx)
    notify.notify(ctx.db, m.user_id, "delegation", f"New delegation from {ctx.user.display_name}", body.purpose, "/professional", m.tenant_id)
    jobs.enqueue(ctx.db, "send_email_raw", {"to": m.user.email, "subject": "You have a new delegated case",
                                             "body": f"{ctx.user.display_name} delegated time-limited access to you until {d.valid_until.date()}.\nScopes: {', '.join(body.scopes)}"})
    audit.record(ctx.db, "delegation.granted", "delegation", d.id, **audit.ctx_kw(ctx), subject_user_id=ctx.user.id,
                 details={"scopes": body.scopes, "days": body.valid_days})
    ctx.db.commit()
    return deleg_out(ctx.db, d)


@router.post("/delegations/{deleg_id}/revoke")
def revoke_delegation(deleg_id: str, ctx: Ctx = Depends(get_ctx)) -> dict:
    d = ctx.db.get(Delegation, parse_uuid(deleg_id))
    if d is None or ctx.workspace != "citizen" or d.principal_user_id != ctx.user.id:
        raise AppError(404, "not_found", "Delegation not found.")
    if d.status != "active":
        raise conflict("This delegation is not active.")
    d.status = "revoked"
    d.revoked_at = utcnow()
    if d.case_id:
        add_event(ctx.db, d.case_id, "delegation.revoked", "Delegated access revoked. The representative can no longer open this case.", ctx=ctx)
    notify.notify(ctx.db, d.delegate_user_id, "delegation", "A delegation was revoked", d.purpose, "/professional", d.delegate_tenant_id)
    audit.record(ctx.db, "delegation.revoked", "delegation", d.id, **audit.ctx_kw(ctx), subject_user_id=ctx.user.id)
    ctx.db.commit()
    return deleg_out(ctx.db, d)
