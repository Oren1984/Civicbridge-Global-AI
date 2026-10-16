"""Idempotent loading of jurisdiction packs and the synthetic demo scenario.

* Packs are loaded per (code, version); a changed checksum for an existing version is rejected (bump the version).
* Demo account passwords and TOTP seeds are generated on first run and written ONLY to the private credentials
  file (CB_DEMO_CREDENTIALS_FILE, a Docker volume). Nothing reusable is committed to the repository.
"""
from __future__ import annotations

import hashlib
import json
import logging
import random
import secrets
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.embeddings import embed
from app.config import get_settings
from app.db import utcnow
from app.deps import Ctx
from app.models import (
    Authority,
    Case,
    ConsentGrant,
    Decision,
    Delegation,
    Document,
    DocumentVersion,
    EmergencyNotice,
    EvidenceLink,
    Holiday,
    Incident,
    IncidentUpdate,
    IntegrationAdapter,
    Jurisdiction,
    JurisdictionPack,
    Membership,
    Procedure,
    Risk,
    RuleSet,
    RuleVersion,
    SecurityIncident,
    Service,
    ServiceRequest,
    SourcePassage,
    SourceRecord,
    Task,
    Tenant,
    User,
    WorkflowTemplate,
)
from app.models.identity import PRIVILEGED_ROLES
from app.security.crypto import encrypt_secret, hash_password, new_totp_secret, password_problems
from app.services import analytics, audit, files, incidents, storage, workflow
from app.services.refs import next_ref

log = logging.getLogger("civicbridge.seed")
PACKS = Path(__file__).resolve().parents[1] / "packs"
PACK_FILES = ["de-1.0.0.json", "il-1.0.0.json", "us-1.0.0.json"]
MUNICIPAL = {"tlv-municipality", "berlin-district", "sf-city-services"}
TENANT_JURISDICTION = {
    "il-population": "IL", "tlv-municipality": "IL-TA-TLV", "berlin-registration": "DE-BE-BER", "berlin-district": "DE-BE-BER",
    "de-pension-liaison": "DE", "sf-city-services": "US-CA-SF", "ca-assistance": "US-CA",
}


def _d(v: str | None) -> date | None:
    return date.fromisoformat(v) if v else None


def _jur(db: Session, code: str | None) -> Jurisdiction | None:
    return db.execute(select(Jurisdiction).where(Jurisdiction.code == code)).scalar_one_or_none() if code else None


def _tenant(db: Session, slug: str, name: str, kind: str, jurisdiction_code: str | None = None, settings: dict | None = None) -> Tenant:
    t = db.execute(select(Tenant).where(Tenant.slug == slug)).scalar_one_or_none()
    if t is None:
        j = _jur(db, jurisdiction_code)
        t = Tenant(slug=slug, name=name, kind=kind, jurisdiction_id=j.id if j else None, settings=settings or {})
        db.add(t)
        db.flush()
    return t


