"""Universal Civic Translator: assisted translation with side-by-side review. Never certified translation."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.ai import tools
from app.ai.provider import mode as ai_mode
from app.ai.translate import segments
from app.db import utcnow
from app.deps import Ctx, get_ctx
from app.errors import AppError, bad_request
from app.models import Document, DocumentVersion, Translation
from app.routers.common import parse_uuid, row
from app.services import audit
from app.services.access import active_delegations, get_document

router = APIRouter(prefix="/api/translations", tags=["translations"])
FIELDS = ["id", "document_version_id", "case_id", "source_lang", "target_lang", "source_text", "target_text", "segments", "mode",
          "status", "uncertainty", "reviewed_at", "review_note", "is_certified", "created_at", "updated_at"]


class TranslateIn(BaseModel):
    document_id: uuid.UUID | None = None
    version: int | None = None
    text: str | None = Field(default=None, max_length=8000)
    source_lang: str = Field(pattern=r"^(en|he|de)$")
    target_lang: str = Field(pattern=r"^(en|he|de)$")


def _owner_and_text(ctx: Ctx, body: TranslateIn) -> tuple[uuid.UUID, str, uuid.UUID | None]:
    if body.document_id:
        doc, acc = get_document(ctx, body.document_id)
        if acc.via == "consent":
            raise AppError(403, "role_not_permitted", "Translation of consented documents is done by the document owner.")
        v = next((x for x in doc.versions if x.version == (body.version or doc.current_version)), None)
        if v is None or v.object.scan_status != "clean":
            raise AppError(423, "file_not_available", "The document must pass the malware scan first.")
        if not v.extracted_text:
            raise AppError(422, "no_text", f"No text could be extracted from this file ({v.extraction_status}). Images are not OCR-processed.")
        return doc.owner_user_id, v.extracted_text[:8000], v.id
    if not body.text:
        raise bad_request("Provide a document or text.")
    if ctx.workspace != "citizen":
        raise AppError(403, "role_not_permitted", "Free-text translation is available to citizens.")
    return ctx.user.id, body.text, None


@router.post("")
def create(body: TranslateIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    owner_id, text, version_id = _owner_and_text(ctx, body)
    if body.source_lang == body.target_lang:
        raise bad_request("Source and target language must differ.")
    if ai_mode(ctx.db) == "rules":
        # Rules-only mode: no assisted translation. Open a manual translation workspace instead.
        segs = [{"source": s, "target": "", "status": "untranslated", "flags": ["manual_translation_required"]} for s in segments(text)]
        out = {"target_text": "", "segments": segs, "mode": "manual", "status": "needs_review", "uncertainty": ["manual_translation_required"],
               "label": "Rules-only mode: AI translation is disabled. Enter the translation manually.", "coverage": 0.0}
    else:
        res = tools.invoke(ctx, "translate_text", {"text": text, "source_lang": body.source_lang, "target_lang": body.target_lang})
        out = res["result"]
    t = Translation(owner_user_id=owner_id, document_version_id=version_id, source_lang=body.source_lang, target_lang=body.target_lang,
                    source_text=text, target_text=out["target_text"], segments=out["segments"], mode=out["mode"], status=out["status"],
                    uncertainty=out["uncertainty"], is_certified=False)
    ctx.db.add(t)
    ctx.db.flush()
    audit.record(ctx.db, "translation.created", "translation", t.id, **audit.ctx_kw(ctx), subject_user_id=owner_id,
                 details={"mode": t.mode, "status": t.status, "coverage": out["coverage"]})
    ctx.db.commit()
    return row(t, FIELDS) | {"label": out["label"], "coverage": out["coverage"]}


def _can_review(ctx: Ctx, t: Translation) -> bool:
    if ctx.workspace == "citizen":
        return t.owner_user_id == ctx.user.id
    if ctx.workspace == "professional":
        return any(d.principal_user_id == t.owner_user_id and "translation_review" in d.scopes for d in active_delegations(ctx.db, ctx.user.id, ctx.tenant_id))
    return False


@router.get("")
def list_translations(ctx: Ctx = Depends(get_ctx)) -> dict:
    if ctx.workspace == "citizen":
        rows = ctx.db.execute(select(Translation).where(Translation.owner_user_id == ctx.user.id).order_by(Translation.created_at.desc())).scalars().all()
    elif ctx.workspace == "professional":
        principals = [d.principal_user_id for d in active_delegations(ctx.db, ctx.user.id, ctx.tenant_id) if "translation_review" in d.scopes]
        rows = ctx.db.execute(select(Translation).where(Translation.owner_user_id.in_(principals)).order_by(Translation.created_at.desc())).scalars().all() if principals else []
    else:
        rows = []
    return {"items": [row(t, FIELDS) for t in rows]}


@router.get("/{tid}")
def get_one(tid: str, ctx: Ctx = Depends(get_ctx)) -> dict:
    t = ctx.db.get(Translation, parse_uuid(tid))
    if t is None or not _can_review(ctx, t):
        raise AppError(404, "not_found", "Not found.")
    doc_title = None
    if t.document_version_id:
        v = ctx.db.get(DocumentVersion, t.document_version_id)
        doc_title = ctx.db.get(Document, v.document_id).title if v else None
    return row(t, FIELDS) | {"document_title": doc_title}


class ReviewIn(BaseModel):
    status: str = Field(pattern=r"^(reviewed|rejected)$")
    target_text: str | None = Field(default=None, max_length=16000)
    note: str = Field(default="", max_length=2000)


@router.post("/{tid}/review")
def review(tid: str, body: ReviewIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    t = ctx.db.get(Translation, parse_uuid(tid))
    if t is None or not _can_review(ctx, t):
        raise AppError(404, "not_found", "Not found.")
    if body.status == "reviewed" and not (body.target_text or t.target_text).strip():
        raise bad_request("Provide the reviewed translation text.")
    if body.target_text is not None:
        t.target_text = body.target_text
        t.mode = t.mode if t.mode != "mock" else "mock+human"
    t.status = body.status
    t.reviewer_user_id = ctx.user.id
    t.reviewed_at = utcnow()
    t.review_note = body.note
    t.is_certified = False
    audit.record(ctx.db, "translation.reviewed", "translation", t.id, **audit.ctx_kw(ctx), subject_user_id=t.owner_user_id, details={"status": body.status})
    ctx.db.commit()
    return row(t, FIELDS)
