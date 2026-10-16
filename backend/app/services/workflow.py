"""Service-request state machine (server-enforced), decisions with four-eyes approval, appeals and SLA handling.

States: draft -> submitted -> triage -> in_review <-> info_requested -> decision_pending -> decided -> closed
        decided -> appealed (creates linked appeal request); open states -> withdrawn.
"""
from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import func, select

from app.db import utcnow
from app.deps import Ctx, deny
from app.errors import AppError, bad_request, conflict
from app.models import (
    Appeal,
    Case,
    Decision,
    InformationRequest,
    Membership,
    Procedure,
    ServiceRequest,
    Tenant,
)
from app.services import audit, calendar, jobs, notify, policies
from app.services.access import case_access, ensure_participant
from app.services.refs import next_ref
from app.services.timeline import add_event

OPEN_STATES = {"submitted", "triage", "in_review", "info_requested", "decision_pending"}
OFFICER_ROLES = {"authority_officer", "authority_supervisor"}

TRANSITIONS: dict[str, dict] = {
    "submit": {"from": {"draft"}, "to": "submitted", "actor": "citizen_side"},
    "withdraw": {"from": {"submitted", "triage", "in_review", "info_requested"}, "to": "withdrawn", "actor": "citizen_side"},
    "accept": {"from": {"submitted"}, "to": "triage", "actor": "officer"},
    "start_review": {"from": {"triage"}, "to": "in_review", "actor": "assignee"},
    "request_info": {"from": {"in_review"}, "to": "info_requested", "actor": "assignee"},
    "respond_info": {"from": {"info_requested"}, "to": "in_review", "actor": "citizen_side"},
    "propose_decision": {"from": {"in_review"}, "to": "decision_pending", "actor": "assignee"},
    "return_for_rework": {"from": {"decision_pending"}, "to": "in_review", "actor": "supervisor"},
    "approve_decision": {"from": {"decision_pending"}, "to": "decided", "actor": "supervisor"},
    "close": {"from": {"decided"}, "to": "closed", "actor": "officer"},
    "appeal": {"from": {"decided"}, "to": "appealed", "actor": "citizen_side"},
}


def allowed_actions(ctx: Ctx, sr: ServiceRequest) -> list[str]:
    out = []
    for action, spec in TRANSITIONS.items():
        if sr.state in spec["from"] and _actor_ok(ctx, sr, spec["actor"], action, raise_=False):
            out.append(action)
    if sr.state in OPEN_STATES and _is_officer(ctx, sr):
        out += ["assign", "escalate"]
    return out


def _is_officer(ctx: Ctx, sr: ServiceRequest) -> bool:
    return ctx.workspace == "authority" and ctx.tenant_id == sr.tenant_id and ctx.role in OFFICER_ROLES


def _citizen_side(ctx: Ctx, sr: ServiceRequest, action: str) -> bool:
    acc = case_access(ctx, sr.case)
    if acc is None:
        return False
    if acc.level == "owner":
        return True
    if acc.level == "professional":
        scope = "respond_info_requests" if action == "respond_info" else "send_messages"
        return acc.can(scope)
    return False


def _actor_ok(ctx: Ctx, sr: ServiceRequest, actor: str, action: str, raise_: bool = True) -> bool:
    ok = False
    if actor == "citizen_side":
        ok = _citizen_side(ctx, sr, action)
    elif actor == "officer":
        ok = _is_officer(ctx, sr)
    elif actor == "assignee":
        ok = _is_officer(ctx, sr) and sr.assigned_user_id == ctx.user.id
    elif actor == "supervisor":
        ok = _is_officer(ctx, sr) and ctx.role == "authority_supervisor"
    if not ok and raise_:
        audit.record_now(
            "workflow.transition_denied",
            "service_request",
            sr.id,
            actor_user_id=ctx.user.id,
            actor_tenant_id=ctx.tenant_id,
            actor_role=ctx.role,
            outcome="denied",
            details={"action": action, "state": sr.state, "required_actor": actor},
        )
        raise AppError(403, "transition_not_permitted", f"You cannot perform '{action}' on this request in your current role.")
    return ok