def load_pack(db: Session, filename: str) -> str:
    raw = (PACKS / filename).read_bytes()
    checksum = hashlib.sha256(raw).hexdigest()
    pack = json.loads(raw)
    existing = db.execute(select(JurisdictionPack).where(JurisdictionPack.code == pack["code"], JurisdictionPack.version == pack["version"])).scalar_one_or_none()
    if existing:
        if existing.checksum != checksum:
            raise RuntimeError(f"Pack {pack['code']} {pack['version']} changed without a version bump; bump the pack version.")
        return "unchanged"
    for j in pack["jurisdictions"]:
        parent = _jur(db, j["parent"])
        row = _jur(db, j["code"]) or Jurisdiction(code=j["code"])
        row.name, row.level, row.parent_id, row.pack_code = j["name"], j["level"], parent.id if parent else None, pack["code"]
        row.locale, row.currency, row.timezone, row.weekend_days = j["locale"], j["currency"], j["timezone"], j["weekend_days"]
        row.address_format, row.retention_default_days, row.is_synthetic = j["address_format"], j["retention_default_days"], True
        db.add(row)
        db.flush()
        for day, name in j.get("holidays", []):
            if not db.execute(select(Holiday).where(Holiday.jurisdiction_id == row.id, Holiday.day == _d(day))).first():
                db.add(Holiday(jurisdiction_id=row.id, day=_d(day), name=name, is_synthetic=True))
    for a in pack["authorities"]:
        kind = "institution" if a["kind"] == "institution" else "authority"
        t = _tenant(db, a["tenant"], a["name"], kind, a["jurisdiction"], {"handles_incidents": a["tenant"] in MUNICIPAL, "synthetic": True})
        auth = db.execute(select(Authority).where(Authority.code == a["code"])).scalar_one_or_none() or Authority(code=a["code"])
        auth.name, auth.jurisdiction_id, auth.tenant_id, auth.kind = a["name"], _jur(db, a["jurisdiction"]).id, t.id, a["kind"]
        db.add(auth)
        db.flush()
        for s in a["services"]:
            svc = db.execute(select(Service).where(Service.code == s["code"])).scalar_one_or_none() or Service(code=s["code"])
            svc.name, svc.authority_id, svc.sla_working_days = s["name"], auth.id, s["sla_working_days"]
            db.add(svc)
            db.flush()
            for p in s["procedures"]:
                proc = db.execute(select(Procedure).where(Procedure.code == p["code"])).scalar_one_or_none() or Procedure(code=p["code"])
                proc.name, proc.service_id, proc.description = p["name"], svc.id, p["description"]
                db.add(proc)
    db.flush()
    for s in pack["sources"]:
        src = db.execute(select(SourceRecord).where(SourceRecord.code == s["code"])).scalar_one_or_none() or SourceRecord(code=s["code"])
        src.title, src.publisher, src.jurisdiction_id, src.url, src.is_placeholder = s["title"], s["publisher"], _jur(db, s["jurisdiction"]).id, None, True
        src.language, src.effective_from, src.effective_to = s["language"], _d(s.get("effective_from")), _d(s.get("effective_to"))
        src.review_date, src.status, src.trust_label = _d(s["review_date"]), "synthetic_placeholder", "synthetic"
        db.add(src)
        db.flush()
        for old in db.execute(select(SourcePassage).where(SourcePassage.source_record_id == src.id)).scalars():
            db.delete(old)
        for i, p in enumerate(s["passages"]):
            db.add(SourcePassage(source_record_id=src.id, ordinal=i, anchor=p["anchor"], text=p["text"], embedding=embed(f"{s['title']} {p['text']}")))
    for rs in pack["rule_sets"]:
        proc = db.execute(select(Procedure).where(Procedure.code == rs["procedure"])).scalar_one()
        rset = db.execute(select(RuleSet).where(RuleSet.code == rs["code"])).scalar_one_or_none() or RuleSet(code=rs["code"])
        rset.name, rset.procedure_id, rset.pack_code, rset.consequential, rset.topic = rs["name"], proc.id, pack["code"], rs["consequential"], rs["topic"]
        db.add(rset)
        db.flush()
        for v in rs["versions"]:
            rv = db.execute(select(RuleVersion).where(RuleVersion.rule_set_id == rset.id, RuleVersion.version == v["version"])).scalar_one_or_none()
            rv = rv or RuleVersion(rule_set_id=rset.id, version=v["version"])
            rv.pack_version, rv.effective_from, rv.effective_to = pack["version"], _d(v["effective_from"]), _d(v.get("effective_to"))
            rv.language, rv.review_date, rv.review_status = v["language"], _d(v["review_date"]), v["review_status"]
            rv.verification_status, rv.confidence, rv.questions, rv.logic = "synthetic_illustrative", v["confidence"], v["questions"], v["logic"]
            rv.required_evidence, rv.source_record_ids, rv.appeal_guidance = v["required_evidence"], v["sources"], v["appeal_guidance"]
            db.add(rv)
    for a in pack.get("integration_adapters", []):
        ad = db.execute(select(IntegrationAdapter).where(IntegrationAdapter.code == a["code"])).scalar_one_or_none() or IntegrationAdapter(code=a["code"])
        t = db.execute(select(Tenant).where(Tenant.slug == a["tenant"])).scalar_one_or_none() if a.get("tenant") else None
        ad.name, ad.jurisdiction_code, ad.tenant_id, ad.state = a["name"], a.get("jurisdiction"), t.id if t else None, a["state"]
        ad.capabilities, ad.description, ad.health_status = a["capabilities"], a["description"], "unknown"
        db.add(ad)
    for n in pack.get("emergency_notices", []):
        if not db.execute(select(EmergencyNotice).where(EmergencyNotice.title == n["title"])).first():
            db.add(EmergencyNotice(jurisdiction_id=_jur(db, n["jurisdiction"]).id, title=n["title"], body=n["body"], severity=n["severity"],
                                   source_label=n["source_label"], source_kind=n["source_kind"], fallback_instructions=n["fallback_instructions"],
                                   issued_at=utcnow(), expires_at=None))
    db.add(JurisdictionPack(code=pack["code"], version=pack["version"], title=pack["title"], checksum=checksum, status=pack["status"],
                            loaded_at=utcnow(), notes=pack["notes"]))
    db.flush()
    return "loaded"


