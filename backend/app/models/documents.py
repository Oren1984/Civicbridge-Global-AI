"""Stored objects, wallet documents, versions, evidence, consent, delegation, translations, privacy requests."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, ForeignKey, Integer, String, Text
from pgvector.sqlalchemy import Vector
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.jurisdiction import EMBED_DIM
from app.models.common import IdMixin, TimestampMixin, tz

SCAN_STATES = ("pending", "clean", "infected", "scan_unavailable", "error")


class StoredObject(IdMixin, TimestampMixin, Base):
    """Every uploaded byte goes through this table: quota, allowlist, hash and malware scan state.

    Only scan_status == 'clean' objects can ever be previewed or downloaded.
    """

    __tablename__ = "stored_objects"
    storage_key: Mapped[str] = mapped_column(String(300), unique=True)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id"))
    purpose: Mapped[str] = mapped_column(String(32))  # document | incident_media | resolution_evidence | export | derived
    original_filename: Mapped[str] = mapped_column(String(300))
    safe_filename: Mapped[str] = mapped_column(String(200))
    mime: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    scan_status: Mapped[str] = mapped_column(String(24), default="pending")
    scan_detail: Mapped[str] = mapped_column(String(300), default="")
    scan_attempts: Mapped[int] = mapped_column(Integer, default=0)
    scanned_at: Mapped[datetime | None] = mapped_column(tz())
    deleted_at: Mapped[datetime | None] = mapped_column(tz())


class Document(IdMixin, TimestampMixin, Base):
    __tablename__ = "documents"
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    category: Mapped[str] = mapped_column(String(32))  # identity | civil_status | employment | education | financial | housing | health | other
    doc_type: Mapped[str] = mapped_column(String(64), default="other")
    issuer: Mapped[str] = mapped_column(String(200), default="")
    issuing_jurisdiction_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jurisdictions.id"))
    issued_at: Mapped[datetime | None] = mapped_column(tz())
    expires_at: Mapped[datetime | None] = mapped_column(tz())
    verification_status: Mapped[str] = mapped_column(String(32), default="unverified")
    language: Mapped[str] = mapped_column(String(8), default="en")
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    retention_until: Mapped[datetime | None] = mapped_column(tz())
    deleted_at: Mapped[datetime | None] = mapped_column(tz())
    versions: Mapped[list[DocumentVersion]] = relationship(
        back_populates="document", order_by="DocumentVersion.version", lazy="selectin"
    )


class DocumentVersion(IdMixin, TimestampMixin, Base):
    __tablename__ = "document_versions"
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    object_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stored_objects.id"))
    kind: Mapped[str] = mapped_column(String(24), default="original")  # original | redacted_derivative
    derived_from_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("document_versions.id"))
    extracted_text: Mapped[str | None] = mapped_column(Text)
    extraction_status: Mapped[str] = mapped_column(String(32), default="pending")
    note: Mapped[str] = mapped_column(String(500), default="")
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    document: Mapped[Document] = relationship(back_populates="versions")
    object: Mapped[StoredObject] = relationship(lazy="joined")


class DocumentChunk(IdMixin, Base):
    """Extracted text chunks of a clean document version, for retrieval. Always filtered by document access first."""

    __tablename__ = "document_chunks"
    document_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_versions.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    embedding = mapped_column(Vector(EMBED_DIM))


class EvidenceLink(IdMixin, TimestampMixin, Base):
    __tablename__ = "evidence_links"
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    service_request_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("service_requests.id", ondelete="SET NULL"))
    evidence_key: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(16), default="attached")  # attached | submitted | accepted | rejected | needs_more
    review_note: Mapped[str] = mapped_column(Text, default="")
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(tz())
    linked_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))


class ConsentGrant(IdMixin, TimestampMixin, Base):
    """Purpose-bound, recipient-bound, category-bound, time-limited consent. Revocation stops future access only."""

    __tablename__ = "consent_grants"
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    recipient_tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    recipient_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    case_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))
    purpose: Mapped[str] = mapped_column(String(300))
    data_categories: Mapped[list] = mapped_column(JSON, default=list)
    document_ids: Mapped[list | None] = mapped_column(JSON)  # None = all documents in the categories
    valid_from: Mapped[datetime] = mapped_column(tz())
    valid_until: Mapped[datetime] = mapped_column(tz())
    status: Mapped[str] = mapped_column(String(16), default="active")  # pending | active | declined | revoked | expired
    revoked_at: Mapped[datetime | None] = mapped_column(tz())
    revoke_reason: Mapped[str] = mapped_column(String(300), default="")
    # Set when an authority/institution asked for this consent (e.g. an interagency handoff request).
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    requested_by_tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id"))
    handoff: Mapped[bool] = mapped_column(Boolean, default=False)
    valid_days: Mapped[int] = mapped_column(Integer, default=30)


class ShareReceipt(IdMixin, Base):
    __tablename__ = "share_receipts"
    consent_grant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("consent_grants.id", ondelete="SET NULL"))
    delegation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("delegations.id", ondelete="SET NULL"))
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    accessed_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    accessed_by_tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id"))
    action: Mapped[str] = mapped_column(String(16))  # metadata | preview | download | meeting_view
    at: Mapped[datetime] = mapped_column(tz())


class Delegation(IdMixin, TimestampMixin, Base):
    __tablename__ = "delegations"
    principal_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    delegate_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    delegate_tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"))
    case_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    document_categories: Mapped[list] = mapped_column(JSON, default=list)
    purpose: Mapped[str] = mapped_column(String(300), default="")
    valid_from: Mapped[datetime] = mapped_column(tz())
    valid_until: Mapped[datetime] = mapped_column(tz())
    status: Mapped[str] = mapped_column(String(16), default="active")  # pending | active | revoked | expired
    revoked_at: Mapped[datetime | None] = mapped_column(tz())


class Translation(IdMixin, TimestampMixin, Base):
    """Assisted translation. Never a certified translation (is_certified stays False)."""

    __tablename__ = "translations"
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    document_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("document_versions.id", ondelete="CASCADE"))
    case_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cases.id", ondelete="SET NULL"))
    source_lang: Mapped[str] = mapped_column(String(8))
    target_lang: Mapped[str] = mapped_column(String(8))
    source_text: Mapped[str] = mapped_column(Text)
    target_text: Mapped[str] = mapped_column(Text, default="")
    segments: Mapped[list] = mapped_column(JSON, default=list)
    mode: Mapped[str] = mapped_column(String(16))  # mock | ollama | manual
    status: Mapped[str] = mapped_column(String(24), default="needs_review")  # needs_review | reviewed | rejected | unsupported
    uncertainty: Mapped[list] = mapped_column(JSON, default=list)
    reviewer_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(tz())
    review_note: Mapped[str] = mapped_column(Text, default="")
    is_certified: Mapped[bool] = mapped_column(Boolean, default=False)


class PrivacyRequest(IdMixin, TimestampMixin, Base):
    __tablename__ = "privacy_requests"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # export | deletion | access
    status: Mapped[str] = mapped_column(String(24), default="queued")  # queued | processing | completed | rejected | partially_completed
    result_object_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("stored_objects.id"))
    notes: Mapped[str] = mapped_column(Text, default="")
    completed_at: Mapped[datetime | None] = mapped_column(tz())
