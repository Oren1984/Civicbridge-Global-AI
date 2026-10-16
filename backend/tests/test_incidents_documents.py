"""Journey B (municipal incident) plus document security: allowlists, malware quarantine, scanner outage, redaction."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from app.config import get_settings
from app.models import Incident, StoredObject
from tests.conftest import login, run_jobs, txt, upload_doc

FIX = Path(__file__).resolve().parents[1] / "packs" / "fixtures"
EICAR = "X5O!P%@AP[4\\PZX54(P^)7CC)7}$" + "EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"  # split so the source file itself is not a signature


def _berlin_district(api) -> str:
    return next(m["id"] for m in api.get("/api/incidents/municipalities").json()["items"] if "Berlin District" in m["name"])


def test_municipal_incident_end_to_end(db):
    jonas = login("jonas")
    tid = _berlin_district(jonas)
    s = jonas.post("/api/incidents/classify", {"description": "The streetlight in front of my house is dark"}).json()
    assert s["category"] == "streetlight" and "not analysed" in s["label"]
    first = jonas.post("/api/incidents", {"tenant_id": tid, "description": "Streetlight out on Beispielstraße corner, dark at night",
                                          "lat": 52.520812, "lon": 13.409531, "location_text": "Beispielstraße corner"}).json()
    assert first["category"] == "streetlight" and first["category_source"] == "rules_suggestion"
    assert first["lat_approx"] == 52.521 and first["location_precision"] == "approx_110m"  # minimised
    img = (FIX / "streetlight_photo.png").read_bytes()
    r = jonas.upload(f"/api/incidents/{first['id']}/media", {"file": ("photo.png", img, "image/png")})
    assert r.status_code == 200 and r.json()["kind"] == "image"
    audio = (FIX / "streetlight_voice_note.wav").read_bytes()
    r = jonas.upload(f"/api/incidents/{first['id']}/media", {"file": ("note.wav", audio, "audio/wav")})
    assert r.json()["transcription_status"] == "fixture" and "Demo fixture" in r.json()["transcription_text"]
    other_audio = audio[:-10] + b"\x00" * 10
    r = jonas.upload(f"/api/incidents/{first['id']}/media", {"file": ("note2.wav", other_audio, "audio/wav")})
    assert r.json()["transcription_status"] == "unavailable"  # original audio kept, no fake transcript
    run_jobs()
    maya = login("maya")
    dup = maya.post("/api/incidents", {"tenant_id": tid, "description": "Streetlight not working near Beispielstraße corner",
                                       "lat": 52.5209, "lon": 13.4094, "category": "streetlight"}).json()

    lena = login("lena").switch("berlin-district")
    q = lena.get("/api/incidents?status=open").json()["items"]
    assert {first["id"], dup["id"]} <= {i["id"] for i in q}
    d = lena.get(f"/api/incidents/{dup['id']}").json()
    assert any(c["incident_id"] == first["id"] for c in d["duplicates"])
    assert lena.post(f"/api/incidents/{dup['id']}/actions", {"action": "mark_duplicate", "data": {"duplicate_of": first["id"]}}).status_code == 200
    act = lambda a, data=None: lena.post(f"/api/incidents/{first['id']}/actions", {"action": a, "data": data or {}})  # noqa: E731
    assert act("start").status_code == 403  # not assigned yet (permission is checked before state)
    assert act("triage", {"priority": "high"}).status_code == 200
    assert act("assign").status_code == 200
    assert act("start", {"note": "Crew dispatched for repair."}).status_code == 200
    assert act("resolve", {"note": "x"}).status_code == 400
    ev = lena.upload(f"/api/incidents/{first['id']}/media", {"file": ("fixed.png", img, "image/png")}, {"role": "resolution_evidence"})
    assert ev.status_code == 200 and ev.json()["role"] == "resolution_evidence"
    assert act("resolve", {"note": "Lamp replaced and tested at night."}).status_code == 200
    run_jobs()
    detail = jonas.get(f"/api/incidents/{first['id']}").json()
    assert detail["incident"]["status"] == "resolved" and detail["incident"]["sla_due_at"]
    assert all(u["author"] is None for u in detail["updates"])  # staff names not exposed to the public reporter
    assert any(m["role"] == "resolution_evidence" and m["available"] for m in detail["media"])
    notes = [n["title"] for n in jonas.get("/api/notifications").json()["items"]]
    assert any("resolved" in t for t in notes)
    r = jonas.post(f"/api/incidents/{first['id']}/actions", {"action": "close", "data": {"rating": 5, "comment": "Fixed quickly, thanks."}})
    assert r.status_code == 200 and r.json()["status"] == "closed" and r.json()["feedback_rating"] == 5
    # Other citizens and other municipalities cannot see it.
    assert maya.get(f"/api/incidents/{first['id']}").status_code == 404
    assert login("amir").get(f"/api/incidents/{first['id']}").status_code == 404


def test_upload_allowlist_and_content_checks():
    maya = login("maya")
    r = maya.upload("/api/documents", {"file": ("run.exe", b"MZ\x90\x00", "application/octet-stream")}, {"title": "bad", "category": "other"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "file_type_not_allowed"
    r = maya.upload("/api/documents", {"file": ("fake.pdf", b"not a pdf", "application/pdf")}, {"title": "bad", "category": "other"})
    assert r.json()["error"]["code"] == "file_content_mismatch"
    r = maya.upload("/api/documents", {"file": ("../../etc/pass wd.txt", b"hello world", "text/plain")}, {"title": "path", "category": "other"})
    assert r.status_code == 200 and r.json()["versions"][0]["filename"] == "pass_wd.txt"
    big = b"a" * (get_settings().max_upload_mb * 1024 * 1024 + 1)
    r = maya.upload("/api/documents", {"file": ("big.txt", big, "text/plain")}, {"title": "big", "category": "other"})
    assert r.status_code == 413


def test_malware_is_quarantined_and_never_served(db):
    maya = login("maya")
    r = maya.upload("/api/documents", txt("eicar.txt", EICAR), {"title": "EICAR test", "category": "other"})
    doc = r.json()
    assert doc["versions"][0]["scan_status"] == "pending"
    assert maya.get(f"/api/documents/{doc['id']}/versions/1/download").status_code == 423  # not yet scanned
    run_jobs()
    v = maya.get(f"/api/documents/{doc['id']}").json()["versions"][0]
    assert v["scan_status"] == "infected" and "Eicar" in v["scan_detail"]
    for path in ("download", "preview"):
        r = maya.get(f"/api/documents/{doc['id']}/versions/1/{path}")
        assert r.status_code == 423 and r.json()["error"]["code"] == "file_not_available"


def test_scanner_outage_keeps_files_quarantined(db, monkeypatch):
    maya = login("maya")
    monkeypatch.setattr(get_settings(), "clamav_host", "unreachable-scanner.invalid")
    monkeypatch.setattr(get_settings(), "scanner_timeout_s", 1.0)
    r = maya.upload("/api/documents", txt("note.txt", "harmless"), {"title": "During outage", "category": "other"})
    run_jobs(max_rounds=1)
    obj = db.execute(select(StoredObject).where(StoredObject.original_filename == "note.txt").order_by(StoredObject.created_at.desc())).scalars().first()
    assert obj.scan_status == "scan_unavailable"
    assert maya.get(f"/api/documents/{r.json()['id']}/versions/1/download").status_code == 423
    monkeypatch.undo()
    from app.models import Job

    job = db.execute(select(Job).where(Job.kind == "scan_object", Job.payload["object_id"].as_string() == str(obj.id))).scalar_one()
    db.refresh(job)
    assert job.status == "queued" and job.attempts == 1  # retried with backoff, not marked clean
    job.run_after = job.created_at
    db.commit()
    run_jobs()
    db.refresh(obj)
    assert obj.scan_status == "clean"


def test_versioning_redaction_and_preview(db):
    maya = login("maya")
    doc = upload_doc(maya, title="Statement", category="financial", name="statement.txt",
                     content="Account holder Maya. IBAN DE00 1234 5678. Balance 1000 EUR.")
    r = maya.post(f"/api/documents/{doc['id']}/redact", {"version": 1, "terms": ["DE00 1234 5678"]})
    assert r.status_code == 200
    vers = r.json()["versions"]
    assert vers[-1]["kind"] == "redacted_derivative" and vers[0]["kind"] == "original"
    run_jobs()
    red = maya.get(f"/api/documents/{doc['id']}/versions/2/download")
    assert red.status_code == 200 and b"1234 5678" not in red.content and "████████".encode() in red.content
    assert b"1234 5678" in maya.get(f"/api/documents/{doc['id']}/versions/1/download").content  # original kept
    prev = maya.get(f"/api/documents/{doc['id']}/versions/1/preview")
    assert "sandbox" in prev.headers["content-security-policy"] and prev.headers["x-content-type-options"] == "nosniff"
    img = (FIX / "streetlight_photo.png").read_bytes()
    r = maya.upload("/api/documents", {"file": ("id.png", img, "image/png")}, {"title": "ID scan", "category": "identity"})
    run_jobs()
    r = maya.post(f"/api/documents/{r.json()['id']}/redact", {"version": 1, "regions": [[0.0, 0.0, 0.5, 0.2]]})
    assert r.status_code == 200 and "overwritten" in r.json()["versions"][-1]["note"]
    new = maya.upload(f"/api/documents/{doc['id']}/versions", txt("statement_v3.txt", "Updated statement"))
    assert new.json()["current_version"] == 3
