"""Deterministic screening engine for the Civic Rights Navigator.

Output is a *screening indication* only: likely_applicable | likely_not_applicable | insufficient_information.
It is never an official eligibility determination and never denies anything; consequential rule sets always
flag human review.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RuleVersion, SourcePassage, SourceRecord

OPS = {
    "eq": lambda a, b: a == b,
    "neq": lambda a, b: a != b,
    "gte": lambda a, b: float(a) >= float(b),
    "lte": lambda a, b: float(a) <= float(b),
    "gt": lambda a, b: float(a) > float(b),
    "lt": lambda a, b: float(a) < float(b),
    "in": lambda a, b: a in b,
}


def current_version(db: Session, rule_set_id, on: date | None = None) -> RuleVersion | None:
    on = on or date.today()
    rows = db.execute(select(RuleVersion).where(RuleVersion.rule_set_id == rule_set_id)).scalars().all()
    valid = [r for r in rows if r.effective_from <= on and (r.effective_to is None or r.effective_to >= on)]
    return sorted(valid, key=lambda r: r.effective_from)[-1] if valid else None


def _eval(node: dict, answers: dict, trace: list, missing: list) -> bool | None:
    if "all" in node or "any" in node:
        key = "all" if "all" in node else "any"
        results = [_eval(c, answers, trace, missing) for c in node[key]]
        if key == "all":
            if any(r is False for r in results):
                return False
            return None if any(r is None for r in results) else True
        if any(r is True for r in results):
            return True
        return None if any(r is None for r in results) else False
    q, op, value = node["q"], node["op"], node.get("value")
    if q not in answers or answers[q] in (None, ""):
        if q not in missing:
            missing.append(q)
        trace.append({"question": q, "result": "missing", "explain": node.get("explain", "")})
        return None
    try:
        ok = bool(OPS[op](answers[q], value))
    except (TypeError, ValueError):
        missing.append(q)
        return None
    trace.append({"question": q, "result": "met" if ok else "not_met", "explain": node.get("explain", "")})
    return ok


def screen(db: Session, rv: RuleVersion, answers: dict[str, Any]) -> dict[str, Any]:
    trace: list = []
    missing: list = []
    result = _eval(rv.logic.get("when", {}), answers, trace, missing)
    if result is None:
        indication = "insufficient_information"
    elif result:
        indication = "likely_applicable"
    else:
        indication = "likely_not_applicable"

    uncertainty = []
    today = date.today()
    if rv.verification_status.startswith("synthetic"):
        uncertainty.append({"code": "synthetic_rule", "message": "Synthetic, illustrative rule. Not legal coverage."})
    if rv.review_date < today:
        uncertainty.append(
            {"code": "stale_rule", "message": f"Rule review date {rv.review_date.isoformat()} has passed; it may be outdated."}
        )
    if rv.review_status != "reviewed":
        uncertainty.append({"code": "unreviewed", "message": f"Rule review status: {rv.review_status}."})
    if rv.confidence < 0.7:
        uncertainty.append({"code": "low_confidence", "message": f"Rule confidence {rv.confidence:.0%}."})

    citations = []
    for code in rv.source_record_ids:
        src = db.execute(select(SourceRecord).where(SourceRecord.code == code)).scalar_one_or_none()
        if src is None:
            continue
        passages = db.execute(
            select(SourcePassage).where(SourcePassage.source_record_id == src.id).order_by(SourcePassage.ordinal).limit(2)
        ).scalars()
        for p in passages:
            citations.append(
                {
                    "source_code": src.code,
                    "title": src.title,
                    "publisher": src.publisher,
                    "jurisdiction": src.jurisdiction.code,
                    "url": src.url,
                    "is_placeholder": src.is_placeholder,
                    "anchor": p.anchor,
                    "passage": p.text,
                    "review_date": src.review_date.isoformat(),
                    "stale": src.review_date < today,
                }
            )
        if src.is_placeholder:
            uncertainty.append(
                {"code": "placeholder_source", "message": f"Source '{src.title}' is a synthetic placeholder with no official URL."}
            )

    outcome_text = rv.logic.get("outcomes", {}).get(indication, "")
    return {
        "indication": indication,
        "indication_text": outcome_text,
        "explanation": trace,
        "missing": missing,
        "uncertainty": uncertainty,
        "citations": citations,
        "required_evidence": rv.required_evidence,
        "requires_human_review": bool(rv.rule_set.consequential or indication != "likely_applicable"),
        "appeal_guidance": rv.appeal_guidance,
        "rule": {
            "rule_set": rv.rule_set.code,
            "name": rv.rule_set.name,
            "version": rv.version,
            "pack_version": rv.pack_version,
            "effective_from": rv.effective_from.isoformat(),
            "effective_to": rv.effective_to.isoformat() if rv.effective_to else None,
            "review_date": rv.review_date.isoformat(),
            "review_status": rv.review_status,
            "verification_status": rv.verification_status,
            "confidence": rv.confidence,
            "jurisdiction": rv.rule_set.procedure.service.authority.jurisdiction.code,
            "authority": rv.rule_set.procedure.service.authority.name,
        },
        "disclaimer": "Screening indication only. This is not an official eligibility determination. "
        "Only the responsible authority can decide, and a human must review consequential outcomes.",
    }
