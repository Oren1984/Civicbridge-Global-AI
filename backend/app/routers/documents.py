"""Global Civic Identity Wallet: document vault, versions, scanning state, safe preview/download, redaction, receipts."""
from __future__ import annotations

import io
import re
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.db import utcnow
from app.deps import Ctx, get_ctx
from app.errors import AppError, bad_request
from app.models import Document, DocumentVersion, EvidenceLink, ShareReceipt, Tenant, User
from app.routers.common import iso, parse_uuid, row
from app.services import audit, files, jobs, storage
from app.services.access import active_delegations, document_access, get_document, receipt, require_clean

router = APIRouter(prefix="/api/documents", tags=["documents"])
CATEGORIES = ("identity", "civil_status", "employment", "education", "financial", "housing", "health", "other")
DOC_FIELDS = ["id", "title", "category", "doc_type", "issuer", "issued_at", "expires_at", "verification_status", "language",
              "current_version", "retention_until", "created_at", "updated_at"]


def _version_out(v: DocumentVersion) -> dict:
    o = v.object
    return {
        **row(v, ["id", "version", "kind", "derived_from_version_id", "extraction_status", "note", "created_at"]),
        "filename": o.safe_filename, "mime": o.mime, "size": o.size, "sha256": o.sha256,
        "scan_status": o.scan_status, "scan_detail": o.scan_detail, "scanned_at": iso(o.scanned_at),
        "available": o.scan_status == "clean",
    }


def doc_out(doc: Document, via: str) -> dict:
    return {**row(doc, DOC_FIELDS), "access_via": via, "versions": [_version_out(v) for v in doc.versions]}


def _owner_for_upload(ctx: Ctx, on_behalf_of: str | None) -> uuid.UUID:
    if ctx.workspace == "citizen":
        return ctx.user.id
    if ctx.workspace == "professional" and on_behalf_of:
        principal = parse_uuid(on_behalf_of, "on_behalf_of")
        if any(d.principal_user_id == principal and "upload_documents" in d.scopes for d in active_delegations(ctx.db, ctx.user.id, ctx.tenant_id)):
            return principal
    raise AppError(403, "role_not_permitted", "You cannot upload documents in this context.")


@router.get("")
def list_documents(ctx: Ctx = Depends(get_ctx), owner: str | None = None, category: str | None = None, q: str | None = None) -> dict:
    db = ctx.db
    stmt = select(Document).where(Document.deleted_at.is_(None))
    if ctx.workspace == "citizen":
        stmt = stmt.where(Document.owner_user_id == ctx.user.id)
    elif owner:
        stmt = stmt.where(Document.owner_user_id == parse_uuid(owner, "owner"))
    elif ctx.workspace not in ("professional", "authority", "institution"):
        return {"items": []}
    if category:
        stmt = stmt.where(Document.category == category)
    if q:
        stmt = stmt.where(Document.title.ilike(f"%{q[:80]}%"))
    out = []
    for d in db.execute(stmt.order_by(Document.updated_at.desc()).limit(200)).scalars():
        acc = document_access(ctx, d)
        if acc is not None:
            item = doc_out(d, acc.via)
            if ctx.workspace != "citizen":
                owner_user = db.get(User, d.owner_user_id)
                item["owner"] = {"id": str(owner_user.id), "display_name": owner_user.display_name}
            out.append(item)
    return {"items": out, "categories": CATEGORIES}


