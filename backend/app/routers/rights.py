"""Civic Rights Navigator: deterministic screening, source-linked answers, human review requests."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.ai import rag, rules
from app.deps import Ctx, get_ctx
from app.errors import AppError, bad_request
from app.models import Case, Jurisdiction, RuleSet, RuleVersion, ScreeningResult
from app.routers.common import parse_uuid, row
from app.services import audit, workflow
from app.services.access import accessible_document_ids
from app.services.refs import next_ref
from app.services.timeline import add_event

router = APIRouter(prefix="/api/rights", tags=["rights"])


@router.get("/rulesets")
def rulesets(ctx: Ctx = Depends(get_ctx), jurisdiction: str | None = None) -> dict:
    out = []
    for rs in ctx.db.execute(select(RuleSet).order_by(RuleSet.pack_code, RuleSet.name)).scalars():
        rv = rules.current_version(ctx.db, rs.id)
        j = rs.procedure.service.authority.jurisdiction
        if jurisdiction and not j.code.startswith(jurisdiction):
            continue
        out.append({
            "code": rs.code, "name": rs.name, "topic": rs.topic, "pack": rs.pack_code, "consequential": rs.consequential,
            "jurisdiction": j.code, "jurisdiction_name": j.name, "authority": rs.procedure.service.authority.name,
            "current_version": {
                "id": str(rv.id), "version": rv.version, "effective_from": rv.effective_from.isoformat(),
                "effective_to": rv.effective_to.isoformat() if rv.effective_to else None, "review_date": rv.review_date.isoformat(),
                "review_status": rv.review_status, "verification_status": rv.verification_status, "confidence": rv.confidence,
                "questions": rv.questions, "language": rv.language,
            } if rv else None,
            "versions": [{"version": v.version, "effective_from": v.effective_from.isoformat(),
                          "effective_to": v.effective_to.isoformat() if v.effective_to else None} for v in rs.versions],
        })
    return {"items": out}


class ScreenIn(BaseModel):
    rule_set_code: str = Field(max_length=64)
    answers: dict = Field(default_factory=dict)
    case_id: uuid.UUID | None = None


@router.post("/screen")
def screen(body: ScreenIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    if ctx.workspace not in ("citizen", "professional"):
        raise AppError(403, "role_not_permitted", "Screening is available in the citizen and professional workspaces.")
    rs = ctx.db.execute(select(RuleSet).where(RuleSet.code == body.rule_set_code)).scalar_one_or_none()
    if rs is None:
        raise bad_request("Unknown rule set.")
    rv = rules.current_version(ctx.db, rs.id)
    if rv is None:
        raise AppError(409, "no_valid_rule_version", "No rule version is currently in force for this topic.")
    answers = {k: v for k, v in body.answers.items() if isinstance(v, (str, int, float, bool)) and len(str(k)) < 64}
    res = rules.screen(ctx.db, rv, answers)
    case_id = None
    if body.case_id and ctx.workspace == "citizen":
        c = ctx.db.get(Case, body.case_id)
        if c and c.owner_user_id == ctx.user.id:
            case_id = c.id
    sr = ScreeningResult(user_id=ctx.user.id, case_id=case_id, rule_version_id=rv.id, answers=answers, indication=res["indication"],
                         explanation=res["explanation"], missing=res["missing"], uncertainty=res["uncertainty"], citations=res["citations"],
                         requires_human_review=res["requires_human_review"])
    ctx.db.add(sr)
    ctx.db.flush()
    audit.record(ctx.db, "rights.screened", "screening_result", sr.id, **audit.ctx_kw(ctx), subject_user_id=ctx.user.id,
                 details={"rule_set": rs.code, "version": rv.version, "indication": res["indication"]})
    ctx.db.commit()
    return {"screening_id": str(sr.id), **res}


@router.get("/screenings")
def screenings(ctx: Ctx = Depends(get_ctx)) -> dict:
    rows = ctx.db.execute(select(ScreeningResult).where(ScreeningResult.user_id == ctx.user.id).order_by(ScreeningResult.created_at.desc()).limit(50)).scalars()
    out = []
    for s in rows:
        rv = ctx.db.get(RuleVersion, s.rule_version_id)
        out.append({**row(s, ["id", "indication", "requires_human_review", "review_request_id", "case_id", "created_at", "missing", "uncertainty"]),
                    "rule_set": rv.rule_set.code, "rule_name": rv.rule_set.name, "version": rv.version})
    return {"items": out}


class ReviewIn(BaseModel):
    note: str = Field(default="", max_length=2000)


@router.post("/screenings/{sid}/request-review")
def request_review(sid: str, body: ReviewIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    """Ask the responsible authority for a human decision. Creates/uses a rights case and submits a review request."""
    s = ctx.db.get(ScreeningResult, parse_uuid(sid))
    if s is None or s.user_id != ctx.user.id or ctx.workspace != "citizen":
        raise AppError(404, "not_found", "Screening not found.")
    if s.review_request_id:
        return {"service_request_id": str(s.review_request_id), "case_id": str(s.case_id)}
    rv = ctx.db.get(RuleVersion, s.rule_version_id)
    proc = rv.rule_set.procedure
    tenant_id = proc.service.authority.tenant_id
    if tenant_id is None:
        raise AppError(409, "authority_not_onboarded", "This authority has no CivicBridge workspace; export your screening and contact them directly.")
    case = ctx.db.get(Case, s.case_id) if s.case_id else None
    if case is None:
        case = Case(reference=next_ref(ctx.db, "CB"), owner_user_id=ctx.user.id, title=f"Rights review: {rv.rule_set.name}", case_type="rights",
                    jurisdiction_id=proc.service.authority.jurisdiction_id)
        ctx.db.add(case)
        ctx.db.flush()
        s.case_id = case.id
    sr = workflow.create_request(ctx, case, tenant_id, f"Human review: {rv.rule_set.name}", proc.id, kind="rights_review",
                                 payload={"screening_id": str(s.id), "rule_set": rv.rule_set.code, "rule_version": rv.version,
                                          "indication": s.indication, "answers": s.answers, "note": body.note[:2000], "queue": "rights_review"})
    s.review_request_id = sr.id
    add_event(ctx.db, case.id, "rights.screening_attached", f"Screening result attached ({s.indication.replace('_', ' ')}, rule {rv.rule_set.code} v{rv.version}). "
              "It is an indication only; the authority decides.", ctx=ctx)
    ctx.db.commit()
    workflow.transition(ctx, sr, "submit", {})
    return {"service_request_id": str(sr.id), "case_id": str(case.id)}


class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    jurisdictions: list[str] = Field(default_factory=list, max_length=6)
    include_my_documents: bool = False


@router.post("/ask")
def ask(body: AskIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    codes = [c for c in body.jurisdictions if ctx.db.execute(select(Jurisdiction.id).where(Jurisdiction.code == c)).first()]
    allowed = accessible_document_ids(ctx) if body.include_my_documents and ctx.workspace == "citizen" else None
    res = rag.answer(ctx.db, body.question, codes or None, allowed)
    audit.record(ctx.db, "rights.asked", "knowledge", None, **audit.ctx_kw(ctx), details={"status": res["status"], "citations": len(res["citations"]),
                                                                                       "jurisdictions": codes})
    ctx.db.commit()
    return res
