"""Runtime configuration.

Secrets are never hard-coded. In Docker they are generated on first start by the
``init-secrets`` service into a private volume and read here from ``*_FILE`` paths.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _read(path: str | None) -> str | None:
    if not path:
        return None
    p = Path(path)
    return p.read_text(encoding="utf-8").strip() if p.exists() else None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CB_", extra="ignore")

    env: str = "local"
    public_origin: str = "http://localhost:8084"
    allowed_origins: str = "http://localhost:8084,http://127.0.0.1:8084"

    db_host: str = "db"
    db_port: int = 5432
    db_name: str = "civicbridge"
    db_user: str = "civicbridge_app"  # non-superuser runtime role (no UPDATE/DELETE on audit_events)
    db_password: str | None = None
    db_password_file: str | None = None
    db_admin_user: str = "civicbridge_admin"  # migrations, backup, restore checks
    db_admin_password: str | None = None
    db_admin_password_file: str | None = None

    secret_key: str | None = None
    secret_key_file: str | None = None
    mfa_key: str | None = None  # Fernet key used to encrypt TOTP secrets at rest
    mfa_key_file: str | None = None

    s3_endpoint: str = "http://storage:8333"
    s3_bucket: str = "civicbridge-documents"
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_credentials_file: str | None = None  # "access:secret"

    clamav_host: str = "clamav"
    clamav_port: int = 3310
    scanner_timeout_s: float = 30.0

    smtp_host: str = "mailpit"
    smtp_port: int = 1025
    mail_from: str = "CivicBridge Local <no-reply@civicbridge.local>"

    internal_api_url: str = "http://backend:8000"
    livekit_internal_url: str = "http://livekit:7880"
    livekit_public_url: str = "ws://localhost:8084"
    livekit_api_key: str | None = None
    livekit_api_secret: str | None = None
    livekit_credentials_file: str | None = None  # "key:secret"
    meeting_token_ttl_s: int = 600

    ai_mode: str = "mock"  # rules | mock | ollama
    ollama_url: str = "http://ollama:11434"
    ollama_model: str = "llama3.2:3b"

    demo_credentials_file: str | None = None
    session_idle_minutes: int = 30
    session_absolute_hours: int = 12
    cookie_secure: bool = False
    max_upload_mb: int = 15
    backup_dir: str = "/backups"
    seed_demo: bool = True

    def resolved_db_password(self) -> str:
        return self.db_password or _read(self.db_password_file) or "civicbridge"

    def resolved_secret_key(self) -> str:
        key = self.secret_key or _read(self.secret_key_file)
        if not key:
            raise RuntimeError("CB_SECRET_KEY / CB_SECRET_KEY_FILE is required")
        return key

    def resolved_mfa_key(self) -> str:
        key = self.mfa_key or _read(self.mfa_key_file)
        if not key:
            raise RuntimeError("CB_MFA_KEY / CB_MFA_KEY_FILE is required")
        return key

    def s3_credentials(self) -> tuple[str, str]:
        if self.s3_access_key and self.s3_secret_key:
            return self.s3_access_key, self.s3_secret_key
        raw = _read(self.s3_credentials_file) or ":"
        a, _, s = raw.partition(":")
        return a, s

    def livekit_credentials(self) -> tuple[str, str]:
        if self.livekit_api_key and self.livekit_api_secret:
            return self.livekit_api_key, self.livekit_api_secret
        raw = _read(self.livekit_credentials_file) or ":"
        k, _, s = raw.partition(":")
        return k, s

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.db_user}:{self.resolved_db_password()}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    def resolved_db_admin_password(self) -> str:
        return self.db_admin_password or _read(self.db_admin_password_file) or self.resolved_db_password()

    def admin_database_url(self, db_name: str | None = None) -> str:
        return (
            f"postgresql+psycopg://{self.db_admin_user}:{self.resolved_db_admin_password()}"
            f"@{self.db_host}:{self.db_port}/{db_name or self.db_name}"
        )

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
