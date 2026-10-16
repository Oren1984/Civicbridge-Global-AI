"""Background worker: job handlers and periodic sweeps.

Run: python -m app.worker
"""
from __future__ import annotations

import io
import json
import logging
import os
import socket
import time
import uuid
import zipfile
from datetime import timedelta

from sqlalchemy import select

from app import logging_setup
from app.ai.embeddings import chunk_text, embed
from app.db import session_factory, utcnow
from app.models import (
    Case,
    CaseEvent,
    ConsentGrant,
    Delegation,
    Document,
    DocumentChunk,
    DocumentVersion,
    Incident,
    Meeting,
    Message,
    Notification,
    PrivacyRequest,
    ScreeningResult,
    ServiceRequest,
    StoredObject,
    Task,
    User,
    WorkerHeartbeat,
)
from app.services import analytics, audit, files, incidents, integrations, jobs, mail, notify, scanner, storage, workflow

logging_setup.setup()
log = logging.getLogger("civicbridge.worker")
WORKER_ID = f"{socket.gethostname()}-{os.getpid()}"


class Retry(Exception):
    """Raise to retry with backoff (counts as a failed attempt)."""


# ------------------------------------------------------------------ handlers


def h_scan_object(db, payload: dict, final: bool) -> None:
    obj = db.get(StoredObject, uuid.UUID(payload["object_id"]))
    if obj is None or obj.deleted_at:
        return
    data = storage.get(obj.storage_key)
    status, detail = scanner.scan_bytes(data)
    obj.scan_attempts += 1
    obj.scan_status = status
    obj.scan_detail = detail
    obj.scanned_at = utcnow()
    audit.record(db, f"file.scan_{status}", "stored_object", obj.id, subject_user_id=obj.owner_user_id, outcome="success" if status == "clean" else "error",
                 details={"purpose": obj.purpose, "detail": detail[:120]})
    if status == "infected":
        notify.notify(db, obj.owner_user_id, "security", "An uploaded file was quarantined",
                      f"'{obj.safe_filename}' matched a malware signature and cannot be opened or shared.")
    db.commit()
    if status in ("scan_unavailable", "error"):
        raise Retry(f"scanner {status}: {detail}")
    if status == "clean":
        v = db.execute(select(DocumentVersion).where(DocumentVersion.object_id == obj.id)).scalar_one_or_none()
        if v is not None and v.extraction_status == "pending":
            jobs.enqueue(db, "extract_text", {"version_id": str(v.id)})
            db.commit()


def h_extract_text(db, payload: dict, final: bool) -> None:
    v = db.get(DocumentVersion, uuid.UUID(payload["version_id"]))
    if v is None or v.object.scan_status != "clean":
        return
    text, status = files.extract_text(storage.get(v.object.storage_key), v.object.mime)
    v.extracted_text = text
    v.extraction_status = status
    doc = db.get(Document, v.document_id)
    for old in db.execute(select(DocumentChunk).where(DocumentChunk.document_id == doc.id)).scalars():
        db.delete(old)
    if text and v.version == doc.current_version:
        for i, chunk in enumerate(chunk_text(text)):
            db.add(DocumentChunk(document_version_id=v.id, document_id=doc.id, owner_user_id=doc.owner_user_id, ordinal=i, text=chunk, embedding=embed(chunk)))
    db.commit()


def h_send_email(db, payload: dict, final: bool) -> None:
    user = db.get(User, uuid.UUID(payload["user_id"]))
    if user is None:
        return
    body = payload.get("body", "")
    if payload.get("link"):
        body += f"\n\nOpen: {os.environ.get('CB_PUBLIC_ORIGIN', 'http://localhost:8084')}{payload['link']}"
    mail.send(user.email, payload.get("subject", "Notification"), body)


def h_send_email_raw(db, payload: dict, final: bool) -> None:
    mail.send(payload["to"], payload["subject"], payload["body"])


def h_delete_object(db, payload: dict, final: bool) -> None:
    obj = db.get(StoredObject, uuid.UUID(payload["object_id"]))
    if obj is None:
        return
    try:
        storage.delete(obj.storage_key)
    except Exception as exc:  # noqa: BLE001
        raise Retry(str(exc)) from exc
    obj.deleted_at = utcnow()
    audit.record(db, "file.erased", "stored_object", obj.id, subject_user_id=obj.owner_user_id)
    db.commit()


def h_integration_dispatch(db, payload: dict, final: bool) -> None:
    try:
        integrations.dispatch_service_request(db, uuid.UUID(payload["service_request_id"]), payload["operation"], final)
    except Exception as exc:  # noqa: BLE001
        raise Retry(str(exc)) from exc


