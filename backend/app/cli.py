"""Operations CLI.

  python -m app.cli bootstrap              migrations (admin role) + idempotent pack load + demo seed
  python -m app.cli demo-credentials       print local demo accounts, passwords and current TOTP codes
  python -m app.cli reset-demo-credentials regenerate demo passwords/TOTP seeds (demo accounts only)
  python -m app.cli totp <account-key>     print the current TOTP code for a demo account
  python -m app.cli verify-audit           recompute the audit hash chain (exit 1 if broken)
  python -m app.cli audit-anchor           print the current chain head for external anchoring
  python -m app.cli backup                 pg_dump + object store copy into $CB_BACKUP_DIR/<timestamp>
  python -m app.cli restore-check <dir>    restore a backup into a scratch database and verify it (non-destructive)
  python -m app.cli list-backups
  python -m app.cli provision-admin        create/update the owner governance admin from JSON on stdin (email, display_name, password)
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tarfile
import time
from datetime import datetime, timezone
from pathlib import Path

import pyotp
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import session_factory


def _pg_env() -> dict:
    s = get_settings()
    return {**os.environ, "PGPASSWORD": s.resolved_db_admin_password(), "PGHOST": s.db_host, "PGPORT": str(s.db_port), "PGUSER": s.db_admin_user}


def ensure_app_role() -> None:
    """Create/refresh the non-superuser runtime role with the password from the secrets volume."""
    s = get_settings()
    eng = create_engine(s.admin_database_url(), isolation_level="AUTOCOMMIT")
    with eng.connect() as c:
        exists = c.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": s.db_user}).first()
        pw = s.resolved_db_password().replace("'", "''")
        verb = "ALTER" if exists else "CREATE"
        c.execute(text(f"{verb} ROLE {s.db_user} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD '{pw}'"))
        c.execute(text(f"GRANT CONNECT ON DATABASE {s.db_name} TO {s.db_user}"))
    eng.dispose()


def apply_grants() -> None:
    """Least privilege: full DML on application tables, but audit_events is append-only (SELECT, INSERT)."""
    s = get_settings()
    eng = create_engine(s.admin_database_url(), isolation_level="AUTOCOMMIT")
    with eng.connect() as c:
        u = s.db_user
        c.execute(text(f"GRANT USAGE ON SCHEMA public TO {u}"))
        c.execute(text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {u}"))
        c.execute(text(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {u}"))
        c.execute(text(f"REVOKE UPDATE, DELETE, TRUNCATE ON audit_events FROM {u}"))
        c.execute(text(f"REVOKE ALL ON alembic_version FROM {u}"))
        c.execute(text(f"GRANT SELECT ON alembic_version TO {u}"))
    eng.dispose()


def bootstrap() -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    for attempt in range(30):
        try:
            ensure_app_role()
            command.upgrade(cfg, "head")
            break
        except Exception as exc:  # noqa: BLE001
            if attempt == 29:
                raise
            print(f"waiting for database ({type(exc).__name__}: {str(exc)[:120]})", flush=True)
            time.sleep(2)
    apply_grants()
    from app import seed

    seed.run(seed_demo=get_settings().seed_demo)
    print("bootstrap complete", flush=True)


def demo_credentials() -> None:
    from app.seed import credentials_path

    p = credentials_path()
    if not p.exists():
        print("No demo credentials yet. Start the stack once (docker compose up --build -d).")
        sys.exit(1)
    data = json.loads(p.read_text(encoding="utf-8"))
    print(f"CivicBridge LOCAL DEMO credentials (synthetic accounts; generated {data['generated_at']})\n")
    print(f"{'key':10} {'email':42} {'password':22} {'TOTP now':9} roles")
    for key, a in data["accounts"].items():
        code = pyotp.TOTP(a["totp_secret"]).now() if a.get("totp_secret") else "-"
        ro = " [READ-ONLY]" if a.get("read_only") else ""
        print(f"{key:10} {a['email']:42} {a['password']:22} {code:9} {', '.join(a['roles'])}{ro}")
    print("\nTOTP codes rotate every 30 s and can be used once. Run `python -m app.cli totp <key>` for a fresh code, or add the")
    print("secret to an authenticator app: `python -m app.cli totp <key> --secret`.")


def reset_demo_credentials() -> None:
    from app.seed import ensure_accounts

    with session_factory()() as db:
        ensure_accounts(db, reset=True)
        db.commit()
    print("Demo credentials regenerated. Run `python -m app.cli demo-credentials` to view them.")


def totp(key: str, show_secret: bool) -> None:
    from app.seed import credentials_path

    a = json.loads(credentials_path().read_text(encoding="utf-8"))["accounts"].get(key)
    if not a or not a.get("totp_secret"):
        print("Unknown account key or account has no MFA.")
        sys.exit(1)
    print(a["totp_secret"] if show_secret else pyotp.TOTP(a["totp_secret"]).now())


def verify_audit() -> None:
    from app.services.audit import verify_chain

    with session_factory()() as db:
        res = verify_chain(db)
    print(json.dumps(res, indent=2))
    sys.exit(0 if res["ok"] else 1)


def audit_anchor() -> None:
    from app.models import AuditEvent

    with session_factory()() as db:
        head = db.execute(select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(1)).scalar_one_or_none()
    print(json.dumps({"seq": head.seq if head else 0, "hash": head.hash if head else None, "at": head.at.isoformat() if head else None,
                      "note": "Store this outside the database (e.g. a signed ticket) to detect a full-chain rewrite later."}, indent=2))


def _counts(db: Session) -> dict:
    from app.models import AuditEvent, Case, Document, Incident, StoredObject, User

    return {m.__tablename__: db.execute(select(func.count()).select_from(m)).scalar_one() for m in (User, Case, Document, Incident, StoredObject, AuditEvent)}


def backup() -> None:
    from app.models import AuditEvent
    from app.services import storage

    s = get_settings()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(s.backup_dir) / stamp
    out.mkdir(parents=True, exist_ok=False)
    subprocess.run(["pg_dump", "-Fc", "-d", s.db_name, "-f", str(out / "db.dump")], env=_pg_env(), check=True)
    keys = storage.list_keys()
    with tarfile.open(out / "objects.tar", "w") as tar:
        for k in keys:
            data = storage.get(k)
            info = tarfile.TarInfo(name=k)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    with session_factory()() as db:
        head = db.execute(select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(1)).scalar_one_or_none()
        manifest = {"created_at": stamp, "counts": _counts(db), "objects": len(keys), "audit_head": head.hash if head else None,
                    "note": "Backup files are NOT encrypted by CivicBridge. Protect the backup directory with host-level encryption."}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"backup": str(out), **manifest}, indent=2))


def restore_check(path: str) -> None:
    """Restore into a scratch database, verify counts + audit chain, then drop it. Never touches the live database."""
    s = get_settings()
    src = Path(path)
    manifest = json.loads((src / "manifest.json").read_text(encoding="utf-8"))
    scratch = "civicbridge_restore_check"
    admin = create_engine(s.admin_database_url("postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f"DROP DATABASE IF EXISTS {scratch}"))
        c.execute(text(f"CREATE DATABASE {scratch}"))
    try:
        subprocess.run(["pg_restore", "--no-owner", "-d", scratch, str(src / "db.dump")], env=_pg_env(), check=True)
        eng = create_engine(s.admin_database_url(scratch))
        from app.services.audit import verify_chain

        with Session(eng) as db:
            counts = _counts(db)
            chain = verify_chain(db)
        eng.dispose()
        with tarfile.open(src / "objects.tar") as tar:
            objects = len(tar.getmembers())
        ok = counts == manifest["counts"] and chain["ok"] and chain["head"] == manifest["audit_head"] and objects == manifest["objects"]
        print(json.dumps({"ok": ok, "restored_counts": counts, "manifest_counts": manifest["counts"], "audit_chain": chain,
                          "objects_in_archive": objects}, indent=2, default=str))
        if not ok:
            sys.exit(1)
    finally:
        with admin.connect() as c:
            c.execute(text(f"DROP DATABASE IF EXISTS {scratch}"))
        admin.dispose()


def list_backups() -> None:
    root = Path(get_settings().backup_dir)
    for p in sorted(root.glob("*/manifest.json")):
        m = json.loads(p.read_text(encoding="utf-8"))
        print(p.parent.name, m["counts"], "objects:", m["objects"])


def provision_admin() -> None:
    """Create or update the owner's governance administrator from JSON on stdin: {"email", "display_name", "password"}.
    Reads the password from stdin so it never appears in process arguments or shell history. On first creation a TOTP
    secret is generated (the role requires MFA) and printed once as JSON; later runs only reset password and lockout."""
    from app.db import utcnow
    from app.models import Membership, Tenant, User
    from app.security.crypto import encrypt_secret, hash_password, new_totp_secret, password_problems
    from app.services import audit

    data = json.loads(sys.stdin.read())
    email, name, password = data["email"].strip().lower(), data.get("display_name") or "Owner admin", data["password"]
    if problems := password_problems(password):
        print(json.dumps({"ok": False, "error": "weak password: " + ", ".join(problems)}))
        sys.exit(1)
    with session_factory()() as db:
        tenant = db.execute(select(Tenant).where(Tenant.slug == "governance")).scalar_one()
        user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        created, secret = user is None, None
        if created:
            user = User(email=email, display_name=name, locale="en", timezone="Asia/Jerusalem", is_read_only=False, is_synthetic=False,
                        email_verified_at=utcnow(), password_hash=hash_password(password))
            db.add(user)
            db.flush()
        else:
            user.password_hash = hash_password(password)
            user.locked_until, user.failed_logins = None, 0
        if not db.execute(select(Membership).where(Membership.user_id == user.id, Membership.tenant_id == tenant.id,
                                                   Membership.role == "governance_admin")).first():
            db.add(Membership(user_id=user.id, tenant_id=tenant.id, role="governance_admin"))
        if not user.mfa_enabled:
            secret = new_totp_secret()
            user.mfa_secret_enc, user.mfa_enabled, user.mfa_last_step = encrypt_secret(secret), True, None
        audit.record(db, "auth.admin_provisioned", "user", user.id, details={"created": created})
        db.commit()
    out = {"ok": True, "email": email, "created": created}
    if secret:
        out |= {"totp_secret": secret, "otpauth_uri": pyotp.TOTP(secret).provisioning_uri(email, issuer_name="CivicBridge")}
    print(json.dumps(out))


def main(argv: list[str]) -> None:
    if not argv:
        print(__doc__)
        return
    cmd, rest = argv[0], argv[1:]
    if cmd == "bootstrap":
        bootstrap()
    elif cmd == "demo-credentials":
        demo_credentials()
    elif cmd == "reset-demo-credentials":
        reset_demo_credentials()
    elif cmd == "totp" and rest:
        totp(rest[0], "--secret" in rest)
    elif cmd == "verify-audit":
        verify_audit()
    elif cmd == "audit-anchor":
        audit_anchor()
    elif cmd == "backup":
        backup()
    elif cmd == "restore-check" and rest:
        restore_check(rest[0])
    elif cmd == "list-backups":
        list_backups()
    elif cmd == "provision-admin":
        provision_admin()
    else:
        print(__doc__)
        sys.exit(2)


if __name__ == "__main__":
    main(sys.argv[1:])
