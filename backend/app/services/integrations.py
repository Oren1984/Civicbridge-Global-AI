"""Integration registry and adapters.

States: mock | public_data | sandbox | authorized_live. This installation ships NO authorized-live adapter.
* mock        - in-process synthetic authority gateway; returns labelled simulated acknowledgements.
* public_data - reads the bundled jurisdiction-pack reference snapshot (synthetic) through the adapter contract.
* sandbox     - real HTTP round-trip to a local sandbox endpoint, exercising timeouts and retries.
Every call: timeout, idempotency key, bounded retries (job queue), recorded errors, dead-letter after max attempts.
"""
from __future__ import annotations

import time
import uuid

import httpx
from sqlalchemy import select

from app.config import get_settings
from app.db import utcnow
from app.models import IntegrationAdapter, IntegrationRun, ServiceRequest, SourceRecord
from app.services import audit
from app.services.timeline import add_event


class AdapterError(Exception):
    pass


def _call(db, adapter: IntegrationAdapter, operation: str, payload: dict) -> dict:
    if not adapter.enabled:
        raise AdapterError("adapter disabled")
    if adapter.failure_injection == "timeout":
        time.sleep(min(adapter.timeout_ms, 3000) / 1000)
        raise AdapterError(f"timeout after {adapter.timeout_ms} ms (injected)")
    if adapter.failure_injection == "error":
        raise AdapterError("upstream returned HTTP 503 (injected)")
    if adapter.state == "mock":
        return {
            "simulated": True,
            "acknowledgement": f"SIM-ACK-{uuid.uuid4().hex[:10].upper()}",
            "note": "Synthetic acknowledgement from a mock authority gateway. Not an official submission.",
            "operation": operation,
        }
    if adapter.state == "public_data":
        count = db.execute(select(SourceRecord.id)).all()
        return {"simulated": False, "dataset": "bundled synthetic reference snapshot", "records": len(count)}
    if adapter.state == "sandbox":
        r = httpx.post(
            f"{get_settings().internal_api_url}/api/integrations/sandbox/echo",
            json={"operation": operation, "payload": payload},
            timeout=adapter.timeout_ms / 1000,
        )
        r.raise_for_status()
        return {"simulated": True, "sandbox_echo": r.json()}
    raise AdapterError(f"state {adapter.state} has no implementation in this installation")


def adapter_for_tenant(db, tenant_id) -> IntegrationAdapter | None:
    return db.execute(select(IntegrationAdapter).where(IntegrationAdapter.tenant_id == tenant_id)).scalars().first()


def dispatch_service_request(db, sr_id: uuid.UUID, operation: str, final_attempt: bool) -> dict:
    sr = db.get(ServiceRequest, sr_id)
    if sr is None:
        return {"skipped": "request not found"}
    adapter = adapter_for_tenant(db, sr.tenant_id)
    if adapter is None:
        add_event(db, sr.case_id, "exchange.internal", f"{sr.reference} delivered to the authority's CivicBridge workspace (no external integration).",
                  actor_label="CivicBridge routing")
        db.commit()
        return {"internal": True}
    key = f"{operation}:{sr.id}"
    run = db.execute(select(IntegrationRun).where(IntegrationRun.idempotency_key == key)).scalar_one_or_none()
    if run and run.status == "success":
        return {"idempotent_replay": True, "response": run.response_summary}
    if run is None:
        run = IntegrationRun(adapter_id=adapter.id, idempotency_key=key, operation=operation, status="pending",
                             service_request_id=sr.id, request_summary={"reference": sr.reference, "kind": sr.kind})
        db.add(run)
        db.flush()
    run.attempts += 1
    try:
        resp = _call(db, adapter, operation, {"reference": sr.reference})
    except (AdapterError, httpx.HTTPError) as exc:
        run.error = str(exc)[:1000]
        run.status = "dead_letter" if final_attempt else "retrying"
        adapter.health_status = "degraded"
        adapter.last_error = str(exc)[:500]
        if final_attempt:
            run.finished_at = utcnow()
            add_event(db, sr.case_id, "exchange.failed", f"Simulated exchange for {sr.reference} failed after {run.attempts} attempts and was dead-lettered. "
                      "The request remains available in the authority's CivicBridge workspace.", actor_label=adapter.name)
            audit.record(db, "integration.dead_letter", "integration_run", run.id, outcome="error", details={"adapter": adapter.code})
        db.commit()
        raise
    run.status = "success"
    run.response_summary = resp
    run.finished_at = utcnow()
    adapter.health_status = "healthy"
    adapter.last_error = ""
    add_event(db, sr.case_id, "exchange.acknowledged",
              f"{adapter.name}: {resp.get('acknowledgement', 'acknowledged')} (simulated exchange; not an official government submission).",
              actor_label=adapter.name, data={"adapter_state": adapter.state})
    audit.record(db, "integration.success", "integration_run", run.id, details={"adapter": adapter.code, "state": adapter.state})
    db.commit()
    return resp


def health_check(db, adapter: IntegrationAdapter) -> IntegrationAdapter:
    start = time.monotonic()
    try:
        if adapter.failure_injection != "none":
            raise AdapterError(f"failure injection active: {adapter.failure_injection}")
        if adapter.state == "sandbox":
            httpx.get(f"{get_settings().internal_api_url}/api/health/live", timeout=adapter.timeout_ms / 1000).raise_for_status()
        adapter.health_status = "healthy"
        adapter.last_error = ""
    except Exception as exc:  # noqa: BLE001
        adapter.health_status = "down"
        adapter.last_error = str(exc)[:500]
    adapter.last_check_at = utcnow()
    db.commit()
    return adapter