def get_request_for(ctx: Ctx, sr_id: uuid.UUID) -> ServiceRequest:
    sr = ctx.db.get(ServiceRequest, sr_id)
    if sr is not None:
        # Drafts belong to the citizen until submitted: the authority cannot see them.
        if ctx.workspace == "authority" and sr.tenant_id == ctx.tenant_id and ctx.role in OFFICER_ROLES and sr.state != "draft":
            return sr
        if ctx.workspace in ("citizen", "professional") and case_access(ctx, sr.case) is not None:
            return sr
    raise deny(ctx, "service_request.access_denied", "service_request", sr_id, "no_request_access")


def _officers(db, tenant_id: uuid.UUID, supervisors_only: bool = False) -> list[uuid.UUID]:
    roles = ("authority_supervisor",) if supervisors_only else tuple(OFFICER_ROLES)
    return list(
        db.execute(
            select(Membership.user_id).where(Membership.tenant_id == tenant_id, Membership.role.in_(roles), Membership.is_active)
        ).scalars()
    )


def _sla_days(db, sr: ServiceRequest) -> int:
    if sr.procedure_id:
        proc = db.get(Procedure, sr.procedure_id)
        if proc:
            return proc.service.sla_working_days
    return 10


def _tenant_jurisdiction(db, tenant_id):
    t = db.get(Tenant, tenant_id)
    return t.jurisdiction_id if t else None


def next_reference(db, prefix: str, _model=None) -> str:
    return next_ref(db, prefix)


def create_request(
    ctx: Ctx, case: Case, tenant_id: uuid.UUID, title: str, procedure_id=None, kind: str = "application", payload=None
) -> ServiceRequest:
    sr = ServiceRequest(
        reference=next_reference(ctx.db, "SR", ServiceRequest),
        case_id=case.id,
        tenant_id=tenant_id,
        procedure_id=procedure_id,
        kind=kind,
        title=title,
        state="draft",
        queue=(payload or {}).get("queue", "general"),
        payload=payload or {},
    )
    ctx.db.add(sr)
    ctx.db.flush()
    add_event(ctx.db, case.id, "request.created", f"Draft request {sr.reference} prepared: {title}", ctx=ctx)
    return sr


