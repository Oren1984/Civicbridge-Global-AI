"""Subject access / export and deletion requests (processed by the worker)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.deps import Ctx, require_workspace
from app.errors import AppError, bad_request
from app.models import PrivacyRequest, StoredObject
from app.routers.common import parse_uuid, row
from app.services import audit, jobs, storage

router = APIRouter(prefix="/api/privacy", tags=["privacy"])
FIELDS = ["id", "kind", "status", "notes", "created_at", "completed_at", "result_object_id"]


class RequestIn(BaseModel):
    kind: str = Field(pattern=r"^(export|deletion)$")
    confirm: str = Field(default="", max_length=20)


@router.post("/requests")
def create(body: RequestIn, ctx: Ctx = Depends(require_workspace("citizen"))) -> dict:
    if body.kind == "deletion" and body.confirm != "DELETE":
        raise bad_request("Type DELETE to confirm the deletion request.")
    open_ = ctx.db.execute(select(PrivacyRequest).where(PrivacyRequest.user_id == ctx.user.id, PrivacyRequest.kind == body.kind,
                                                       PrivacyRequest.status.in_(("queued", "processing")))).scalar_one_or_none()
    if open_:
        return row(open_, FIELDS)
    pr = PrivacyRequest(user_id=ctx.user.id, kind=body.kind)
    ctx.db.add(pr)
    ctx.db.flush()
    jobs.enqueue(ctx.db, f"privacy_{body.kind}", {"request_id": str(pr.id)})
    audit.record(ctx.db, f"privacy.{body.kind}_requested", "privacy_request", pr.id, **audit.ctx_kw(ctx), subject_user_id=ctx.user.id)
    ctx.db.commit()
    return row(pr, FIELDS)


@router.get("/requests")
def list_requests(ctx: Ctx = Depends(require_workspace("citizen"))) -> dict:
    rows = ctx.db.execute(select(PrivacyRequest).where(PrivacyRequest.user_id == ctx.user.id).order_by(PrivacyRequest.created_at.desc())).scalars()
    return {"items": [row(r, FIELDS) for r in rows]}


@router.get("/requests/{rid}/download")
def download(rid: str, ctx: Ctx = Depends(require_workspace("citizen"))) -> Response:
    pr = ctx.db.get(PrivacyRequest, parse_uuid(rid))
    if pr is None or pr.user_id != ctx.user.id or pr.result_object_id is None:
        raise AppError(404, "not_found", "Not found.")
    o = ctx.db.get(StoredObject, pr.result_object_id)
    if o.scan_status != "clean" or o.deleted_at:
        raise AppError(423, "file_not_available", f"Export not available yet (scan status: {o.scan_status}).")
    audit.record(ctx.db, "privacy.export_downloaded", "privacy_request", pr.id, **audit.ctx_kw(ctx), subject_user_id=ctx.user.id)
    ctx.db.commit()
    return Response(storage.get(o.storage_key), media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="civicbridge-export.zip"', "Cache-Control": "private, no-store",
                             "X-Content-Type-Options": "nosniff"})
