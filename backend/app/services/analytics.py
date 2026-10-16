"""Public Accountability & Transparency: privacy-aware aggregates with small-group suppression.

Aggregates never include names, references, free text or coordinates. Any count below the policy threshold k
(default 5) is suppressed, as is any rate whose denominator is below k. Primary suppression only: complementary
suppression (preventing subtraction attacks across totals) is a documented limitation.
"""
from __future__ import annotations

import statistics
import uuid
from datetime import date, timedelta

from sqlalchemy import select

from app.db import utcnow
from app.models import AnalyticsSnapshot, Incident, RuleVersion, ServiceRequest, SourceRecord, Tenant
from app.services import policies

OPEN_SR = ("submitted", "triage", "in_review", "info_requested", "decision_pending")
OPEN_INC = ("submitted", "triaged", "assigned", "in_progress")


def _sup(n: int, k: int):
    return {"value": n, "suppressed": False} if n >= k else {"value": None, "suppressed": True}


def _rate(num: int, den: int, k: int):
    if den < k:
        return {"value": None, "suppressed": True}
    return {"value": round(100 * num / den, 1), "suppressed": False}


def tenant_metrics(db, tenant: Tenant, k: int) -> dict:
    now = utcnow()
    srs = db.execute(select(ServiceRequest).where(ServiceRequest.tenant_id == tenant.id, ServiceRequest.state != "draft")).scalars().all()
    incs = db.execute(select(Incident).where(Incident.tenant_id == tenant.id)).scalars().all()
    open_sr = [s for s in srs if s.state in OPEN_SR]
    decided = [s for s in srs if s.state in ("decided", "closed", "appealed") and s.submitted_at]
    decided_in_sla = [s for s in decided if s.sla_due_at and not s.sla_breached]
    open_inc = [i for i in incs if i.status in OPEN_INC]
    resolved = [i for i in incs if i.resolved_at]
    res_days = [(i.resolved_at - i.created_at).total_seconds() / 86400 for i in resolved]
    in_sla_inc = [i for i in resolved if i.sla_due_at and i.resolved_at <= i.sla_due_at]
    weeks = []
    for w in range(7, -1, -1):
        start = (now - timedelta(days=now.weekday() + 7 * w)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=7)
        n = sum(1 for i in incs if start <= i.created_at < end)
        weeks.append({"week_start": start.date().isoformat(), "new_incidents": _sup(n, k)})
    by_cat = {}
    for i in incs:
        by_cat[i.category] = by_cat.get(i.category, 0) + 1
    with_loc = sum(1 for i in incs if i.location_precision != "none")
    rated = [i.feedback_rating for i in incs if i.feedback_rating]
    return {
        "tenant": {"id": str(tenant.id), "name": tenant.name},
        "requests": {
            "open_backlog": _sup(len(open_sr), k),
            "decided_total": _sup(len(decided), k),
            "sla_adherence_pct": _rate(len(decided_in_sla), len(decided), k),
            "breached_open": _sup(sum(1 for s in open_sr if s.sla_breached), k),
        },
        "incidents": {
            "open_backlog": _sup(len(open_inc), k),
            "resolved_total": _sup(len(resolved), k),
            "median_resolution_days": {"value": round(statistics.median(res_days), 1), "suppressed": False}
            if len(res_days) >= k else {"value": None, "suppressed": True},
            "sla_adherence_pct": _rate(len(in_sla_inc), len(resolved), k),
            "by_category": {c: _sup(n, k) for c, n in sorted(by_cat.items())},
            "weekly_trend": weeks,
            "satisfaction_avg": {"value": round(sum(rated) / len(rated), 2), "suppressed": False}
            if len(rated) >= k else {"value": None, "suppressed": True},
        },
        "data_quality": {
            "incidents_with_location_pct": _rate(with_loc, len(incs), k),
            "incidents_category_suggested_pct": _rate(sum(1 for i in incs if i.category_source == "rules_suggestion"), len(incs), k),
        },
    }


def compute(db) -> dict:
    k = int(policies.get(db, "small_group_threshold"))
    tenants = db.execute(select(Tenant).where(Tenant.kind == "authority").order_by(Tenant.name)).scalars().all()
    today = date.today()
    stale_rules = db.execute(select(RuleVersion).where(RuleVersion.review_date < today)).scalars().all()
    stale_sources = db.execute(select(SourceRecord).where(SourceRecord.review_date < today)).scalars().all()
    all_sources = db.execute(select(SourceRecord)).scalars().all()
    payload = {
        "k_threshold": k,
        "authorities": [tenant_metrics(db, t, k) for t in tenants],
        "provenance": {
            "rule_versions_past_review": len(stale_rules),
            "sources_past_review": len(stale_sources),
            "sources_total": len(all_sources),
            "sources_placeholder": sum(1 for s in all_sources if s.is_placeholder),
        },
        "notice": "Aggregates over synthetic demo data. Counts below k are suppressed. No personal case details are included.",
    }
    return payload


def refresh(db) -> AnalyticsSnapshot:
    snap = AnalyticsSnapshot(id=uuid.uuid4(), scope="public", payload=compute(db), computed_at=utcnow())
    db.add(snap)
    # keep the last 50 snapshots
    old = db.execute(select(AnalyticsSnapshot).where(AnalyticsSnapshot.scope == "public").order_by(AnalyticsSnapshot.computed_at.desc()).offset(50)).scalars().all()
    for o in old:
        db.delete(o)
    db.commit()
    return snap


def latest(db) -> AnalyticsSnapshot | None:
    return db.execute(select(AnalyticsSnapshot).where(AnalyticsSnapshot.scope == "public").order_by(AnalyticsSnapshot.computed_at.desc()).limit(1)).scalar_one_or_none()