def transition(ctx: Ctx, sr: ServiceRequest, action: str, data: dict | None = None) -> ServiceRequest:
    data = data or {}
    db = ctx.db
    if action in ("assign", "escalate"):
        return _non_state_action(ctx, sr, action, data)
    spec = TRANSITIONS.get(action)
    if spec is None:
        raise bad_request(f"Unknown action '{action}'.")
    expected = data.get("expected_version")
    if expected is not None and int(expected) != sr.version:
        raise conflict("This request was changed by someone else. Reload and try again.", "stale_version")
    _actor_ok(ctx, sr, spec["actor"], action)
    if sr.state not in spec["from"]:
        raise conflict(f"Action '{action}' is not allowed from state '{sr.state}'.", "invalid_transition")

    now = utcnow()
    case = sr.case
    prev = sr.state
    internal = None

    if action == "submit":
        sr.submitted_at = now
        sr.sla_due_at = calendar.add_working_days(db, _tenant_jurisdiction(db, sr.tenant_id), now, _sla_days(db, sr))
        ensure_participant(db, case, sr.tenant_id, "authority", "submission")
        jobs.enqueue(
            db,
            "integration_dispatch",
            {"service_request_id": str(sr.id), "operation": "submit_request"},
            dedupe_key=f"sr:{sr.id}:submit",
        )
        for uid in _officers(db, sr.tenant_id):
            notify.notify(db, uid, "assignment", f"New request in queue: {sr.reference}", sr.title, f"/authority/requests/{sr.id}", sr.tenant_id)
    elif action == "withdraw":
        sr.closed_at = now
    elif action == "start_review":
        pass
    elif action == "request_info":
        message = (data.get("message") or "").strip()
        if len(message) < 10:
            raise bad_request("Describe what information is needed (at least 10 characters).")
        due_days = int(data.get("due_working_days") or 10)
        ir = InformationRequest(
            service_request_id=sr.id,
            requested_by=ctx.user.id,
            message=message,
            items=[str(i)[:200] for i in (data.get("items") or [])][:20],
            due_at=calendar.add_working_days(db, _tenant_jurisdiction(db, sr.tenant_id), now, due_days),
        )
        db.add(ir)
        sr.sla_paused_at = now
        notify.notify(db, case.owner_user_id, "info_request", f"Information requested for {sr.reference}", message, f"/cases/{case.id}")
    elif action == "respond_info":
        response = (data.get("response") or "").strip()
        if len(response) < 2:
            raise bad_request("Please write a response.")
        ir = db.execute(
            select(InformationRequest).where(InformationRequest.service_request_id == sr.id, InformationRequest.status == "open")
        ).scalars().first()
        if ir:
            ir.status = "answered"
            ir.response = response
            ir.responded_by = ctx.user.id
            ir.responded_at = now
        if sr.sla_paused_at and sr.sla_due_at:
            sr.sla_due_at = sr.sla_due_at + (now - sr.sla_paused_at)
        sr.sla_paused_at = None
        if sr.assigned_user_id:
            notify.notify(db, sr.assigned_user_id, "info_request", f"Citizen responded on {sr.reference}", "", f"/authority/requests/{sr.id}", sr.tenant_id)
    elif action == "propose_decision":
        outcome = data.get("outcome")
        rationale = (data.get("rationale") or "").strip()
        if outcome not in ("approved", "rejected", "partially_approved", "referred"):
            raise bad_request("Choose a decision outcome.")
        if len(rationale) < 30:
            raise bad_request("A decision rationale of at least 30 characters is required.")
        version = (db.execute(select(func.max(Decision.version)).where(Decision.service_request_id == sr.id)).scalar() or 0) + 1
        db.add(
            Decision(
                service_request_id=sr.id,
                version=version,
                outcome=outcome,
                rationale=rationale,
                rule_version_ids=[str(x) for x in (data.get("rule_version_ids") or [])],
                proposed_by=ctx.user.id,
                status="proposed",
            )
        )
        internal = sr.tenant_id
        for uid in _officers(db, sr.tenant_id, supervisors_only=True):
            notify.notify(db, uid, "decision", f"Decision awaiting approval: {sr.reference}", "", f"/authority/requests/{sr.id}", sr.tenant_id)
    elif action in ("return_for_rework", "approve_decision"):
        d = db.execute(
            select(Decision).where(Decision.service_request_id == sr.id, Decision.status == "proposed").order_by(Decision.version.desc())
        ).scalars().first()
        if d is None:
            raise conflict("No proposed decision found.")
        if action == "return_for_rework":
            d.status = "returned"
            internal = sr.tenant_id
        else:
            if d.proposed_by == ctx.user.id:
                audit.record_now(
                    "workflow.four_eyes_denied", "decision", d.id, actor_user_id=ctx.user.id,
                    actor_tenant_id=ctx.tenant_id, actor_role=ctx.role, outcome="denied", details={"reason_code": "same_person"},
                )
                raise AppError(403, "four_eyes_required", "A different supervisor must approve a decision you proposed.")
            d.status = "approved"
            d.approved_by = ctx.user.id
            d.approved_at = now
            d.appeal_deadline = now + timedelta(days=int(policies.get(db, "appeal_window_days")))
            older = db.execute(
                select(Decision).where(Decision.service_request_id == sr.id, Decision.status == "approved", Decision.id != d.id)
            ).scalars().all()
            for o in older:
                o.status = "superseded"
                d.supersedes_id = o.id
            notify.notify(
                db, case.owner_user_id, "decision", f"Decision issued on {sr.reference}: {d.outcome.replace('_', ' ')}",
                "Open the case to read the rationale and your appeal options.", f"/cases/{case.id}",
            )
            if sr.kind == "appeal" and sr.parent_request_id:
                _resolve_appeal(ctx, sr, d)
    elif action == "close":
        sr.closed_at = now
    elif action == "appeal":
        return _file_appeal(ctx, sr, data)

    sr.state = spec["to"]
    sr.version += 1
    add_event(
        db,
        case.id,
        f"request.{action}",
        _describe(action, sr, data),
        ctx=ctx,
        data={"request": sr.reference, "from": prev, "to": sr.state},
        internal_for_tenant=internal,
    )
    audit.record(db, f"workflow.{action}", "service_request", sr.id, **audit.ctx_kw(ctx), subject_user_id=case.owner_user_id,
                 details={"from": prev, "to": sr.state})
    db.commit()
    return sr


