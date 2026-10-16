"""Country > Region > Municipality > Authority > Service > Procedure > RuleSet > RuleVersion.

Plus source provenance (SourceRecord / SourcePassage) and jurisdiction packs.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Boolean, Date, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.common import IdMixin, TimestampMixin, tz

EMBED_DIM = 256


class JurisdictionPack(IdMixin, TimestampMixin, Base):
    __tablename__ = "jurisdiction_packs"
    __table_args__ = (UniqueConstraint("code", "version"),)
    code: Mapped[str] = mapped_column(String(16))
    version: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(200))
    checksum: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="synthetic_illustrative")
    loaded_at: Mapped[datetime] = mapped_column(tz())
    notes: Mapped[str] = mapped_column(Text, default="")


class Jurisdiction(IdMixin, TimestampMixin, Base):
    __tablename__ = "jurisdictions"
    code: Mapped[str] = mapped_column(String(32), unique=True)  # IL, IL-TA, DE, DE-BE, DE-BE-BER, US, US-CA, US-CA-SF
    name: Mapped[str] = mapped_column(String(200))
    level: Mapped[str] = mapped_column(String(16))  # country | region | municipality | supranational
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jurisdictions.id"))
    pack_code: Mapped[str] = mapped_column(String(16))
    locale: Mapped[str] = mapped_column(String(16))  # e.g. he-IL
    currency: Mapped[str] = mapped_column(String(3))
    timezone: Mapped[str] = mapped_column(String(64))
    weekend_days: Mapped[list] = mapped_column(JSON, default=list)  # ISO weekday numbers 1..7
    address_format: Mapped[list] = mapped_column(JSON, default=list)
    retention_default_days: Mapped[int] = mapped_column(Integer, default=3650)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)


class Holiday(IdMixin, Base):
    __tablename__ = "holidays"
    __table_args__ = (UniqueConstraint("jurisdiction_id", "day"),)
    jurisdiction_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jurisdictions.id"), index=True)
    day: Mapped[date] = mapped_column(Date)
    name: Mapped[str] = mapped_column(String(200))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)


class Authority(IdMixin, TimestampMixin, Base):
    __tablename__ = "authorities"
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    jurisdiction_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jurisdictions.id"))
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id"))
    kind: Mapped[str] = mapped_column(String(32))  # authority | institution
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)
    jurisdiction: Mapped[Jurisdiction] = relationship(lazy="joined")


class Service(IdMixin, TimestampMixin, Base):
    __tablename__ = "services"
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    authority_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("authorities.id"))
    sla_working_days: Mapped[int] = mapped_column(Integer, default=10)
    authority: Mapped[Authority] = relationship(lazy="joined")


class Procedure(IdMixin, TimestampMixin, Base):
    __tablename__ = "procedures"
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    service_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("services.id"))
    description: Mapped[str] = mapped_column(Text, default="")
    service: Mapped[Service] = relationship(lazy="joined")


class SourceRecord(IdMixin, TimestampMixin, Base):
    """Provenance for rules and passages. URL is null for synthetic placeholders: we never invent URLs."""

    __tablename__ = "source_records"
    code: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(String(300))
    publisher: Mapped[str] = mapped_column(String(200))
    jurisdiction_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jurisdictions.id"))
    url: Mapped[str | None] = mapped_column(String(500))
    is_placeholder: Mapped[bool] = mapped_column(Boolean, default=True)
    language: Mapped[str] = mapped_column(String(8))
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    review_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(32), default="synthetic_placeholder")
    trust_label: Mapped[str] = mapped_column(String(32), default="synthetic")
    jurisdiction: Mapped[Jurisdiction] = relationship(lazy="joined")


class SourcePassage(IdMixin, Base):
    __tablename__ = "source_passages"
    source_record_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_records.id", ondelete="CASCADE"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    anchor: Mapped[str] = mapped_column(String(64))
    text: Mapped[str] = mapped_column(Text)
    embedding = mapped_column(Vector(EMBED_DIM))
    source: Mapped[SourceRecord] = relationship(lazy="joined")


class RuleSet(IdMixin, TimestampMixin, Base):
    __tablename__ = "rule_sets"
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    procedure_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("procedures.id"))
    pack_code: Mapped[str] = mapped_column(String(16))
    consequential: Mapped[bool] = mapped_column(Boolean, default=True)
    topic: Mapped[str] = mapped_column(String(64))
    procedure: Mapped[Procedure] = relationship(lazy="joined")
    versions: Mapped[list[RuleVersion]] = relationship(back_populates="rule_set", order_by="RuleVersion.version")


class RuleVersion(IdMixin, TimestampMixin, Base):
    __tablename__ = "rule_versions"
    __table_args__ = (UniqueConstraint("rule_set_id", "version"),)
    rule_set_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rule_sets.id"))
    version: Mapped[str] = mapped_column(String(16))
    pack_version: Mapped[str] = mapped_column(String(16))
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    language: Mapped[str] = mapped_column(String(8))
    review_date: Mapped[date] = mapped_column(Date)
    review_status: Mapped[str] = mapped_column(String(32))  # synthetic_unreviewed | reviewed | needs_review
    verification_status: Mapped[str] = mapped_column(String(32), default="synthetic_illustrative")
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    questions: Mapped[list] = mapped_column(JSON, default=list)
    logic: Mapped[dict] = mapped_column(JSON, default=dict)
    required_evidence: Mapped[list] = mapped_column(JSON, default=list)
    source_record_ids: Mapped[list] = mapped_column(JSON, default=list)
    appeal_guidance: Mapped[str] = mapped_column(Text, default="")
    rule_set: Mapped[RuleSet] = relationship(back_populates="versions", lazy="joined")


class WorkflowTemplate(IdMixin, TimestampMixin, Base):
    """Life-event journey template composed from one or more jurisdiction packs."""

    __tablename__ = "workflow_templates"
    code: Mapped[str] = mapped_column(String(64), unique=True)
    life_event_type: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(200))
    origin_code: Mapped[str | None] = mapped_column(String(32))
    destination_code: Mapped[str | None] = mapped_column(String(32))
    pack_versions: Mapped[dict] = mapped_column(JSON, default=dict)
    definition: Mapped[dict] = mapped_column(JSON, default=dict)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)
