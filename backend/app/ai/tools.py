"""Bounded AI tool gateway.

Every AI-initiated action goes through ``invoke``:
1. allowlist (unknown or forbidden tools are denied and audited),
2. workspace/role permission per tool, then resource authorization inside the tool,
3. per-user hourly execution budget,
4. pydantic-validated input and size-checked output,
5. a wall-clock budget (results produced after the deadline are discarded and recorded as timeout),
6. human approval for consequential tools (status pending_approval until a human approves),
7. an AIToolCall row plus an audit event for every attempt.

Deterministic services own state transitions; no tool can change case/decision state.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from datetime import timedelta
from typing import Any, Callable

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select

from app.ai import rag
from app.ai.provider import mode as ai_mode
from app.ai.translate import translate
from app.db import utcnow
from app.deps import Ctx
from app.errors import AppError
from app.models import (
    AIToolCall,
    Decision,
    EvidenceLink,
    Incident,
    InformationRequest,
    Message,
    ServiceRequest,
    Task,
)
from app.services import audit, policies

FORBIDDEN = {
    "submit_official_application": "CivicBridge never submits official government applications autonomously.",
    "issue_decision": "Binding decisions are issued only by authorised humans.",
    "approve_decision": "Decision approval requires a human supervisor.",
    "deny_eligibility": "Eligibility is never denied by automation.",
    "release_personal_records": "Personal records are only released by the data owner's explicit consent.",
    "dispatch_emergency": "CivicBridge is not an emergency dispatch service.",
    "delete_records": "Deletion follows the privacy-request workflow, not AI tools.",
    "change_case_state": "State transitions are owned by the deterministic workflow engine.",
}


class CaseArgs(BaseModel):
    case_id: uuid.UUID


class DraftArgs(BaseModel):
    case_id: uuid.UUID
    intent: str = Field(pattern=r"^(status_question|provide_information|request_meeting|thank_you|request_extension)$")
    language: str = Field(default="en", pattern=r"^(en|he|de)$")


class SendArgs(BaseModel):
    case_id: uuid.UUID
    body: str = Field(min_length=1, max_length=4000)


class ClassifyArgs(BaseModel):
    description: str = Field(min_length=3, max_length=4000)


class IncidentArgs(BaseModel):
    incident_id: uuid.UUID


class SearchArgs(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    jurisdictions: list[str] = Field(default_factory=list, max_length=6)


class TranslateArgs(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    source_lang: str = Field(pattern=r"^(en|he|de)$")
    target_lang: str = Field(pattern=r"^(en|he|de)$")


class RequestArgs(BaseModel):
    service_request_id: uuid.UUID


# ---------------------------------------------------------------- tool implementations


def _summarize_case(ctx: Ctx, a: CaseArgs, _deadline: float) -> dict:
    from app.services.access import get_case

    case, _acc = get_case(ctx, a.case_id, "view_case")
    tasks = ctx.db.execute(select(Task).where(Task.case_id == case.id)).scalars().all()
    done = [t for t in tasks if t.status == "done"]
    open_ = sorted([t for t in tasks if t.status not in ("done", "skipped")], key=lambda t: (t.due_at is None, t.due_at))
    reqs = ctx.db.execute(select(ServiceRequest).where(ServiceRequest.case_id == case.id)).scalars().all()
    infos = ctx.db.execute(
        select(InformationRequest).join(ServiceRequest).where(ServiceRequest.case_id == case.id, InformationRequest.status == "open")
    ).scalars().all()
    lines = [f"Case {case.reference}: {case.title}.", f"{len(done)} of {len(tasks)} checklist tasks are complete."]
    if open_:
        nxt = open_[0]
        due = f" (due {nxt.due_at.date().isoformat()})" if nxt.due_at else ""
        lines.append(f"Next open task: {nxt.title}{due}.")
    for r in reqs:
        lines.append(f"Request {r.reference} to the authority is in state '{r.state}'.")
    if infos:
        lines.append(f"{len(infos)} information request(s) are waiting for a reply.")
    return {"summary": " ".join(lines), "label": "Template summary generated from case records (no generative model)."}


def _next_steps(ctx: Ctx, a: CaseArgs, _deadline: float) -> dict:
    from app.services.access import get_case

    case, _acc = get_case(ctx, a.case_id, "view_case")
    tasks = ctx.db.execute(select(Task).where(Task.case_id == case.id).order_by(Task.sort_order)).scalars().all()
    by_key = {t.key: t for t in tasks}
    ready = []
    for t in tasks:
        if t.status in ("done", "skipped"):
            continue
        blockers = [d for d in t.depends_on if d in by_key and by_key[d].status not in ("done", "skipped")]
        if not blockers:
            ready.append(
                {
                    "task_id": str(t.id),
                    "title": t.title,
                    "due_at": t.due_at.isoformat() if t.due_at else None,
                    "missing_evidence": t.required_evidence,
                    "why": "All prerequisite tasks are complete." if t.depends_on else "No prerequisites.",
                }
            )
    ready.sort(key=lambda r: (r["due_at"] is None, r["due_at"] or ""))
    return {"steps": ready[:5], "label": "Suggestions computed from task dependencies. You decide what to do."}


_DRAFTS = {
    "en": {
        "status_question": "Hello, I would like to ask about the current status of my request {ref}. Thank you.",
        "provide_information": "Hello, I have added the requested information and documents to case {ref}. Please let me know if anything else is needed.",
        "request_meeting": "Hello, could we schedule a short video consultation about case {ref}? I am available on weekdays.",
        "thank_you": "Thank you for your help with case {ref}.",
        "request_extension": "Hello, I need a little more time to provide the requested documents for case {ref}. Could the deadline be extended?",
    },
    "de": {
        "status_question": "Guten Tag, ich möchte mich nach dem aktuellen Stand meines Antrags {ref} erkundigen. Vielen Dank.",
        "provide_information": "Guten Tag, ich habe die angeforderten Informationen und Unterlagen zum Vorgang {ref} hinzugefügt.",
        "request_meeting": "Guten Tag, könnten wir eine kurze Videoberatung zum Vorgang {ref} vereinbaren?",
        "thank_you": "Vielen Dank für Ihre Unterstützung beim Vorgang {ref}.",
        "request_extension": "Guten Tag, ich benötige etwas mehr Zeit für die angeforderten Unterlagen zum Vorgang {ref}. Ist eine Fristverlängerung möglich?",
    },
    "he": {
        "status_question": "שלום, אבקש לברר את מצב הבקשה שלי {ref}. תודה.",
        "provide_information": "שלום, הוספתי את המידע והמסמכים שהתבקשו לתיק {ref}.",
        "request_meeting": "שלום, האם נוכל לקבוע פגישת וידאו קצרה בנושא תיק {ref}?",
        "thank_you": "תודה על העזרה בתיק {ref}.",
        "request_extension": "שלום, אני זקוק/ה לעוד זמן כדי להגיש את המסמכים שהתבקשו בתיק {ref}. האם ניתן להאריך את המועד?",
    },
}


def _draft_message(ctx: Ctx, a: DraftArgs, _deadline: float) -> dict:
    from app.services.access import get_case

    case, acc = get_case(ctx, a.case_id, "view_case")
    if acc.level == "professional" and not acc.can("draft_messages"):
        raise AppError(403, "scope_missing", "Your delegation does not include drafting messages.")
    return {
        "draft": _DRAFTS[a.language][a.intent].format(ref=case.reference),
        "label": "Template draft. Review and edit before sending; nothing is sent automatically.",
    }


def _send_message(ctx: Ctx, a: SendArgs, _deadline: float) -> dict:
    from app.services.access import get_case
    from app.services import notify

    case, acc = get_case(ctx, a.case_id, "send_messages")
    msg = Message(
        case_id=case.id,
        sender_user_id=ctx.user.id,
        sender_tenant_id=ctx.tenant_id,
        sender_label=ctx.user.display_name,
        body=a.body,
        ai_drafted=True,
        on_behalf_of_user_id=case.owner_user_id if acc.level == "professional" else None,
    )
    ctx.db.add(msg)
    ctx.db.flush()
    if case.owner_user_id != ctx.user.id:
        notify.notify(ctx.db, case.owner_user_id, "message", f"New message on {case.reference}", link=f"/cases/{case.id}")
    return {"message_id": str(msg.id), "sent": True}


_INCIDENT_KEYWORDS = {
    "streetlight": ["streetlight", "street light", "lamp", "light out", "dark street", "פנס", "תאורה", "laterne", "straßenlaterne"],
    "pothole": ["pothole", "hole in the road", "road damage", "בור", "כביש", "schlagloch"],
    "waste": ["garbage", "trash", "waste", "bin", "litter", "פסולת", "זבל", "müll", "abfall"],
    "water": ["leak", "water", "flood", "pipe", "נזילה", "מים", "wasser", "rohr"],
    "graffiti": ["graffiti", "vandal", "גרפיטי", "schmiererei"],
    "accessibility": ["ramp", "wheelchair", "elevator", "lift", "נגישות", "barriere", "rollstuhl"],
}


def classify_text(description: str) -> dict:
    text = description.lower()
    scores = {cat: sum(1 for k in kws if k in text) for cat, kws in _INCIDENT_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return {"category": "other", "confidence": 0.0, "matched": [], "label": "No keyword matched; please choose a category."}
    matched = [k for k in _INCIDENT_KEYWORDS[best] if k in text]
    return {
        "category": best,
        "confidence": min(0.9, 0.4 + 0.2 * scores[best]),
        "matched": matched,
        "label": "Keyword rule suggestion from the text only. Images and audio are not analysed.",
    }


def _classify(_ctx: Ctx, a: ClassifyArgs, _deadline: float) -> dict:
    return classify_text(a.description)


def _duplicates(ctx: Ctx, a: IncidentArgs, _deadline: float) -> dict:
    from app.services.incidents import duplicate_candidates, get_incident_for

    inc = get_incident_for(ctx, a.incident_id)
    return {"candidates": duplicate_candidates(ctx.db, inc), "label": "Suggestions only. Staff decide whether to merge."}


def _search(ctx: Ctx, a: SearchArgs, _deadline: float) -> dict:
    return {"results": rag.search_sources(ctx.db, a.query, a.jurisdictions or None, k=5)}


def _translate(ctx: Ctx, a: TranslateArgs, deadline: float) -> dict:
    if a.source_lang == a.target_lang:
        raise AppError(400, "invalid_request", "Source and target language must differ.")
    return translate(a.text, a.source_lang, a.target_lang, ai_mode(ctx.db), timeout_s=max(1.0, deadline - time.monotonic()))


def _draft_rationale(ctx: Ctx, a: RequestArgs, _deadline: float) -> dict:
    from app.services.workflow import get_request_for

    sr = get_request_for(ctx, a.service_request_id)
    ev = ctx.db.execute(select(EvidenceLink).where(EvidenceLink.service_request_id == sr.id)).scalars().all()
    accepted = sum(1 for e in ev if e.status == "accepted")
    pending = sum(1 for e in ev if e.status in ("submitted", "attached"))
    prior = ctx.db.execute(select(func.count(Decision.id)).where(Decision.service_request_id == sr.id)).scalar_one()
    text = (
        f"Request {sr.reference}: {accepted} evidence item(s) accepted, {pending} awaiting review. "
        f"{'Previous decision versions exist and must be referenced. ' if prior else ''}"
        "[Officer: state the applicable rule version, the facts relied on, and the reasons for the outcome.]"
    )
    return {"draft": text, "label": "Scaffold only. The officer writes and owns the rationale; AI cannot decide."}


TOOLS: dict[str, dict[str, Any]] = {
    "summarize_case": {"args": CaseArgs, "fn": _summarize_case, "workspaces": {"citizen", "authority", "institution", "professional"}, "consequential": False},
    "suggest_next_steps": {"args": CaseArgs, "fn": _next_steps, "workspaces": {"citizen", "professional"}, "consequential": False},
    "draft_message": {"args": DraftArgs, "fn": _draft_message, "workspaces": {"citizen", "professional", "authority"}, "consequential": False},
    "send_case_message": {"args": SendArgs, "fn": _send_message, "workspaces": {"citizen", "professional", "authority"}, "consequential": True},
    "classify_incident": {"args": ClassifyArgs, "fn": _classify, "workspaces": {"citizen", "authority"}, "consequential": False},
    "suggest_duplicates": {"args": IncidentArgs, "fn": _duplicates, "workspaces": {"authority"}, "consequential": False},
    "search_sources": {"args": SearchArgs, "fn": _search, "workspaces": {"citizen", "authority", "institution", "professional", "governance"}, "consequential": False},
    "translate_text": {"args": TranslateArgs, "fn": _translate, "workspaces": {"citizen", "professional", "authority", "institution"}, "consequential": False},
    "draft_decision_rationale": {"args": RequestArgs, "fn": _draft_rationale, "workspaces": {"authority"}, "consequential": False},
}


def _record(ctx: Ctx, tool: str, status: str, inp: dict, out: dict, reason: str, ms: int) -> AIToolCall:
    call = AIToolCall(
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        tool=tool[:64],
        mode=ai_mode(ctx.db),
        status=status,
        input=json.loads(json.dumps(inp, default=str)[:8000]) if len(json.dumps(inp, default=str)) <= 8000 else {"truncated": True},
        output=out,
        reason=reason,
        duration_ms=ms,
    )
    ctx.db.add(call)
    ctx.db.flush()
    audit.record(
        ctx.db,
        f"ai.tool.{status}",
        "ai_tool_call",
        call.id,
        **audit.ctx_kw(ctx),
        outcome="denied" if status in ("denied", "invalid") else "success",
        details={"tool": tool[:64], "reason_code": reason[:80]},
    )
    return call


def _deny_call(ctx: Ctx, tool: str, inp: dict, reason: str, code: str, status: int = 403) -> AppError:
    _record(ctx, tool, "denied", inp, {}, code, 0)
    ctx.db.commit()
    return AppError(status, code, reason)


def invoke(ctx: Ctx, tool: str, raw_args: dict, *, approved_call: AIToolCall | None = None) -> dict:
    inp = raw_args or {}
    if tool in FORBIDDEN:
        raise _deny_call(ctx, tool, inp, FORBIDDEN[tool], "tool_forbidden")
    spec = TOOLS.get(tool)
    if spec is None or not re.fullmatch(r"[a-z_]{3,64}", tool):
        raise _deny_call(ctx, tool, inp, "This tool is not on the allowlist.", "tool_not_allowlisted")
    if ctx.workspace not in spec["workspaces"]:
        raise _deny_call(ctx, tool, inp, "This tool is not permitted in your active workspace.", "tool_scope_denied")
    if ai_mode(ctx.db) == "rules" and tool in ("draft_message", "translate_text"):
        raise _deny_call(ctx, tool, inp, "AI drafting and translation are disabled in rules-only mode.", "ai_mode_rules_only", 409)

    if approved_call is None:
        budget = int(policies.get(ctx.db, "ai_budget_per_hour"))
        used = ctx.db.execute(
            select(func.count(AIToolCall.id)).where(
                AIToolCall.user_id == ctx.user.id, AIToolCall.created_at > utcnow() - timedelta(hours=1)
            )
        ).scalar_one()
        if used >= budget:
            raise _deny_call(ctx, tool, inp, f"AI tool budget of {budget} calls per hour reached.", "budget_exceeded", 429)
    try:
        args = spec["args"](**inp)
    except ValidationError as exc:
        _record(ctx, tool, "invalid", inp, {"errors": json.loads(exc.json())[:5]}, "input_validation_failed", 0)
        ctx.db.commit()
        raise AppError(422, "invalid_tool_input", "Tool input failed validation.") from exc

    if spec["consequential"] and approved_call is None:
        call = _record(ctx, tool, "pending_approval", json.loads(args.model_dump_json()), {}, "human_approval_required", 0)
        ctx.db.commit()
        return {
            "status": "pending_approval",
            "call_id": str(call.id),
            "tool": tool,
            "input": json.loads(args.model_dump_json()),
            "message": "This action needs your explicit approval before it runs.",
        }

    timeout_s = float(policies.get(ctx.db, "ai_tool_timeout_s"))
    start = time.monotonic()
    deadline = start + timeout_s
    fn: Callable = spec["fn"]
    try:
        out = fn(ctx, args, deadline)
    except AppError:
        ctx.db.rollback()
        _record(ctx, tool, "denied", inp, {}, "resource_authorization_failed", int((time.monotonic() - start) * 1000))
        ctx.db.commit()
        raise
    ms = int((time.monotonic() - start) * 1000)
    if time.monotonic() > deadline:
        ctx.db.rollback()
        _record(ctx, tool, "timeout", inp, {}, "execution_budget_exceeded", ms)
        ctx.db.commit()
        raise AppError(504, "tool_timeout", "The AI tool exceeded its time budget; no result was used.")
    encoded = json.dumps(out, default=str)
    if not isinstance(out, dict) or len(encoded) > 60_000:
        ctx.db.rollback()
        _record(ctx, tool, "error", inp, {}, "output_validation_failed", ms)
        ctx.db.commit()
        raise AppError(502, "tool_output_invalid", "Tool output failed validation.")
    out = json.loads(encoded)
    if approved_call is not None:
        approved_call.status = "approved"
        approved_call.output = out
        approved_call.approved_by = ctx.user.id
        approved_call.approved_at = utcnow()
        approved_call.duration_ms = ms
        audit.record(ctx.db, "ai.tool.approved_executed", "ai_tool_call", approved_call.id, **audit.ctx_kw(ctx), details={"tool": tool})
    else:
        _record(ctx, tool, "executed", json.loads(args.model_dump_json()), out, "ok", ms)
    ctx.db.commit()
    return {"status": "executed", "tool": tool, "mode": ai_mode(ctx.db), "result": out}


def approve(ctx: Ctx, call_id: uuid.UUID, approve_it: bool) -> dict:
    call = ctx.db.get(AIToolCall, call_id)
    if call is None or call.user_id != ctx.user.id or call.status != "pending_approval":
        raise AppError(404, "not_found", "No pending action found.")
    if not approve_it:
        call.status = "rejected"
        audit.record(ctx.db, "ai.tool.rejected_by_human", "ai_tool_call", call.id, **audit.ctx_kw(ctx), details={"tool": call.tool})
        ctx.db.commit()
        return {"status": "rejected"}
    return invoke(ctx, call.tool, call.input, approved_call=call)


def plan(message: str, case_id: str | None) -> dict:
    """Deterministic planner for the assistant. It only reads the *user's own request*, never document or
    retrieved text, so instructions embedded in uploaded content cannot select tools."""
    m = message.lower()
    if case_id and re.search(r"summar|overview|סיכום|zusammenfass", m):
        return {"tool": "summarize_case", "args": {"case_id": case_id}}
    if case_id and re.search(r"next|what should|הבא|nächste", m):
        return {"tool": "suggest_next_steps", "args": {"case_id": case_id}}
    if case_id and re.search(r"draft|write|נסח|entwurf", m):
        return {"tool": "draft_message", "args": {"case_id": case_id, "intent": "status_question"}}
    return {"tool": "answer_with_sources", "args": {"question": message}}
