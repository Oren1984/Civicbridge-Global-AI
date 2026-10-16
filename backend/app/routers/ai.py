"""AI assistant endpoints: status, bounded tool invocation, human approvals, planner-driven assist."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.ai import rag, tools
from app.ai.provider import mode, ollama_status
from app.deps import Ctx, get_ctx
from app.models import AIToolCall
from app.routers.common import parse_uuid, row
from app.services import audit

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.get("/status")
def status(ctx: Ctx = Depends(get_ctx)) -> dict:
    m = mode(ctx.db)
    return {
        "mode": m,
        "modes": {
            "rules": "Deterministic rules and templates only. No generated text.",
            "mock": "Deterministic, labelled fixture outputs (default). No model, no downloads, no API keys.",
            "ollama": "Optional local model through the 'ollama' compose profile; falls back to extractive answers.",
        },
        "ollama": ollama_status() if m == "ollama" else {"checked": False},
        "retrieval": "Lexical hash embeddings in pgvector (no semantic model).",
        "tools": {name: {"consequential": spec["consequential"], "workspaces": sorted(spec["workspaces"])} for name, spec in tools.TOOLS.items()},
        "never_automated": tools.FORBIDDEN,
    }


class InvokeIn(BaseModel):
    tool: str = Field(max_length=80)
    args: dict = Field(default_factory=dict)


@router.post("/tools/invoke")
def invoke(body: InvokeIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    return tools.invoke(ctx, body.tool, body.args)


class ApprovalIn(BaseModel):
    approve: bool


@router.post("/tools/calls/{call_id}/decision")
def decide(call_id: str, body: ApprovalIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    return tools.approve(ctx, parse_uuid(call_id), body.approve)


@router.get("/tools/calls")
def my_calls(ctx: Ctx = Depends(get_ctx)) -> dict:
    rows = ctx.db.execute(select(AIToolCall).where(AIToolCall.user_id == ctx.user.id).order_by(AIToolCall.created_at.desc()).limit(30)).scalars()
    return {"items": [row(c, ["id", "tool", "mode", "status", "reason", "duration_ms", "created_at", "approved_at", "input"]) for c in rows]}


class AssistIn(BaseModel):
    message: str = Field(min_length=2, max_length=1000)
    case_id: uuid.UUID | None = None
    jurisdictions: list[str] = Field(default_factory=list, max_length=6)


@router.post("/assist")
def assist(body: AssistIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    plan = tools.plan(body.message, str(body.case_id) if body.case_id else None)
    if plan["tool"] == "answer_with_sources":
        res = rag.answer(ctx.db, body.message, body.jurisdictions or None)
        audit.record(ctx.db, "ai.assist", "knowledge", None, **audit.ctx_kw(ctx), details={"status": res["status"]})
        ctx.db.commit()
        return {"plan": plan, "result": res}
    return {"plan": plan, "result": tools.invoke(ctx, plan["tool"], plan["args"])}
