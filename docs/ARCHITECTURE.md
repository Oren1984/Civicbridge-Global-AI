# Architecture and decisions

CivicBridge is a **modular monolith**: one FastAPI backend process, one worker process using the same code base and database, a React single-page app served by nginx, and off-the-shelf infrastructure services. Everything runs locally with `docker compose up --build -d`.

## System architecture

```mermaid
flowchart LR
  subgraph Browser
    SPA["React app (Vite build)<br/>service worker: app shell only<br/>outbox in localStorage"]
  end
  subgraph Host["Docker host (127.0.0.1)"]
    NGINX["frontend · nginx-unprivileged<br/>:8084 → 8080<br/>static files, CSP, proxy"]
    API["backend · FastAPI/uvicorn :8000<br/>auth, authorization, workflow,<br/>AI gateway, meetings API"]
    WORKER["worker · same code<br/>job queue (SKIP LOCKED), sweeps"]
    DB[("PostgreSQL 16 + pgvector<br/>data, jobs, audit chain")]
    S3[("SeaweedFS S3<br/>document objects")]
    CLAM["ClamAV clamd"]
    MAIL["Mailpit :8095"]
    LK["LiveKit SFU<br/>signalling 7880 (internal)<br/>media TCP 7891, UDP 50100-50160"]
    OLL["Ollama (optional profile)"]
  end
  SPA -- "HTTPS/HTTP same origin<br/>/api/*" --> NGINX
  SPA -- "ws /rtc (signalling)" --> NGINX
  SPA -. "WebRTC media (UDP/TCP)" .-> LK
  NGINX -- "/api/ (X-Forwarded-For overwritten)" --> API
  NGINX -- "/rtc websocket" --> LK
  API --> DB
  WORKER --> DB
  API --> S3
  WORKER --> S3
  WORKER -- "INSTREAM scan" --> CLAM
  WORKER -- SMTP --> MAIL
  API -- "room service API" --> LK
  LK -- "webhook (signed)" --> API
  API -. "ai_mode=ollama" .-> OLL
```

Only nginx (8084), Mailpit (8095) and LiveKit media ports are published, all bound to 127.0.0.1 by default. nginx returns 404 for `/api/metrics`, `/api/integrations/sandbox/*` and `/api/meetings/livekit/webhook`, which are reachable only inside the Docker network.

## Backend layout

| Path | Role |
|---|---|
| `backend/app/main.py` | App factory, routers, error handlers, security headers |
| `backend/app/deps.py` | `get_ctx`: session cookie → user, membership, CSRF/Origin checks, MFA gate, read-only enforcement |
| `backend/app/routers/*` | HTTP API, one module per domain (140 operations) |
| `backend/app/services/*` | Domain logic: `access` (authorization), `workflow`, `calendar`, `incidents`, `meetings`, `audit`, `jobs`, `files`, `scanner`, `storage`, `analytics`, `integrations`, `notify` |
| `backend/app/ai/*` | Rule engine, embeddings, RAG, tool gateway, translation, model provider |
| `backend/app/worker.py` | Job handlers and periodic sweeps |
| `backend/app/cli.py` | Operations CLI (bootstrap, credentials, backup, restore check, audit) |
| `backend/packs/*` | Versioned synthetic jurisdiction packs, templates, glossary, fixtures |
| `backend/alembic/` | Migration `0001_initial` (schema, audit trigger, grants, HNSW index) |

## Frontend layout

| Path | Role |
|---|---|
| `frontend/src/App.tsx` | Routes per workspace, lazy-loaded pages, `Protected` guard, replay on reconnect |
| `frontend/src/lib/` | API client (CSRF header, auth events), auth context, i18n (en/he/de, RTL), offline outbox, preferences |
| `frontend/src/components/` | Shell and navigation, shared UI primitives (accessible fields, modal with focus trap, tabs) |
| `frontend/src/pages/{public,citizen,authority,shared,governance}` | Workspace pages |
| `frontend/src/help/articles.ts` | Help Center content and contextual mapping |
| `frontend/nginx/default.conf.template` | Proxy, CSP and caching rules |
| `frontend/e2e/` | Playwright suites (smoke, journeys, video, accessibility, mobile, screenshots) |

## Case lifecycle and human review

The state machine lives in `backend/app/services/workflow.py`; the server rejects any transition not allowed for the actor and state, and the UI shows only `allowed_actions` returned by the server.

