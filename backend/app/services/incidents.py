"""Civic Incident & Resolution Network: intake, location minimisation, duplicates, routing, SLA, resolution, feedback."""
from __future__ import annotations

import math
import uuid
from datetime import timedelta

from sqlalchemy import select

from app.ai.embeddings import cosine, embed
from app.db import utcnow
from app.deps import Ctx, deny
from app.errors import AppError, bad_request, conflict
from app.models import Incident, IncidentUpdate, Membership, Tenant
from app.services import audit, calendar, notify, policies
from app.services.refs import next_ref

OFFICER_ROLES = ("authority_officer", "authority_supervisor")
QUEUES = {
    "streetlight": "lighting",
    "pothole": "roads",
    "waste": "sanitation",
    "water": "water",
    "graffiti": "public_spaces",
    "accessibility": "accessibility",
    "other": "public_works",
}
TRANSITIONS = {
    "triage": ({"submitted"}, "triaged", "officer"),
    "assign": ({"triaged", "assigned"}, "assigned", "officer"),
    "start": ({"assigned"}, "in_progress", "assignee"),
    "resolve": ({"in_progress"}, "resolved", "assignee"),
    "reopen": ({"resolved"}, "in_progress", "reporter"),
    "close": ({"resolved"}, "closed", "reporter_or_officer"),
    "mark_duplicate": ({"submitted", "triaged"}, "duplicate", "officer"),
}


def minimise(lat: float | None, lon: float | None) -> tuple[float | None, float | None, str]:
    """Round to 3 decimal places (about 110 m). Precise coordinates are never stored."""
    if lat is None or lon is None:
        return None, None, "none"
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise bad_request("Invalid coordinates.")
    return round(lat, 3), round(lon, 3), "approx_110m"


def _distance_m(a: Incident, b: Incident) -> float | None:
    if None in (a.lat_approx, a.lon_approx, b.lat_approx, b.lon_approx):
        return None
    r = 6371000
    p1, p2 = math.radians(a.lat_approx), math.radians(b.lat_approx)
    dp, dl = p2 - p1, math.radians(b.lon_approx - a.lon_approx)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def duplicate_candidates(db, inc: Incident) -> list[dict]:
    since = utcnow() - timedelta(days=30)
    rows = db.execute(
        select(Incident).where(
            Incident.tenant_id == inc.tenant_id,
            Incident.id != inc.id,
            Incident.created_at > since,
            Incident.status.notin_(("closed", "duplicate")),
        )
    ).scalars().all()
    qv = embed(inc.description)
    out = []
    for o in rows:
        score = 0.0
        reasons = []
        if o.category == inc.category:
            score += 0.4
            reasons.append("same category")
        d = _distance_m(inc, o)
        if d is not None and d < 300:
            score += 0.3
            reasons.append(f"about {int(d)} m apart")
        elif d is not None and d < 1000:
            score += 0.15
            reasons.append(f"about {int(d)} m apart")
        sim = cosine(qv, embed(o.description))
        score += 0.3 * max(0.0, sim)
        if sim > 0.3:
            reasons.append("similar description")
        if score >= 0.45:
            out.append({"incident_id": str(o.id), "reference": o.reference, "status": o.status, "score": round(score, 2), "reasons": reasons})
    return sorted(out, key=lambda r: r["score"], reverse=True)[:5]


def get_incident_for(ctx: Ctx, incident_id: uuid.UUID) -> Incident:
    inc = ctx.db.get(Incident, incident_id)
    if inc is not None:
        if ctx.workspace == "citizen" and inc.reporter_user_id == ctx.user.id:
            return inc
        if ctx.workspace == "authority" and ctx.role in OFFICER_ROLES and inc.tenant_id == ctx.tenant_id:
            return inc
    raise deny(ctx, "incident.access_denied", "incident", incident_id, "no_incident_access")


def municipal_tenants(db) -> list[Tenant]:
    return list(db.execute(select(Tenant).where(Tenant.kind == "authority", Tenant.settings["handles_incidents"].as_boolean())).scalars())


def create(ctx: Ctx, *, tenant_id: uuid.UUID, category: str, description: str, lat, lon, location_text: str,
           category_source: str, draft_key: str | None = None) -> Incident:
    db = ctx.db
    t = db.get(Tenant, tenant_id)
    if t is None or not (t.settings or {}).get("handles_incidents"):
        raise bad_request("Choose a municipality that accepts incident reports.")
    if category not in QUEUES:
        raise bad_request("Unknown category.")
    if draft_key:
        existing = db.execute(
            select(Incident).where(Incident.reporter_user_id == ctx.user.id, Incident.client_draft_key == draft_key)
        ).scalar_one_or_none()
        if existing:
            return existing  # idempotent replay from offline outbox
    la, lo, precision = minimise(lat, lon)
    if precision == "none" and location_text:
        precision = "text_only"
    inc = Incident(
        reference=next_ref(db, "INC"),
        reporter_user_id=ctx.user.id,
        tenant_id=tenant_id,
        category=category,
        category_source=category_source,
        description=description.strip()[:4000],
        lat_approx=la,
        lon_approx=lo,
        location_text=location_text.strip()[:300],
        location_precision=precision,
        queue=QUEUES[category],
        sla_due_at=calendar.add_working_days(db, t.jurisdiction_id, utcnow(), int(policies.get(db, "incident_sla_working_days"))),
        client_draft_key=draft_key,
    )
    db.add(inc)
    db.flush()
    db.add(IncidentUpdate(incident_id=inc.id, author_user_id=ctx.user.id, kind="status", body="Report received.", public=True,
                          data={"status": "submitted"}))
    for uid in db.execute(select(Membership.user_id).where(Membership.tenant_id == tenant_id, Membership.role.in_(OFFICER_ROLES))).scalars():
        notify.notify(db, uid, "incident_update", f"New incident {inc.reference}", inc.description[:140], f"/authority/incidents/{inc.id}", tenant_id)
    audit.record(db, "incident.created", "incident", inc.id, **audit.ctx_kw(ctx), details={"category": category, "precision": precision})
    return inc


