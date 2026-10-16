"""Cross-Border Life Events: template-driven, multi-jurisdiction journeys with dependencies, evidence and deadlines."""
from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.deps import Ctx, get_ctx
from app.errors import AppError, bad_request
from app.models import Case, Document, EvidenceLink, Jurisdiction, LifeEvent, Task, WorkflowTemplate
from app.routers.common import iso, parse_uuid, row
from app.services import audit, calendar
from app.services.access import get_case
from app.services.refs import next_ref
from app.services.timeline import add_event

router = APIRouter(prefix="/api/life-events", tags=["life-events"])
EVENT_TYPES = ("relocation", "employment", "study", "family", "retirement", "business")


def _jur(db, code: str | None) -> Jurisdiction | None:
    return db.execute(select(Jurisdiction).where(Jurisdiction.code == code)).scalar_one_or_none() if code else None


@router.get("/templates")
def templates(ctx: Ctx = Depends(get_ctx)) -> dict:
    rows = ctx.db.execute(select(WorkflowTemplate).order_by(WorkflowTemplate.life_event_type, WorkflowTemplate.name)).scalars().all()
    out = []
    for t in rows:
        d = t.definition
        out.append({
            **row(t, ["id", "code", "life_event_type", "name", "origin_code", "destination_code", "pack_versions", "is_synthetic"]),
            "summary": d.get("summary", ""),
            "jurisdictions": d.get("jurisdictions", []),
            "task_count": len(d.get("tasks", [])),
            "questions": d.get("questions", []),
        })
    return {"items": out, "event_types": EVENT_TYPES}


class StartIn(BaseModel):
    template_code: str = Field(max_length=64)
    target_date: datetime
    answers: dict = Field(default_factory=dict)
    title: str | None = Field(default=None, max_length=300)


def _due(db, task_def: dict, target: datetime, jur: Jurisdiction | None) -> tuple[datetime | None, str]:
    tzname = jur.timezone if jur else "UTC"
    if "offset_days" in task_def:
        d = (target + timedelta(days=int(task_def["offset_days"]))).date()
        due = datetime.combine(d, time(17, 0), tzinfo=ZoneInfo(tzname))
        rel = "before" if task_def["offset_days"] < 0 else "after"
        return due, f"{abs(task_def['offset_days'])} calendar days {rel} the target date ({tzname})"
    if "working_days_after" in task_def:
        n = int(task_def["working_days_after"])
        due = calendar.add_working_days(db, jur.id if jur else None, target, n)
        return due, f"{n} working days after the target date, using the {jur.name if jur else 'default'} calendar (synthetic holidays)"
    return None, ""


