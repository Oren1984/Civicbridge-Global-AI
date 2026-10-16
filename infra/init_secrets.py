"""First-run local secret generation (runs once in the `init-secrets` service).

Creates random secrets in the private `secrets` volume if they do not exist yet. Existing files are never
overwritten, so restarts keep the same credentials. Each consumer gets its own copy with tight ownership:
  uid 999   = postgres (database container)
  uid 10001 = CivicBridge backend/worker
  uid 1000  = SeaweedFS (its entrypoint drops to the 'seaweed' user)
  uid 0     = LiveKit (runs as root in its official image)
"""
import base64
import json
import os
import secrets
import sys

ROOT = "/secrets"
APP, PG, ROOTUID, SEAWEED = 10001, 999, 0, 1000


def write(name: str, content: str, uid: int, mode: int = 0o400) -> None:
    path = os.path.join(ROOT, name)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    os.chown(path, uid, uid)
    os.chmod(path, mode)


def read_or(name: str, factory) -> str:
    path = os.path.join(ROOT, name)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    return factory()


def main() -> None:
    os.makedirs(ROOT, exist_ok=True)
    os.chmod(ROOT, 0o755)
    pg_admin = read_or("pg_admin_password", lambda: secrets.token_urlsafe(24))
    pg_app = read_or("pg_app_password", lambda: secrets.token_urlsafe(24))
    write("pg_admin_password", pg_admin, PG)
    write("pg_admin_password_app", pg_admin, APP)
    write("pg_app_password", pg_app, APP)
    write("app_secret_key", secrets.token_urlsafe(48), APP)
    write("mfa_key", base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(), APP)

    s3_access = read_or("s3_credentials", lambda: f"cb{secrets.token_hex(8)}:{secrets.token_urlsafe(30)}")
    access, _, secret = s3_access.partition(":")
    write("s3_credentials", f"{access}:{secret}", APP)
    write("s3.json", json.dumps({"identities": [{"name": "civicbridge", "credentials": [{"accessKey": access, "secretKey": secret}],
                                                 "actions": ["Admin", "Read", "Write", "List", "Tagging"]}]}), SEAWEED)

    # LiveKit: the key name is fixed (not secret, referenced by livekit.yaml webhook config); the secret is random.
    lk_secret = read_or("livekit_credentials", lambda: "cbkey:" + secrets.token_urlsafe(40)).partition(":")[2]
    write("livekit_credentials", f"cbkey:{lk_secret}", APP)
    write("livekit_keys.yaml", f"cbkey: {lk_secret}\n", ROOTUID, 0o600)
    print("secrets ready (existing files kept)", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"secret initialisation failed: {exc}", file=sys.stderr)
        sys.exit(1)
