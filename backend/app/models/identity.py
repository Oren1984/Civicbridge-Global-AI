"""Users, tenants, memberships, sessions and one-time tokens."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.common import IdMixin, TimestampMixin, tz

# Tenant kinds
TENANT_KINDS = ("citizen_space", "authority", "institution", "professional_org", "governance")

# Roles and the workspace each one opens
ROLE_WORKSPACE = {
    "citizen": "citizen",
    "authority_officer": "authority",
    "authority_supervisor": "authority",
    "institution_liaison": "institution",
    "professional": "professional",
    "interpreter": "professional",
    "governance_admin": "governance",
    "governance_auditor": "governance",
}
PRIVILEGED_ROLES = {
    "authority_officer",
    "authority_supervisor",
    "institution_liaison",
    "governance_admin",
    "governance_auditor",
}


class Tenant(IdMixin, TimestampMixin, Base):
    __tablename__ = "tenants"
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(32))
    jurisdiction_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jurisdictions.id"))
    settings: Mapped[dict] = mapped_column(JSON, default=dict)


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))
    locale: Mapped[str] = mapped_column(String(8), default="en")
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_read_only: Mapped[bool] = mapped_column(Boolean, default=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(tz())
    mfa_secret_enc: Mapped[str | None] = mapped_column(Text)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    mfa_last_step: Mapped[int | None] = mapped_column(Integer)  # replay protection for TOTP
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(tz())
    password_changed_at: Mapped[datetime | None] = mapped_column(tz())

    memberships: Mapped[list[Membership]] = relationship(back_populates="user", lazy="selectin")


class Membership(IdMixin, TimestampMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "tenant_id", "role"),)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    role: Mapped[str] = mapped_column(String(40))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    user: Mapped[User] = relationship(back_populates="memberships")
    tenant: Mapped[Tenant] = relationship(lazy="joined")

    @property
    def workspace(self) -> str:
        return ROLE_WORKSPACE.get(self.role, "citizen")


class AuthSession(TimestampMixin, Base):
    """Server-side session. The cookie carries a random token; only its SHA-256 is stored."""

    __tablename__ = "auth_sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # sha256(token)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    membership_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("memberships.id"))
    csrf_token: Mapped[str] = mapped_column(String(64))
    mfa_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    last_seen_at: Mapped[datetime] = mapped_column(tz())
    idle_expires_at: Mapped[datetime] = mapped_column(tz())
    absolute_expires_at: Mapped[datetime] = mapped_column(tz())
    revoked_at: Mapped[datetime | None] = mapped_column(tz())
    revoked_reason: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    ip_hash: Mapped[str | None] = mapped_column(String(64))


class OneTimeToken(IdMixin, TimestampMixin, Base):
    """Email verification, password recovery and invitation tokens (hash stored only)."""

    __tablename__ = "one_time_tokens"
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    email: Mapped[str] = mapped_column(String(254))
    purpose: Mapped[str] = mapped_column(String(32))  # verify_email | reset_password | invitation
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    expires_at: Mapped[datetime] = mapped_column(tz())
    used_at: Mapped[datetime | None] = mapped_column(tz())