```mermaid
stateDiagram-v2
  [*] --> draft: resident prepares request
  draft --> submitted: submit (resident / delegate)
  submitted --> triage: accept (officer)
  triage --> in_review: start_review (assignee)
  in_review --> info_requested: request_info (assignee)\nSLA clock pauses
  info_requested --> in_review: respond_info (resident / delegate)\nSLA resumes
  in_review --> decision_pending: propose_decision (assignee)\noutcome + rationale ≥ 30 chars
  decision_pending --> in_review: return_for_rework (supervisor)
  decision_pending --> decided: approve_decision (different supervisor)\nfour-eyes rule
  decided --> appealed: appeal (resident)\ncreates linked follow-up request
  decided --> closed: close (officer)
  submitted --> withdrawn
  triage --> withdrawn
  in_review --> withdrawn
  info_requested --> withdrawn
  closed --> [*]
```

Assignment and escalation are available in every open state. SLA deadlines use working-day calendars per jurisdiction (weekends and synthetic holidays); the worker's SLA sweep flags breaches and escalates. AI can draft a rationale scaffold but cannot call any transition (see [AI.md](AI.md)).

## Consent and controlled cross-tenant handoff

```mermaid
sequenceDiagram
  autonumber
  actor R as Resident
  participant A as Authority (tenant A)
  participant CB as CivicBridge API
  participant I as Institution (tenant B)
  A->>CB: POST /api/consents/requests (case, recipient = tenant B, purpose, categories, days)
  CB-->>R: notification + pending consent (status pending, handoff = true)
  Note over CB,I: tenant B has no participation and no document access yet
  R->>CB: POST /api/consents/{id}/approve
  CB->>CB: grant active · CaseParticipant(tenant B, granted_via = handoff)
  I->>CB: GET case / documents
  CB->>CB: access.document_access: active, purpose-bound, case-scoped grant covers only documents attached to that case
  CB-->>I: allowed items + share receipt for each document view
  R->>CB: POST /api/consents/{id}/revoke
  CB->>CB: grant revoked · participation ended
  I->>CB: GET case
  CB-->>I: 404 (audited denial)
```

## Video admission and authorization

```mermaid
sequenceDiagram
  autonumber
  actor H as Host
  actor P as Participant
  participant API as CivicBridge API
  participant LK as LiveKit
  H->>API: POST /meetings (case, invitees with roles)
  API->>API: each invitee must hold an eligible role on the case (interpreter: meeting only)
  H->>API: POST /meetings/{id}/open
  API->>LK: create room (auto_create disabled on the server)
  P->>API: POST /meetings/{id}/join → status waiting
  P->>API: POST /meetings/{id}/token → 403 not_admitted
  H->>API: POST /participants/{pid}/admit
  P->>API: POST /meetings/{id}/token → 10-minute room-scoped token
  P->>LK: connect via /rtc (signalling) + WebRTC media
  H->>API: POST /participants/{pid}/remove
  API->>LK: remove participant (kick)
  LK-->>API: webhook participant_joined (signed) → kick if not admitted
  loop every 10 s (worker)
    API->>LK: list participants → remove identities not currently admitted
  end
  P->>API: POST /token → 403
```

Documents shared in a meeting are authorized per viewer on every preview (`/meetings/{id}/shared/{doc}/preview`); meeting membership never replaces consent or delegation.

## Key decisions

| Decision | Reason | Consequence |
|---|---|---|
| Modular monolith + one worker | Small team, single deployment unit, transactional consistency | Scale-out needs shared rate limiting (currently in-process) |
| PostgreSQL job queue (`SKIP LOCKED`) instead of a broker | One less service; jobs commit with the data that created them | Throughput bounded by the database; fine for this scale |
| Server-side sessions, HttpOnly cookie, CSRF double-submit + Origin check | No tokens in JavaScript; immediate revocation | Same-origin deployment required (nginx proxy) |
| Deny-by-default authorization in one module (`services/access.py`) | One place to review; tenant isolation returns 404 and is audited | New features must route through it |
| Hash-chained, append-only audit with a restricted DB role | Tamper evidence without extra infrastructure | Not tamper-proof against a database superuser |
| Lexical hash embeddings in pgvector | No model download, deterministic tests | Retrieval quality is lexical, not semantic |
| LiveKit SFU, rooms created only by the backend | Proven WebRTC stack; server-side kick and webhooks | LAN/internet use needs host configuration ([VIDEO_SETUP.md](VIDEO_SETUP.md)) |
| Synthetic adapters with real contracts (idempotency, retries, dead letter) | No real government systems are available or authorized | `authorized_live` state exists in the model but no adapter uses it |
| Offline: app shell cache + per-user outbox, no offline case data | Minimise sensitive data on devices | Reloading without a connection cannot restore the session |
