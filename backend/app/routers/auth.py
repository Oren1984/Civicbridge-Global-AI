"""Authentication, MFA, context switching, recovery, registration and session management."""
from __future__ import annotations

import re
import uuid
from datetime import timedelta
from zoneinfo import available_timezones

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db, utcnow
from app.deps import SESSION_COOKIE, Ctx, get_ctx, load_session
from app.errors import AppError, bad_request
from app.models import AuthSession, Membership, OneTimeToken, Tenant, User
from app.models.identity import PRIVILEGED_ROLES, ROLE_WORKSPACE
from app.routers.common import client_ip, iso, limiter
from app.security.crypto import (
    decrypt_secret,
    encrypt_secret,
    hash_password,
    keyed_hash,
    new_token,
    new_totp_secret,
    password_problems,
    sha256_hex,
    totp_uri,
    verify_password,
    verify_totp,
)
from app.services import audit, jobs, policies

router = APIRouter(prefix="/api/auth", tags=["auth"])
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,24}$")
_TZS = available_timezones()


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=256)


def _needs_mfa(user: User) -> bool:
    return any(m.role in PRIVILEGED_ROLES and m.is_active for m in user.memberships)


def _membership_out(m: Membership) -> dict:
    return {
        "id": str(m.id),
        "role": m.role,
        "workspace": ROLE_WORKSPACE.get(m.role),
        "tenant": {"id": str(m.tenant.id), "name": m.tenant.name, "kind": m.tenant.kind, "slug": m.tenant.slug},
        "privileged": m.role in PRIVILEGED_ROLES,
    }


def me_payload(db: Session, user: User, sess: AuthSession) -> dict:
    active = db.get(Membership, sess.membership_id) if sess.membership_id else None
    return {
        "user": {
            "id": str(user.id),
            "email": user.email,
            "display_name": user.display_name,
            "locale": user.locale,
            "timezone": user.timezone,
            "read_only": user.is_read_only,
            "mfa_enabled": user.mfa_enabled,
            "email_verified": user.email_verified_at is not None,
            "synthetic": user.is_synthetic,
        },
        "memberships": [_membership_out(m) for m in user.memberships if m.is_active],
        "active": _membership_out(active) if active else None,
        "mfa_verified": sess.mfa_verified,
        "mfa_required": bool(active and active.role in PRIVILEGED_ROLES and not sess.mfa_verified),
        "mfa_setup_required": bool(_needs_mfa(user) and not user.mfa_enabled),
        "csrf_token": sess.csrf_token,
        "session": {"idle_expires_at": iso(sess.idle_expires_at), "absolute_expires_at": iso(sess.absolute_expires_at)},
    }


