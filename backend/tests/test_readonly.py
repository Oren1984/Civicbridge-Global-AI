"""Journey H: the read-only demo account is blocked server-side from every mutation."""
from __future__ import annotations

from sqlalchemy import select

from app.models import AuditEvent
from tests.conftest import login, txt


def test_read_only_reads_work_and_writes_are_denied(db):
    v = login("viewer")
    assert v.me["user"]["read_only"] is True
    assert v.get("/api/cases").status_code == 200
    assert v.get("/api/documents").status_code == 200
    attempts = [
        ("post", "/api/cases", {"title": "Should fail"}),
        ("post", "/api/life-events", {"template_code": "relocation-il-de", "target_date": "2027-01-01T00:00:00Z"}),
        ("post", "/api/consents", {"recipient_tenant_id": "00000000-0000-0000-0000-000000000000", "purpose": "x" * 6, "data_categories": ["identity"], "valid_days": 5}),
        ("post", "/api/delegations", {}),
        ("post", "/api/incidents", {"tenant_id": "x", "description": "a long description here"}),
        ("post", "/api/ai/tools/invoke", {"tool": "summarize_case", "args": {}}),
        ("post", "/api/rights/screen", {"rule_set_code": "DE-BER-REG-OBLIGATION", "answers": {}}),
        ("post", "/api/meetings/00000000-0000-0000-0000-000000000000/token", None),
        ("post", "/api/privacy/requests", {"kind": "export"}),
        ("patch", "/api/auth/profile", {"locale": "de"}),
        ("put", "/api/drafts/k1", {"kind": "case_note", "payload": {}}),
        ("post", "/api/sync/replay", {"ops": []}),
    ]
    for method, url, body in attempts:
        r = getattr(v, method)(url, body)
        assert r.status_code == 403, (url, r.status_code, r.text)
        assert r.json()["error"]["code"] == "read_only_account", url
    r = v.upload("/api/documents", txt("x.txt", "hello"), {"title": "nope", "category": "other"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "read_only_account"
    denials = db.execute(select(AuditEvent).where(AuditEvent.action == "access.denied")).scalars().all()
    assert any(e.details.get("reason_code") == "read_only_account" for e in denials)
    # Logging out is still allowed.
    assert v.post("/api/auth/logout").status_code == 200
