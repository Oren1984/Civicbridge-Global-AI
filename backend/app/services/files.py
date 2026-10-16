"""Upload validation: size quota, extension + magic-byte allowlist, safe filenames, storage and scan queueing."""
from __future__ import annotations

import hashlib
import io
import re
import unicodedata
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import AppError, bad_request
from app.models import StoredObject
from app.services import jobs, policies, storage

# extension -> (mime, magic check)
_TYPES = {
    "pdf": ("application/pdf", lambda b: b.startswith(b"%PDF-")),
    "png": ("image/png", lambda b: b.startswith(b"\x89PNG\r\n\x1a\n")),
    "jpg": ("image/jpeg", lambda b: b.startswith(b"\xff\xd8\xff")),
    "jpeg": ("image/jpeg", lambda b: b.startswith(b"\xff\xd8\xff")),
    "txt": ("text/plain", lambda b: b"\x00" not in b[:4096]),
    "webm": ("audio/webm", lambda b: b.startswith(b"\x1a\x45\xdf\xa3")),
    "ogg": ("audio/ogg", lambda b: b.startswith(b"OggS")),
    "mp3": ("audio/mpeg", lambda b: b.startswith(b"ID3") or b[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")),
    "wav": ("audio/wav", lambda b: b.startswith(b"RIFF") and b[8:12] == b"WAVE"),
    "m4a": ("audio/mp4", lambda b: b[4:8] == b"ftyp"),
}
ALLOW = {
    "document": {"pdf", "png", "jpg", "jpeg", "txt"},
    "incident_media": {"png", "jpg", "jpeg", "webm", "ogg", "mp3", "wav", "m4a"},
    "resolution_evidence": {"png", "jpg", "jpeg", "pdf"},
}


def safe_filename(name: str) -> str:
    name = unicodedata.normalize("NFKC", (name or "file").replace("\\", "/").split("/")[-1])
    stem, _, ext = name.rpartition(".")
    if not stem:
        stem, ext = ext, ""
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._") or "file"
    ext = re.sub(r"[^A-Za-z0-9]", "", ext).lower()[:8]
    return f"{stem[:80]}.{ext}" if ext else stem[:80]


def classify(filename: str, data: bytes, purpose: str) -> tuple[str, str]:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOW.get(purpose, set()):
        raise bad_request(
            f"File type '.{ext}' is not allowed here. Allowed: {', '.join(sorted(ALLOW[purpose]))}.", "file_type_not_allowed"
        )
    mime, check = _TYPES[ext]
    if not check(data):
        raise bad_request("File content does not match its extension.", "file_content_mismatch")
    if ext == "txt":
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise bad_request("Text files must be UTF-8.", "file_content_mismatch") from exc
    return ext, mime


def store_upload(db: Session, *, owner_user_id: uuid.UUID, tenant_id, purpose: str, filename: str, data: bytes) -> StoredObject:
    max_mb = int(policies.get(db, "max_upload_mb"))
    if len(data) == 0:
        raise bad_request("The file is empty.", "file_empty")
    if len(data) > max_mb * 1024 * 1024:
        raise AppError(413, "file_too_large", f"Files must be {max_mb} MB or smaller.")
    used = db.execute(
        select(func.coalesce(func.sum(StoredObject.size), 0)).where(
            StoredObject.owner_user_id == owner_user_id, StoredObject.deleted_at.is_(None)
        )
    ).scalar_one()
    quota_mb = int(policies.get(db, "user_quota_mb"))
    if used + len(data) > quota_mb * 1024 * 1024:
        raise AppError(413, "quota_exceeded", f"Storage quota of {quota_mb} MB would be exceeded.")
    ext, mime = classify(filename, data, purpose)
    oid = uuid.uuid4()
    key = f"{purpose}/{owner_user_id}/{oid}.{ext}"
    storage.put(key, data, mime)
    obj = StoredObject(
        id=oid,
        storage_key=key,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
        purpose=purpose,
        original_filename=(filename or "file")[:300],
        safe_filename=safe_filename(filename),
        mime=mime,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        scan_status="pending",
    )
    db.add(obj)
    db.flush()
    jobs.enqueue(db, "scan_object", {"object_id": str(obj.id)}, max_attempts=6)
    return obj


def store_derived(db: Session, *, owner_user_id: uuid.UUID, purpose: str, filename: str, data: bytes, mime: str) -> StoredObject:
    """Server-generated derivative (redaction, export). Still scanned before it can be served."""
    oid = uuid.uuid4()
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    key = f"{purpose}/{owner_user_id}/{oid}.{ext}"
    storage.put(key, data, mime)
    obj = StoredObject(
        id=oid,
        storage_key=key,
        owner_user_id=owner_user_id,
        purpose=purpose,
        original_filename=filename,
        safe_filename=safe_filename(filename),
        mime=mime,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        scan_status="pending",
    )
    db.add(obj)
    db.flush()
    jobs.enqueue(db, "scan_object", {"object_id": str(obj.id)}, max_attempts=6)
    return obj


def extract_text(data: bytes, mime: str) -> tuple[str | None, str]:
    """Return (text, status). Images: no OCR is bundled, so text extraction is reported as unsupported."""
    if mime == "text/plain":
        return data.decode("utf-8", errors="replace")[:200_000], "extracted"
    if mime == "application/pdf":
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data))
            parts = []
            for page in reader.pages[:50]:
                parts.append(page.extract_text() or "")
            text = "\n".join(parts).strip()
            return (text[:200_000], "extracted") if text else (None, "no_text_layer")
        except Exception:  # noqa: BLE001
            return None, "extraction_failed"
    if mime.startswith("image/"):
        return None, "unsupported_no_ocr"
    return None, "not_applicable"
