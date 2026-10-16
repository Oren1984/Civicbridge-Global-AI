"""Governance workspace: policies, audit integrity, risks, security/privacy incidents, integrations, jobs, data quality,
aggregate reporting. Governance roles never receive citizens' document contents or case narratives."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.db import utcnow
from app.deps import Ctx, require_roles, require_workspace
from app.errors import AppError, bad_request
from app.models import (
    AIToolCall,
    AuditEvent,
    ConsentGrant,
    Delegation,
    Document,
    IntegrationAdapter,
    IntegrationRun,
    Job,
    JurisdictionPack,
    Membership,
    Risk,
    RuleVersion,
    SecurityIncident,
    SourceRecord,
    StoredObject,
    Task,
    Tenant,
    WorkerHeartbeat,
)
from app.models.identity import ROLE_WORKSPACE
from app.routers.common import iso, paginate, parse_uuid, row
from app.services import analytics, audit, integrations, policies, scanner, storage

router = APIRouter(prefix="/api/governance", tags=["governance"])
gov = require_workspace("governance")
admin = require_roles("governance_admin")


@router.get("/overview")
def overview(ctx: Ctx = Depends(gov)) -> dict:
    db = ctx.db
    by_ws: dict = {}
    for role, n in db.execute(select(Membership.role, func.count()).group_by(Membership.role)).all():
        ws = ROLE_WORKSPACE.get(role, "other")
        by_ws[ws] = by_ws.get(ws, 0) + n
    today = date.today()
    head = db.execute(select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(1)).scalar_one_or_none()
    return {
        "memberships_by_workspace": by_ws,
        "tenants": db.execute(select(func.count()).select_from(Tenant)).scalar_one(),
        "open_security_incidents": db.execute(select(func.count()).select_from(SecurityIncident).where(SecurityIncident.status != "closed")).scalar_one(),
        "open_risks": db.execute(select(func.count()).select_from(Risk).where(Risk.status != "closed")).scalar_one(),
        "adapters": [row(a, ["code", "name", "state", "health_status"]) for a in db.execute(select(IntegrationAdapter)).scalars()],
        "jobs": {s: n for s, n in db.execute(select(Job.status, func.count()).group_by(Job.status)).all()},
        "audit": {"events": head.seq if head else 0, "head_hash": head.hash if head else None, "last_at": iso(head.at) if head else None},
        "rule_versions_past_review": db.execute(select(func.count()).select_from(RuleVersion).where(RuleVersion.review_date < today)).scalar_one(),
        "quarantined_files": db.execute(select(func.count()).select_from(StoredObject).where(StoredObject.scan_status.in_(("infected", "scan_unavailable", "error", "pending")),
                                                                                        StoredObject.deleted_at.is_(None))).scalar_one(),
        "ai_mode": policies.get(db, "ai_mode"),
    }


@router.get("/audit")
def audit_events(ctx: Ctx = Depends(gov), action: str | None = Query(None, max_length=80), outcome: str | None = None,
                 resource_type: str | None = None, page: int = 1, page_size: int = 50) -> dict:
    stmt = select(AuditEvent)
    if action:
        stmt = stmt.where(AuditEvent.action.ilike(f"{action}%"))
    if outcome:
        stmt = stmt.where(AuditEvent.outcome == outcome)
    if resource_type:
        stmt = stmt.where(AuditEvent.resource_type == resource_type)
    items, meta = paginate(ctx.db, stmt.order_by(AuditEvent.seq.desc()), page, page_size)
    audit.record(ctx.db, "governance.audit_viewed", "audit", None, **audit.ctx_kw(ctx), details={"page": page})
    ctx.db.commit()
    # Metadata only: subject identities are pseudonymised for governance viewers.
    return {"items": [{**row(e, ["seq", "at", "action", "resource_type", "resource_id", "outcome", "details", "actor_role", "hash", "prev_hash"]),
                       "actor": str(e.actor_user_id)[:8] if e.actor_user_id else "system",
                       "subject": ("subj-" + str(e.subject_user_id)[:8]) if e.subject_user_id else None} for e in items], "meta": meta}


@router.post("/audit/verify")
def verify(ctx: Ctx = Depends(gov)) -> dict:
    res = audit.verify_chain(ctx.db)
    audit.record(ctx.db, "governance.audit_verified", "audit", None, **audit.ctx_kw(ctx), outcome="success" if res["ok"] else "error",
                 details={"checked": res["checked"], "ok": res["ok"]})
    ctx.db.commit()
    return res | {"scope": "Tamper-evident hash chain. Detects modification, deletion or reordering of events. "
                           "It cannot prevent a database superuser from rewriting the whole chain; compare the head hash with an external anchor."}


@router.get("/policies")
def get_policies(ctx: Ctx = Depends(gov)) -> dict:
    return {"items": policies.all_policies(ctx.db)}


class PolicyIn(BaseModel):
    value: bool | int | float | str


@router.put("/policies/{key}")
def put_policy(key: str, body: PolicyIn, ctx: Ctx = Depends(admin)) -> dict:
    if key not in policies.DEFAULTS:
        raise AppError(404, "not_found", "Unknown policy.")
    if policies.DEFAULTS[key][2]:
        raise AppError(409, "policy_locked", "This policy is locked in this installation.")
    v = body.value
    if key == "ai_mode" and v not in ("rules", "mock", "ollama"):
        raise bad_request("ai_mode must be rules, mock or ollama.")
    if key != "ai_mode" and not isinstance(v, (int, float)):
        raise bad_request("Numeric value expected.")
    if isinstance(v, (int, float)) and (v < 1 or v > 100000):
        raise bad_request("Value out of range.")
    old = policies.get(ctx.db, key)
    policies.set_policy(ctx.db, key, v, ctx.user.id)
    audit.record(ctx.db, "governance.policy_changed", "policy", key, **audit.ctx_kw(ctx), details={"from": str(old), "to": str(v)})
    ctx.db.commit()
    return {"items": policies.all_policies(ctx.db)}


R_FIELDS = ["id", "title", "description", "category", "likelihood", "impact", "owner", "status", "mitigation", "created_at", "updated_at"]


@router.get("/risks")
def risks(ctx: Ctx = Depends(gov)) -> dict:
    rows = ctx.db.execute(select(Risk).order_by((Risk.likelihood * Risk.impact).desc())).scalars()
    return {"items": [row(r, R_FIELDS) | {"score": r.likelihood * r.impact} for r in rows]}


class RiskIn(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    description: str = Field(default="", max_length=4000)
    category: str = Field(default="operational", max_length=32)
    likelihood: int = Field(ge=1, le=5)
    impact: int = Field(ge=1, le=5)
    owner: str = Field(default="", max_length=200)
    status: str = Field(default="open", pattern=r"^(open|mitigating|accepted|closed)$")
    mitigation: str = Field(default="", max_length=4000)


@router.post("/risks")
def add_risk(body: RiskIn, ctx: Ctx = Depends(admin)) -> dict:
    r = Risk(**body.model_dump())
    ctx.db.add(r)
    ctx.db.flush()
    audit.record(ctx.db, "governance.risk_created", "risk", r.id, **audit.ctx_kw(ctx))
    ctx.db.commit()
    return row(r, R_FIELDS)


@router.put("/risks/{rid}")
def edit_risk(rid: str, body: RiskIn, ctx: Ctx = Depends(admin)) -> dict:
    r = ctx.db.get(Risk, parse_uuid(rid))
    if r is None:
        raise AppError(404, "not_found", "Risk not found.")
    for k, v in body.model_dump().items():
        setattr(r, k, v)
    audit.record(ctx.db, "governance.risk_updated", "risk", r.id, **audit.ctx_kw(ctx), details={"status": r.status})
    ctx.db.commit()
    return row(r, R_FIELDS)


SI_FIELDS = ["id", "title", "kind", "severity", "status", "description", "detected_at", "personal_data_involved", "notification_due_at", "timeline", "created_at"]
SI_FLOW = {"open": {"triaged"}, "triaged": {"contained"}, "contained": {"notified", "closed"}, "notified": {"closed"}}


@router.get("/security-incidents")
def security_incidents(ctx: Ctx = Depends(gov)) -> dict:
    rows = ctx.db.execute(select(SecurityIncident).order_by(SecurityIncident.detected_at.desc())).scalars()
    return {"items": [row(s, SI_FIELDS) for s in rows]}


class SIIn(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    kind: str = Field(pattern=r"^(security|privacy_breach|availability|integrity)$")
    severity: str = Field(pattern=r"^(low|medium|high|critical)$")
    description: str = Field(default="", max_length=4000)
    personal_data_involved: bool = False


@router.post("/security-incidents")
def open_si(body: SIIn, ctx: Ctx = Depends(admin)) -> dict:
    now = utcnow()
    hours = int(policies.get(ctx.db, "breach_notification_hours"))
    s = SecurityIncident(**body.model_dump(), detected_at=now, reported_by=ctx.user.id,
                         notification_due_at=now + timedelta(hours=hours) if body.personal_data_involved else None,
                         timeline=[{"at": now.isoformat(), "status": "open", "note": "Incident recorded."}])
    ctx.db.add(s)
    ctx.db.flush()
    audit.record(ctx.db, "governance.security_incident_opened", "security_incident", s.id, **audit.ctx_kw(ctx), details={"severity": s.severity, "kind": s.kind})
    ctx.db.commit()
    return row(s, SI_FIELDS)


class SIStep(BaseModel):
    status: str
    note: str = Field(min_length=3, max_length=2000)


@router.post("/security-incidents/{sid}/advance")
def advance_si(sid: str, body: SIStep, ctx: Ctx = Depends(admin)) -> dict:
    s = ctx.db.get(SecurityIncident, parse_uuid(sid))
    if s is None:
        raise AppError(404, "not_found", "Not found.")
    if body.status not in SI_FLOW.get(s.status, set()):
        raise AppError(409, "invalid_transition", f"Cannot move from {s.status} to {body.status}.")
    if body.status == "closed" and s.personal_data_involved and s.status != "notified":
        raise AppError(409, "notification_required", "Record the notification decision (status 'notified') before closing a personal-data breach.")
    s.status = body.status
    s.timeline = [*s.timeline, {"at": utcnow().isoformat(), "status": body.status, "note": body.note}]
    audit.record(ctx.db, "governance.security_incident_advanced", "security_incident", s.id, **audit.ctx_kw(ctx), details={"status": body.status})
    ctx.db.commit()
    return row(s, SI_FIELDS)


A_FIELDS = ["id", "code", "name", "jurisdiction_code", "state", "capabilities", "description", "health_status", "last_check_at",
            "last_error", "timeout_ms", "max_retries", "enabled", "failure_injection"]


@router.get("/integrations")
def adapters(ctx: Ctx = Depends(gov)) -> dict:
    out = []
    for a in ctx.db.execute(select(IntegrationAdapter).order_by(IntegrationAdapter.code)).scalars():
        runs = ctx.db.execute(select(IntegrationRun.status, func.count()).where(IntegrationRun.adapter_id == a.id).group_by(IntegrationRun.status)).all()
        out.append(row(a, A_FIELDS) | {"runs": {s: n for s, n in runs}})
    return {"items": out, "states": {"mock": "Synthetic in-process gateway", "public_data": "Reads bundled public reference snapshot",
                                     "sandbox": "Real HTTP round-trip to a local sandbox", "authorized_live": "None configured in this installation"}}


@router.post("/integrations/{aid}/check")
def check(aid: str, ctx: Ctx = Depends(gov)) -> dict:
    a = ctx.db.get(IntegrationAdapter, parse_uuid(aid))
    if a is None:
        raise AppError(404, "not_found", "Not found.")
    integrations.health_check(ctx.db, a)
    return row(a, A_FIELDS)


class AdapterPatch(BaseModel):
    enabled: bool | None = None
    failure_injection: str | None = Field(default=None, pattern=r"^(none|timeout|error)$")


@router.patch("/integrations/{aid}")
def patch_adapter(aid: str, body: AdapterPatch, ctx: Ctx = Depends(admin)) -> dict:
    a = ctx.db.get(IntegrationAdapter, parse_uuid(aid))
    if a is None:
        raise AppError(404, "not_found", "Not found.")
    if body.enabled is not None:
        a.enabled = body.enabled
    if body.failure_injection is not None:
        a.failure_injection = body.failure_injection
    audit.record(ctx.db, "governance.adapter_changed", "integration_adapter", a.id, **audit.ctx_kw(ctx),
                 details={"enabled": a.enabled, "failure_injection": a.failure_injection})
    ctx.db.commit()
    return row(a, A_FIELDS)


@router.get("/jobs")
def jobs_list(ctx: Ctx = Depends(gov), status: str | None = None, page: int = 1, page_size: int = 30) -> dict:
    stmt = select(Job)
    if status:
        stmt = stmt.where(Job.status == status)
    items, meta = paginate(ctx.db, stmt.order_by(Job.created_at.desc()), page, page_size)
    beats = ctx.db.execute(select(WorkerHeartbeat)).scalars().all()
    return {"items": [row(j, ["id", "kind", "status", "attempts", "max_attempts", "run_after", "last_error", "finished_at", "created_at"]) for j in items],
            "meta": meta, "workers": [{"worker_id": b.worker_id, "seen_at": iso(b.seen_at), "alive": b.seen_at > utcnow() - timedelta(seconds=60)} for b in beats]}


@router.post("/jobs/{jid}/retry")
def retry(jid: str, ctx: Ctx = Depends(admin)) -> dict:
    j = ctx.db.get(Job, parse_uuid(jid))
    if j is None or j.status not in ("dead", "failed"):
        raise AppError(409, "not_retryable", "Only dead-lettered jobs can be retried.")
    j.status, j.attempts, j.run_after, j.last_error = "queued", 0, utcnow(), j.last_error + "\nmanually re-queued"
    audit.record(ctx.db, "governance.job_retried", "job", j.id, **audit.ctx_kw(ctx), details={"kind": j.kind})
    ctx.db.commit()
    return {"ok": True}


@router.get("/data-quality")
def data_quality(ctx: Ctx = Depends(gov)) -> dict:
    db = ctx.db
    today = date.today()
    now = utcnow()
    scan = dict(db.execute(select(StoredObject.scan_status, func.count()).where(StoredObject.deleted_at.is_(None)).group_by(StoredObject.scan_status)).all())
    return {
        "rule_versions": [{"rule_set": r.rule_set.code, "version": r.version, "review_date": iso(r.review_date), "review_status": r.review_status,
                           "verification_status": r.verification_status, "stale": r.review_date < today}
                          for r in db.execute(select(RuleVersion)).scalars()],
        "sources": {"total": db.execute(select(func.count()).select_from(SourceRecord)).scalar_one(),
                    "placeholder": db.execute(select(func.count()).select_from(SourceRecord).where(SourceRecord.is_placeholder)).scalar_one(),
                    "past_review": db.execute(select(func.count()).select_from(SourceRecord).where(SourceRecord.review_date < today)).scalar_one()},
        "packs": [row(p, ["code", "version", "title", "checksum", "status", "loaded_at"]) for p in db.execute(select(JurisdictionPack)).scalars()],
        "scan_status": scan,
        "documents_expiring_90d": db.execute(select(func.count()).select_from(Document).where(Document.deleted_at.is_(None), Document.expires_at.is_not(None),
                                                                                         Document.expires_at < now + timedelta(days=90))).scalar_one(),
        "overdue_tasks": db.execute(select(func.count()).select_from(Task).where(Task.status.notin_(("done", "skipped")), Task.due_at < now)).scalar_one(),
        "consents": dict(db.execute(select(ConsentGrant.status, func.count()).group_by(ConsentGrant.status)).all()),
        "delegations": dict(db.execute(select(Delegation.status, func.count()).group_by(Delegation.status)).all()),
    }


@router.get("/analytics")
def tenant_analytics(ctx: Ctx = Depends(gov)) -> dict:
    snap = analytics.latest(ctx.db)
    if snap is None or snap.computed_at < utcnow() - timedelta(minutes=10):
        snap = analytics.refresh(ctx.db)
    return {"computed_at": iso(snap.computed_at), **snap.payload}


@router.get("/ai")
def ai_oversight(ctx: Ctx = Depends(gov)) -> dict:
    rows = ctx.db.execute(select(AIToolCall.tool, AIToolCall.status, func.count()).group_by(AIToolCall.tool, AIToolCall.status)).all()
    recent = ctx.db.execute(select(AIToolCall).where(AIToolCall.status.in_(("denied", "invalid", "timeout", "pending_approval")))
                            .order_by(AIToolCall.created_at.desc()).limit(30)).scalars()
    return {"by_tool": [{"tool": t, "status": s, "count": n} for t, s, n in rows],
            "recent_exceptions": [row(c, ["id", "tool", "status", "reason", "mode", "created_at"]) for c in recent],
            "note": "Tool inputs and outputs are not shown here; they may contain personal data."}


@router.get("/consent-oversight")
def consent_oversight(ctx: Ctx = Depends(gov)) -> dict:
    k = int(policies.get(ctx.db, "small_group_threshold"))
    rows = ctx.db.execute(select(Tenant.name, ConsentGrant.status, func.count()).join(Tenant, Tenant.id == ConsentGrant.recipient_tenant_id)
                          .group_by(Tenant.name, ConsentGrant.status)).all()
    return {"k_threshold": k, "items": [{"recipient": t, "status": s, "count": n if n >= k else None, "suppressed": n < k} for t, s, n in rows]}


@router.get("/operations")
def operations(ctx: Ctx = Depends(gov)) -> dict:
    s_ok, s_msg = storage.healthy()
    c_ok, c_msg = scanner.ping()
    from app.services.meetings import livekit_health

    l_ok, l_msg = livekit_health()
    return {"storage": {"ok": s_ok, "detail": s_msg}, "scanner": {"ok": c_ok, "detail": c_msg, "version": scanner.version() if c_ok else None},
            "video": {"ok": l_ok, "detail": l_msg}}
