"""Journeys A and C: Israel-to-Germany relocation, consent, simulated authority handoff, review, decision, appeal."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db import session_factory
from app.models import Decision, IntegrationRun, ServiceRequest
from tests.conftest import login, run_jobs, upload_doc


def _tenant_id(api, slug_name_part: str) -> str:
    items = api.get("/api/consents/recipients").json()["items"]
    return next(t["id"] for t in items if slug_name_part in t["name"])


def start_relocation(api):
    target = (datetime.now(timezone.utc) + timedelta(days=40)).isoformat()
    r = api.post("/api/life-events", {"template_code": "relocation-il-de", "target_date": target,
                                       "answers": {"needs_language_course": False, "has_employer": True}})
    assert r.status_code == 200, r.text
    return r.json()["case_id"]


def test_relocation_journey_end_to_end():
    maya = login("maya")
    case_id = start_relocation(maya)
    detail = maya.get(f"/api/cases/{case_id}").json()
    keys = [t["key"] for t in detail["tasks"]]
    assert "de-registration" in keys and "de-employment-contract" in keys and "de-language-course" not in keys
    prog = maya.get(f"/api/life-events/by-case/{case_id}/progress").json()
    codes = {g["code"] for g in prog["groups"]}
    assert {"IL", "DE-BE-BER", "DE"} <= codes
    reg = next(i for g in prog["groups"] for i in g["items"] if i["key"] == "de-registration")
    assert any(e["code"] == "blocked" for e in reg["explain"]) and any(e["code"] == "missing_evidence" for e in reg["explain"])
    assert reg["due_at"] and "calendar days" in reg["deadline_basis"]

    # Dependencies are enforced server-side.
    tasks = {t["key"]: t for t in detail["tasks"]}
    r = maya.patch(f"/api/cases/{case_id}/tasks/{tasks['de-registration']['id']}", {"status": "done"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "task_blocked"

    # Evidence: upload passport + landlord confirmation (real ClamAV scan through the worker).
    passport = upload_doc(maya)
    landlord = upload_doc(maya, title="Landlord confirmation", category="housing", name="landlord.txt",
                          content="Wohnungsgeberbestätigung (synthetisches Demo-Dokument)\nHiermit bestätige ich den Einzug der folgenden Person.")
    assert maya.get(f"/api/documents/{passport['id']}").json()["versions"][0]["scan_status"] == "clean"
    for doc, key, task in ((passport, "passport", "il-gather-docs"), (landlord, "landlord_confirmation", "de-housing")):
        assert maya.post(f"/api/cases/{case_id}/evidence", {"document_id": doc["id"], "task_id": tasks[task]["id"], "evidence_key": key}).status_code == 200
        assert maya.patch(f"/api/cases/{case_id}/tasks/{tasks[task]['id']}", {"status": "done"}).status_code == 200

    # Prepare and submit the registration request (simulated exchange).
    sr = maya.post(f"/api/cases/{case_id}/requests", {"procedure_code": "DE-BER-ANMELDUNG"}).json()
    for doc, key in ((passport, "passport"), (landlord, "landlord_confirmation")):
        maya.post(f"/api/cases/{case_id}/evidence", {"document_id": doc["id"], "service_request_id": sr["id"], "evidence_key": key})
    berlin = _tenant_id(maya, "Registration Office")

    lena = login("lena").switch("berlin-registration")
    # Not visible to the authority before submission.
    assert lena.get(f"/api/authority/requests/{sr['id']}").status_code == 404
    r = maya.post(f"/api/cases/{case_id}/requests/{sr['id']}/actions", {"action": "submit"})
    assert r.status_code == 200 and r.json()["state"] == "submitted"
    run_jobs()
    with session_factory()() as s:
        run = s.execute(select(IntegrationRun).where(IntegrationRun.service_request_id == sr["id"])).scalar_one()
        assert run.status == "success" and run.response_summary["simulated"] is True

    queue = lena.get("/api/authority/queue?state=open").json()
    assert any(i["id"] == sr["id"] for i in queue["items"])
    detail = lena.get(f"/api/authority/requests/{sr['id']}").json()
    # No consent yet: evidence documents are restricted for the authority.
    assert all(e["document"].get("restricted") for e in detail["evidence"] if e["service_request_id"] == sr["id"])
    assert lena.get(f"/api/documents/{passport['id']}").status_code == 404

    # Purpose-bound consent for identity + housing documents.
    g = maya.post("/api/consents", {"recipient_tenant_id": berlin, "purpose": "Address registration review", "data_categories": ["identity", "housing"],
                                    "case_id": case_id, "valid_days": 30})
    assert g.status_code == 200, g.text
    assert lena.get(f"/api/documents/{passport['id']}").status_code == 200
    assert lena.get(f"/api/documents/{passport['id']}/versions/1/download").status_code == 200
    receipts = maya.get(f"/api/documents/{passport['id']}/receipts").json()["items"]
    assert {r["action"] for r in receipts} >= {"metadata", "download"}

    # Authority workflow with server-enforced transitions.
    act = lambda a, d=None: lena.post(f"/api/authority/requests/{sr['id']}/actions", {"action": a, "data": d or {}})  # noqa: E731
    assert act("start_review").status_code == 403  # not the assignee (permission checked before state)
    assert act("accept").status_code == 200
    assert act("start_review").status_code == 403  # not the assignee yet
    assert act("assign").status_code == 200
    assert act("start_review").status_code == 200
    ev = next(e for e in lena.get(f"/api/authority/requests/{sr['id']}").json()["evidence"] if e["service_request_id"] == sr["id"])
    assert lena.post(f"/api/authority/evidence/{ev['id']}/review", {"status": "accepted"}).status_code == 200
    assert act("request_info", {"message": "Please confirm your move-in date.", "items": ["move-in date"]}).status_code == 200
    with session_factory()() as s:
        assert s.get(ServiceRequest, sr["id"]).sla_paused_at is not None
    r = maya.post(f"/api/cases/{case_id}/requests/{sr['id']}/actions", {"action": "respond_info", "data": {"response": "Moved in on the 1st."}})
    assert r.status_code == 200 and r.json()["state"] == "in_review"
    assert act("propose_decision", {"outcome": "approved", "rationale": "short"}).status_code == 400
    assert act("propose_decision", {"outcome": "approved", "rationale": "Identity and landlord confirmation reviewed; registration confirmed."}).status_code == 200
    # Citizen cannot see the internal proposed decision.
    case = maya.get(f"/api/cases/{case_id}").json()
    assert all(d["status"] != "proposed" for r_ in case["requests"] for d in r_["decisions"])
    # Four-eyes: the officer cannot approve; the supervisor can.
    assert act("approve_decision").status_code == 403
    thomas = login("thomas").switch("berlin-registration")
    r = thomas.post(f"/api/authority/requests/{sr['id']}/actions", {"action": "approve_decision"})
    assert r.status_code == 200 and r.json()["state"] == "decided"

    # Persistent timeline + notifications for the citizen.
    tl = maya.get(f"/api/cases/{case_id}/timeline").json()["items"]
    kinds = {e["kind"] for e in tl}
    assert {"life_event.started", "request.submit", "exchange.acknowledged", "request.approve_decision", "consent.granted"} <= kinds
    assert not any(e["visibility"] == "internal" for e in tl)
    notes = maya.get("/api/notifications").json()["items"]
    assert any("Decision issued" in n["title"] for n in notes)
    # Re-login (fresh client) still sees everything = persisted.
    again = login("maya")
    assert again.get(f"/api/cases/{case_id}").json()["requests"][0]["state"] == "decided"


def test_rights_screening_review_decision_and_appeal(db):
    jonas = login("jonas")
    rs = jonas.get("/api/rights/rulesets").json()["items"]
    fam = next(r for r in rs if r["code"] == "DE-FAMILY-BENEFIT")
    assert fam["current_version"]["version"] == "2.0" and len(fam["versions"]) == 2
    res = jonas.post("/api/rights/screen", {"rule_set_code": "DE-FAMILY-BENEFIT", "answers": {"resident_in_de": True, "child_in_household": True}}).json()
    assert res["indication"] == "insufficient_information" and set(res["missing"]) == {"child_age", "has_tax_id"}
    res = jonas.post("/api/rights/screen", {"rule_set_code": "DE-FAMILY-BENEFIT",
                                             "answers": {"resident_in_de": True, "child_in_household": True, "child_age": 7, "has_tax_id": False}}).json()
    assert res["indication"] == "likely_not_applicable"
    assert res["requires_human_review"] is True
    codes = {u["code"] for u in res["uncertainty"]}
    assert {"synthetic_rule", "stale_rule", "placeholder_source"} <= codes
    assert res["citations"] and all(c["url"] is None and c["is_placeholder"] for c in res["citations"])
    assert "not an official eligibility determination" in res["disclaimer"]

    r = jonas.post(f"/api/rights/screenings/{res['screening_id']}/request-review", {"note": "Please review my situation."})
    assert r.status_code == 200, r.text
    sr_id, case_id = r.json()["service_request_id"], r.json()["case_id"]
    lena = login("lena").switch("berlin-registration")
    act = lambda who, a, d=None: who.post(f"/api/authority/requests/{sr_id}/actions", {"action": a, "data": d or {}})  # noqa: E731
    for a in ("accept", "assign", "start_review"):
        assert act(lena, a).status_code == 200
    assert act(lena, "propose_decision", {"outcome": "rejected", "rationale": "Tax identification number not yet available; please reapply later."}).status_code == 200
    thomas = login("thomas").switch("berlin-registration")
    assert act(thomas, "approve_decision").status_code == 200

    # Appeal creates a linked follow-up request.
    r = jonas.post(f"/api/cases/{case_id}/requests/{sr_id}/actions", {"action": "appeal", "data": {"grounds": "short"}})
    assert r.status_code == 400
    r = jonas.post(f"/api/cases/{case_id}/requests/{sr_id}/actions", {"action": "appeal", "data": {"grounds": "My tax ID has now been issued; see attached letter."}})
    assert r.status_code == 200 and r.json()["state"] == "appealed"
    follow = db.execute(select(ServiceRequest).where(ServiceRequest.parent_request_id == sr_id)).scalar_one()
    assert follow.kind == "appeal" and follow.state == "submitted"
    fid = str(follow.id)
    act2 = lambda who, a, d=None: who.post(f"/api/authority/requests/{fid}/actions", {"action": a, "data": d or {}})  # noqa: E731
    for a in ("accept", "assign", "start_review"):
        assert act2(lena, a).status_code == 200
    assert act2(lena, "propose_decision", {"outcome": "approved", "rationale": "New evidence: tax ID issued. Original refusal reversed on appeal."}).status_code == 200
    assert act2(thomas, "approve_decision").status_code == 200
    db.expire_all()
    decs = db.execute(select(Decision).where(Decision.service_request_id == sr_id).order_by(Decision.version)).scalars().all()
    assert [d.status for d in decs] == ["superseded", "approved"] and decs[1].supersedes_id == decs[0].id and decs[1].outcome == "approved"
    tl = {e["kind"] for e in jonas.get(f"/api/cases/{case_id}/timeline").json()["items"]}
    assert {"request.appeal", "decision.superseded"} <= tl
    gov = login("auditor")
    actions = {e["action"] for e in gov.get("/api/governance/audit?action=workflow").json()["items"]}
    assert {"workflow.appeal", "workflow.approve_decision"} <= actions
    assert gov.post("/api/governance/audit/verify").json()["ok"] is True
