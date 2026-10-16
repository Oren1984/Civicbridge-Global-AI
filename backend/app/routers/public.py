"""Unauthenticated public endpoints: transparency aggregates, emergency notices, jurisdictions, health, metrics."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.db import get_db, utcnow
from app.errors import AppError
from app.models import AuditEvent, Holiday, Incident, Job, Jurisdiction, ServiceRequest, WorkerHeartbeat
from app.routers.common import iso, limiter, client_ip, row
from app.routers.sync import notices_out
from app.services import analytics, scanner, storage

router = APIRouter(tags=["public"])


@router.get("/api/health/live")
def live() -> dict:
    return {"status": "ok"}


@router.get("/api/health/ready")
def ready(db: Session = Depends(get_db)) -> dict:
    checks = {}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["database"] = type(exc).__name__
    ok, msg = storage.healthy()
    checks["storage"] = msg
    c_ok, c_msg = scanner.ping()
    checks["scanner"] = "ok" if c_ok else f"unavailable ({c_msg}) - uploads stay quarantined"
    beat = db.execute(select(func.max(WorkerHeartbeat.seen_at))).scalar()
    checks["worker"] = "ok" if beat and beat > utcnow() - timedelta(seconds=60) else "no recent heartbeat"
    ready_ = checks["database"] == "ok" and ok
    if not ready_:
        raise AppError(503, "not_ready", "Service not ready.", {"checks": checks})
    return {"status": "ready", "checks": checks}


@router.get("/api/metrics", response_class=PlainTextResponse)
def metrics(request: Request, db: Session = Depends(get_db)) -> str:
    """Prometheus text format. Aggregate counters only (no personal data). Not exposed by the reverse proxy."""
    lines = []
    for status, n in db.execute(select(Job.status, func.count()).group_by(Job.status)).all():
        lines.append(f'civicbridge_jobs{{status="{status}"}} {n}')
    for state, n in db.execute(select(ServiceRequest.state, func.count()).group_by(ServiceRequest.state)).all():
        lines.append(f'civicbridge_service_requests{{state="{state}"}} {n}')
    for status, n in db.execute(select(Incident.status, func.count()).group_by(Incident.status)).all():
        lines.append(f'civicbridge_incidents{{status="{status}"}} {n}')
    lines.append(f"civicbridge_audit_events_total {db.execute(select(func.count()).select_from(AuditEvent)).scalar_one()}")
    lines.append(f"civicbridge_scanner_up {1 if scanner.ping()[0] else 0}")
    return "\n".join(lines) + "\n"


@router.get("/api/public/transparency")
def transparency(request: Request, db: Session = Depends(get_db)) -> dict:
    limiter.check(f"public:{client_ip(request)}", 120, 60)
    snap = analytics.latest(db)
    if snap is None:
        snap = analytics.refresh(db)
    return {"computed_at": iso(snap.computed_at), "fresh": snap.computed_at > utcnow() - timedelta(minutes=30), **snap.payload}


@router.get("/api/public/emergency-notices")
def public_notices(db: Session = Depends(get_db)) -> dict:
    return {"items": notices_out(db), "disclaimer": "CivicBridge is not an emergency dispatch service. In danger, call your local emergency number."}


@router.get("/api/public/jurisdictions")
def jurisdictions(db: Session = Depends(get_db)) -> dict:
    rows = db.execute(select(Jurisdiction).order_by(Jurisdiction.code)).scalars().all()
    out = []
    for j in rows:
        hol = db.execute(select(Holiday).where(Holiday.jurisdiction_id == j.id).order_by(Holiday.day)).scalars().all()
        out.append(row(j, ["id", "code", "name", "level", "parent_id", "pack_code", "locale", "currency", "timezone", "weekend_days",
                           "address_format", "retention_default_days", "is_synthetic"])
                   | {"holidays": [{"day": iso(h.day), "name": h.name, "synthetic": h.is_synthetic} for h in hol]})
    return {"items": out}


class EchoIn(BaseModel):
    operation: str
    payload: dict = {}


@router.post("/api/integrations/sandbox/echo", include_in_schema=False)
def sandbox_echo(body: EchoIn) -> dict:
    """Local sandbox counterpart for the 'sandbox' adapter (blocked at the reverse proxy)."""
    return {"received": body.operation, "sandbox": True, "at": utcnow().isoformat()}
