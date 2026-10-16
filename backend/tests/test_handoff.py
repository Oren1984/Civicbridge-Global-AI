"""Institution workspace: consented, case-scoped interagency handoff and its revocation."""
from __future__ import annotations

from tests.conftest import login, upload_doc
from tests.test_relocation_workflow import start_relocation


def test_consented_handoff_to_institution_and_revocation():
    maya = login("maya")
    case_id = start_relocation(maya)
    doc = upload_doc(maya, title="Insurance record", category="financial", name="record.txt", content="Insurance periods (synthetic)")
    maya.post(f"/api/cases/{case_id}/evidence", {"document_id": doc["id"], "evidence_key": "insurance_record"})
    sr = maya.post(f"/api/cases/{case_id}/requests", {"procedure_code": "DE-BER-ANMELDUNG"}).json()
    maya.post(f"/api/cases/{case_id}/requests/{sr['id']}/actions", {"action": "submit"})
    lena = login("lena").switch("berlin-registration")
    petra = login("petra")
    pension = next(t["id"] for t in maya.get("/api/consents/recipients").json()["items"] if "Pension" in t["name"])
    assert petra.get(f"/api/cases/{case_id}").status_code == 404
    # The authority asks; nothing is shared until the citizen approves.
    r = lena.post("/api/consents/requests", {"case_id": case_id, "recipient_tenant_id": pension, "purpose": "Coordinate insurance periods",
                                             "data_categories": ["financial"], "valid_days": 14})
    assert r.status_code == 200 and r.json()["status"] == "pending" and r.json()["handoff"] is True
    grant_id = r.json()["id"]
    assert petra.get(f"/api/cases/{case_id}").status_code == 404
    # An institution cannot request consent for a case it does not participate in.
    assert petra.post("/api/consents/requests", {"case_id": case_id, "purpose": "Fishing for data", "data_categories": ["identity"]}).status_code == 404
    pending = [g for g in maya.get("/api/consents").json()["items"] if g["status"] == "pending"]
    assert any(g["id"] == grant_id and g["requested_by"].startswith("Demo Berlin") for g in pending)
    assert maya.post(f"/api/consents/{grant_id}/approve").status_code == 200
    # Institution now sees the case and only the consented category of documents attached to it.
    assert petra.get(f"/api/cases/{case_id}").status_code == 200
    assert petra.get(f"/api/documents/{doc['id']}").status_code == 200
    passport = upload_doc(maya)
    maya.post(f"/api/cases/{case_id}/evidence", {"document_id": passport["id"], "evidence_key": "passport"})
    assert petra.get(f"/api/documents/{passport['id']}").status_code == 404  # identity not consented
    assert any(c["id"] == case_id for c in petra.get("/api/overview/institution").json()["cases"])
    assert petra.post(f"/api/cases/{case_id}/messages", {"body": "We received the handoff."}).status_code == 200
    # Revocation ends participation and document access immediately.
    assert maya.post(f"/api/consents/{grant_id}/revoke", {"reason": "Done"}).status_code == 200
    assert petra.get(f"/api/cases/{case_id}").status_code == 404
    assert petra.get(f"/api/documents/{doc['id']}").status_code == 404
    kinds = {e["kind"] for e in maya.get(f"/api/cases/{case_id}/timeline").json()["items"]}
    assert {"consent.requested", "handoff.approved", "consent.revoked"} <= kinds
