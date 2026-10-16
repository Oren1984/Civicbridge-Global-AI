"""Audit chain, jobs, policies, risks, security incidents, integrations, AI tool calls, analytics snapshots."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.common import IdMixin, TimestampMixin, tz


class AuditEvent(Base):
    """Append-only (enforced by a DB trigger) and hash-chained. details never contain document contents."""

    __tablename__ = "audit_events"
    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(tz(), index=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    actor_tenant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    actor_role: Mapped[str | None] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(80), index=True)
    resource_type: Mapped[str] = mapped_column(String(48))
    resource_id: Mapped[str | None] = mapped_column(String(80), index=True)
    subject_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)  # whose data was touched
    outcome: Mapped[str] = mapped_column(String(16))  # success | denied | error
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


class Job(IdMixin, TimestampMixin, Base):
    __tablename__ = "jobs"
    kind: Mapped[str] = mapped_column(String(48), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)  # queued | running | succeeded | failed | dead
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    run_after: Mapped[datetime] = mapped_column(tz(), index=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    locked_by: Mapped[str | None] = mapped_column(String(80))
    locked_at: Mapped[datetime | None] = mapped_column(tz())
    finished_at: Mapped[datetime | None] = mapped_column(tz())
    dedupe_key: Mapped[str | None] = mapped_column(String(120), index=True)


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"
    worker_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    seen_at: Mapped[datetime] = mapped_column(tz())
    info: Mapped[dict] = mapped_column(JSON, default=dict)


class Policy(Base):
    __tablename__ = "policies"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
    description: Mapped[str] = mapped_column(Text, default="")
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    updated_at: Mapped[datetime] = mapped_column(tz())


class Risk(IdMixin, TimestampMixin, Base):
    __tablename__ = "risks"
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(32), default="operational")
    likelihood: Mapped[int] = mapped_column(Integer, default=3)
    impact: Mapped[int] = mapped_column(Integer, default=3)
    owner: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | mitigating | accepted | closed
    mitigation: Mapped[str] = mapped_column(Text, default="")


class SecurityIncident(IdMixin, TimestampMixin, Base):
    __tablename__ = "security_incidents"
    title: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(24))  # security | privacy_breach | availability | integrity
    severity: Mapped[str] = mapped_column(String(12))  # low | medium | high | critical
    status: Mapped[str] = mapped_column(String(24), default="open")  # open | triaged | contained | notified | closed
    description: Mapped[str] = mapped_column(Text, default="")
    detected_at: Mapped[datetime] = mapped_column(tz())
    personal_data_involved: Mapped[bool] = mapped_column(Boolean, default=False)
    notification_due_at: Mapped[datetime | None] = mapped_column(tz())
    timeline: Mapped[list] = mapped_column(JSON, default=list)
    reported_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class IntegrationAdapter(IdMixin, TimestampMixin, Base):
    __tablename__ = "integration_adapters"
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    jurisdiction_code: Mapped[str | None] = mapped_column(String(32))
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id"))
    state: Mapped[str] = mapped_column(String(24))  # mock | public_data | sandbox | authorized_live
    capabilities: Mapped[list] = mapped_column(JSON, default=list)
    description: Mapped[str] = mapped_column(Text, default="")
    health_status: Mapped[str] = mapped_column(String(16), default="unknown")  # healthy | degraded | down | unknown
    last_check_at: Mapped[datetime | None] = mapped_column(tz())
    last_error: Mapped[str] = mapped_column(Text, default="")
    timeout_ms: Mapped[int] = mapped_column(Integer, default=3000)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    failure_injection: Mapped[str] = mapped_column(String(24), default="none")  # none | timeout | error (demo/testing)


class IntegrationRun(IdMixin, TimestampMixin, Base):
    __tablename__ = "integration_runs"
    adapter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("integration_adapters.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True)
    operation: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))  # pending | success | retrying | dead_letter
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    request_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    response_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    service_request_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("service_requests.id", ondelete="SET NULL"))
    finished_at: Mapped[datetime | None] = mapped_column(tz())


class AIToolCall(IdMixin, TimestampMixin, Base):
    __tablename__ = "ai_tool_calls"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id"))
    tool: Mapped[str] = mapped_column(String(64))
    mode: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24))  # executed | denied | pending_approval | approved | rejected | timeout | error | invalid
    input: Mapped[dict] = mapped_column(JSON, default=dict)
    output: Mapped[dict] = mapped_column(JSON, default=dict)
    reason: Mapped[str] = mapped_column(Text, default="")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(tz())


class AnalyticsSnapshot(IdMixin, Base):
    __tablename__ = "analytics_snapshots"
    scope: Mapped[str] = mapped_column(String(64), index=True)  # public | tenant:<id>
    payload: Mapped[dict] = mapped_column(JSON)
    computed_at: Mapped[datetime] = mapped_column(tz())