@router.post("")
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(..., min_length=2, max_length=300),
    category: str = Form(...),
    doc_type: str = Form("other", max_length=64),
    issuer: str = Form("", max_length=200),
    issued_at: str | None = Form(None),
    expires_at: str | None = Form(None),
    language: str = Form("en", pattern=r"^(en|he|de)$"),
    on_behalf_of: str | None = Form(None),
    ctx: Ctx = Depends(get_ctx),
) -> dict:
    if category not in CATEGORIES:
        raise bad_request("Unknown category.")
    owner_id = _owner_for_upload(ctx, on_behalf_of)
    data = await file.read(16 * 1024 * 1024 + 1)

    def _dt(v: str | None):
        if not v:
            return None
        try:
            return datetime.fromisoformat(v)
        except ValueError as exc:
            raise bad_request("Invalid date.") from exc

    obj = files.store_upload(ctx.db, owner_user_id=owner_id, tenant_id=None, purpose="document", filename=file.filename or "file", data=data)
    doc = Document(owner_user_id=owner_id, title=title, category=category, doc_type=doc_type, issuer=issuer,
                   issued_at=_dt(issued_at), expires_at=_dt(expires_at), language=language)
    ctx.db.add(doc)
    ctx.db.flush()
    v = DocumentVersion(document_id=doc.id, version=1, object_id=obj.id, created_by=ctx.user.id,
                        note="Uploaded by authorized representative" if owner_id != ctx.user.id else "")
    ctx.db.add(v)
    audit.record(ctx.db, "document.uploaded", "document", doc.id, **audit.ctx_kw(ctx), subject_user_id=owner_id,
                 details={"category": category, "size": obj.size, "mime": obj.mime, "scan_status": obj.scan_status})
    ctx.db.commit()
    ctx.db.refresh(doc)
    return doc_out(doc, "owner" if owner_id == ctx.user.id else "delegation")


@router.get("/{doc_id}")
def get_doc(doc_id: str, ctx: Ctx = Depends(get_ctx)) -> dict:
    doc, acc = get_document(ctx, parse_uuid(doc_id))
    receipt(ctx, doc, acc, "metadata")
    links = ctx.db.execute(select(EvidenceLink).where(EvidenceLink.document_id == doc.id)).scalars().all()
    ctx.db.commit()
    out = doc_out(doc, acc.via)
    out["evidence_links"] = [row(e, ["id", "case_id", "task_id", "service_request_id", "evidence_key", "status"]) for e in links] if acc.via == "owner" else []
    cur = next((v for v in doc.versions if v.version == doc.current_version), None)
    out["extracted_text_preview"] = (cur.extracted_text or "")[:4000] if cur and cur.object.scan_status == "clean" else None
    return out


@router.post("/{doc_id}/versions")
async def new_version(doc_id: str, file: UploadFile = File(...), note: str = Form("", max_length=500), ctx: Ctx = Depends(get_ctx)) -> dict:
    doc, acc = get_document(ctx, parse_uuid(doc_id))
    if acc.via == "consent" or (acc.via == "delegation" and "upload_documents" not in acc.delegation.scopes):
        raise AppError(403, "role_not_permitted", "You cannot add versions to this document.")
    data = await file.read(16 * 1024 * 1024 + 1)
    obj = files.store_upload(ctx.db, owner_user_id=doc.owner_user_id, tenant_id=None, purpose="document", filename=file.filename or "file", data=data)
    doc.current_version += 1
    ctx.db.add(DocumentVersion(document_id=doc.id, version=doc.current_version, object_id=obj.id, created_by=ctx.user.id, note=note))
    doc.verification_status = "unverified"
    audit.record(ctx.db, "document.version_added", "document", doc.id, **audit.ctx_kw(ctx), subject_user_id=doc.owner_user_id,
                 details={"version": doc.current_version})
    ctx.db.commit()
    ctx.db.refresh(doc)
    return doc_out(doc, acc.via)


def _version(doc: Document, number: int) -> DocumentVersion:
    v = next((x for x in doc.versions if x.version == number), None)
    if v is None:
        raise AppError(404, "not_found", "Version not found.")
    return v


_SAFE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; sandbox",
    "Cache-Control": "private, no-store",
    "Cross-Origin-Resource-Policy": "same-origin",
}


@router.get("/{doc_id}/versions/{number}/download")
def download(doc_id: str, number: int, ctx: Ctx = Depends(get_ctx)) -> Response:
    doc, acc = get_document(ctx, parse_uuid(doc_id))
    v = _version(doc, number)
    require_clean(v)
    data = storage.get(v.object.storage_key)
    receipt(ctx, doc, acc, "download")
    audit.record(ctx.db, "document.downloaded", "document", doc.id, **audit.ctx_kw(ctx), subject_user_id=doc.owner_user_id,
                 details={"version": number, "via": acc.via})
    ctx.db.commit()
    return Response(data, media_type="application/octet-stream",
                    headers={**_SAFE_HEADERS, "Content-Disposition": f'attachment; filename="{v.object.safe_filename}"'})


