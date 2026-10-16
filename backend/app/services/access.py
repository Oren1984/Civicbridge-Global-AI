"""Resource-level authorization (ABAC on top of RBAC). Deny by default.

Rules, in short:
* Citizen (workspace=citizen): own cases and own documents only.
* Authority / Institution: a case only through an active CaseParticipant row for the *active* tenant.
  Documents only through an active, unexpired consent grant to that tenant covering the document's category.
* Professional: only through an active, unexpired delegation from the case owner, limited to its scopes,
  document categories and (optionally) a single case.
* Governance: no case or document content. Aggregates, audit metadata and operations only.
* Quarantined or unscanned files are never served to anyone.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.deps import Ctx, deny
from app.errors import AppError
from app.models import (
    Case,
    CaseParticipant,
    ConsentGrant,
    Delegation,
    Document,
    DocumentVersion,
    EvidenceLink,
    ShareReceipt,
)

DELEGATION_SCOPES = (
    "view_case",
    "view_documents",
    "upload_documents",
    "draft_messages",
    "send_messages",
    "respond_info_requests",
    "translation_review",
    "attend_meetings",
)


@dataclass
class CaseAccess:
    level: str  # owner | authority | institution | professional
    scopes: set[str] = field(default_factory=set)
    participant: CaseParticipant | None = None
    delegation: Delegation | None = None

    def can(self, scope: str) -> bool:
        return self.level == "owner" or scope in self.scopes


ALL_OWNER = set(DELEGATION_SCOPES)
INSTITUTIONAL_SCOPES = {"view_case", "send_messages", "attend_meetings"}


def _delegation_valid(d: Delegation) -> bool:
    now = utcnow()
    return d.status == "active" and d.valid_from <= now < d.valid_until and d.revoked_at is None


def _consent_valid(g: ConsentGrant) -> bool:
    now = utcnow()
    return g.status == "active" and g.valid_from <= now < g.valid_until and g.revoked_at is None


def active_delegations(db: Session, delegate_user_id: uuid.UUID, tenant_id: uuid.UUID | None) -> list[Delegation]:
    now = utcnow()
    rows = db.execute(
        select(Delegation).where(
            Delegation.delegate_user_id == delegate_user_id,
            Delegation.delegate_tenant_id == tenant_id,
            Delegation.status == "active",
            Delegation.revoked_at.is_(None),
            Delegation.valid_from <= now,
            Delegation.valid_until > now,
        )
    ).scalars()
    return list(rows)


def case_access(ctx: Ctx, case: Case) -> CaseAccess | None:
    db = ctx.db
    ws = ctx.workspace
    if ws == "citizen":
        return CaseAccess("owner", set(ALL_OWNER)) if case.owner_user_id == ctx.user.id else None
    if ws in ("authority", "institution"):
        if ctx.role == "interpreter":
            return None
        p = db.execute(
            select(CaseParticipant).where(
                CaseParticipant.case_id == case.id,
                CaseParticipant.tenant_id == ctx.tenant_id,
                CaseParticipant.role == ws,
                CaseParticipant.status == "active",
            )
        ).scalar_one_or_none()
        if p is None:
            return None
        if p.consent_grant_id:
            g = db.get(ConsentGrant, p.consent_grant_id)
            if g is None or not _consent_valid(g):
                return None
        return CaseAccess(ws, set(INSTITUTIONAL_SCOPES), participant=p)
    if ws == "professional" and ctx.role == "professional":
        for d in active_delegations(db, ctx.user.id, ctx.tenant_id):
            if d.principal_user_id == case.owner_user_id and (d.case_id is None or d.case_id == case.id):
                if "view_case" in d.scopes:
                    return CaseAccess("professional", set(d.scopes), delegation=d)
        return None
    return None


def get_case(ctx: Ctx, case_id: uuid.UUID, scope: str | None = None) -> tuple[Case, CaseAccess]:
    case = ctx.db.get(Case, case_id)
    acc = case_access(ctx, case) if case else None
    if case is None or acc is None:
        raise deny(ctx, "case.access_denied", "case", case_id, "no_case_access")
    if scope and not acc.can(scope):
        raise deny(ctx, "case.scope_denied", "case", case_id, f"missing_scope:{scope}")
    return case, acc


def visible_case_filter(ctx: Ctx):
    """SQL filter for case listings in the active context (same rules as case_access)."""
    ws = ctx.workspace
    now = utcnow()
    if ws == "citizen":
        return Case.owner_user_id == ctx.user.id
    if ws in ("authority", "institution") and ctx.role != "interpreter":
        return exists().where(
            CaseParticipant.case_id == Case.id,
            CaseParticipant.tenant_id == ctx.tenant_id,
            CaseParticipant.role == ws,
            CaseParticipant.status == "active",
        )
    if ws == "professional" and ctx.role == "professional":
        return exists().where(
            Delegation.delegate_user_id == ctx.user.id,
            Delegation.delegate_tenant_id == ctx.tenant_id,
            Delegation.principal_user_id == Case.owner_user_id,
            Delegation.status == "active",
            Delegation.revoked_at.is_(None),
            Delegation.valid_from <= now,
            Delegation.valid_until > now,
            or_(Delegation.case_id.is_(None), Delegation.case_id == Case.id),
        )
    return Case.id.is_(None)  # governance and anything else: nothing


@dataclass
class DocAccess:
    via: str  # owner | consent | delegation
    consent: ConsentGrant | None = None
    delegation: Delegation | None = None


def document_access(ctx: Ctx, doc: Document) -> DocAccess | None:
    db = ctx.db
    if doc.deleted_at is not None:
        return None
    ws = ctx.workspace
    if ws == "citizen":
        return DocAccess("owner") if doc.owner_user_id == ctx.user.id else None
    if ws in ("authority", "institution") and ctx.role != "interpreter":
        grants = db.execute(
            select(ConsentGrant).where(
                ConsentGrant.owner_user_id == doc.owner_user_id,
                ConsentGrant.recipient_tenant_id == ctx.tenant_id,
                ConsentGrant.status == "active",
            )
        ).scalars()
        for g in grants:
            if not _consent_valid(g):
                continue
            if g.recipient_user_id and g.recipient_user_id != ctx.user.id:
                continue
            if doc.category not in (g.data_categories or []):
                continue
            if g.document_ids is not None and str(doc.id) not in [str(x) for x in g.document_ids]:
                continue
            if g.case_id is not None:
                # Purpose binding: a case-scoped consent covers only documents attached to that case.
                case = db.get(Case, g.case_id)
                if case is None or case_access(ctx, case) is None:
                    continue
                linked = db.execute(
                    select(EvidenceLink.id).where(EvidenceLink.document_id == doc.id, EvidenceLink.case_id == g.case_id)
                ).first()
                if not linked:
                    continue
            return DocAccess("consent", consent=g)
        return None
    if ws == "professional" and ctx.role == "professional":
        for d in active_delegations(db, ctx.user.id, ctx.tenant_id):
            if d.principal_user_id != doc.owner_user_id or "view_documents" not in d.scopes:
                continue
            if doc.category not in (d.document_categories or []):
                continue
            if d.case_id is not None:
                linked = db.execute(
                    select(EvidenceLink.id).where(EvidenceLink.document_id == doc.id, EvidenceLink.case_id == d.case_id)
                ).first()
                if not linked:
                    continue
            return DocAccess("delegation", delegation=d)
        return None
    return None


def get_document(ctx: Ctx, doc_id: uuid.UUID) -> tuple[Document, DocAccess]:
    doc = ctx.db.get(Document, doc_id)
    acc = document_access(ctx, doc) if doc else None
    if doc is None or acc is None:
        raise deny(ctx, "document.access_denied", "document", doc_id, "no_document_access")
    return doc, acc


def require_clean(version: DocumentVersion) -> None:
    if version.object.scan_status != "clean":
        raise AppError(
            423,
            "file_not_available",
            f"This file is not available (scan status: {version.object.scan_status}). Files are only served after a clean malware scan.",
        )


def receipt(ctx: Ctx, doc: Document, acc: DocAccess, action: str) -> None:
    if acc.via == "owner":
        return
    ctx.db.add(
        ShareReceipt(
            consent_grant_id=acc.consent.id if acc.consent else None,
            delegation_id=acc.delegation.id if acc.delegation else None,
            owner_user_id=doc.owner_user_id,
            document_id=doc.id,
            accessed_by_user_id=ctx.user.id,
            accessed_by_tenant_id=ctx.tenant_id,
            action=action,
            at=utcnow(),
        )
    )


def accessible_document_ids(ctx: Ctx, owner_user_id: uuid.UUID | None = None) -> list[uuid.UUID]:
    """All document ids the context may read (used to pre-filter retrieval before any vector search)."""
    q = select(Document).where(Document.deleted_at.is_(None))
    if ctx.workspace == "citizen":
        q = q.where(Document.owner_user_id == ctx.user.id)
    elif ctx.workspace in ("authority", "institution"):
        owners = select(ConsentGrant.owner_user_id).where(
            ConsentGrant.recipient_tenant_id == ctx.tenant_id, ConsentGrant.status == "active"
        )
        q = q.where(Document.owner_user_id.in_(owners))
    elif ctx.workspace == "professional":
        q = q.where(Document.owner_user_id.in_([d.principal_user_id for d in active_delegations(ctx.db, ctx.user.id, ctx.tenant_id)]))
    else:
        return []
    if owner_user_id is not None:
        q = q.where(Document.owner_user_id == owner_user_id)
    out = []
    for d in ctx.db.execute(q).scalars():
        if document_access(ctx, d) is not None:
            out.append(d.id)
    return out


def ensure_participant(
    db: Session,
    case: Case,
    tenant_id: uuid.UUID,
    role: str,
    via: str,
    consent_grant_id: uuid.UUID | None = None,
) -> CaseParticipant:
    p = db.execute(
        select(CaseParticipant).where(
            and_(CaseParticipant.case_id == case.id, CaseParticipant.tenant_id == tenant_id, CaseParticipant.role == role)
        )
    ).scalar_one_or_none()
    if p is None:
        p = CaseParticipant(case_id=case.id, tenant_id=tenant_id, role=role, granted_via=via, consent_grant_id=consent_grant_id)
        db.add(p)
    else:
        p.status = "active"
        p.ended_at = None
        if consent_grant_id:
            p.consent_grant_id = consent_grant_id
    db.flush()
    return p