def load_templates(db: Session) -> None:
    data = json.loads((PACKS / "templates.json").read_text(encoding="utf-8"))
    for t in data["templates"]:
        row = db.execute(select(WorkflowTemplate).where(WorkflowTemplate.code == t["code"])).scalar_one_or_none() or WorkflowTemplate(code=t["code"])
        row.life_event_type, row.name, row.origin_code, row.destination_code = t["life_event_type"], t["name"], t["origin"], t["destination"]
        row.pack_versions, row.is_synthetic = t["pack_versions"], True
        row.definition = {k: t[k] for k in ("summary", "jurisdictions", "questions", "tasks")}
        db.add(row)
    db.flush()


# ------------------------------------------------------------------ accounts

ACCOUNTS = [
    # key, email, display name, locale, timezone, [(tenant_slug, role)], read_only
    ("maya", "maya.cohen@demo.civicbridge.local", "Maya Cohen", "he", "Asia/Jerusalem", [("citizens", "citizen")], False),
    ("jonas", "jonas.weber@demo.civicbridge.local", "Jonas Weber", "de", "Europe/Berlin", [("citizens", "citizen")], False),
    ("alex", "alex.rivera@demo.civicbridge.local", "Alex Rivera", "en", "America/Los_Angeles", [("citizens", "citizen")], False),
    ("lena", "lena.fischer@demo.civicbridge.local", "Lena Fischer", "de", "Europe/Berlin",
     [("berlin-registration", "authority_officer"), ("berlin-district", "authority_officer")], False),
    ("thomas", "thomas.braun@demo.civicbridge.local", "Thomas Braun", "de", "Europe/Berlin",
     [("berlin-registration", "authority_supervisor"), ("berlin-district", "authority_supervisor")], False),
    ("noa", "noa.levi@demo.civicbridge.local", "Noa Levi", "he", "Asia/Jerusalem", [("il-population", "authority_officer")], False),
    ("amir", "amir.katz@demo.civicbridge.local", "Amir Katz", "he", "Asia/Jerusalem", [("tlv-municipality", "authority_officer")], False),
    ("dana", "dana.mizrahi@demo.civicbridge.local", "Dana Mizrahi", "he", "Asia/Jerusalem",
     [("tlv-municipality", "authority_supervisor"), ("il-population", "authority_supervisor")], False),
    ("sam", "sam.taylor@demo.civicbridge.local", "Sam Taylor", "en", "America/Los_Angeles",
     [("sf-city-services", "authority_officer"), ("ca-assistance", "authority_officer")], False),
    ("casey", "casey.morgan@demo.civicbridge.local", "Casey Morgan", "en", "America/Los_Angeles",
     [("sf-city-services", "authority_supervisor"), ("ca-assistance", "authority_supervisor")], False),
    ("petra", "petra.schmidt@demo.civicbridge.local", "Petra Schmidt", "de", "Europe/Berlin", [("de-pension-liaison", "institution_liaison")], False),
    ("david", "david.benami@demo.civicbridge.local", "David Ben-Ami", "en", "Europe/Berlin", [("legal-aid", "professional")], False),
    ("rina", "rina.adler@demo.civicbridge.local", "Rina Adler", "he", "Europe/Berlin", [("interpreting", "interpreter")], False),
    ("govadmin", "gov.admin@demo.civicbridge.local", "Governance Admin (demo)", "en", "Europe/Berlin", [("governance", "governance_admin")], False),
    ("auditor", "gov.auditor@demo.civicbridge.local", "Governance Auditor (demo)", "en", "Europe/Berlin", [("governance", "governance_auditor")], False),
    ("viewer", "demo.viewer@demo.civicbridge.local", "Demo Viewer (read-only)", "en", "Europe/Berlin", [("citizens", "citizen")], True),
]


