"""Messages, notifications, drafts/offline sync, appointments, meetings, emergency notices, incidents."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.common import IdMixin, TimestampMixin, tz


class Message(IdMixin, TimestampMixin, Base):
    __tablename__ = "messages"
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    sender_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    sender_tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id"))
    sender_label: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    on_behalf_of_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    ai_drafted: Mapped[bool] = mapped_column(Boolean, default=False)


class Notification(IdMixin, TimestampMixin, Base):
    __tablename__ = "notifications"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id"))
    kind: Mapped[str] = mapped_column(String(48))
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str] = mapped_column(String(300), default="")
    read_at: Mapped[datetime | None] = mapped_column(tz())
    emailed_at: Mapped[datetime | None] = mapped_column(tz())


class NotificationPreference(IdMixin, Base):
    __tablename__ = "notification_preferences"
    __table_args__ = (UniqueConstraint("user_id", "category"),)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    category: Mapped[str] = mapped_column(String(32))  # case | message | deadline | meeting | incident | security | emergency
    in_app: Mapped[bool] = mapped_column(Boolean, default=True)
    email: Mapped[bool] = mapped_column(Boolean, default=False)


class Draft(IdMixin, TimestampMixin, Base):
    """Saved drafts (also the target of offline replay). version enables conflict detection."""

    __tablename__ = "drafts"
    __table_args__ = (UniqueConstraint("user_id", "draft_key"),)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    draft_key: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(32))  # incident_report | case_message | case_note | life_event_note
    title: Mapped[str] = mapped_column(String(300), default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    deleted_at: Mapped[datetime | None] = mapped_column(tz())


class SyncOperation(IdMixin, Base):
    __tablename__ = "sync_operations"
    __table_args__ = (UniqueConstraint("user_id", "idempotency_key"),)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    idempotency_key: Mapped[str] = mapped_column(String(80))
    op: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))  # applied | conflict | rejected
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    at: Mapped[datetime] = mapped_column(tz())


class Appointment(IdMixin, TimestampMixin, Base):
    __tablename__ = "appointments"
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    starts_at: Mapped[datetime] = mapped_column(tz())  # stored UTC
    duration_minutes: Mapped[int] = mapped_column(Integer, default=30)
    organizer_timezone: Mapped[str] = mapped_column(String(64))
    organizer_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    organizer_tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id"))
    mode: Mapped[str] = mapped_column(String(16), default="video")  # video | in_person | phone
    status: Mapped[str] = mapped_column(String(16), default="scheduled")  # scheduled | cancelled | completed
    meeting_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("meetings.id"))


class Meeting(IdMixin, TimestampMixin, Base):
    __tablename__ = "meetings"
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    room_name: Mapped[str] = mapped_column(String(80), unique=True)
    host_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    host_tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id"))
    scheduled_start: Mapped[datetime] = mapped_column(tz())
    duration_minutes: Mapped[int] = mapped_column(Integer, default=30)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    status: Mapped[str] = mapped_column(String(16), default="scheduled")  # scheduled | open | ended | cancelled
    recording_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    opened_at: Mapped[datetime | None] = mapped_column(tz())
    ended_at: Mapped[datetime | None] = mapped_column(tz())


class MeetingParticipant(IdMixin, TimestampMixin, Base):
    __tablename__ = "meeting_participants"
    __table_args__ = (UniqueConstraint("meeting_id", "user_id"),)
    meeting_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("meetings.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id"))
    role: Mapped[str] = mapped_column(String(24))  # host | citizen | authority | institution | professional | interpreter
    display_name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16), default="invited")  # invited | waiting | admitted | left | removed | revoked
    invite_expires_at: Mapped[datetime] = mapped_column(tz())
    identity: Mapped[str] = mapped_column(String(80))
    admitted_at: Mapped[datetime | None] = mapped_column(tz())
    removed_at: Mapped[datetime | None] = mapped_column(tz())
    last_token_at: Mapped[datetime | None] = mapped_column(tz())


class MeetingSharedDocument(IdMixin, TimestampMixin, Base):
    __tablename__ = "meeting_shared_documents"
    __table_args__ = (UniqueConstraint("meeting_id", "document_id"),)
    meeting_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("meetings.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    shared_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class EmergencyNotice(IdMixin, TimestampMixin, Base):
    __tablename__ = "emergency_notices"
    jurisdiction_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jurisdictions.id"))
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(16))  # info | advisory | warning | critical
    source_label: Mapped[str] = mapped_column(String(300))
    source_kind: Mapped[str] = mapped_column(String(32), default="synthetic_demo")  # synthetic_demo | official_placeholder | authority_tenant
    issued_by_tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id"))
    fallback_instructions: Mapped[str] = mapped_column(Text, default="")
    issued_at: Mapped[datetime] = mapped_column(tz())
    expires_at: Mapped[datetime | None] = mapped_column(tz())


class Incident(IdMixin, TimestampMixin, Base):
    __tablename__ = "incidents"
    reference: Mapped[str] = mapped_column(String(32), unique=True)
    reporter_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)  # responsible municipal authority
    case_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cases.id", ondelete="SET NULL"))
    category: Mapped[str] = mapped_column(String(32))
    category_source: Mapped[str] = mapped_column(String(24), default="reporter")  # reporter | rules_suggestion
    description: Mapped[str] = mapped_column(Text)
    lat_approx: Mapped[float | None] = mapped_column(Float)
    lon_approx: Mapped[float | None] = mapped_column(Float)
    location_text: Mapped[str] = mapped_column(String(300), default="")
    location_precision: Mapped[str] = mapped_column(String(16), default="none")  # none | approx_110m | text_only
    status: Mapped[str] = mapped_column(String(16), default="submitted")
    priority: Mapped[str] = mapped_column(String(12), default="normal")
    queue: Mapped[str] = mapped_column(String(48), default="public_works")
    assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("incidents.id"))
    sla_due_at: Mapped[datetime | None] = mapped_column(tz())
    sla_breached: Mapped[bool] = mapped_column(Boolean, default=False)
    resolved_at: Mapped[datetime | None] = mapped_column(tz())
    closed_at: Mapped[datetime | None] = mapped_column(tz())
    feedback_rating: Mapped[int | None] = mapped_column(Integer)
    feedback_comment: Mapped[str | None] = mapped_column(Text)
    client_draft_key: Mapped[str | None] = mapped_column(String(120))


class IncidentMedia(IdMixin, TimestampMixin, Base):
    __tablename__ = "incident_media"
    incident_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    object_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stored_objects.id"))
    kind: Mapped[str] = mapped_column(String(16))  # image | audio
    role: Mapped[str] = mapped_column(String(24), default="report")  # report | resolution_evidence
    transcription_status: Mapped[str] = mapped_column(String(24), default="not_applicable")  # unavailable | fixture | not_applicable
    transcription_text: Mapped[str | None] = mapped_column(Text)
    analysis_note: Mapped[str] = mapped_column(String(300), default="")


class IncidentUpdate(IdMixin, TimestampMixin, Base):
    __tablename__ = "incident_updates"
    incident_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    author_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(24))  # status | public_update | internal_note | resolution | feedback
    body: Mapped[str] = mapped_column(Text)
    public: Mapped[bool] = mapped_column(Boolean, default=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