def _export_bundle(db, user: User) -> bytes:
    def rows(model, *where):
        return [{c.name: (str(getattr(r, c.name)) if getattr(r, c.name) is not None else None) for c in model.__table__.columns
                 if c.name not in ("password_hash", "mfa_secret_enc", "embedding")} for r in db.execute(select(model).where(*where)).scalars()]

    cases = db.execute(select(Case).where(Case.owner_user_id == user.id)).scalars().all()
    case_ids = [c.id for c in cases]
    data = {
        "profile": rows(User, User.id == user.id)[0],
        "cases": rows(Case, Case.owner_user_id == user.id),
        "timeline": rows(CaseEvent, CaseEvent.case_id.in_(case_ids), CaseEvent.visibility == "all"),
        "tasks": rows(Task, Task.case_id.in_(case_ids)),
        "service_requests": rows(ServiceRequest, ServiceRequest.case_id.in_(case_ids)),
        "messages": rows(Message, Message.case_id.in_(case_ids)),
        "documents": rows(Document, Document.owner_user_id == user.id),
        "consents": rows(ConsentGrant, ConsentGrant.owner_user_id == user.id),
        "delegations": rows(Delegation, Delegation.principal_user_id == user.id),
        "incidents": rows(Incident, Incident.reporter_user_id == user.id),
        "screenings": rows(ScreeningResult, ScreeningResult.user_id == user.id),
        "notifications": rows(Notification, Notification.user_id == user.id),
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.txt", "CivicBridge personal data export (subject access). Synthetic demo installation.\n"
                   "Internal authority working notes and other people's data are excluded. Files are included only if they passed scanning.\n")
        z.writestr("data.json", json.dumps(data, indent=2, ensure_ascii=False))
        for doc in db.execute(select(Document).where(Document.owner_user_id == user.id, Document.deleted_at.is_(None))).scalars():
            for v in doc.versions:
                if v.object.scan_status == "clean":
                    z.writestr(f"documents/{doc.id}/v{v.version}_{v.object.safe_filename}", storage.get(v.object.storage_key))
    return buf.getvalue()


def h_privacy_export(db, payload: dict, final: bool) -> None:
    pr = db.get(PrivacyRequest, uuid.UUID(payload["request_id"]))
    if pr is None or pr.status == "completed":
        return
    pr.status = "processing"
    db.commit()
    user = db.get(User, pr.user_id)
    obj = files.store_derived(db, owner_user_id=user.id, purpose="export", filename="civicbridge-export.zip", data=_export_bundle(db, user),
                              mime="application/zip")
    pr.result_object_id = obj.id
    pr.status = "completed"
    pr.completed_at = utcnow()
    pr.notes = "Export ready after malware scan. The download link stays available for 7 days."
    jobs.enqueue(db, "expire_export", {"object_id": str(obj.id)}, run_after=utcnow() + timedelta(days=7))
    notify.notify(db, user.id, "privacy", "Your data export is ready", "", "/privacy")
    audit.record(db, "privacy.export_completed", "privacy_request", pr.id, subject_user_id=user.id)
    db.commit()


def h_expire_export(db, payload: dict, final: bool) -> None:
    h_delete_object(db, payload, final)


def h_privacy_deletion(db, payload: dict, final: bool) -> None:
    """Erase what can be erased; retain what an (illustrative) authority record-keeping duty requires, and say so."""
    pr = db.get(PrivacyRequest, uuid.UUID(payload["request_id"]))
    if pr is None or pr.status in ("completed", "partially_completed"):
        return
    user = db.get(User, pr.user_id)
    retained_cases = []
    for case in db.execute(select(Case).where(Case.owner_user_id == user.id)).scalars():
        decided = db.execute(select(ServiceRequest).where(ServiceRequest.case_id == case.id,
                                                          ServiceRequest.state.in_(("decided", "closed", "appealed")))).first()
        if decided:
            retained_cases.append(case.reference)
            case.status = "archived"
    erased = 0
    for doc in db.execute(select(Document).where(Document.owner_user_id == user.id, Document.deleted_at.is_(None))).scalars():
        doc.deleted_at = utcnow()
        for v in doc.versions:
            jobs.enqueue(db, "delete_object", {"object_id": str(v.object_id)})
        erased += 1
    for g in db.execute(select(ConsentGrant).where(ConsentGrant.owner_user_id == user.id, ConsentGrant.status.in_(("active", "pending")))).scalars():
        g.status, g.revoked_at, g.revoke_reason = "revoked", utcnow(), "account deletion"
    for d in db.execute(select(Delegation).where(Delegation.principal_user_id == user.id, Delegation.status == "active")).scalars():
        d.status, d.revoked_at = "revoked", utcnow()
    for inc in db.execute(select(Incident).where(Incident.reporter_user_id == user.id)).scalars():
        inc.description = "[removed at reporter's request]"
        inc.lat_approx = inc.lon_approx = None
        inc.location_text = ""
    user.display_name = "Deleted user"
    user.email = f"deleted-{user.id.hex[:12]}@invalid.local"
    user.is_active = False
    pr.completed_at = utcnow()
    if retained_cases:
        pr.status = "partially_completed"
        pr.notes = (f"{erased} document(s) erased, consents and delegations revoked, account deactivated. Case records "
                    f"{', '.join(retained_cases)} are retained (archived) because they contain authority decisions subject to an "
                    "illustrative record-keeping obligation. Audit events are retained (they contain no document contents).")
    else:
        pr.status = "completed"
        pr.notes = f"{erased} document(s) erased, consents and delegations revoked, account deactivated."
    audit.record(db, "privacy.deletion_processed", "privacy_request", pr.id, subject_user_id=user.id, details={"retained_cases": len(retained_cases)})
    db.commit()


