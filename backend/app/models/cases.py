"""Cases, participation, timeline, tasks, life events, service requests, decisions and appeals."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.common import IdMixin, TimestampMixin, tz


class Case(IdMixin, TimestampMixin, Base):
    __tablename__ = "cases"
    reference: Mapped[str] = mapped_column(String(32), unique=True)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    case_type: Mapped[str] = mapped_column(String(32))  # life_event | rights | incident | general
    status: Mapped[str] = mapped_column(String(24), default="open")  # open | closed | archived
    jurisdiction_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jurisdictions.id"))
    summary: Mapped[str] = mapped_column(Text, default="")
    retention_until: Mapped[datetime | None] = mapped_column(tz())
    version: Mapped[int] = mapped_column(Integer, default=1)


class CaseParticipant(IdMixin, TimestampMixin, Base):
    """Explicit participation is the only route to a case for non-owners. It never relaxes tenant isolation:
    each participant row names exactly one tenant and how the access was granted."""

    __tablename__ = "case_participants"
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(String(24))  # authority | institution | professional
    granted_via: Mapped[str] = mapped_column(String(24))  # submission | handoff | delegation | consent
    consent_grant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("consent_grants.id"))
    delegation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("delegations.id"))
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | ended
    scope: Mapped[dict] = mapped_column(JSON, default=dict)
    ended_at: Mapped[datetime | None] = mapped_column(tz())


class CaseEvent(IdMixin, Base):
    """Unified case timeline. visibility=internal entries are only shown to the acting authority tenant."""

    __tablename__ = "case_events"
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    at: Mapped[datetime] = mapped_column(tz())
    kind: Mapped[str] = mapped_column(String(48))
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    actor_tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id"))
    actor_label: Mapped[str] = mapped_column(String(200), default="")
    summary: Mapped[str] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    visibility: Mapped[str] = mapped_column(String(16), default="all")
    visible_tenant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class LifeEvent(IdMixin, TimestampMixin, Base):
    __tablename__ = "life_events"
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))
    template_code: Mapped[str] = mapped_column(String(64))
    event_type: Mapped[str] = mapped_column(String(32))
    origin_jurisdiction_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jurisdictions.id"))
    destination_jurisdiction_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jurisdictions.id"))
    target_date: Mapped[datetime | None] = mapped_column(tz())
    status: Mapped[str] = mapped_column(String(24), default="active")
    answers: Mapped[dict] = mapped_column(JSON, default=dict)


class Task(IdMixin, TimestampMixin, Base):
    __tablename__ = "tasks"
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    jurisdiction_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jurisdictions.id"))
    phase: Mapped[str] = mapped_column(String(32), default="intake")
    status: Mapped[str] = mapped_column(String(16), default="todo")  # todo | in_progress | blocked | done | skipped
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    depends_on: Mapped[list] = mapped_column(JSON, default=list)
    required_evidence: Mapped[list] = mapped_column(JSON, default=list)
    due_at: Mapped[datetime | None] = mapped_column(tz())
    deadline_basis: Mapped[str] = mapped_column(String(200), default="")
    requires_human_review: Mapped[bool] = mapped_column(Boolean, default=False)
    procedure_code: Mapped[str | None] = mapped_column(String(64))
    assignee_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reminder_sent_at: Mapped[datetime | None] = mapped_column(tz())
    completed_at: Mapped[datetime | None] = mapped_column(tz())
    completed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class ServiceRequest(IdMixin, TimestampMixin, Base):
    """A case's request to one authority tenant. Authority work happens here; state machine enforced server-side.

    channel='simulated' means the request was routed to a synthetic authority tenant inside CivicBridge.
    It is never an official submission to a real government.
    """

    __tablename__ = "service_requests"
    reference: Mapped[str] = mapped_column(String(32), unique=True)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    procedure_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("procedures.id"))
    kind: Mapped[str] = mapped_column(String(24), default="application")  # application | rights_review | appeal | handoff
    title: Mapped[str] = mapped_column(String(300))
    state: Mapped[str] = mapped_column(String(24), default="draft")
    queue: Mapped[str] = mapped_column(String(48), default="general")
    priority: Mapped[str] = mapped_column(String(12), default="normal")
    assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    channel: Mapped[str] = mapped_column(String(24), default="simulated")
    submitted_at: Mapped[datetime | None] = mapped_column(tz())
    sla_due_at: Mapped[datetime | None] = mapped_column(tz())
    sla_paused_at: Mapped[datetime | None] = mapped_column(tz())
    sla_breached: Mapped[bool] = mapped_column(Boolean, default=False)
    escalation_level: Mapped[int] = mapped_column(Integer, default=0)
    parent_request_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("service_requests.id"))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    closed_at: Mapped[datetime | None] = mapped_column(tz())
    version: Mapped[int] = mapped_column(Integer, default=1)
    case: Mapped[Case] = relationship(lazy="joined")


class InformationRequest(IdMixin, TimestampMixin, Base):
    __tablename__ = "information_requests"
    service_request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("service_requests.id", ondelete="CASCADE"), index=True)
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    message: Mapped[str] = mapped_column(Text)
    items: Mapped[list] = mapped_column(JSON, default=list)
    due_at: Mapped[datetime | None] = mapped_column(tz())
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | answered | cancelled
    response: Mapped[str | None] = mapped_column(Text)
    responded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    responded_at: Mapped[datetime | None] = mapped_column(tz())


class Decision(IdMixin, TimestampMixin, Base):
    """Versioned decision with rationale. proposed_by and approved_by must differ (four-eyes)."""

    __tablename__ = "decisions"
    service_request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("service_requests.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(String(24))  # approved | rejected | partially_approved | referred
    rationale: Mapped[str] = mapped_column(Text)
    rule_version_ids: Mapped[list] = mapped_column(JSON, default=list)
    proposed_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(16), default="proposed")  # proposed | approved | returned | superseded
    approved_at: Mapped[datetime | None] = mapped_column(tz())
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("decisions.id"))
    appeal_deadline: Mapped[datetime | None] = mapped_column(tz())
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=True)


class Appeal(IdMixin, TimestampMixin, Base):
    __tablename__ = "appeals"
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    decision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("decisions.id"))
    follow_up_request_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("service_requests.id"))
    filed_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    grounds: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="filed")  # filed | under_review | resolved | withdrawn
    resolution_decision_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("decisions.id"))


class ScreeningResult(IdMixin, TimestampMixin, Base):
    """Rights Navigator screening output. Always an indication, never an official eligibility determination."""

    __tablename__ = "screening_results"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    case_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cases.id", ondelete="SET NULL"))
    rule_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rule_versions.id"))
    answers: Mapped[dict] = mapped_column(JSON, default=dict)
    indication: Mapped[str] = mapped_column(String(32))  # likely_applicable | likely_not_applicable | insufficient_information
    explanation: Mapped[list] = mapped_column(JSON, default=list)
    missing: Mapped[list] = mapped_column(JSON, default=list)
    uncertainty: Mapped[list] = mapped_column(JSON, default=list)
    citations: Mapped[list] = mapped_column(JSON, default=list)
    requires_human_review: Mapped[bool] = mapped_column(Boolean, default=True)
    review_request_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("service_requests.id"))
