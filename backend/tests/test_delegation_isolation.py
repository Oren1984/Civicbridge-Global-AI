"""Journeys D and G: delegated professional scope/expiry/revocation, cross-tenant and cross-user isolation."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.db import utcnow
from app.models import Delegation, Tenant
from tests.conftest import login, upload_doc
from tests.test_relocation_workflow import start_relocation


def _legal_aid(db):
    return db.execute(select(Tenant).where(Tenant.slug == "legal-aid")).scalar_one()


def test_delegated_professional_scope_expiry_and_revocation(db):
    maya = login("maya")
    case_id = start_relocation(maya)
    passport = upload_doc(maya)
    health = upload_doc(maya, title="Health record", category="health", name="health.txt", content="Health insurance confirmation (synthetic demo document)")
    maya.post(f"/api/cases/{case_id}/evidence", {"document_id": passport["id"], "evidence_key": "passport"})
    maya.post(f"/api/cases/{case_id}/evidence", {"document_id": health["id"], "evidence_key": "health_insurance"})
    david_id = next(p for p in maya.get("/api/delegations/professionals").json()["items"] if p["display_name"] == "David Ben-Ami")
    david = login("david")
    assert david.get(f"/api/cases/{case_id}").status_code == 404  # nothing before delegation
    r = maya.post("/api/delegations", {"delegate_user_id": david_id["user_id"], "delegate_tenant_id": david_id["tenant_id"], "case_id": case_id,
                                        "scopes": ["view_case", "view_documents", "draft_messages"], "document_categories": ["identity"],
                                        "purpose": "Prepare the registration file", "valid_days": 7})
    assert r.status_code == 200, r.text
    deleg_id = r.json()["id"]
    assert david.get(f"/api/cases/{case_id}").status_code == 200
    assert david.get(f"/api/documents/{passport['id']}").status_code == 200
    assert david.get(f"/api/documents/{health['id']}").status_code == 404  # category not delegated
    # Scope without send_messages: messaging denied, AI drafting allowed.
    assert david.post(f"/api/cases/{case_id}/messages", {"body": "hello"}).status_code == 404
    d = david.post("/api/ai/tools/invoke", {"tool": "draft_message", "args": {"case_id": case_id, "intent": "status_question", "language": "de"}})
    assert d.status_code == 200 and d.json()["status"] == "executed"
    # Other cases of the same citizen are not covered by a case-scoped delegation.
    other = maya.post("/api/cases", {"title": "Private matter"}).json()
    assert david.get(f"/api/cases/{other['id']}").status_code == 404
    # Expiry blocks access.
    dl = db.get(Delegation, deleg_id)
    dl.valid_until = utcnow() - timedelta(seconds=1)
    db.commit()
    assert david.get(f"/api/cases/{case_id}").status_code == 404
    dl.valid_until = utcnow() + timedelta(days=1)
    db.commit()
    assert david.get(f"/api/cases/{case_id}").status_code == 200
    # Revocation blocks future access immediately.
    assert maya.post(f"/api/delegations/{deleg_id}/revoke").status_code == 200
    assert david.get(f"/api/cases/{case_id}").status_code == 404
    assert david.get(f"/api/documents/{passport['id']}").status_code == 404
    assert david.get("/api/cases").json()["meta"]["total"] == 0 or all(c["id"] != case_id for c in david.get("/api/cases").json()["items"])
    tl = {e["kind"] for e in maya.get(f"/api/cases/{case_id}/timeline").json()["items"]}
    assert {"delegation.granted", "delegation.revoked"} <= tl


def test_cross_tenant_and_cross_user_attacks():
    maya, jonas = login("maya"), login("jonas")
    case_id = start_relocation(maya)
    doc = upload_doc(maya, content="Passport (synthetic demo document)\nSecret passport number DEMO-999111")
    # Another citizen: record, document, download, timeline, export, messages.
    for url in (f"/api/cases/{case_id}", f"/api/documents/{doc['id']}", f"/api/documents/{doc['id']}/versions/1/download",
                f"/api/cases/{case_id}/timeline", f"/api/cases/{case_id}/export", f"/api/cases/{case_id}/messages",
                f"/api/life-events/by-case/{case_id}/progress"):
        assert jonas.get(url).status_code == 404, url
    assert all(c["id"] != case_id for c in jonas.get("/api/cases").json()["items"])
    # Retrieval: Jonas's document search never sees Maya's chunks.
    res = jonas.post("/api/rights/ask", {"question": "passport number DEMO-999111", "include_my_documents": True}).json()
    assert all(h["document_id"] != doc["id"] for h in res["personal_document_hits"])
    # Authority of another tenant (Tel Aviv) cannot see Berlin-routed requests.
    sr = maya.post(f"/api/cases/{case_id}/requests", {"procedure_code": "DE-BER-ANMELDUNG"}).json()
    maya.post(f"/api/cases/{case_id}/requests/{sr['id']}/actions", {"action": "submit"})
    amir = login("amir")
    assert amir.get(f"/api/authority/requests/{sr['id']}").status_code == 404
    assert all(i["id"] != sr["id"] for i in amir.get("/api/authority/queue").json()["items"])
    assert amir.get(f"/api/cases/{case_id}").status_code == 404
    assert amir.post(f"/api/authority/requests/{sr['id']}/actions", {"action": "accept"}).status_code == 404
    # The client cannot pick another tenant by sending ids: membership switch to a foreign membership fails.
    lena = login("lena")
    assert amir.post("/api/auth/context", {"membership_id": lena.me["memberships"][0]["id"]}).status_code == 404
    # Notifications are per user.
    n = maya.get("/api/notifications").json()["items"]
    if n:
        assert jonas.post(f"/api/notifications/{n[0]['id']}/read").status_code == 404
    # Governance: no case or document content, pseudonymised audit, suppressed aggregates.
    gov = login("govadmin")
    assert gov.get(f"/api/cases/{case_id}").status_code == 404
    assert gov.get(f"/api/documents/{doc['id']}").status_code == 404
    assert gov.get("/api/cases").json()["items"] == []
    audit_items = gov.get("/api/governance/audit").json()["items"]
    assert all("@" not in str(e) for e in audit_items)
    analytics = gov.get("/api/governance/analytics").json()
    assert "DEMO-999111" not in str(analytics) and "maya" not in str(analytics).lower()
    # Authority audit views/analytics endpoints are not reachable from other workspaces.
    assert jonas.get("/api/governance/audit").status_code == 403
    assert amir.get("/api/governance/analytics").status_code == 403
