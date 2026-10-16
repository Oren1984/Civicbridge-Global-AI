"""Append-only, hash-chained application audit log.

Integrity model (described honestly in docs/security/AUDIT.md):
* Each event stores prev_hash and hash = SHA-256(prev_hash || canonical(event)).
* A database trigger rejects UPDATE/DELETE/TRUNCATE on audit_events for the application role.
* ``verify_chain`` recomputes every hash; any edit, deletion or re-ordering breaks the chain.
* This is tamper-*evident*, not tamper-proof: a database superuser can disable the trigger and
  rewrite the whole chain. Anchoring the head hash externally (``audit-anchor`` CLI output) narrows that.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db import session_factory, utcnow
from app.models import AuditEvent
from app.security.crypto import sha256_hex

GENESIS = "0" * 64
_SENSITIVE_KEYS = re.compile(r"(^|_)(password|passwd|secret|token|otp|mfa_code|content|body|text|email)($|_)", re.I)


def _redact(details: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in (details or {}).items():
        if _SENSITIVE_KEYS.search(k):
            out[k] = "[redacted]"
        elif isinstance(v, dict):
            out[k] = _redact(v)
        elif isinstance(v, (str, int, float, bool)) or v is None:
            out[k] = v if not isinstance(v, str) else v[:300]
        elif isinstance(v, (list, tuple)):
            out[k] = [str(x)[:100] for x in v][:50]
        else:
            out[k] = str(v)[:300]
    return out


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _s(v: Any) -> str | None:
    return None if v is None else str(v)


def canonical(ev: AuditEvent) -> str:
    return json.dumps(
        {
            "at": _iso(ev.at),
            "actor_user_id": _s(ev.actor_user_id),
            "actor_tenant_id": _s(ev.actor_tenant_id),
            "actor_role": ev.actor_role,
            "action": ev.action,
            "resource_type": ev.resource_type,
            "resource_id": ev.resource_id,
            "subject_user_id": _s(ev.subject_user_id),
            "outcome": ev.outcome,
            "details": ev.details,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def record(
    db: Session,
    action: str,
    resource_type: str,
    resource_id: Any = None,
    *,
    actor_user_id: uuid.UUID | None = None,
    actor_tenant_id: uuid.UUID | None = None,
    actor_role: str | None = None,
    subject_user_id: uuid.UUID | None = None,
    outcome: str = "success",
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    """Append within the caller's transaction (committed or rolled back together with the change)."""
    db.execute(text("SELECT pg_advisory_xact_lock(727274)"))  # serialise chain appends
    prev = db.execute(select(AuditEvent.hash).order_by(AuditEvent.seq.desc()).limit(1)).scalar()
    ev = AuditEvent(
        at=utcnow(),
        actor_user_id=actor_user_id,
        actor_tenant_id=actor_tenant_id,
        actor_role=actor_role,
        action=action,
        resource_type=resource_type,
        resource_id=_s(resource_id),
        subject_user_id=subject_user_id,
        outcome=outcome,
        details=_redact(details or {}),
        prev_hash=prev or GENESIS,
        hash="",
    )
    ev.hash = sha256_hex((ev.prev_hash + canonical(ev)).encode())
    db.add(ev)
    db.flush()
    return ev


def record_now(action: str, resource_type: str, resource_id: Any = None, **kw: Any) -> None:
    """Append in an independent transaction (used for denials, so they persist even if the request fails)."""
    with session_factory()() as db:
        record(db, action, resource_type, resource_id, **kw)
        db.commit()


def ctx_kw(ctx) -> dict[str, Any]:
    return {
        "actor_user_id": ctx.user.id,
        "actor_tenant_id": ctx.tenant_id,
        "actor_role": ctx.role,
    }


def verify_chain(db: Session, batch: int = 2000) -> dict[str, Any]:
    prev = GENESIS
    count = 0
    last_seq = 0
    while True:
        rows = db.execute(select(AuditEvent).where(AuditEvent.seq > last_seq).order_by(AuditEvent.seq).limit(batch)).scalars().all()
        if not rows:
            break
        for ev in rows:
            expected = sha256_hex((prev + canonical(ev)).encode())
            if ev.prev_hash != prev or ev.hash != expected:
                return {"ok": False, "checked": count, "broken_at_seq": ev.seq, "head": prev}
            prev = ev.hash
            count += 1
            last_seq = ev.seq
        db.expunge_all()
    return {"ok": True, "checked": count, "head": prev, "verified_at": _iso(utcnow())}