def _gen_password() -> str:
    while True:
        pw = f"Cb-{secrets.token_urlsafe(10)}-{secrets.randbelow(90) + 10}"
        if not password_problems(pw):
            return pw


def credentials_path() -> Path:
    return Path(get_settings().demo_credentials_file or "/run/civicbridge/demo/demo_credentials.json")


def ensure_accounts(db: Session, reset: bool = False) -> None:
    path = credentials_path()
    creds = {} if reset or not path.exists() else json.loads(path.read_text(encoding="utf-8"))
    accounts = creds.get("accounts", {})
    now = utcnow()
    for key, email, name, locale, tzname, mships, read_only in ACCOUNTS:
        entry = accounts.get(key) or {}
        user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if "password" not in entry:
            entry["password"] = _gen_password()
        if user is None:
            user = User(email=email, display_name=name, locale=locale, timezone=tzname, is_read_only=read_only, is_synthetic=True,
                        email_verified_at=now, password_hash=hash_password(entry["password"]))
            db.add(user)
            db.flush()
        elif reset or key not in accounts:
            user.password_hash = hash_password(entry["password"])
            user.locked_until, user.failed_logins = None, 0
        for slug, role in mships:
            t = db.execute(select(Tenant).where(Tenant.slug == slug)).scalar_one()
            if not db.execute(select(Membership).where(Membership.user_id == user.id, Membership.tenant_id == t.id, Membership.role == role)).first():
                db.add(Membership(user_id=user.id, tenant_id=t.id, role=role))
        if any(r in PRIVILEGED_ROLES for _s, r in mships):
            if "totp_secret" not in entry or not user.mfa_enabled:
                entry["totp_secret"] = entry.get("totp_secret") or new_totp_secret()
                user.mfa_secret_enc = encrypt_secret(entry["totp_secret"])
                user.mfa_enabled = True
                user.mfa_last_step = None
        entry.update({"email": email, "display_name": name, "roles": [f"{r}@{s}" for s, r in mships], "read_only": read_only})
        accounts[key] = entry
    db.flush()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"generated_at": now.isoformat(), "warning": "Local synthetic demo credentials. Never reuse elsewhere.",
                                "accounts": accounts}, indent=2), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def ensure_base_tenants(db: Session) -> None:
    _tenant(db, "citizens", "CivicBridge Citizens", "citizen_space")
    _tenant(db, "governance", "CivicBridge Governance Office (demo)", "governance")
    _tenant(db, "legal-aid", "Demo Cross-Border Legal Aid", "professional_org", "DE")
    _tenant(db, "interpreting", "Demo Interpreting Services", "professional_org", "DE")


# ------------------------------------------------------------------ demo scenario


def as_ctx(db: Session, email: str, slug: str | None = None, role: str | None = None) -> Ctx:
    user = db.execute(select(User).where(User.email == email)).scalar_one()
    m = None
    for mm in user.memberships:
        if (slug is None or mm.tenant.slug == slug) and (role is None or mm.role == role):
            m = mm
            break
    return Ctx(user=user, session=None, membership=m, db=db)  # type: ignore[arg-type]


def _doc(db: Session, ctx: Ctx, title: str, category: str, filename: str, text: str, language: str, expires_days: int | None = None) -> Document:
    obj = files.store_upload(db, owner_user_id=ctx.user.id, tenant_id=None, purpose="document", filename=filename, data=text.encode("utf-8"))
    doc = Document(owner_user_id=ctx.user.id, title=title, category=category, doc_type=category, language=language,
                   expires_at=utcnow() + timedelta(days=expires_days) if expires_days else None)
    db.add(doc)
    db.flush()
    db.add(DocumentVersion(document_id=doc.id, version=1, object_id=obj.id, created_by=ctx.user.id))
    db.flush()
    return doc


DOC_TEXTS = {
    "passport": "Passport (synthetic demo document)\nName: {name}\nPassport number: DEMO-{num}\nThis document is synthetic and for demonstration only.",
    "birth": "תעודת לידה (מסמך הדגמה סינתטי)\nשם: {name}\nמקום לידה: תל אביב-יפו\nמסמך זה סינתטי ומיועד להדגמה בלבד.",
    "landlord": "Wohnungsgeberbestätigung (synthetisches Demo-Dokument)\nHiermit bestätige ich den Einzug der folgenden Person.\nName: {name}\n"
                "Anschrift: Beispielstraße 12, 10115 Berlin\nDieses Dokument ist synthetisch und nur für Demonstrationszwecke.",
    "health": "Health insurance confirmation (synthetic demo document)\nInsured person: {name}\nThis document is synthetic and for demonstration only.",
}


