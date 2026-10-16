"""Journey I: authentication, sessions, MFA, recovery, registration, role switching."""
from __future__ import annotations

import re
from datetime import timedelta

import pyotp
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import utcnow
from app.main import app
from app.models import AuthSession, Job, User
from tests.conftest import Api, creds, login, run_jobs


def test_login_me_logout_and_session_persistence():
    api = login("maya")
    me = api.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["user"]["email"].startswith("maya")
    assert me.json()["active"]["workspace"] == "citizen"
    # The same client (cookie) keeps working across requests = persistence across refresh.
    assert api.get("/api/overview/citizen").status_code == 200
    assert api.post("/api/auth/logout").status_code == 200
    assert api.get("/api/auth/me").status_code == 401


def test_wrong_password_and_lockout(db):
    c = TestClient(app)
    email = creds()["jonas"]["email"]
    for _ in range(5):
        assert c.post("/api/auth/login", json={"email": email, "password": "wrong-password-1A"}).status_code == 401
    r = c.post("/api/auth/login", json={"email": email, "password": creds()["jonas"]["password"]})
    assert r.status_code == 423
    u = db.execute(select(User).where(User.email == email)).scalar_one()
    u.locked_until = None
    db.commit()


def test_unknown_user_gets_same_error():
    r = TestClient(app).post("/api/auth/login", json={"email": "nobody@demo.civicbridge.local", "password": "Whatever-123"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_credentials"


def test_csrf_required_for_mutations():
    api = login("maya")
    r = api.c.post("/api/cases", json={"title": "No CSRF header"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf_failed"
    r = api.c.post("/api/cases", json={"title": "Bad origin"}, headers={"X-CSRF-Token": api.csrf, "Origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "bad_origin"


def test_session_idle_expiry(db):
    api = login("alex")
    sid = db.execute(select(AuthSession).where(AuthSession.csrf_token == api.csrf)).scalar_one()
    sid.idle_expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    r = api.get("/api/auth/me")
    assert r.status_code == 401 and r.json()["error"]["code"] == "session_expired"


def test_privileged_role_requires_mfa_and_rejects_replay(db):
    a = creds()["lena"]
    api = Api(TestClient(app))
    r = api.c.post("/api/auth/login", json={"email": a["email"], "password": a["password"]})
    api.me, api.csrf = r.json(), r.json()["csrf_token"]
    assert api.me["mfa_required"] is True
    assert api.get("/api/authority/queue").json()["error"]["code"] == "mfa_required"
    assert api.post("/api/auth/mfa/verify", {"code": "000000"}).status_code == 401
    u = db.execute(select(User).where(User.email == a["email"])).scalar_one()
    u.mfa_last_step = None
    db.commit()
    code = pyotp.TOTP(a["totp_secret"]).now()
    assert api.post("/api/auth/mfa/verify", {"code": code}).status_code == 200
    assert api.get("/api/authority/queue").status_code == 200
    # Same code again on a new session: replay rejected.
    api2 = Api(TestClient(app))
    r = api2.c.post("/api/auth/login", json={"email": a["email"], "password": a["password"]})
    api2.csrf = r.json()["csrf_token"]
    assert api2.post("/api/auth/mfa/verify", {"code": code}).status_code == 401


def test_role_and_tenant_switching():
    api = login("lena")
    slugs = {m["tenant"]["slug"] for m in api.me["memberships"]}
    assert {"berlin-registration", "berlin-district"} <= slugs
    api.switch("berlin-district")
    assert api.get("/api/authority/stats").json()["tenant"].startswith("Demo Berlin District")
    api.switch("berlin-registration")
    assert "Registration" in api.get("/api/authority/stats").json()["tenant"]


def test_switch_to_foreign_membership_denied():
    maya, lena = login("maya"), login("lena")
    foreign = lena.me["memberships"][0]["id"]
    assert maya.post("/api/auth/context", {"membership_id": foreign}).status_code == 404


def _last_mail_body(db, to: str) -> str:
    jobs = db.execute(select(Job).where(Job.kind == "send_email_raw").order_by(Job.created_at.desc())).scalars().all()
    return next(j.payload["body"] for j in jobs if j.payload["to"] == to)


def test_password_recovery_flow(db):
    a = creds()["alex"]
    c = TestClient(app)
    assert c.post("/api/auth/password/forgot", json={"email": a["email"]}).status_code == 200
    body = _last_mail_body(db, a["email"])
    token = re.search(r"token=([\w-]+)", body).group(1)
    run_jobs()  # delivers to Mailpit
    assert c.post("/api/auth/password/reset", json={"token": token, "password": "short"}).status_code == 400
    new_pw = "Recovered-Pass-2026"
    assert c.post("/api/auth/password/reset", json={"token": token, "password": new_pw}).status_code == 200
    assert c.post("/api/auth/password/reset", json={"token": token, "password": new_pw}).status_code == 400  # single use
    assert c.post("/api/auth/login", json={"email": a["email"], "password": new_pw}).status_code == 200
    # restore the generated password for other tests
    from app.security.crypto import hash_password

    u = db.execute(select(User).where(User.email == a["email"])).scalar_one()
    u.password_hash = hash_password(a["password"])
    db.commit()


def test_registration_requires_email_verification(db):
    c = TestClient(app)
    email = "new.citizen@demo.civicbridge.local"
    r = c.post("/api/auth/register", json={"email": email, "display_name": "New Citizen", "password": "Fresh-Account-99"})
    assert r.status_code == 200
    assert c.post("/api/auth/login", json={"email": email, "password": "Fresh-Account-99"}).json()["error"]["code"] == "email_not_verified"
    token = re.search(r"token=([\w-]+)", _last_mail_body(db, email)).group(1)
    assert c.post("/api/auth/verify-email", json={"token": token}).status_code == 200
    assert c.post("/api/auth/login", json={"email": email, "password": "Fresh-Account-99"}).status_code == 200


def test_session_list_and_revoke_other_session():
    a, b = login("jonas"), login("jonas")
    items = a.get("/api/auth/sessions").json()["items"]
    other = next(s for s in items if not s["current"] and s["active"])
    assert a.delete(f"/api/auth/sessions/{other['id']}").status_code == 200
    assert b.get("/api/auth/me").status_code == 401