@router.get("/{doc_id}/versions/{number}/preview")
def preview(doc_id: str, number: int, ctx: Ctx = Depends(get_ctx)) -> Response:
    """Inline preview only for clean images, PDFs and text, served with a sandboxing CSP."""
    doc, acc = get_document(ctx, parse_uuid(doc_id))
    v = _version(doc, number)
    require_clean(v)
    if v.object.mime not in ("image/png", "image/jpeg", "application/pdf", "text/plain"):
        raise AppError(415, "preview_not_supported", "Preview is not available for this file type; download it instead.")
    data = storage.get(v.object.storage_key)
    receipt(ctx, doc, acc, "preview")
    audit.record(ctx.db, "document.previewed", "document", doc.id, **audit.ctx_kw(ctx), subject_user_id=doc.owner_user_id,
                 details={"version": number, "via": acc.via})
    ctx.db.commit()
    mime = "text/plain; charset=utf-8" if v.object.mime == "text/plain" else v.object.mime
    return Response(data, media_type=mime, headers={**_SAFE_HEADERS, "Content-Disposition": "inline"})


class DocPatch(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=300)
    expires_at: datetime | None = None
    issuer: str | None = Field(default=None, max_length=200)
    category: str | None = None


@router.patch("/{doc_id}")
def patch_doc(doc_id: str, body: DocPatch, ctx: Ctx = Depends(get_ctx)) -> dict:
    doc, acc = get_document(ctx, parse_uuid(doc_id))
    if acc.via != "owner":
        raise AppError(403, "role_not_permitted", "Only the owner edits document metadata.")
    if body.category and body.category not in CATEGORIES:
        raise bad_request("Unknown category.")
    for f in ("title", "expires_at", "issuer", "category"):
        val = getattr(body, f)
        if val is not None:
            setattr(doc, f, val)
    audit.record(ctx.db, "document.updated", "document", doc.id, **audit.ctx_kw(ctx), subject_user_id=doc.owner_user_id)
    ctx.db.commit()
    return doc_out(doc, acc.via)


@router.delete("/{doc_id}")
def delete_doc(doc_id: str, ctx: Ctx = Depends(get_ctx)) -> dict:
    doc, acc = get_document(ctx, parse_uuid(doc_id))
    if acc.via != "owner":
        raise AppError(403, "role_not_permitted", "Only the owner deletes documents.")
    doc.deleted_at = utcnow()
    for v in doc.versions:
        jobs.enqueue(ctx.db, "delete_object", {"object_id": str(v.object_id)})
    audit.record(ctx.db, "document.deleted", "document", doc.id, **audit.ctx_kw(ctx), subject_user_id=doc.owner_user_id)
    ctx.db.commit()
    return {"ok": True, "note": "The document is no longer accessible. Stored file versions are erased by the background worker."}


class RedactIn(BaseModel):
    version: int
    terms: list[str] = Field(default_factory=list, max_length=50)
    regions: list[list[float]] = Field(default_factory=list, max_length=50)  # [x, y, w, h] as fractions 0..1 for images


