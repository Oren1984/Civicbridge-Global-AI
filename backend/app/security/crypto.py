"""Password hashing (Argon2id), random tokens, TOTP with replay protection, MFA secret encryption."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet

from app.config import get_settings

_ph = PasswordHasher()  # argon2id with library defaults
_DUMMY_HASH = _ph.hash("timing-equaliser-not-a-password")


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _ph.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def password_problems(password: str) -> list[str]:
    problems = []
    if len(password) < 12:
        problems.append("at least 12 characters")
    if password.lower() == password or password.upper() == password:
        problems.append("mixed upper and lower case")
    if not any(c.isdigit() for c in password):
        problems.append("at least one digit")
    return problems


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def sha256_hex(value: str | bytes) -> str:
    if isinstance(value, str):
        value = value.encode()
    return hashlib.sha256(value).hexdigest()


def keyed_hash(value: str) -> str:
    """HMAC used for pseudonymised values such as IP addresses in sessions/logs."""
    return hmac.new(get_settings().resolved_secret_key().encode(), value.encode(), hashlib.sha256).hexdigest()[:32]


def _fernet() -> Fernet:
    return Fernet(get_settings().resolved_mfa_key().encode())


def encrypt_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def decrypt_secret(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name="CivicBridge (local demo)")


def verify_totp(secret: str, code: str, last_step: int | None) -> int | None:
    """Return the accepted time step, or None. Rejects re-use of an already accepted step (replay)."""
    code = (code or "").strip().replace(" ", "")
    if not code.isdigit() or len(code) != 6:
        return None
    totp = pyotp.TOTP(secret)
    now_step = int(time.time()) // 30
    for step in (now_step - 1, now_step, now_step + 1):
        if hmac.compare_digest(totp.at(step * 30), code):
            if last_step is not None and step <= last_step:
                return None
            return step
    return None