def _set_cookie(response: Response, token: str, max_age: int) -> None:
    response.set_cookie(
        SESSION_COOKIE, token, httponly=True, secure=get_settings().cookie_secure, samesite="strict", max_age=max_age, path="/"
    )


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    ip = client_ip(request)
    email = body.email.strip().lower()
    limiter.check(f"login-ip:{ip}", 20, 300)
    limiter.check(f"login-email:{email}", 8, 300)
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    now = utcnow()
    if user and user.locked_until and user.locked_until > now:
        audit.record_now("auth.login", "user", user.id, actor_user_id=user.id, outcome="denied", details={"reason_code": "locked"})
        raise AppError(423, "account_locked", "Too many failed attempts. The account is temporarily locked; try again later or reset your password.")
    ok = verify_password(user.password_hash if user else None, body.password)
    if not user or not ok or not user.is_active:
        if user:
            user.failed_logins += 1
            if user.failed_logins >= 5:
                user.locked_until = now + timedelta(minutes=15)
                user.failed_logins = 0
            db.commit()
        audit.record_now("auth.login", "user", user.id if user else None, actor_user_id=user.id if user else None,
                         outcome="denied", details={"reason_code": "bad_credentials"})
        raise AppError(401, "invalid_credentials", "Email or password is incorrect.")
    if user.email_verified_at is None:
        raise AppError(403, "email_not_verified", "Please verify your email address first. Check the local mail inbox.")
    user.failed_logins = 0
    user.locked_until = None
    token = new_token()
    idle = int(policies.get(db, "session_idle_minutes"))
    absolute = int(policies.get(db, "session_absolute_hours"))
    memberships = [m for m in user.memberships if m.is_active]
    default = next((m for m in memberships if m.role not in PRIVILEGED_ROLES), memberships[0] if memberships else None)
    if _needs_mfa(user) and memberships:
        default = memberships[0]
    sess = AuthSession(
        id=sha256_hex(token),
        user_id=user.id,
        membership_id=default.id if default else None,
        csrf_token=new_token(24),
        mfa_verified=False,
        last_seen_at=now,
        idle_expires_at=now + timedelta(minutes=idle),
        absolute_expires_at=now + timedelta(hours=absolute),
        user_agent=(request.headers.get("user-agent") or "")[:300],
        ip_hash=keyed_hash(ip),
    )
    db.add(sess)
    audit.record(db, "auth.login", "user", user.id, actor_user_id=user.id, details={"mfa_pending": _needs_mfa(user)})
    db.commit()
    _set_cookie(response, token, absolute * 3600)
    return me_payload(db, user, sess)


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    sess = load_session(db, request)
    if sess and sess.revoked_at is None:
        # CSRF still applies to logout for an active session.
        if request.headers.get("x-csrf-token") != sess.csrf_token:
            raise AppError(403, "csrf_failed", "Security token missing or invalid.")
        sess.revoked_at = utcnow()
        sess.revoked_reason = "logout"
        audit.record(db, "auth.logout", "user", sess.user_id, actor_user_id=sess.user_id)
        db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(ctx: Ctx = Depends(get_ctx)) -> dict:
    return me_payload(ctx.db, ctx.user, ctx.session)


class ContextIn(BaseModel):
    membership_id: uuid.UUID


@router.post("/context")
def switch_context(body: ContextIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    m = ctx.db.get(Membership, body.membership_id)
    if m is None or m.user_id != ctx.user.id or not m.is_active:
        raise AppError(404, "not_found", "Membership not found.")
    ctx.session.membership_id = m.id
    audit.record(ctx.db, "auth.context_switch", "membership", m.id, actor_user_id=ctx.user.id, actor_tenant_id=m.tenant_id, actor_role=m.role)
    ctx.db.commit()
    return me_payload(ctx.db, ctx.user, ctx.session)


class CodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=8)


@router.post("/mfa/verify")
def mfa_verify(body: CodeIn, request: Request, ctx: Ctx = Depends(get_ctx)) -> dict:
    limiter.check(f"mfa:{ctx.user.id}", 6, 300)
    user = ctx.user
    if not user.mfa_enabled or not user.mfa_secret_enc:
        raise AppError(409, "mfa_not_enabled", "MFA is not set up yet.")
    step = verify_totp(decrypt_secret(user.mfa_secret_enc), body.code, user.mfa_last_step)
    if step is None:
        audit.record_now("auth.mfa_verify", "user", user.id, actor_user_id=user.id, outcome="denied", details={"reason_code": "bad_code"})
        raise AppError(401, "invalid_mfa_code", "That code is not valid. Codes change every 30 seconds and can be used once.")
    user.mfa_last_step = step
    ctx.session.mfa_verified = True
    audit.record(ctx.db, "auth.mfa_verify", "user", user.id, actor_user_id=user.id)
    ctx.db.commit()
    return me_payload(ctx.db, user, ctx.session)


@router.post("/mfa/setup")
def mfa_setup(ctx: Ctx = Depends(get_ctx)) -> dict:
    if ctx.user.mfa_enabled:
        raise AppError(409, "mfa_already_enabled", "MFA is already enabled.")
    secret = new_totp_secret()
    ctx.user.mfa_secret_enc = encrypt_secret(secret)
    ctx.db.commit()
    return {"secret": secret, "otpauth_uri": totp_uri(secret, ctx.user.email)}


