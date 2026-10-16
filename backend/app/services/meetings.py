"""Case-linked multiparty video consultations on a self-hosted LiveKit SFU.

Authorization model:
* Only explicitly invited, authorized users have a MeetingParticipant row. Interpreters are invited explicitly and
  get no case or document access through the invitation.
* Joining = request -> waiting room -> host admission -> short-lived (default 10 min) room token for one room.
* LiveKit runs with auto_create disabled, so tokens are useless for rooms the backend has not opened.
* Removal: participant status -> removed, LiveKit RemoveParticipant, no further tokens. Because an already issued
  token stays valid until it expires, the backend also enforces presence: LiveKit webhooks (participant_joined)
  and a periodic reconciliation remove any identity in a room that is not currently admitted.
* Recording is disabled (locked policy). Media is never stored; only lifecycle events are audited.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta

import aiohttp
from livekit import api as lk
from sqlalchemy import select

from app.config import get_settings
from app.db import utcnow
from app.deps import Ctx, deny
from app.errors import AppError, bad_request, conflict
from app.models import (
    Case,
    CaseParticipant,
    Meeting,
    MeetingParticipant,
    Membership,
    Tenant,
    User,
)
from app.services import audit, notify
from app.services.access import active_delegations, case_access
from app.services.timeline import add_event

HOST_WORKSPACES = {"authority", "institution", "citizen"}


def _run(coro_factory):
    async def runner():
        s = get_settings()
        key, secret = s.livekit_credentials()
        client = lk.LiveKitAPI(s.livekit_internal_url, key, secret, timeout=aiohttp.ClientTimeout(total=8))
        try:
            return await coro_factory(client)
        finally:
            await client.aclose()

    return asyncio.run(runner())


def livekit_health() -> tuple[bool, str]:
    try:
        rooms = _run(lambda c: c.room.list_rooms(lk.ListRoomsRequest()))
        return True, f"ok ({len(rooms.rooms)} active rooms)"
    except Exception as exc:  # noqa: BLE001
        return False, type(exc).__name__


def _eligible_role(db, case: Case, user: User, membership: Membership | None, requested_role: str) -> str | None:
    """Return the meeting role this user may hold for the case, or None."""
    if requested_role == "citizen":
        return "citizen" if user.id == case.owner_user_id else None
    if membership is None:
        return None
    if requested_role in ("authority", "institution"):
        expected = {"authority": ("authority_officer", "authority_supervisor"), "institution": ("institution_liaison",)}[requested_role]
        if membership.role not in expected:
            return None
        p = db.execute(
            select(CaseParticipant).where(
                CaseParticipant.case_id == case.id, CaseParticipant.tenant_id == membership.tenant_id,
                CaseParticipant.role == requested_role, CaseParticipant.status == "active",
            )
        ).scalar_one_or_none()
        return requested_role if p else None
    if requested_role == "professional":
        if membership.role != "professional":
            return None
        for d in active_delegations(db, user.id, membership.tenant_id):
            if d.principal_user_id == case.owner_user_id and (d.case_id in (None, case.id)) and "attend_meetings" in d.scopes:
                return "professional"
        return None
    if requested_role == "interpreter":
        return "interpreter" if membership.role == "interpreter" else None
    return None


def candidate_invitees(ctx: Ctx, case: Case) -> list[dict]:
    """People the host could invite, already filtered by authorization."""
    db = ctx.db
    out = []
    owner = db.get(User, case.owner_user_id)
    out.append({"user_id": str(owner.id), "display_name": owner.display_name, "role": "citizen", "tenant": "Citizen"})
    parts = db.execute(select(CaseParticipant).where(CaseParticipant.case_id == case.id, CaseParticipant.status == "active")).scalars()
    for p in parts:
        if p.role not in ("authority", "institution"):
            continue
        roles = ("authority_officer", "authority_supervisor") if p.role == "authority" else ("institution_liaison",)
        for m in db.execute(select(Membership).where(Membership.tenant_id == p.tenant_id, Membership.role.in_(roles))).scalars():
            out.append({"user_id": str(m.user_id), "display_name": m.user.display_name, "role": p.role, "tenant": m.tenant.name})
    from app.models import Delegation

    for d in db.execute(select(Delegation).where(Delegation.principal_user_id == case.owner_user_id)).scalars():
        u = db.get(User, d.delegate_user_id)
        if _eligible_role(db, case, u, _membership(db, u.id, d.delegate_tenant_id, "professional"), "professional"):
            out.append({"user_id": str(u.id), "display_name": u.display_name, "role": "professional", "tenant": db.get(Tenant, d.delegate_tenant_id).name})
    for m in db.execute(select(Membership).where(Membership.role == "interpreter")).scalars():
        out.append({"user_id": str(m.user_id), "display_name": m.user.display_name, "role": "interpreter", "tenant": m.tenant.name})
    seen, uniq = set(), []
    for c in out:
        if (c["user_id"], c["role"]) not in seen and c["user_id"] != str(ctx.user.id):
            seen.add((c["user_id"], c["role"]))
            uniq.append(c)
    return uniq


def _membership(db, user_id, tenant_id, role) -> Membership | None:
    q = select(Membership).where(Membership.user_id == user_id, Membership.role == role)
    if tenant_id:
        q = q.where(Membership.tenant_id == tenant_id)
    return db.execute(q).scalars().first()


_ROLE_FOR_MEMBERSHIP = {
    "citizen": None,
    "authority": ("authority_officer", "authority_supervisor"),
    "institution": ("institution_liaison",),
    "professional": ("professional",),
    "interpreter": ("interpreter",),
}


def create(ctx: Ctx, case_id: uuid.UUID, title: str, starts_at: datetime, duration: int, tzname: str, invitees: list[dict]) -> Meeting:
    db = ctx.db
    case = db.get(Case, case_id)
    if case is None or case_access(ctx, case) is None or ctx.workspace not in HOST_WORKSPACES:
        raise deny(ctx, "meeting.create_denied", "case", case_id, "no_case_access")
    if not (5 <= duration <= 240):
        raise bad_request("Duration must be between 5 and 240 minutes.")
    m = Meeting(
        case_id=case.id, title=title[:300], room_name=f"cb-{uuid.uuid4().hex[:20]}", host_user_id=ctx.user.id,
        host_tenant_id=ctx.tenant_id, scheduled_start=starts_at, duration_minutes=duration, timezone=tzname, recording_enabled=False,
    )
    db.add(m)
    db.flush()
    expires = starts_at + timedelta(minutes=duration + 60)
    host_role = {"citizen": "citizen", "authority": "authority", "institution": "institution"}[ctx.workspace]
    _add_participant(db, m, ctx.user, ctx.tenant_id, "host" if host_role != "citizen" else "citizen", expires, host=True)
    for inv in invitees:
        _invite(ctx, m, case, inv, expires)
    add_event(db, case.id, "meeting.scheduled", f"Video consultation scheduled: {m.title}", ctx=ctx,
              data={"meeting_id": str(m.id), "starts_at": starts_at.isoformat(), "timezone": tzname})
    audit.record(db, "meeting.created", "meeting", m.id, **audit.ctx_kw(ctx), subject_user_id=case.owner_user_id,
                 details={"invitees": len(invitees), "recording": False})
    db.commit()
    return m


def _add_participant(db, m: Meeting, user: User, tenant_id, role: str, expires: datetime, host: bool = False) -> MeetingParticipant:
    existing = db.execute(select(MeetingParticipant).where(MeetingParticipant.meeting_id == m.id, MeetingParticipant.user_id == user.id)).scalar_one_or_none()
    if existing:
        return existing
    pid = uuid.uuid4()
    p = MeetingParticipant(
        id=pid, meeting_id=m.id, user_id=user.id, tenant_id=tenant_id, role=role, display_name=user.display_name,
        status="invited", invite_expires_at=expires, identity=f"p-{pid.hex[:16]}",
    )
    if host:
        p.role = "host" if role == "host" else role
    db.add(p)
    db.flush()
    return p


def _invite(ctx: Ctx, m: Meeting, case: Case, inv: dict, expires: datetime) -> MeetingParticipant:
    db = ctx.db
    try:
        uid = uuid.UUID(str(inv.get("user_id")))
    except ValueError as exc:
        raise bad_request("Invalid invitee.") from exc
    role = inv.get("role")
    user = db.get(User, uid)
    if user is None or role not in _ROLE_FOR_MEMBERSHIP:
        raise bad_request("Invalid invitee.")
    membership = None
    if role != "citizen":
        membership = db.execute(select(Membership).where(Membership.user_id == uid, Membership.role.in_(_ROLE_FOR_MEMBERSHIP[role]))).scalars().first()
    if _eligible_role(db, case, user, membership, role) is None:
        audit.record_now("meeting.invite_denied", "meeting", m.id, actor_user_id=ctx.user.id, actor_tenant_id=ctx.tenant_id,
                         actor_role=ctx.role, outcome="denied", details={"role": role, "reason_code": "invitee_not_authorized"})
        raise AppError(403, "invitee_not_authorized", f"{user.display_name} is not authorized to join as {role} for this case.")
    p = _add_participant(db, m, user, membership.tenant_id if membership else None, role, expires)
    local = m.scheduled_start
    notify.notify(db, uid, "meeting_invite", f"Video consultation invitation: {m.title}",
                  f"Starts {local.isoformat()} (organizer time zone {m.timezone}).", f"/meetings/{m.id}", p.tenant_id)
    audit.record(db, "meeting.invited", "meeting", m.id, **audit.ctx_kw(ctx), details={"participant": p.identity, "role": role})
    return p


def get_for(ctx: Ctx, meeting_id: uuid.UUID) -> tuple[Meeting, MeetingParticipant]:
    db = ctx.db
    m = db.get(Meeting, meeting_id)
    p = None
    if m is not None:
        p = db.execute(select(MeetingParticipant).where(MeetingParticipant.meeting_id == m.id, MeetingParticipant.user_id == ctx.user.id)).scalar_one_or_none()
    if m is None or p is None:
        raise deny(ctx, "meeting.access_denied", "meeting", meeting_id, "not_invited")
    return m, p


def _is_host(m: Meeting, p: MeetingParticipant) -> bool:
    return m.host_user_id == p.user_id


def _require_host(ctx: Ctx, m: Meeting, p: MeetingParticipant) -> None:
    if not _is_host(m, p):
        audit.record_now("meeting.host_action_denied", "meeting", m.id, actor_user_id=ctx.user.id, outcome="denied")
        raise AppError(403, "host_only", "Only the host can do this.")


def _check_invite_valid(ctx: Ctx, m: Meeting, p: MeetingParticipant) -> None:
    now = utcnow()
    if p.status in ("removed", "revoked"):
        audit.record_now("meeting.join_denied", "meeting", m.id, actor_user_id=ctx.user.id, outcome="denied", details={"reason_code": p.status})
        raise AppError(403, f"invitation_{p.status}", "Your access to this meeting was withdrawn by the host.")
    if now > p.invite_expires_at:
        audit.record_now("meeting.join_denied", "meeting", m.id, actor_user_id=ctx.user.id, outcome="denied", details={"reason_code": "expired"})
        raise AppError(403, "invitation_expired", "This invitation has expired.")
    if m.status in ("ended", "cancelled"):
        raise AppError(409, "meeting_ended", "This meeting has ended.")


def open_meeting(ctx: Ctx, m: Meeting, p: MeetingParticipant) -> Meeting:
    _require_host(ctx, m, p)
    if m.status == "ended":
        raise conflict("This meeting has ended.")
    if m.status != "open":
        _run(lambda c: c.room.create_room(lk.CreateRoomRequest(name=m.room_name, empty_timeout=900, max_participants=12)))
        m.status = "open"
        m.opened_at = utcnow()
        audit.record(ctx.db, "meeting.opened", "meeting", m.id, **audit.ctx_kw(ctx))
    p.status = "admitted"
    p.admitted_at = utcnow()
    ctx.db.commit()
    return m


def request_join(ctx: Ctx, m: Meeting, p: MeetingParticipant) -> MeetingParticipant:
    _check_invite_valid(ctx, m, p)
    if _is_host(m, p):
        open_meeting(ctx, m, p)
        return p
    if p.status in ("invited", "left") or (p.status == "waiting"):
        p.status = "admitted" if (p.status == "left" and p.admitted_at) else "waiting"
        audit.record(ctx.db, "meeting.join_requested", "meeting", m.id, **audit.ctx_kw(ctx), details={"participant": p.identity, "status": p.status})
        if p.status == "waiting":
            notify.notify(ctx.db, m.host_user_id, "meeting_update", f"{p.display_name} is waiting to join", m.title, f"/meetings/{m.id}")
        ctx.db.commit()
    return p


def admit(ctx: Ctx, m: Meeting, host: MeetingParticipant, participant_id: uuid.UUID) -> MeetingParticipant:
    _require_host(ctx, m, host)
    target = ctx.db.get(MeetingParticipant, participant_id)
    if target is None or target.meeting_id != m.id:
        raise bad_request("Unknown participant.")
    if target.status != "waiting":
        raise conflict(f"Participant is {target.status}, not waiting.")
    if m.status != "open":
        raise conflict("Open the meeting first.")
    target.status = "admitted"
    target.admitted_at = utcnow()
    audit.record(ctx.db, "meeting.admitted", "meeting", m.id, **audit.ctx_kw(ctx), details={"participant": target.identity, "role": target.role})
    ctx.db.commit()
    return target


def issue_token(ctx: Ctx, m: Meeting, p: MeetingParticipant) -> dict:
    _check_invite_valid(ctx, m, p)
    if m.status != "open":
        raise AppError(409, "meeting_not_open", "The host has not opened the meeting yet.")
    if p.status != "admitted":
        audit.record_now("meeting.token_denied", "meeting", m.id, actor_user_id=ctx.user.id, outcome="denied", details={"reason_code": p.status})
        raise AppError(403, "not_admitted", "Wait for the host to admit you.")
    s = get_settings()
    key, secret = s.livekit_credentials()
    ttl = timedelta(seconds=s.meeting_token_ttl_s)
    grants = lk.VideoGrants(
        room_join=True, room=m.room_name, can_publish=True, can_subscribe=True, can_publish_data=False,
        can_publish_sources=["camera", "microphone", "screen_share", "screen_share_audio"],
        room_record=False, room_admin=False, room_create=False,
    )
    token = (
        lk.AccessToken(key, secret).with_identity(p.identity).with_name(p.display_name)
        .with_metadata(f'{{"role":"{p.role}"}}').with_grants(grants).with_ttl(ttl).to_jwt()
    )
    p.last_token_at = utcnow()
    audit.record(ctx.db, "meeting.token_issued", "meeting", m.id, **audit.ctx_kw(ctx), details={"participant": p.identity, "ttl_s": s.meeting_token_ttl_s})
    ctx.db.commit()
    return {"token": token, "url": s.livekit_public_url, "identity": p.identity, "expires_in": s.meeting_token_ttl_s}


def _kick(room: str, identity: str) -> bool:
    try:
        _run(lambda c: c.room.remove_participant(lk.RoomParticipantIdentity(room=room, identity=identity)))
        return True
    except Exception:  # noqa: BLE001  (participant may not be connected)
        return False


def remove(ctx: Ctx, m: Meeting, host: MeetingParticipant, participant_id: uuid.UUID) -> MeetingParticipant:
    _require_host(ctx, m, host)
    target = ctx.db.get(MeetingParticipant, participant_id)
    if target is None or target.meeting_id != m.id or target.id == host.id:
        raise bad_request("Unknown participant.")
    target.status = "removed" if target.status in ("admitted", "waiting", "left") else "revoked"
    target.removed_at = utcnow()
    ctx.db.commit()
    kicked = _kick(m.room_name, target.identity) if m.status == "open" else False
    audit.record(ctx.db, f"meeting.{target.status}", "meeting", m.id, **audit.ctx_kw(ctx),
                 details={"participant": target.identity, "disconnected": kicked})
    ctx.db.commit()
    return target


def leave(ctx: Ctx, m: Meeting, p: MeetingParticipant) -> None:
    if p.status == "admitted":
        p.status = "left"
        audit.record(ctx.db, "meeting.left", "meeting", m.id, **audit.ctx_kw(ctx), details={"participant": p.identity})
        ctx.db.commit()


def end(ctx: Ctx, m: Meeting, p: MeetingParticipant) -> Meeting:
    _require_host(ctx, m, p)
    if m.status == "ended":
        return m
    try:
        _run(lambda c: c.room.delete_room(lk.DeleteRoomRequest(room=m.room_name)))
    except Exception:  # noqa: BLE001
        pass
    m.status = "ended"
    m.ended_at = utcnow()
    for other in ctx.db.execute(select(MeetingParticipant).where(MeetingParticipant.meeting_id == m.id)).scalars():
        if other.status in ("admitted", "waiting"):
            other.status = "left"
    add_event(ctx.db, m.case_id, "meeting.ended", f"Video consultation ended: {m.title}", ctx=ctx)
    audit.record(ctx.db, "meeting.ended", "meeting", m.id, **audit.ctx_kw(ctx))
    ctx.db.commit()
    return m


def room_participants(m: Meeting) -> list[str]:
    try:
        res = _run(lambda c: c.room.list_participants(lk.ListParticipantsRequest(room=m.room_name)))
        return [x.identity for x in res.participants]
    except Exception:  # noqa: BLE001
        return []


def enforce_room(db, m: Meeting, reason: str) -> list[str]:
    """Remove any connected identity that is not currently admitted. Used by webhook and reconciliation."""
    allowed = {
        p.identity
        for p in db.execute(select(MeetingParticipant).where(MeetingParticipant.meeting_id == m.id, MeetingParticipant.status == "admitted")).scalars()
    }
    removed = []
    for identity in room_participants(m):
        if identity not in allowed and _kick(m.room_name, identity):
            removed.append(identity)
            audit.record(db, "meeting.unauthorized_presence_removed", "meeting", m.id, outcome="denied",
                         details={"participant": identity, "reason_code": reason})
    db.commit()
    return removed


def handle_webhook(db, body: str, auth_header: str) -> dict:
    s = get_settings()
    key, secret = s.livekit_credentials()
    receiver = lk.WebhookReceiver(lk.TokenVerifier(key, secret))
    event = receiver.receive(body, auth_header)  # raises on invalid signature
    room = event.room.name if event.room else None
    m = db.execute(select(Meeting).where(Meeting.room_name == room)).scalar_one_or_none() if room else None
    if m is None:
        return {"ok": True, "ignored": True}
    if event.event == "participant_joined":
        identity = event.participant.identity
        p = db.execute(select(MeetingParticipant).where(MeetingParticipant.meeting_id == m.id, MeetingParticipant.identity == identity)).scalar_one_or_none()
        if m.status != "open" or p is None or p.status != "admitted":
            _kick(m.room_name, identity)
            audit.record(db, "meeting.unauthorized_presence_removed", "meeting", m.id, outcome="denied",
                         details={"participant": identity, "reason_code": "webhook_not_admitted"})
        else:
            audit.record(db, "meeting.media_joined", "meeting", m.id, actor_user_id=p.user_id, details={"participant": identity})
    elif event.event == "participant_left":
        audit.record(db, "meeting.media_left", "meeting", m.id, details={"participant": event.participant.identity})
    db.commit()
    return {"ok": True}