HANDLERS = {
    "scan_object": h_scan_object,
    "extract_text": h_extract_text,
    "send_email": h_send_email,
    "send_email_raw": h_send_email_raw,
    "delete_object": h_delete_object,
    "integration_dispatch": h_integration_dispatch,
    "privacy_export": h_privacy_export,
    "privacy_deletion": h_privacy_deletion,
    "expire_export": h_expire_export,
}


# ------------------------------------------------------------------ periodic sweeps


def sweep_expiry(db) -> None:
    now = utcnow()
    for g in db.execute(select(ConsentGrant).where(ConsentGrant.status == "active", ConsentGrant.valid_until <= now)).scalars():
        g.status = "expired"
        audit.record(db, "consent.expired", "consent_grant", g.id, subject_user_id=g.owner_user_id)
    for d in db.execute(select(Delegation).where(Delegation.status == "active", Delegation.valid_until <= now)).scalars():
        d.status = "expired"
        notify.notify(db, d.principal_user_id, "delegation", "A delegation expired", d.purpose, "/delegations")
        audit.record(db, "delegation.expired", "delegation", d.id, subject_user_id=d.principal_user_id)
    db.commit()


def sweep_reminders(db) -> None:
    now = utcnow()
    rows = db.execute(select(Task, Case).join(Case, Case.id == Task.case_id).where(
        Task.status.notin_(("done", "skipped")), Task.due_at.is_not(None), Task.due_at < now + timedelta(days=3), Task.reminder_sent_at.is_(None))).all()
    for t, c in rows:
        t.reminder_sent_at = now
        notify.notify(db, c.owner_user_id, "task_due", f"Deadline soon: {t.title}", f"Due {t.due_at.date().isoformat()} ({c.reference})", f"/cases/{c.id}")
    db.commit()


def sweep_retention(db) -> None:
    now = utcnow()
    for doc in db.execute(select(Document).where(Document.deleted_at.is_(None), Document.retention_until.is_not(None), Document.retention_until < now)).scalars():
        doc.deleted_at = now
        for v in doc.versions:
            jobs.enqueue(db, "delete_object", {"object_id": str(v.object_id)})
        audit.record(db, "retention.document_expired", "document", doc.id, subject_user_id=doc.owner_user_id)
    db.commit()


def sweep_meetings(db) -> None:
    from app.services.meetings import enforce_room

    for m in db.execute(select(Meeting).where(Meeting.status == "open")).scalars().all():
        try:
            enforce_room(db, m, "reconciliation")
        except Exception:  # noqa: BLE001
            log.warning("meeting reconciliation failed")


def heartbeat(db) -> None:
    hb = db.get(WorkerHeartbeat, WORKER_ID) or WorkerHeartbeat(worker_id=WORKER_ID, seen_at=utcnow(), info={})
    hb.seen_at = utcnow()
    hb.info = {"handlers": sorted(HANDLERS)}
    db.merge(hb)
    db.commit()


PERIODIC = [
    (5, heartbeat),
    (10, sweep_meetings),
    (30, lambda db: jobs.requeue_stale(db)),
    (60, workflow.sla_sweep),
    (60, incidents.sla_sweep),
    (60, sweep_expiry),
    (300, sweep_reminders),
    (600, sweep_retention),
    (300, lambda db: analytics.refresh(db)),
]


def run_once(db) -> int:
    claimed = jobs.claim(db, WORKER_ID)
    for job in claimed:
        handler = HANDLERS.get(job.kind)
        final = job.attempts >= job.max_attempts
        try:
            if handler is None:
                raise Retry(f"no handler for {job.kind}")
            handler(db, job.payload, final)
            jobs.succeed(db, job)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            job = db.merge(job)
            log.warning("job failed", extra={"job": job.kind, "job_id": str(job.id)})
            jobs.fail(db, job, f"{type(exc).__name__}: {exc}")
    return len(claimed)


def main() -> None:
    log.info(f"worker {WORKER_ID} starting")
    last: dict[int, float] = {}
    while True:
        with session_factory()() as db:
            for i, (every, fn) in enumerate(PERIODIC):
                if time.monotonic() - last.get(i, 0) >= every:
                    try:
                        fn(db)
                    except Exception:  # noqa: BLE001
                        db.rollback()
                        log.exception("periodic task failed")
                    last[i] = time.monotonic()
            try:
                n = run_once(db)
            except Exception:  # noqa: BLE001
                db.rollback()
                log.exception("job loop error")
                n = 0
        if n == 0:
            time.sleep(1.0)


if __name__ == "__main__":
    main()