@router.post("/mfa/enable")
def mfa_enable(body: CodeIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    if ctx.user.mfa_enabled or not ctx.user.mfa_secret_enc:
        raise AppError(409, "mfa_setup_missing", "Start MFA setup first.")
    step = verify_totp(decrypt_secret(ctx.user.mfa_secret_enc), body.code, None)
    if step is None:
        raise AppError(401, "invalid_mfa_code", "That code is not valid.")
    ctx.user.mfa_enabled = True
    ctx.user.mfa_last_step = step
    ctx.session.mfa_verified = True
    audit.record(ctx.db, "auth.mfa_enabled", "user", ctx.user.id, actor_user_id=ctx.user.id)
    ctx.db.commit()
    return me_payload(ctx.db, ctx.user, ctx.session)


class EmailIn(BaseModel):
    email: str = Field(max_length=254)


def _issue_token(db: Session, user: User | None, email: str, purpose: str, hours: int, payload: dict | None = None) -> str:
    raw = new_token()
    db.add(OneTimeToken(user_id=user.id if user else None, email=email, purpose=purpose, token_hash=sha256_hex(raw),
                        payload=payload or {}, expires_at=utcnow() + timedelta(hours=hours)))
    return raw


def _consume(db: Session, raw: str, purpose: str) -> OneTimeToken:
    t = db.execute(select(OneTimeToken).where(OneTimeToken.token_hash == sha256_hex(raw or ""), OneTimeToken.purpose == purpose)).scalar_one_or_none()
    if t is None or t.used_at is not None or t.expires_at < utcnow():
        raise AppError(400, "invalid_token", "This link is invalid or has expired. Request a new one.")
    t.used_at = utcnow()
    return t


@router.post("/password/forgot")
def forgot(body: EmailIn, request: Request, db: Session = Depends(get_db)) -> dict:
    limiter.check(f"forgot:{client_ip(request)}", 5, 600)
    email = body.email.strip().lower()
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user and user.is_active and not user.is_read_only:
        raw = _issue_token(db, user, email, "reset_password", 1)
        link = f"{get_settings().public_origin}/reset-password?token={raw}"
        jobs.enqueue(db, "send_email_raw", {"to": email, "subject": "Reset your password",
                                            "body": f"Use this link within 1 hour to choose a new password:\n{link}\n\nIf you did not ask for this, ignore this message."})
        audit.record(db, "auth.password_reset_requested", "user", user.id, actor_user_id=user.id)
        db.commit()
    return {"ok": True, "message": "If an account exists for that address, a reset link was sent to the local mail inbox."}


class ResetIn(BaseModel):
    token: str = Field(max_length=200)
    password: str = Field(max_length=256)


def _check_password(pw: str) -> None:
    problems = password_problems(pw)
    if problems:
        raise bad_request("Password needs " + ", ".join(problems) + ".", "weak_password")


@router.post("/password/reset")
def reset(body: ResetIn, db: Session = Depends(get_db)) -> dict:
    _check_password(body.password)
    t = _consume(db, body.token, "reset_password")
    user = db.get(User, t.user_id)
    if user is None or user.is_read_only:
        raise AppError(400, "invalid_token", "This link is invalid or has expired.")
    user.password_hash = hash_password(body.password)
    user.password_changed_at = utcnow()
    user.failed_logins = 0
    user.locked_until = None
    for s in db.execute(select(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))).scalars():
        s.revoked_at = utcnow()
        s.revoked_reason = "password_reset"
    audit.record(db, "auth.password_reset", "user", user.id, actor_user_id=user.id)
    db.commit()
    return {"ok": True}