def _relocation(db: Session, email: str, with_request: bool) -> Case:
    from app.routers.life_events import StartIn, start

    ctx = as_ctx(db, email)
    res = start(StartIn(template_code="relocation-il-de", target_date=utcnow() + timedelta(days=40),
                        answers={"needs_language_course": True, "has_employer": False}), ctx)
    case = db.get(Case, uuid.UUID(res["case_id"]))
    name = ctx.user.display_name
    num = secrets.randbelow(900000) + 100000
    passport = _doc(db, ctx, "Passport (synthetic)", "identity", "passport.txt", DOC_TEXTS["passport"].format(name=name, num=num), "en", 2900)
    birth = _doc(db, ctx, "Birth certificate (synthetic, Hebrew)", "civil_status", "birth_certificate.txt", DOC_TEXTS["birth"].format(name=name), "he")
    landlord = _doc(db, ctx, "Landlord confirmation (synthetic, German)", "housing", "landlord_confirmation.txt", DOC_TEXTS["landlord"].format(name=name), "de")
    tasks = {t.key: t for t in db.execute(select(Task).where(Task.case_id == case.id)).scalars()}
    for doc, key, ev in ((passport, "il-gather-docs", "passport"), (birth, "il-gather-docs", "birth_certificate"),
                         (landlord, "de-housing", "landlord_confirmation"), (passport, "de-registration", "passport"),
                         (landlord, "de-registration", "landlord_confirmation")):
        db.add(EvidenceLink(document_id=doc.id, case_id=case.id, task_id=tasks[key].id, evidence_key=ev, linked_by=ctx.user.id))
    tasks["il-gather-docs"].status = "done"
    tasks["il-gather-docs"].completed_at = utcnow()
    tasks["de-housing"].status = "done"
    tasks["de-housing"].completed_at = utcnow()
    db.flush()
    if with_request:
        proc = db.execute(select(Procedure).where(Procedure.code == "DE-BER-ANMELDUNG")).scalar_one()
        sr = workflow.create_request(ctx, case, proc.service.authority.tenant_id, proc.name, proc.id, payload={"queue": proc.service.code})
        for doc, ev in ((passport, "passport"), (landlord, "landlord_confirmation")):
            db.add(EvidenceLink(document_id=doc.id, case_id=case.id, task_id=tasks["de-registration"].id, service_request_id=sr.id,
                                evidence_key=ev, status="submitted", linked_by=ctx.user.id))
        berlin = db.execute(select(Tenant).where(Tenant.slug == "berlin-registration")).scalar_one()
        now = utcnow()
        db.add(ConsentGrant(owner_user_id=ctx.user.id, recipient_tenant_id=berlin.id, case_id=case.id, purpose="Address registration review",
                            data_categories=["identity", "housing"], valid_from=now, valid_until=now + timedelta(days=60), status="active", valid_days=60))
        db.commit()
        workflow.transition(ctx, sr, "submit", {})
        lena = as_ctx(db, "lena.fischer@demo.civicbridge.local", "berlin-registration")
        workflow.transition(lena, sr, "accept", {})
        workflow.transition(lena, sr, "assign", {"user_id": str(lena.user.id)})
        workflow.transition(lena, sr, "start_review", {})
    db.commit()
    return case


