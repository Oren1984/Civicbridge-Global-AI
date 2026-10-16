"""Test fixtures: a scratch PostgreSQL database (civicbridge_test), real object storage, real ClamAV and LiveKit.

Accounts are created by the same seeding code as the demo, with credentials written to a temporary file that
exists only for the test session. Nothing here touches the live `civicbridge` database.
"""
from __future__ import annotations

import json
import os
import tempfile
import time

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

os.environ.setdefault("CB_DB_NAME", "civicbridge_test")
os.environ["CB_DEMO_CREDENTIALS_FILE"] = os.path.join(tempfile.mkdtemp(), "test_credentials.json")

from app.config import get_settings  # noqa: E402

S = get_settings()
assert S.db_name.endswith("_test"), "tests must never run against the live database"


def _create_db() -> None:
    eng = create_engine(S.admin_database_url("postgres"), isolation_level="AUTOCOMMIT")
    with eng.connect() as c:
        c.execute(text(f"DROP DATABASE IF EXISTS {S.db_name} WITH (FORCE)"))
        c.execute(text(f"CREATE DATABASE {S.db_name}"))
    eng.dispose()


@pytest.fixture(scope="session", autouse=True)
def database():
    _create_db()
    from alembic import command
    from alembic.config import Config

    from app import cli, seed

    cli.ensure_app_role()
    command.upgrade(Config("alembic.ini"), "head")
    cli.apply_grants()
    seed.run(seed_demo=False)
    from app.db import session_factory

    with session_factory()() as db:
        seed.ensure_accounts(db)
        db.commit()
    yield


@pytest.fixture()
def db():
    from app.db import session_factory

    with session_factory()() as s:
        yield s


def creds() -> dict:
    return json.loads(open(os.environ["CB_DEMO_CREDENTIALS_FILE"], encoding="utf-8").read())["accounts"]


def run_jobs(max_rounds: int = 20) -> None:
    """Process queued jobs synchronously with the real worker handlers (scanner, storage, mail)."""
    from app import worker
    from app.db import session_factory

    for _ in range(max_rounds):
        with session_factory()() as s:
            if worker.run_once(s) == 0:
                return


class Api:
    def __init__(self, client: TestClient):
        self.c = client
        self.csrf = None
        self.me = None

    def _h(self):
        return {"X-CSRF-Token": self.csrf} if self.csrf else {}

    def get(self, url, **kw):
        return self.c.get(url, **kw)

    def post(self, url, json=None, **kw):
        return self.c.post(url, json=json, headers=self._h(), **kw)

    def put(self, url, json=None, **kw):
        return self.c.put(url, json=json, headers=self._h(), **kw)

    def patch(self, url, json=None, **kw):
        return self.c.patch(url, json=json, headers=self._h(), **kw)

    def delete(self, url, **kw):
        return self.c.delete(url, headers=self._h(), **kw)

    def upload(self, url, files, data=None):
        return self.c.post(url, files=files, data=data or {}, headers=self._h())

    def switch(self, tenant_slug: str, role: str | None = None):
        m = next(x for x in self.me["memberships"] if x["tenant"]["slug"] == tenant_slug and (role is None or x["role"] == role))
        r = self.post("/api/auth/context", {"membership_id": m["id"]})
        assert r.status_code == 200, r.text
        self.me = r.json()
        return self


def login(key: str) -> Api:
    from app.db import session_factory
    from app.main import app
    from app.models import User
    from sqlalchemy import select

    a = creds()[key]
    api = Api(TestClient(app))
    r = api.c.post("/api/auth/login", json={"email": a["email"], "password": a["password"]})
    assert r.status_code == 200, r.text
    api.me = r.json()
    api.csrf = api.me["csrf_token"]
    if api.me["mfa_required"]:
        # Test-only: clear the replay marker so repeated logins inside one 30 s window can verify.
        with session_factory()() as s:
            u = s.execute(select(User).where(User.email == a["email"])).scalar_one()
            u.mfa_last_step = None
            s.commit()
        r = api.post("/api/auth/mfa/verify", {"code": pyotp.TOTP(a["totp_secret"]).now()})
        assert r.status_code == 200, r.text
        api.me = r.json()
    return api


@pytest.fixture()
def as_user():
    return login


def wait_until(fn, timeout=20.0, interval=0.5):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = fn()
        if v:
            return v
        time.sleep(interval)
    return fn()


def txt(name: str, content: str):
    return {"file": (name, content.encode("utf-8"), "text/plain")}


def upload_doc(api: Api, title="Passport (test)", category="identity", content="Passport (synthetic demo document)\nName: Test", name="passport.txt", **data):
    r = api.upload("/api/documents", txt(name, content), {"title": title, "category": category, **data})
    assert r.status_code == 200, r.text
    run_jobs()
    return r.json()


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """The suite logs the same accounts in many times; rate limiting itself is tested in test_rate_limit."""
    from app.routers.common import limiter

    limiter.hits.clear()
    yield