def _describe(action: str, sr: ServiceRequest, data: dict) -> str:
    return {
        "submit": f"Request {sr.reference} sent to the authority workspace (simulated exchange; not an official government submission).",
        "withdraw": f"Request {sr.reference} withdrawn.",
        "accept": f"Request {sr.reference} accepted for triage.",
        "start_review": f"Review started on {sr.reference}.",
        "request_info": f"The authority requested more information on {sr.reference}.",
        "respond_info": f"Information provided for {sr.reference}.",
        "propose_decision": f"Decision proposed on {sr.reference} (internal; awaiting supervisor approval).",
        "return_for_rework": f"Proposed decision on {sr.reference} returned for rework (internal).",
        "approve_decision": f"Decision issued on {sr.reference}.",
        "close": f"Request {sr.reference} closed.",
    }.get(action, action)


def _non_state_action(ctx: Ctx, sr: ServiceRequest, action: str, data: dict) -> ServiceRequest:
    db = ctx.db
    if not _is_officer(ctx, sr):
        _actor_ok(ctx, sr, "officer", action)
    if sr.state not in OPEN_STATES:
        raise conflict("The request is not open.")
    if action == "assign":
        uid = data.get("user_id")
        try:
            target = uuid.UUID(str(uid)) if uid else ctx.user.id
        except ValueError as exc:
            raise bad_request("Invalid user.") from exc
        member = db.execute(
            select(Membership).where(
                Membership.user_id == target, Membership.tenant_id == sr.tenant_id, Membership.role.in_(tuple(OFFICER_ROLES))
            )
        ).scalars().first()
        if member is None:
            raise bad_request("Assignee must be an officer of this authority.")
        sr.assigned_user_id = target
        if target != ctx.user.id:
            notify.notify(db, target, "assignment", f"Assigned to you: {sr.reference}", sr.title, f"/authority/requests/{sr.id}", sr.tenant_id)
        add_event(db, sr.case_id, "request.assigned", f"{sr.reference} assigned to a case officer.", ctx=ctx, internal_for_tenant=sr.tenant_id)
    else:
        sr.escalation_level += 1
        for uid in _officers(db, sr.tenant_id, supervisors_only=True):
            notify.notify(db, uid, "escalation", f"Escalated: {sr.reference}", data.get("reason", "")[:300], f"/authority/requests/{sr.id}", sr.tenant_id)
        add_event(db, sr.case_id, "request.escalated", f"{sr.reference} escalated (level {sr.escalation_level}).", ctx=ctx, internal_for_tenant=sr.tenant_id)
    sr.version += 1
    audit.record(db, f"workflow.{action}", "service_request", sr.id, **audit.ctx_kw(ctx), details={"state": sr.state})
    db.commit()
    return sr


