"""Request context: session resolution, expiry, CSRF, read-only enforcement, MFA gate and role checks.

Every authenticated route depends on ``get_ctx``. Mutations by read-only accounts are rejected here,
centrally, so no individual route can forget the check (deny by default).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db, utcnow
from app.errors import AppError, forbidden
from app.models import AuthSession, Membership, User
from app.models.identity import PRIVILEGED_ROLES, ROLE_WORKSPACE
from app.security.crypto import sha256_hex
from app.services import audit, policies

SESSION_COOKIE = "cb_session"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
# Unsafe endpoints a read-only account may still call: ending or re-scoping its own session only.
READ_ONLY_ALLOWED = {"/api/auth/logout", "/api/auth/context"}
# Endpoints reachable before MFA is satisfied for a privileged membership.
PRE_MFA_ALLOWED = {
    "/api/auth/me",
    "/api/auth/logout",
    "/api/auth/mfa/verify",
    "/api/auth/mfa/setup",
    "/api/auth/mfa/enable",
    "/api/auth/context",
}


@dataclass
class Ctx:
    user: User
    session: AuthSession
    membership: Membership | None
    db: Session

    @property
    def role(self) -> str | None:
        return self.membership.role if self.membership else None

    @property
    def tenant_id(self) -> uuid.UUID | None:
        return self.membership.tenant_id if self.membership else None

    @property
    def workspace(self) -> str | None:
        return ROLE_WORKSPACE.get(self.role) if self.role else None

    @property
    def read_only(self) -> bool:
        return bool(self.user.is_read_only)

    def has_role(self, *roles: str) -> bool:
        return self.role in roles


def _deny(request: Request, code: str, message: str, user: User | None = None, status: int = 403) -> AppError:
    audit.record_now(
        "access.denied",
        "endpoint",
        f"{request.method} {request.url.path}",
        actor_user_id=user.id if user else None,
        outcome="denied",
        details={"reason_code": code},
    )
    return AppError(status, code, message)


def load_session(db: Session, request: Request) -> AuthSession | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return db.get(AuthSession, sha256_hex(token))


def get_ctx(request: Request, db: Session = Depends(get_db)) -> Ctx:
    sess = load_session(db, request)
    now = utcnow()
    if sess is None or sess.revoked_at is not None:
        raise AppError(401, "not_authenticated", "Please sign in.")
    if now >= sess.absolute_expires_at or now >= sess.idle_expires_at:
        sess.revoked_at = now
        sess.revoked_reason = "expired"
        db.commit()
        raise AppError(401, "session_expired", "Your session expired. Please sign in again.")
    user = db.get(User, sess.user_id)
    if user is None or not user.is_active:
        raise AppError(401, "not_authenticated", "Please sign in.")

    method = request.method.upper()
    path = request.url.path
    if method not in SAFE_METHODS:
        # CSRF: double-submit token bound to the server-side session, plus Origin check.
        origin = request.headers.get("origin")
        if origin and origin not in get_settings().origins:
            raise _deny(request, "bad_origin", "Request origin not allowed.", user)
        if request.headers.get("x-csrf-token") != sess.csrf_token:
            raise _deny(request, "csrf_failed", "Security token missing or invalid. Reload the page and try again.", user)
        if user.is_read_only and path not in READ_ONLY_ALLOWED:
            raise _deny(request, "read_only_account", "This demo account is read-only. Changes are disabled.", user)

    membership = None
    if sess.membership_id:
        membership = db.get(Membership, sess.membership_id)
        if membership is None or not membership.is_active or membership.user_id != user.id:
            membership = None
    if membership and membership.role in PRIVILEGED_ROLES and not sess.mfa_verified and path not in PRE_MFA_ALLOWED:
        raise AppError(403, "mfa_required", "Multi-factor verification is required for this role.")

    # Sliding idle expiry (written at most once per minute to limit write load).
    if (now - sess.last_seen_at) > timedelta(seconds=60):
        idle = int(policies.get(db, "session_idle_minutes"))
        sess.last_seen_at = now
        sess.idle_expires_at = min(now + timedelta(minutes=idle), sess.absolute_expires_at)
        db.commit()
    return Ctx(user=user, session=sess, membership=membership, db=db)


def require_roles(*roles: str):
    def dep(request: Request, ctx: Ctx = Depends(get_ctx)) -> Ctx:
        if ctx.role not in roles:
            raise _deny(request, "role_not_permitted", "Your active role cannot perform this action.", ctx.user)
        return ctx

    return dep


def require_workspace(*workspaces: str):
    def dep(request: Request, ctx: Ctx = Depends(get_ctx)) -> Ctx:
        if ctx.workspace not in workspaces:
            raise _deny(request, "workspace_not_permitted", "Switch to the right workspace to continue.", ctx.user)
        return ctx

    return dep


def deny(ctx: Ctx, action: str, resource_type: str, resource_id, reason: str) -> AppError:
    """Record a resource-level denial and return a 404 so existence is not leaked across tenants."""
    audit.record_now(
        action,
        resource_type,
        resource_id,
        actor_user_id=ctx.user.id,
        actor_tenant_id=ctx.tenant_id,
        actor_role=ctx.role,
        outcome="denied",
        details={"reason_code": reason},
    )
    return AppError(404, "not_found", "Not found.")


__all__ = ["Ctx", "get_ctx", "require_roles", "require_workspace", "deny", "forbidden", "SESSION_COOKIE"]
