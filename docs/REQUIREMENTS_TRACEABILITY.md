# Requirements traceability

Maps the implementation contract (`prompt_01.md`, sections 2–18, and the owner's master specification) to code and evidence. **Backend** = `backend/tests/…`; **E2E** = `frontend/e2e/…` against the running stack. Status: ✅ implemented and verified, 🟡 implemented with partial verification, ⛔ not implemented.

## Workspaces

| Workspace | Code | Evidence | Status |
|---|---|---|---|
| Citizen | `frontend/src/pages/citizen/*`, `shared/*` | smoke (17 pages), journeys A–E, J, translator, keyboard, a11y, mobile | ✅ |
| Authority | `pages/authority/*`, `routers/authority.py` | smoke, journeys A, B, G, role switch | ✅ |
| Institution | `pages/shared/Workspaces.tsx`, `routers/workspaces.py`, consent handoff | Backend `test_handoff.py`; smoke | 🟡 (handoff approval not driven through the browser) |
| Professional | `Workspaces.tsx`, delegations, translation review | Backend `test_delegation_isolation.py`; journey D; smoke | ✅ |
| Governance | `pages/governance/*`, `routers/governance.py` | smoke (10 pages), journey K, a11y, backend ops tests | ✅ |
| Public transparency | `pages/public/Transparency.tsx`, `routers/public.py` | smoke, a11y, screenshot | ✅ |

## Product domains (§6)

| Requirement | Implementation | Evidence | Status |
|---|---|---|---|
| 6.1 Wallet: vault, versions, expiry, verification status | `routers/documents.py`, `Wallet.tsx`, `DocumentDetail.tsx` | Backend `test_incidents_documents.py`; smoke; screenshot 04 | ✅ |
| 6.1 Evidence associations | `routers/cases.py` evidence, `CaseDetail.tsx` | Backend `test_relocation_workflow.py`; review page | ✅ |
| 6.1 Purpose-bound consent, recipient/category limits, expiry, revocation | `routers/consent.py`, `services/access.py`, `Consent.tsx` | Backend tests (case-scoped consent defect fixed); journey F (consent-gated meeting document) | ✅ |
| 6.1 Time-limited delegation | `consent.py` delegations, `Delegations.tsx` | Backend; journey D | ✅ |
| 6.1 Sharing receipts and audit | `share_receipts`, `services/audit.py` | Backend; consent receipts tab | ✅ |
| 6.2 Six life-event journeys, multi-jurisdiction tasks, dependencies, evidence, local deadlines, explanations | `packs/templates.json`, `routers/life_events.py`, `CaseDetail.tsx` | Backend relocation test; journey A; screenshot 02 | ✅ |
| 6.2 Complete IL→DE relocation | seeded scenario + template | Journey A | ✅ |
| 6.3 Intake, routing, queues, filters, ownership | `routers/authority.py`, `Queue.tsx` | Journey A, G | ✅ |
| 6.3 Server-enforced state machine, RFI, SLA, escalation, four-eyes decisions, appeals | `services/workflow.py`, `RequestReview.tsx` | Backend; journey A + C | ✅ |
| 6.3 Messages and notifications | `cases.py` messages, `notify.py`, `Notifications.tsx` | Backend; smoke | 🟡 (notifications not asserted in E2E) |
| 6.4 Deterministic screening, sources, dates, uncertainty, human review, appeal guidance | `ai/rules.py`, `routers/rights.py`, `Rights.tsx` | Backend `test_ai.py`; journey J; screenshot 06 | ✅ |
| 6.5 en/he/de UI, RTL | `lib/i18n.tsx`, `i18n/*` | Journey I (dir=rtl), a11y dark + Hebrew, screenshot 10 | 🟡 (he/de partial, English fallback) |
| 6.5 Extraction, assisted translation, side-by-side, review, original preserved, mock honesty, not certified | `ai/translate.py`, `Translations.tsx` | Backend `test_ai.py`; translator journey | ✅ |
| 6.6 Text/image/audio intake, location minimisation, duplicates, routing, SLA, resolution evidence, feedback | `services/incidents.py`, `Incidents.tsx`, `IncidentDetail.tsx` | Backend `test_incidents_documents.py`; journey B | 🟡 (image/audio and duplicates verified in backend tests, not via the browser) |
| 6.7 Backlog, SLA, trends, freshness, quality, suppression | `services/analytics.py`, `Transparency.tsx`, `Ops.tsx` Reporting | Backend; smoke; screenshot 18 | ✅ |
| 6.8 Source-labelled notices, offline drafts, pending-sync state, idempotent replay, conflicts, minimal storage, logout cleanup, fallback instructions | `routers/sync.py`, `lib/offline.ts`, `Continuity.tsx`, `Notices.tsx` | Backend `test_sync_meetings_ops.py`; journeys E, E + I | 🟡 (conflict dialog not driven in the browser) |

## Shared capabilities (§7)

| Requirement | Evidence | Status |
|---|---|---|
| Unified timeline, tasks, reminders, templates | Backend; journey A | ✅ |
| Search, filters, sorting, pagination | Queue, incident queue, cases, audit, jobs; journey A (search) | ✅ |
| Saved drafts | Backend; Continuity page | ✅ |
| Versioned decisions, appeals | Journey A + C | ✅ |
| Document requests and evidence review | Backend; review page (accept / needs more / reject) | 🟡 (evidence review not clicked in E2E) |
| Export and privacy requests | Backend `test_sync_meetings_ops.py`; Privacy page smoke | 🟡 |
| Appointments with time zones | `routers/meetings.py`; journey F | ✅ |

## Video (§8)

| Requirement | Evidence | Status |
|---|---|---|
| Self-hosted WebRTC (LiveKit), no paid service | `docker-compose.yml`, `infra/livekit/` | ✅ |
| Citizen, authority, interpreter participants; eligibility by case role | Journey F; backend | ✅ (institution and professional participants: backend only) |
| Waiting room, admission, token gating | Journey F | ✅ |
| Camera, microphone, screen share controls | MeetingRoom UI; journey F (camera/mic via fake devices) | 🟡 (screen share not automated) |
| Case-linked sharing with per-viewer authorization | Journey F | ✅ |
| Removal of a connected participant, meeting end | Journey F | ✅ |
| External networks | [VIDEO_SETUP.md](VIDEO_SETUP.md) | ⛔ not verified |

## Platform (§§ 9–15)

| Requirement | Evidence | Status |
|---|---|---|
| Authentication, sessions, MFA, recovery, role switching | Backend `test_auth.py`; E2E setup, I, role switch, sign-out | ✅ |
| Authorization and tenant isolation | Backend `test_delegation_isolation.py`; journey G | ✅ |
| Read-only demo account | Backend `test_readonly.py`; journey H | ✅ |
| AI modes, tool boundaries, approval gate, budget | Backend `test_ai.py`; journey J | 🟡 (Ollama not verified) |
| Integrations with honest states | Backend; Governance › Integrations | ✅ |
| Audit chain, governance | Backend; journey K | ✅ |
| Help Center (13 topics, role-aware, contextual) | `help/articles.ts`, `Help.tsx`; smoke `/help`, `/help/video-meetings` | ✅ |
| Docker: single command, health, readiness, secrets, volumes | `docker-compose.yml`; [VERIFICATION_REPORT.md](VERIFICATION_REPORT.md) | ✅ |
| Accessibility, keyboard, mobile, themes | a11y (20), mobile (14), keyboard test | 🟡 (automated only) |

## Documentation (§16)

| Item | Location |
|---|---|
| README WHAT / WHY / HOW with screenshots | [../README.md](../README.md) |
| Mermaid: architecture, case lifecycle, consent handoff, video admission | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Topic documents | [README.md](README.md) index |
| Screenshots (login, overview, life event, authority review, consent, rights, incident resolution, governance, video, Hebrew RTL, mobile) | [screenshots/](screenshots/) |
