"""Journeys E (offline continuity), F (video authorization, backend side) and K (data and operations)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, text

from app.config import get_settings
from app.db import session_factory, utcnow
from app.models import AuditEvent, Incident, IntegrationAdapter, IntegrationRun, Job, MeetingParticipant
from app.services import audit
from tests.conftest import login, run_jobs, upload_doc
from tests.test_relocation_workflow import start_relocation


# ------------------------------------------------------------------ E: offline continuity

def test_offline_replay_is_idempotent_and_detects_conflicts(db):
    jonas = login("jonas")
    tid = next(m["id"] for m in jonas.get("/api/incidents/municipalities").json()["items"] if "Berlin" in m["name"])
    k1, k2 = uuid.uuid4().hex, uuid.uuid4().hex
    ops = [
        {"idempotency_key": k1, "op": "upsert_draft", "draft_key": "inc-draft-1", "kind": "incident_report", "title": "Pothole",
         "payload": {"description": "Pothole drafted offline"}},
        {"idempotency_key": k2, "op": "submit_incident", "draft_key": "inc-draft-1",
         "payload": {"tenant_id": tid, "description": "Pothole on the cycle lane, drafted offline", "category": "pothole"}},
    ]
    r1 = jonas.post("/api/sync/replay", {"ops": ops}).json()["results"]
    assert [x["status"] for x in r1] == ["applied", "applied"] and not any(x["replayed"] for x in r1)
    r2 = jonas.post("/api/sync/replay", {"ops": ops}).json()["results"]
    assert all(x["replayed"] for x in r2) and r2[1]["result"]["reference"] == r1[1]["result"]["reference"]
    n = db.execute(select(Incident).where(Incident.client_draft_key == "inc-draft-1")).scalars().all()
    assert len(n) == 1
    # Conflict: draft edited on device A (server version moves on), device B replays an older base version.
    assert jonas.put("/api/drafts/note-1", {"kind": "case_note", "title": "v1", "payload": {"t": "a"}}).json()["version"] == 1
    assert jonas.put("/api/drafts/note-1", {"kind": "case_note", "title": "v2", "payload": {"t": "b"}, "base_version": 1}).json()["version"] == 2
    res = jonas.post("/api/sync/replay", {"ops": [{"idempotency_key": uuid.uuid4().hex, "op": "upsert_draft", "draft_key": "note-1",
                                                  "kind": "case_note", "title": "offline edit", "payload": {"t": "c"}, "base_version": 1}]}).json()["results"][0]
    assert res["status"] == "conflict" and res["result"]["server"]["version"] == 2
    # User resolves by keeping their copy on top of the server version.
    r = jonas.put("/api/drafts/note-1", {"kind": "case_note", "title": "offline edit", "payload": {"t": "c"}, "base_version": 2})
    assert r.status_code == 200 and r.json()["version"] == 3
    assert jonas.put("/api/drafts/note-1", {"kind": "case_note", "payload": {}, "base_version": 1}).status_code == 409


def test_emergency_notices_are_source_labelled():
    r = login("maya").get("/api/emergency/notices").json()
    assert r["items"] and all(n["source_kind"] in ("synthetic_demo", "official_placeholder", "authority_tenant") for n in r["items"])
    assert "not an emergency dispatch service" in r["disclaimer"]


# ------------------------------------------------------------------ F: video (authorization + LiveKit server API)

def test_meeting_admission_tokens_removal_and_end(db):
    maya, lena = login("maya"), login("lena").switch("berlin-registration")
    case_id = start_relocation(maya)
    sr = maya.post(f"/api/cases/{case_id}/requests", {"procedure_code": "DE-BER-ANMELDUNG"}).json()
    maya.post(f"/api/cases/{case_id}/requests/{sr['id']}/actions", {"action": "submit"})
    cands = {(c["display_name"], c["role"]): c for c in lena.get(f"/api/meetings/candidates?case_id={case_id}").json()["items"]}
    assert ("Maya Cohen", "citizen") in cands and ("Rina Adler", "interpreter") in cands
    assert ("Thomas Braun", "authority") in cands and ("Petra Schmidt", "institution") not in cands  # no handoff consent yet
    petra = login("petra")
    start = (datetime.now(ZoneInfo("Europe/Berlin")) + timedelta(minutes=5)).replace(microsecond=0, tzinfo=None).isoformat()
    bad = lena.post("/api/meetings", {"case_id": case_id, "title": "Consultation", "starts_at_local": start, "timezone": "Europe/Berlin",
                                      "invitees": [{"user_id": petra.me["user"]["id"], "role": "institution"}]})
    assert bad.status_code == 403 and bad.json()["error"]["code"] == "invitee_not_authorized"
    m = lena.post("/api/meetings", {"case_id": case_id, "title": "Consultation", "starts_at_local": start, "timezone": "Europe/Berlin", "duration_minutes": 30,
                                    "invitees": [{"user_id": maya.me["user"]["id"], "role": "citizen"},
                                                 {"user_id": cands[("Thomas Braun", "authority")]["user_id"], "role": "authority"},
                                                 {"user_id": cands[("Rina Adler", "interpreter")]["user_id"], "role": "interpreter"}]})
    assert m.status_code == 200, m.text
    mid = m.json()["id"]
    assert m.json()["recording_enabled"] is False
    # Uninvited users cannot see or join.
    jonas = login("jonas")
    assert jonas.get(f"/api/meetings/{mid}").status_code == 404
    assert jonas.post(f"/api/meetings/{mid}/token").status_code == 404
    # Citizen before the host opens: token denied.
    assert maya.post(f"/api/meetings/{mid}/token").status_code == 409
    assert lena.post(f"/api/meetings/{mid}/join").status_code == 200  # host opens the room on LiveKit
    host_tok = lena.post(f"/api/meetings/{mid}/token").json()
    assert host_tok["token"].count(".") == 2 and host_tok["expires_in"] == get_settings().meeting_token_ttl_s
    assert maya.post(f"/api/meetings/{mid}/join").json()["me"]["status"] == "waiting"
    assert maya.post(f"/api/meetings/{mid}/token").json()["error"]["code"] == "not_admitted"
    view = lena.get(f"/api/meetings/{mid}").json()
    me_p = next(p for p in view["waiting"] if p["display_name"] == "Maya Cohen")
    assert maya.post(f"/api/meetings/{mid}/participants/{me_p['id']}/admit").status_code == 403  # not host
    assert lena.post(f"/api/meetings/{mid}/participants/{me_p['id']}/admit").status_code == 200
    assert "token" in maya.post(f"/api/meetings/{mid}/token").json()
    rina = login("rina")
    rina_p = next(p for p in lena.get(f"/api/meetings/{mid}").json()["participants"] if p["role"] == "interpreter")
    rina.post(f"/api/meetings/{mid}/join")
    lena.post(f"/api/meetings/{mid}/participants/{rina_p['id']}/admit")
    assert "token" in rina.post(f"/api/meetings/{mid}/token").json()
    # Interpreter invitation grants no case or document access.
    assert rina.get(f"/api/cases/{case_id}").status_code == 404
    # Document shared in the meeting: each viewer is authorized individually.
    doc = upload_doc(maya)
    assert maya.post(f"/api/meetings/{mid}/share", {"document_id": doc["id"]}).status_code == 200
    shared = rina.get(f"/api/meetings/{mid}").json()["shared_documents"][0]
    assert shared["can_view"] is False and shared["title"] is None
    assert rina.get(f"/api/meetings/{mid}/shared/{doc['id']}/preview").status_code == 403
    assert lena.get(f"/api/meetings/{mid}/shared/{doc['id']}/preview").status_code == 403  # consents are case-scoped; this doc is not attached to the case
    assert maya.get(f"/api/meetings/{mid}/shared/{doc['id']}/preview").status_code == 200
    # Removal: no new tokens; room enforcement removes any lingering identity.
    assert lena.post(f"/api/meetings/{mid}/participants/{rina_p['id']}/remove").status_code == 200
    r = rina.post(f"/api/meetings/{mid}/token")
    assert r.status_code == 403 and r.json()["error"]["code"] == "invitation_removed"
    check = lena.get(f"/api/meetings/{mid}/room-check").json()
    assert rina_p["identity"] not in check["connected"]
    # Expired invitation.
    with session_factory()() as s:
        p = s.execute(select(MeetingParticipant).where(MeetingParticipant.meeting_id == mid, MeetingParticipant.role == "authority")).scalar_one()
        p.invite_expires_at = utcnow() - timedelta(minutes=1)
        s.commit()
    thomas = login("thomas")
    assert thomas.post(f"/api/meetings/{mid}/join").json()["error"]["code"] == "invitation_expired"
    # End meeting: tokens no longer issued; the room is deleted on LiveKit.
    assert lena.post(f"/api/meetings/{mid}/end").json()["meeting"]["status"] == "ended"
    assert maya.post(f"/api/meetings/{mid}/token").json()["error"]["code"] == "meeting_ended"
    actions = {e.action for e in db.execute(select(AuditEvent).where(AuditEvent.resource_id == mid)).scalars()}
    assert {"meeting.created", "meeting.opened", "meeting.admitted", "meeting.token_issued", "meeting.removed", "meeting.ended"} <= actions


# ------------------------------------------------------------------ K: data and operations

def test_audit_is_append_only_for_app_role_and_tamper_evident(db):
    s = get_settings()
    from sqlalchemy import create_engine

    app_engine = create_engine(f"postgresql+psycopg://{'civicbridge_app'}:{open('/secrets/pg_app_password').read().strip()}@{s.db_host}/{s.db_name}")
    with app_engine.connect() as c:
        with pytest.raises(Exception):
            c.execute(text("UPDATE audit_events SET outcome = 'success' WHERE seq = 1"))
        c.rollback()
        with pytest.raises(Exception):
            c.execute(text("DELETE FROM audit_events WHERE seq = 1"))
        c.rollback()
    app_engine.dispose()
    assert audit.verify_chain(db)["ok"] is True
    # Simulated privileged tampering (admin disables the trigger inside a transaction that is rolled back).
    from sqlalchemy.orm import Session

    admin = create_engine(s.admin_database_url())
    with Session(admin) as t:
        t.execute(text("ALTER TABLE audit_events DISABLE TRIGGER audit_events_no_update"))
        t.execute(text("UPDATE audit_events SET details = '{\"forged\": true}' WHERE seq = (SELECT min(seq) + 1 FROM audit_events)"))
        res = audit.verify_chain(t)
        assert res["ok"] is False and res["broken_at_seq"] is not None
        t.rollback()
    admin.dispose()
    assert audit.verify_chain(db)["ok"] is True


def test_integration_retries_and_dead_letter(db):
    maya = login("maya")
    case_id = start_relocation(maya)
    ad = db.execute(select(IntegrationAdapter).where(IntegrationAdapter.code == "de-ber-registration-mock")).scalar_one()
    ad.failure_injection = "error"
    db.commit()
    try:
        sr = maya.post(f"/api/cases/{case_id}/requests", {"procedure_code": "DE-BER-ANMELDUNG"}).json()
        maya.post(f"/api/cases/{case_id}/requests/{sr['id']}/actions", {"action": "submit"})
        job = db.execute(select(Job).where(Job.kind == "integration_dispatch", Job.payload["service_request_id"].as_string() == sr["id"])).scalar_one()
        for _ in range(job.max_attempts):
            db.refresh(job)
            job.run_after = utcnow() - timedelta(seconds=1)
            db.commit()
            run_jobs(max_rounds=1)
        db.refresh(job)
        assert job.status == "dead" and "503" in job.last_error
        run = db.execute(select(IntegrationRun).where(IntegrationRun.service_request_id == sr["id"])).scalar_one()
        db.refresh(run)
        assert run.status == "dead_letter" and run.attempts == job.max_attempts
        # Request still available internally; manual retry after the outage succeeds exactly once.
        ad.failure_injection = "none"
        db.commit()
        gov = login("govadmin")
        assert gov.post(f"/api/governance/jobs/{job.id}/retry").status_code == 200
        run_jobs()
        db.refresh(run)
        assert run.status == "success"
        assert "exchange.failed" in {e["kind"] for e in maya.get(f"/api/cases/{case_id}/timeline").json()["items"]}
    finally:
        ad.failure_injection = "none"
        db.commit()


def test_transparency_suppresses_small_groups(db):
    from fastapi.testclient import TestClient

    from app.main import app

    data = TestClient(app).get("/api/public/transparency").json()
    k = data["k_threshold"]
    for a in data["authorities"]:
        for cat in a["incidents"]["by_category"].values():
            assert (cat["value"] is None) == cat["suppressed"]
            if not cat["suppressed"]:
                assert cat["value"] >= k
    text_ = str(data)
    assert "@" not in text_ and "INC-" not in text_ and "CB-" not in text_


def test_privacy_export_and_deletion(db):
    from app.models import PrivacyRequest, User

    alex = login("alex")
    start_relocation(alex)
    upload_doc(alex)
    r = alex.post("/api/privacy/requests", {"kind": "export"}).json()
    run_jobs()
    run_jobs()
    pr = alex.get("/api/privacy/requests").json()["items"][0]
    assert pr["status"] == "completed"
    z = alex.get(f"/api/privacy/requests/{r['id']}/download")
    assert z.status_code == 200 and z.content[:2] == b"PK"
    assert alex.post("/api/privacy/requests", {"kind": "deletion"}).status_code == 400  # confirmation required
    # Deletion is exercised on a throwaway registered user so other tests keep their accounts.
    from tests.test_auth import _last_mail_body
    from fastapi.testclient import TestClient
    import re

    from app.main import app

    c = TestClient(app)
    email = "to.delete@demo.civicbridge.local"
    c.post("/api/auth/register", json={"email": email, "display_name": "To Delete", "password": "Delete-Me-Now-1"})
    token = re.search(r"token=([\w-]+)", _last_mail_body(db, email)).group(1)
    c.post("/api/auth/verify-email", json={"token": token})
    me = c.post("/api/auth/login", json={"email": email, "password": "Delete-Me-Now-1"}).json()
    h = {"X-CSRF-Token": me["csrf_token"]}
    c.post("/api/documents", files={"file": ("a.txt", b"my data", "text/plain")}, data={"title": "Mine", "category": "other"}, headers=h)
    assert c.post("/api/privacy/requests", json={"kind": "deletion", "confirm": "DELETE"}, headers=h).status_code == 200
    run_jobs()
    run_jobs()
    u = db.execute(select(User).where(User.display_name == "Deleted user")).scalars().all()
    assert u and all(not x.is_active for x in u)
    assert c.post("/api/auth/login", json={"email": email, "password": "Delete-Me-Now-1"}).status_code == 401
    assert db.execute(select(PrivacyRequest).where(PrivacyRequest.kind == "deletion")).scalars().first().status in ("completed", "partially_completed")


def test_health_and_readiness():
    from fastapi.testclient import TestClient

    from app.main import app

    c = TestClient(app)
    assert c.get("/api/health/live").json()["status"] == "ok"
    r = c.get("/api/health/ready").json()
    assert r["checks"]["database"] == "ok" and r["checks"]["storage"] == "ok"
    assert "civicbridge_jobs" in c.get("/api/metrics").text