def _bulk_history(db: Session) -> None:
    """Synthetic historic volume so aggregate views exceed the small-group threshold."""
    rnd = random.Random(20261016)
    citizens = db.execute(select(Tenant).where(Tenant.slug == "citizens")).scalar_one()
    residents = []
    for i in range(1, 9):
        email = f"resident{i:02d}@demo.civicbridge.local"
        u = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if u is None:
            u = User(email=email, display_name=f"Demo Resident {i:02d}", password_hash=hash_password(secrets.token_urlsafe(24) + "aA1"),
                     email_verified_at=utcnow(), is_synthetic=True, is_active=True)
            db.add(u)
            db.flush()
            db.add(Membership(user_id=u.id, tenant_id=citizens.id, role="citizen"))
        residents.append(u)
    descs = {
        "streetlight": ["Streetlight out at the corner", "Lamp flickering all night near the park"],
        "pothole": ["Deep pothole in the bike lane", "Road damage after the rain"],
        "waste": ["Overflowing waste bin at the bus stop", "Litter left after the market"],
        "water": ["Small water leak from a pipe on the sidewalk"],
        "graffiti": ["Graffiti on the school wall"],
        "accessibility": ["Broken ramp at the library entrance"],
    }
    centers = {"tlv-municipality": (32.08, 34.78), "berlin-district": (52.52, 13.40), "sf-city-services": (37.77, -122.42)}
    for slug, (lat, lon) in centers.items():
        t = db.execute(select(Tenant).where(Tenant.slug == slug)).scalar_one()
        officer = db.execute(select(Membership).where(Membership.tenant_id == t.id, Membership.role == "authority_officer")).scalars().first()
        for _ in range(26):
            cat = rnd.choice(list(descs))
            created = utcnow() - timedelta(days=rnd.randint(1, 55), hours=rnd.randint(0, 23))
            status = rnd.choices(["closed", "resolved", "in_progress", "assigned", "submitted"], [5, 2, 2, 1, 1])[0]
            inc = Incident(reference=next_ref(db, "INC"), reporter_user_id=rnd.choice(residents).id, tenant_id=t.id, category=cat,
                           description=rnd.choice(descs[cat]) + " (synthetic history)", lat_approx=round(lat + rnd.uniform(-0.02, 0.02), 3),
                           lon_approx=round(lon + rnd.uniform(-0.02, 0.02), 3), location_precision="approx_110m", status=status,
                           queue=incidents.QUEUES[cat], sla_due_at=created + timedelta(days=5), assigned_user_id=officer.user_id if status != "submitted" else None,
                           category_source=rnd.choice(["reporter", "rules_suggestion"]))
            inc.created_at = created
            if status in ("resolved", "closed"):
                inc.resolved_at = created + timedelta(days=rnd.uniform(0.5, 8))
            if status == "closed":
                inc.closed_at = inc.resolved_at + timedelta(days=1)
                inc.feedback_rating = rnd.randint(3, 5)
            db.add(inc)
            db.flush()
            db.add(IncidentUpdate(incident_id=inc.id, author_user_id=inc.reporter_user_id, kind="status", body="Report received.", public=True))
    berlin = db.execute(select(Tenant).where(Tenant.slug == "berlin-registration")).scalar_one()
    proc = db.execute(select(Procedure).where(Procedure.code == "DE-BER-ANMELDUNG")).scalar_one()
    lena = db.execute(select(User).where(User.email == "lena.fischer@demo.civicbridge.local")).scalar_one()
    thomas = db.execute(select(User).where(User.email == "thomas.braun@demo.civicbridge.local")).scalar_one()
    for i in range(14):
        u = residents[i % len(residents)]
        submitted = utcnow() - timedelta(days=rnd.randint(10, 60))
        case = Case(reference=next_ref(db, "CB"), owner_user_id=u.id, title="Address registration (synthetic history)", case_type="life_event")
        db.add(case)
        db.flush()
        sr = ServiceRequest(reference=next_ref(db, "SR"), case_id=case.id, tenant_id=berlin.id, procedure_id=proc.id, title=proc.name,
                            state="closed" if i % 3 else "decided", queue=proc.service.code, submitted_at=submitted,
                            sla_due_at=submitted + timedelta(days=14), sla_breached=(i % 5 == 0), assigned_user_id=lena.id, closed_at=submitted + timedelta(days=9))
        db.add(sr)
        db.flush()
        db.add(Decision(service_request_id=sr.id, version=1, outcome="approved", rationale="Synthetic historic decision: registration confirmed after document review.",
                        proposed_by=lena.id, approved_by=thomas.id, status="approved", approved_at=submitted + timedelta(days=8)))
    db.commit()


