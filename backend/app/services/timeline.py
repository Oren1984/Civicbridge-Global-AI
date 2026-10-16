from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import CaseEvent


def add_event(
    db: Session,
    case_id: uuid.UUID,
    kind: str,
    summary: str,
    *,
    ctx=None,
    actor_label: str | None = None,
    data: dict[str, Any] | None = None,
    internal_for_tenant: uuid.UUID | None = None,
) -> CaseEvent:
    label = actor_label
    if label is None and ctx is not None:
        tenant_name = ctx.membership.tenant.name if ctx.membership else ""
        label = f"{ctx.user.display_name}" + (f" · {tenant_name}" if ctx.workspace not in (None, "citizen") else "")
    ev = CaseEvent(
        case_id=case_id,
        at=utcnow(),
        kind=kind,
        actor_user_id=ctx.user.id if ctx else None,
        actor_tenant_id=ctx.tenant_id if ctx else None,
        actor_label=label or "CivicBridge",
        summary=summary,
        data=data or {},
        visibility="internal" if internal_for_tenant else "all",
        visible_tenant_id=internal_for_tenant,
    )
    db.add(ev)
    db.flush()
    return ev