def transition(ctx: Ctx, inc: Incident, action: str, data: dict) -> Incident:
    db = ctx.db
    if action not in TRANSITIONS:
        raise bad_request("Unknown action.")
    froms, to, actor = TRANSITIONS[action]
    is_officer = ctx.workspace == "authority" and ctx.role in OFFICER_ROLES and inc.tenant_id == ctx.tenant_id
    is_reporter = ctx.workspace == "citizen" and inc.reporter_user_id == ctx.user.id
    ok = {
        "officer": is_officer,
        "assignee": is_officer and inc.assigned_user_id == ctx.user.id,
        "reporter": is_reporter,
        "reporter_or_officer": is_reporter or is_officer,
    }[actor]
    if not ok:
        audit.record_now("incident.transition_denied", "incident", inc.id, actor_user_id=ctx.user.id, actor_tenant_id=ctx.tenant_id,
                         actor_role=ctx.role, outcome="denied", details={"action": action})
        raise AppError(403, "transition_not_permitted", "You cannot perform this action.")
    if inc.status not in froms:
        raise conflict(f"Not allowed from status '{inc.status}'.", "invalid_transition")
    now = utcnow()
    note = (data.get("note") or "").strip()[:2000]
    public = True
    body = note
    if action == "triage":
        cat = data.get("category") or inc.category
        if cat not in QUEUES:
            raise bad_request("Unknown category.")
        inc.category = cat
        inc.queue = QUEUES[cat]
        inc.priority = data.get("priority") if data.get("priority") in ("low", "normal", "high", "urgent") else inc.priority
        body = note or f"Triaged as {cat.replace('_', ' ')}."
    elif action == "assign":
        target = uuid.UUID(str(data.get("user_id"))) if data.get("user_id") else ctx.user.id
        if not db.execute(select(Membership).where(Membership.user_id == target, Membership.tenant_id == inc.tenant_id,
                                                   Membership.role.in_(OFFICER_ROLES))).first():
            raise bad_request("Assignee must be an officer of this municipality.")
        inc.assigned_user_id = target
        body = "A team member has been assigned."
    elif action == "start":
        body = note or "Work has started."
    elif action == "resolve":
        if len(note) < 10:
            raise bad_request("Describe the resolution (at least 10 characters).")
        inc.resolved_at = now
    elif action == "reopen":
        body = note or "The reporter indicated the issue is not resolved."
        inc.resolved_at = None
    elif action == "close":
        inc.closed_at = now
        if is_reporter:
            rating = data.get("rating")
            if rating is not None:
                if not (isinstance(rating, int) and 1 <= rating <= 5):
                    raise bad_request("Rating must be 1 to 5.")
                inc.feedback_rating = rating
            inc.feedback_comment = (data.get("comment") or "")[:2000] or None
        body = note or "Closed."
    elif action == "mark_duplicate":
        dup = db.get(Incident, uuid.UUID(str(data.get("duplicate_of")))) if data.get("duplicate_of") else None
        if dup is None or dup.tenant_id != inc.tenant_id or dup.id == inc.id:
            raise bad_request("Choose the original incident.")
        inc.duplicate_of_id = dup.id
        body = f"Merged with existing report {dup.reference}. Progress will be tracked there."
    prev = inc.status
    inc.status = to
    db.add(IncidentUpdate(incident_id=inc.id, author_user_id=ctx.user.id, kind="resolution" if action == "resolve" else "status",
                          body=body or to, public=public, data={"from": prev, "to": to}))
    if not is_reporter:
        notify.notify(db, inc.reporter_user_id, "incident_update", f"{inc.reference}: {to.replace('_', ' ')}", body[:200], f"/incidents/{inc.id}")
    elif inc.assigned_user_id:
        notify.notify(db, inc.assigned_user_id, "incident_update", f"{inc.reference}: reporter {action}", body[:200], f"/authority/incidents/{inc.id}", inc.tenant_id)
    audit.record(db, f"incident.{action}", "incident", inc.id, **audit.ctx_kw(ctx), details={"from": prev, "to": to})
    db.commit()
    return inc


def sla_sweep(db) -> int:
    now = utcnow()
    rows = db.execute(
        select(Incident).where(Incident.status.in_(("submitted", "triaged", "assigned", "in_progress")),
                               Incident.sla_due_at < now, Incident.sla_breached.is_(False))
    ).scalars().all()
    for inc in rows:
        inc.sla_breached = True
        for uid in db.execute(select(Membership.user_id).where(Membership.tenant_id == inc.tenant_id,
                                                               Membership.role == "authority_supervisor")).scalars():
            notify.notify(db, uid, "escalation", f"Incident SLA breached: {inc.reference}", "", f"/authority/incidents/{inc.id}", inc.tenant_id)
        audit.record(db, "incident.sla_breach", "incident", inc.id)
    db.commit()
    return len(rows)