def demo_scenario(db: Session) -> None:
    if db.execute(select(Case).limit(1)).first():
        log.info("demo scenario already present; skipping")
        return
    maya_case = _relocation(db, "maya.cohen@demo.civicbridge.local", with_request=True)
    _relocation(db, "demo.viewer@demo.civicbridge.local", with_request=False)
    maya = as_ctx(db, "maya.cohen@demo.civicbridge.local")
    david = db.execute(select(User).where(User.email == "david.benami@demo.civicbridge.local")).scalar_one()
    legal = db.execute(select(Tenant).where(Tenant.slug == "legal-aid")).scalar_one()
    now = utcnow()
    d = Delegation(principal_user_id=maya.user.id, delegate_user_id=david.id, delegate_tenant_id=legal.id, case_id=maya_case.id,
                   scopes=["view_case", "view_documents", "draft_messages", "send_messages", "respond_info_requests", "translation_review", "attend_meetings"],
                   document_categories=["identity", "housing"], purpose="Help with the Berlin registration and translations",
                   valid_from=now, valid_until=now + timedelta(days=30), status="active")
    db.add(d)
    db.commit()
    # A scheduled video consultation hosted by the Berlin officer.
    from app.services import meetings

    lena = as_ctx(db, "lena.fischer@demo.civicbridge.local", "berlin-registration")
    rina = db.execute(select(User).where(User.email == "rina.adler@demo.civicbridge.local")).scalar_one()
    try:
        meetings.create(lena, maya_case.id, "Registration consultation (demo)", now + timedelta(days=1), 30, "Europe/Berlin",
                        [{"user_id": str(maya.user.id), "role": "citizen"}, {"user_id": str(david.id), "role": "professional"},
                         {"user_id": str(rina.id), "role": "interpreter"}])
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        log.warning(f"demo meeting not created: {exc}")
    # Alex: business formation journey.
    from app.routers.life_events import StartIn, start

    alex = as_ctx(db, "alex.rivera@demo.civicbridge.local")
    start(StartIn(template_code="business-us-sf", target_date=now + timedelta(days=60), answers={"will_hire": True}), alex)
    _bulk_history(db)
    for title, cat, li, im, mit in [
        ("Synthetic data mistaken for real records", "privacy", 2, 4, "Every demo record and screen is labelled synthetic; seeds use reserved demo domains."),
        ("Simulated exchanges misread as official submissions", "legal", 3, 4, "Timeline, decisions and adapters are labelled simulated; no authorized-live adapters exist."),
        ("Malware scanner outage", "operational", 3, 3, "Uploads stay quarantined (scan_unavailable) and are retried; files are never served unscanned."),
        ("Privileged insider rewrites audit chain", "security", 1, 5, "Hash chain is tamper-evident only; anchor head hashes externally and restrict DB superuser access."),
        ("Lexical retrieval misses relevant sources", "ai", 3, 2, "Abstain below threshold; show candidates; human review for consequential outcomes."),
    ]:
        db.add(Risk(title=title, category=cat, likelihood=li, impact=im, mitigation=mit, owner="Governance Office (demo)", status="mitigating"))
    db.add(SecurityIncident(title="Synthetic drill: misdirected notification", kind="privacy_breach", severity="low", status="closed",
                            description="Tabletop exercise record (synthetic).", detected_at=now - timedelta(days=20), personal_data_involved=True,
                            notification_due_at=now - timedelta(days=17),
                            timeline=[{"at": (now - timedelta(days=20)).isoformat(), "status": "open", "note": "Drill started."},
                                      {"at": (now - timedelta(days=19)).isoformat(), "status": "notified", "note": "Drill: notification decision recorded."},
                                      {"at": (now - timedelta(days=18)).isoformat(), "status": "closed", "note": "Drill closed."}]))
    db.commit()
    analytics.refresh(db)


def reindex(db: Session) -> None:
    """Recompute lexical embeddings (deterministic, cheap) so a changed embedding scheme never leaves stale vectors."""
    from app.models import DocumentChunk

    for p in db.execute(select(SourcePassage)).scalars():
        p.embedding = embed(f"{p.source.title} {p.text}")
    for c in db.execute(select(DocumentChunk)).scalars():
        c.embedding = embed(c.text)
    db.flush()


def run(seed_demo: bool = True) -> None:
    from app.db import session_factory

    with session_factory()() as db:
        storage.ensure_bucket()
        ensure_base_tenants(db)
        for f in PACK_FILES:
            log.info(f"pack {f}: {load_pack(db, f)}")
        for slug, code in TENANT_JURISDICTION.items():
            t = db.execute(select(Tenant).where(Tenant.slug == slug)).scalar_one_or_none()
            if t and t.jurisdiction_id is None:
                t.jurisdiction_id = _jur(db, code).id
        load_templates(db)
        reindex(db)
        db.commit()
        if seed_demo:
            ensure_accounts(db)
            db.commit()
            demo_scenario(db)
        audit.record(db, "system.seed_completed", "system", None, details={"demo": seed_demo})
        db.commit()