@router.post("")
def start(body: StartIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    if ctx.workspace != "citizen":
        raise AppError(403, "role_not_permitted", "Only citizens start their own life events.")
    db = ctx.db
    tpl = db.execute(select(WorkflowTemplate).where(WorkflowTemplate.code == body.template_code)).scalar_one_or_none()
    if tpl is None:
        raise bad_request("Unknown journey template.")
    d = tpl.definition
    target = body.target_date if body.target_date.tzinfo else body.target_date.replace(tzinfo=ZoneInfo("UTC"))
    origin, dest = _jur(db, tpl.origin_code), _jur(db, tpl.destination_code)
    case = Case(reference=next_ref(db, "CB"), owner_user_id=ctx.user.id, title=body.title or tpl.name, case_type="life_event",
                jurisdiction_id=dest.id if dest else (origin.id if origin else None), summary=d.get("summary", ""))
    db.add(case)
    db.flush()
    le = LifeEvent(owner_user_id=ctx.user.id, case_id=case.id, template_code=tpl.code, event_type=tpl.life_event_type,
                   origin_jurisdiction_id=origin.id if origin else None, destination_jurisdiction_id=dest.id if dest else None,
                   target_date=target, answers={k: v for k, v in body.answers.items() if isinstance(v, (str, int, float, bool))})
    db.add(le)
    skipped = []
    for i, td in enumerate(d.get("tasks", [])):
        cond = td.get("only_if")
        if cond and body.answers.get(cond["q"]) != cond["value"]:
            skipped.append(td["key"])
            continue
        jur = _jur(db, td.get("jurisdiction"))
        due, basis = _due(db, td, target, jur)
        db.add(Task(case_id=case.id, key=td["key"], title=td["title"], description=td.get("description", ""),
                    jurisdiction_id=jur.id if jur else None, phase=td.get("phase", "intake"), sort_order=i,
                    depends_on=[x for x in td.get("depends_on", []) if x not in skipped], required_evidence=td.get("required_evidence", []),
                    due_at=due, deadline_basis=basis, requires_human_review=bool(td.get("requires_human_review")),
                    procedure_code=td.get("procedure_code")))
    add_event(db, case.id, "life_event.started", f"Journey started: {tpl.name} (template {tpl.code}, synthetic illustrative packs)", ctx=ctx,
              data={"pack_versions": tpl.pack_versions})
    audit.record(db, "life_event.started", "case", case.id, **audit.ctx_kw(ctx), subject_user_id=ctx.user.id, details={"template": tpl.code})
    db.commit()
    return {"case_id": str(case.id), "life_event_id": str(le.id), "reference": case.reference}


@router.get("")
def list_events(ctx: Ctx = Depends(get_ctx)) -> dict:
    if ctx.workspace != "citizen":
        return {"items": []}
    rows = ctx.db.execute(select(LifeEvent).where(LifeEvent.owner_user_id == ctx.user.id).order_by(LifeEvent.created_at.desc())).scalars().all()
    return {"items": [row(e, ["id", "case_id", "template_code", "event_type", "target_date", "status", "created_at"]) for e in rows]}


@router.get("/by-case/{case_id}/progress")
def progress(case_id: str, ctx: Ctx = Depends(get_ctx)) -> dict:
    """Progress per jurisdiction with plain-language explanations of what is missing or blocked."""
    case, acc = get_case(ctx, parse_uuid(case_id), "view_case")
    db = ctx.db
    tasks = db.execute(select(Task).where(Task.case_id == case.id).order_by(Task.sort_order)).scalars().all()
    by_key = {t.key: t for t in tasks}
    links = db.execute(select(EvidenceLink).where(EvidenceLink.case_id == case.id)).scalars().all()
    linked_by_task: dict = {}
    for link in links:
        doc = db.get(Document, link.document_id)
        linked_by_task.setdefault(link.task_id, []).append({"key": link.evidence_key, "category": doc.category if doc else None,
                                                            "status": link.status})
    groups: dict = {}
    now = datetime.now(ZoneInfo("UTC"))
    for t in tasks:
        j = db.get(Jurisdiction, t.jurisdiction_id) if t.jurisdiction_id else None
        g = groups.setdefault(j.code if j else "personal", {"jurisdiction": j.name if j else "Personal", "code": j.code if j else None,
                                                            "timezone": j.timezone if j else None, "done": 0, "total": 0, "items": []})
        g["total"] += 1
        explain = []
        if t.status in ("done", "skipped"):
            g["done"] += 1
        else:
            blockers = [by_key[k].title for k in t.depends_on if k in by_key and by_key[k].status not in ("done", "skipped")]
            if blockers:
                explain.append({"code": "blocked", "text": "Waiting for: " + "; ".join(blockers)})
            have = linked_by_task.get(t.id, [])
            for ev in t.required_evidence:
                if not any(h["key"] == ev.get("key") for h in have):
                    explain.append({"code": "missing_evidence", "text": f"Missing evidence: {ev.get('label', ev.get('key'))}", "evidence": ev})
            if t.due_at and t.due_at < now:
                explain.append({"code": "overdue", "text": f"Deadline passed on {t.due_at.date().isoformat()}"})
            if t.requires_human_review:
                explain.append({"code": "human_review", "text": "This step needs a human decision by the responsible authority."})
        g["items"].append({"task_id": str(t.id), "key": t.key, "title": t.title, "status": t.status, "due_at": iso(t.due_at),
                           "deadline_basis": t.deadline_basis, "explain": explain, "procedure_code": t.procedure_code,
                           "required_evidence": t.required_evidence, "linked_evidence": linked_by_task.get(t.id, [])})
    total = sum(g["total"] for g in groups.values())
    done = sum(g["done"] for g in groups.values())
    return {"case_id": str(case.id), "overall": {"done": done, "total": total, "pct": round(100 * done / total) if total else 0},
            "groups": list(groups.values()), "access": acc.level,
            "notice": "Synthetic, illustrative jurisdiction packs. Not complete legal coverage; confirm with the responsible authorities."}