@router.post("/{doc_id}/redact")
def redact(doc_id: str, body: RedactIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    """Create a *derived* version with content removed. The original version is kept unchanged (it is not deleted).

    * text/plain: matching terms are replaced in a new text file.
    * PDF: a new text-only file is produced from the extracted text with terms removed; PDF layout is not preserved.
    * images: pixels in the given regions are overwritten in a new PNG (the derivative contains no original pixels there).
    """
    doc, acc = get_document(ctx, parse_uuid(doc_id))
    if acc.via != "owner":
        raise AppError(403, "role_not_permitted", "Only the owner can create redacted copies.")
    v = _version(doc, body.version)
    require_clean(v)
    data = storage.get(v.object.storage_key)
    mime = v.object.mime
    terms = [t for t in (s.strip() for s in body.terms) if len(t) >= 2]
    if mime in ("text/plain", "application/pdf"):
        if not terms:
            raise bad_request("Enter at least one word or number to remove.")
        text = data.decode("utf-8", errors="replace") if mime == "text/plain" else (v.extracted_text or "")
        if not text:
            raise bad_request("No extractable text in this file; redaction by text is not possible.")
        removed = 0
        for t in terms:
            text, n = re.subn(re.escape(t), "█" * 8, text, flags=re.I)
            removed += n
        out_bytes, out_name, out_mime = text.encode(), f"{v.object.safe_filename.rsplit('.', 1)[0]}_redacted.txt", "text/plain"
        note = f"Redacted derivative: {removed} occurrence(s) of {len(terms)} term(s) removed from the text. " + (
            "Produced as text-only from the PDF's text layer; layout and images are not included." if mime == "application/pdf" else "")
        extracted = text
    elif mime in ("image/png", "image/jpeg"):
        if not body.regions:
            raise bad_request("Select at least one region to black out.")
        from PIL import Image, ImageDraw

        img = Image.open(io.BytesIO(data)).convert("RGB")
        draw = ImageDraw.Draw(img)
        w, h = img.size
        for r in body.regions:
            if len(r) != 4 or not all(0 <= x <= 1 for x in r):
                raise bad_request("Regions must be [x, y, width, height] fractions between 0 and 1.")
            x, y, rw, rh = r
            draw.rectangle([int(x * w), int(y * h), int((x + rw) * w), int((y + rh) * h)], fill=(0, 0, 0))
        buf = io.BytesIO()
        img.save(buf, "PNG")  # re-encoded: no EXIF metadata carried over
        out_bytes, out_name, out_mime = buf.getvalue(), f"{v.object.safe_filename.rsplit('.', 1)[0]}_redacted.png", "image/png"
        note = f"Redacted derivative: {len(body.regions)} region(s) overwritten with black pixels; image metadata removed."
        extracted = None
    else:
        raise AppError(415, "redaction_not_supported", "Redaction is not supported for this file type.")
    obj = files.store_derived(ctx.db, owner_user_id=doc.owner_user_id, purpose="derived", filename=out_name, data=out_bytes, mime=out_mime)
    doc.current_version += 1
    nv = DocumentVersion(document_id=doc.id, version=doc.current_version, object_id=obj.id, kind="redacted_derivative",
                         derived_from_version_id=v.id, extracted_text=extracted, extraction_status="extracted" if extracted else "not_applicable",
                         created_by=ctx.user.id, note=note + " The original version still exists until you delete the document.")
    ctx.db.add(nv)
    audit.record(ctx.db, "document.redacted", "document", doc.id, **audit.ctx_kw(ctx), subject_user_id=doc.owner_user_id,
                 details={"from_version": v.version, "to_version": doc.current_version})
    ctx.db.commit()
    ctx.db.refresh(doc)
    return doc_out(doc, "owner")


@router.get("/{doc_id}/receipts")
def receipts(doc_id: str, ctx: Ctx = Depends(get_ctx)) -> dict:
    doc, acc = get_document(ctx, parse_uuid(doc_id))
    if acc.via != "owner":
        raise AppError(403, "role_not_permitted", "Only the owner sees sharing receipts.")
    rows = ctx.db.execute(select(ShareReceipt).where(ShareReceipt.document_id == doc.id).order_by(ShareReceipt.at.desc()).limit(200)).scalars()
    out = []
    for r in rows:
        u = ctx.db.get(User, r.accessed_by_user_id)
        t = ctx.db.get(Tenant, r.accessed_by_tenant_id) if r.accessed_by_tenant_id else None
        out.append({**row(r, ["id", "action", "at", "consent_grant_id", "delegation_id"]), "accessed_by": u.display_name if u else "?",
                    "organisation": t.name if t else None})
    return {"items": out}


@router.get("/receipts/all")
def all_receipts(ctx: Ctx = Depends(get_ctx)) -> dict:
    if ctx.workspace != "citizen":
        return {"items": []}
    rows = ctx.db.execute(select(ShareReceipt).where(ShareReceipt.owner_user_id == ctx.user.id).order_by(ShareReceipt.at.desc()).limit(200)).scalars()
    out = []
    for r in rows:
        u = ctx.db.get(User, r.accessed_by_user_id)
        t = ctx.db.get(Tenant, r.accessed_by_tenant_id) if r.accessed_by_tenant_id else None
        d = ctx.db.get(Document, r.document_id)
        out.append({**row(r, ["id", "action", "at", "consent_grant_id", "delegation_id", "document_id"]),
                    "document_title": d.title if d else "", "accessed_by": u.display_name if u else "?", "organisation": t.name if t else None})
    return {"items": out}