class ChangePwIn(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


@router.post("/password/change")
def change_password(body: ChangePwIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    if not verify_password(ctx.user.password_hash, body.current_password):
        raise AppError(401, "invalid_credentials", "Current password is incorrect.")
    _check_password(body.new_password)
    ctx.user.password_hash = hash_password(body.new_password)
    ctx.user.password_changed_at = utcnow()
    for s in ctx.db.execute(select(AuthSession).where(AuthSession.user_id == ctx.user.id, AuthSession.revoked_at.is_(None),
                                                      AuthSession.id != ctx.session.id)).scalars():
        s.revoked_at = utcnow()
        s.revoked_reason = "password_changed"
    audit.record(ctx.db, "auth.password_changed", "user", ctx.user.id, actor_user_id=ctx.user.id)
    ctx.db.commit()
    return {"ok": True, "other_sessions_revoked": True}


class RegisterIn(BaseModel):
    email: str = Field(max_length=254)
    display_name: str = Field(min_length=2, max_length=120)
    password: str = Field(max_length=256)
    locale: str = Field(default="en", pattern=r"^(en|he|de)$")


@router.post("/register")
def register(body: RegisterIn, request: Request, db: Session = Depends(get_db)) -> dict:
    limiter.check(f"register:{client_ip(request)}", 5, 3600)
    email = body.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise bad_request("Enter a valid email address.", "invalid_email")
    _check_password(body.password)
    existing = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if existing is None:
        space = db.execute(select(Tenant).where(Tenant.slug == "citizens")).scalar_one()
        user = User(email=email, display_name=body.display_name.strip(), password_hash=hash_password(body.password),
                    locale=body.locale, is_synthetic=False)
        db.add(user)
        db.flush()
        db.add(Membership(user_id=user.id, tenant_id=space.id, role="citizen"))
        raw = _issue_token(db, user, email, "verify_email", 24)
        link = f"{get_settings().public_origin}/verify-email?token={raw}"
        jobs.enqueue(db, "send_email_raw", {"to": email, "subject": "Verify your email", "body": f"Confirm your address:\n{link}"})
        audit.record(db, "auth.registered", "user", user.id, actor_user_id=user.id)
        db.commit()
    # Same response whether or not the address exists (no account enumeration).
    return {"ok": True, "message": "Check the local mail inbox to verify your address."}


class TokenIn(BaseModel):
    token: str = Field(max_length=200)


@router.post("/verify-email")
def verify_email(body: TokenIn, db: Session = Depends(get_db)) -> dict:
    t = _consume(db, body.token, "verify_email")
    user = db.get(User, t.user_id)
    if user:
        user.email_verified_at = utcnow()
        audit.record(db, "auth.email_verified", "user", user.id, actor_user_id=user.id)
    db.commit()
    return {"ok": True}


@router.get("/sessions")
def sessions(ctx: Ctx = Depends(get_ctx)) -> dict:
    rows = ctx.db.execute(
        select(AuthSession).where(AuthSession.user_id == ctx.user.id).order_by(AuthSession.created_at.desc()).limit(20)
    ).scalars()
    now = utcnow()
    return {
        "items": [
            {
                "id": s.id[:16],
                "current": s.id == ctx.session.id,
                "created_at": iso(s.created_at),
                "last_seen_at": iso(s.last_seen_at),
                "user_agent": s.user_agent,
                "active": s.revoked_at is None and s.idle_expires_at > now and s.absolute_expires_at > now,
                "revoked_reason": s.revoked_reason,
            }
            for s in rows
        ]
    }


@router.delete("/sessions/{sid}")
def revoke_session(sid: str, ctx: Ctx = Depends(get_ctx)) -> dict:
    s = ctx.db.execute(select(AuthSession).where(AuthSession.user_id == ctx.user.id, AuthSession.id.startswith(sid[:16]))).scalars().first()
    if s is None or len(sid) < 16:
        raise AppError(404, "not_found", "Session not found.")
    s.revoked_at = utcnow()
    s.revoked_reason = "revoked_by_user"
    audit.record(ctx.db, "auth.session_revoked", "user", ctx.user.id, actor_user_id=ctx.user.id)
    ctx.db.commit()
    return {"ok": True}


class ProfileIn(BaseModel):
    display_name: str | None = Field(default=None, min_length=2, max_length=120)
    locale: str | None = Field(default=None, pattern=r"^(en|he|de)$")
    timezone: str | None = Field(default=None, max_length=64)


@router.patch("/profile")
def profile(body: ProfileIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    if body.timezone and body.timezone not in _TZS:
        raise bad_request("Unknown time zone.")
    for f in ("display_name", "locale", "timezone"):
        v = getattr(body, f)
        if v is not None:
            setattr(ctx.user, f, v)
    audit.record(ctx.db, "auth.profile_updated", "user", ctx.user.id, actor_user_id=ctx.user.id)
    ctx.db.commit()
    return me_payload(ctx.db, ctx.user, ctx.session)