def _file_appeal(ctx: Ctx, sr: ServiceRequest, data: dict) -> ServiceRequest:
    db = ctx.db
    grounds = (data.get("grounds") or "").strip()
    if len(grounds) < 20:
        raise bad_request("Explain the grounds for your appeal (at least 20 characters).")
    d = db.execute(
        select(Decision).where(Decision.service_request_id == sr.id, Decision.status == "approved").order_by(Decision.version.desc())
    ).scalars().first()
    if d is None:
        raise conflict("There is no issued decision to appeal.")
    if d.appeal_deadline and utcnow() > d.appeal_deadline:
        raise conflict("The appeal window for this decision has passed.", "appeal_window_closed")
    case = sr.case
    follow = ServiceRequest(
        reference=next_reference(db, "SR", ServiceRequest),
        case_id=case.id,
        tenant_id=sr.tenant_id,
        procedure_id=sr.procedure_id,
        kind="appeal",
        title=f"Appeal against decision on {sr.reference}",
        state="submitted",
        queue="appeals",
        priority="high",
        parent_request_id=sr.id,
        submitted_at=utcnow(),
        payload={"grounds": grounds[:4000], "decision_id": str(d.id)},
    )
    follow.sla_due_at = calendar.add_working_days(db, _tenant_jurisdiction(db, sr.tenant_id), utcnow(), _sla_days(db, sr))
    db.add(follow)
    db.flush()
    appeal = Appeal(case_id=case.id, decision_id=d.id, follow_up_request_id=follow.id, filed_by=ctx.user.id, grounds=grounds[:4000])
    db.add(appeal)
    prev = sr.state
    sr.state = "appealed"
    sr.version += 1
    add_event(db, case.id, "request.appeal", f"Appeal filed against the decision on {sr.reference}; linked follow-up {follow.reference} created.",
              ctx=ctx, data={"request": sr.reference, "follow_up": follow.reference})
    for uid in _officers(db, sr.tenant_id):
        notify.notify(db, uid, "appeal", f"Appeal filed: {follow.reference}", grounds[:200], f"/authority/requests/{follow.id}", sr.tenant_id)
    audit.record(db, "workflow.appeal", "service_request", sr.id, **audit.ctx_kw(ctx), subject_user_id=case.owner_user_id,
                 details={"from": prev, "to": "appealed", "follow_up": follow.reference})
    db.commit()
    return sr


def _resolve_appeal(ctx: Ctx, appeal_sr: ServiceRequest, appeal_decision: Decision) -> None:
    db = ctx.db
    parent = db.get(ServiceRequest, appeal_sr.parent_request_id)
    appeal = db.execute(select(Appeal).where(Appeal.follow_up_request_id == appeal_sr.id)).scalar_one_or_none()
    original = db.execute(
        select(Decision).where(Decision.service_request_id == parent.id, Decision.status == "approved").order_by(Decision.version.desc())
    ).scalars().first()
    version = (db.execute(select(func.max(Decision.version)).where(Decision.service_request_id == parent.id)).scalar() or 0) + 1
    outcome = "approved" if appeal_decision.outcome == "approved" else (original.outcome if original else appeal_decision.outcome)
    new = Decision(
        service_request_id=parent.id,
        version=version,
        outcome=outcome,
        rationale=f"Decision after appeal {appeal_sr.reference}: {appeal_decision.rationale}",
        rule_version_ids=appeal_decision.rule_version_ids,
        proposed_by=appeal_decision.proposed_by,
        approved_by=appeal_decision.approved_by,
        approved_at=utcnow(),
        status="approved",
        supersedes_id=original.id if original else None,
    )
    db.add(new)
    if original:
        original.status = "superseded"
    parent.state = "decided"
    parent.version += 1
    if appeal:
        appeal.status = "resolved"
        db.flush()
        appeal.resolution_decision_id = new.id
    add_event(db, parent.case_id, "decision.superseded", f"Decision on {parent.reference} updated to version {version} after appeal.", ctx=ctx)


def sla_sweep(db) -> int:
    """Mark breached SLAs, escalate and notify supervisors. Runs in the worker."""
    now = utcnow()
    rows = db.execute(
        select(ServiceRequest).where(
            ServiceRequest.state.in_(tuple(OPEN_STATES)),
            ServiceRequest.sla_due_at < now,
            ServiceRequest.sla_paused_at.is_(None),
            ServiceRequest.sla_breached.is_(False),
        )
    ).scalars().all()
    for sr in rows:
        sr.sla_breached = True
        sr.escalation_level += 1
        for uid in _officers(db, sr.tenant_id, supervisors_only=True):
            notify.notify(db, uid, "escalation", f"SLA breached: {sr.reference}", "Automatically escalated by the SLA clock.", f"/authority/requests/{sr.id}", sr.tenant_id)
        add_event(db, sr.case_id, "request.sla_breached", f"SLA deadline passed on {sr.reference}; escalated automatically.",
                  actor_label="SLA clock", internal_for_tenant=sr.tenant_id)
        audit.record(db, "workflow.sla_breach", "service_request", sr.id, details={"escalation_level": sr.escalation_level})
    db.commit()
    return len(rows)
