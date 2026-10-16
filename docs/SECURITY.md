# Security, privacy and tenant isolation

This covers authentication, authorization, tenant isolation, the threat model and the privacy model as implemented. For limits of these controls see [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md).

## Authentication (`backend/app/routers/auth.py`, `backend/app/deps.py`)

| Control | Implementation |
|---|---|
| Password storage | Argon2id. Policy: ≥ 12 characters, mixed case, a digit. |
| Sessions | Random token in an `HttpOnly`, `SameSite=Strict` cookie; only its SHA-256 is stored. Idle expiry 30 min, absolute 12 h (policies `session_idle_minutes`, `session_absolute_hours`). |
| CSRF | Double-submit token (`X-CSRF-Token`, from `/api/auth/me`) on every non-GET request, plus an `Origin` check against `CB_ALLOWED_ORIGINS`. |
| Brute force | Lockout after 5 failed logins; in-process rate limits: 20 logins per IP and 8 per email per 5 min, 6 MFA attempts per user per 5 min, 5 recovery and 5 registration requests per IP. |
| MFA | TOTP required for privileged roles (authority, institution liaison, governance). Secrets encrypted with Fernet (`mfa_key` secret); each time step accepted once (replay protection). |
| Recovery / registration | Single-use, expiring tokens (hash stored), delivered by email to Mailpit. Email verification before first login. |
| Session management | List and revoke sessions; password change revokes all other sessions. |
| Context switch | `POST /api/auth/context` selects the active membership; every request is evaluated against it only. |
| Read-only demo account | Enforced centrally in `get_ctx`: every non-GET is denied (`403 read_only_account`) except logout and context switch, and the denial is audited. Meeting tokens are POST and therefore denied too. |

## Authorization (`backend/app/services/access.py`)

Deny by default. Decisions are made per request from the active membership:

- **Citizens** see only records they own.
- **Authorities and institutions** see a case only through an explicit `CaseParticipant` row for the active tenant (created by submission or by an approved handoff). Drafts are never visible to authorities.
- **Documents** additionally need an active, purpose-bound consent for the document's category; a case-scoped consent covers only documents attached to that case. Each access writes a share receipt the owner can see.
- **Professionals** act within delegation scopes (`view_case`, `view_documents`, `upload_documents`, `draft_messages`, `send_messages`, `respond_info_requests`, `translation_review`, `attend_meetings`), document categories, an optional single case and an expiry.
- **Interpreters** invited to a meeting get meeting access only.
- **Governance** gets metadata, aggregates and pseudonymised audit entries; no case narratives or document contents.
- **Workflow transitions** are checked per actor (officer, assignee, supervisor, citizen side) and state; decision approval requires a different supervisor than the proposer (four eyes).

Cross-tenant requests return **404** (not 403) so the existence of records is not revealed, and every denial is written to the audit log.

## Tenant isolation evidence

`backend/tests/test_delegation_isolation.py` (journey G) checks records, documents, downloads, timeline, export, messages, retrieval, queue, notifications, governance and analytics across tenants. The browser suite (`frontend/e2e/journeys.spec.ts`, test G) checks that an officer of another authority gets "not found" in the UI and 404 from the API for a request outside their tenant.

## Files

Uploads pass a size limit (15 MB), a per-citizen quota (200 MB), an extension allowlist **and** a magic-byte check, get a random storage key and a safe filename, and are scanned by ClamAV (INSTREAM) in the worker. Files are served only when `clean`; a scanner outage leaves them `scan_unavailable` and retries. Downloads stream through the API (no pre-signed URLs) with `Content-Security-Policy: default-src 'none'; sandbox`, `nosniff` and `no-store`. Previews in the browser use sandboxed iframes or `<img>` from `blob:` URLs.

## Web entry point (`frontend/nginx/default.conf.template`)

CSP `default-src 'self'; script-src 'self'` (no inline script), `frame-ancestors 'none'`, `object-src 'none'`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `nosniff`, a Permissions-Policy limited to camera, microphone, display capture and geolocation for the app itself. `X-Forwarded-For` is overwritten with the connecting address. Internal endpoints are not reachable through nginx. The `/rtc` location does not write access logs because the LiveKit token travels in its query string.

## Audit (`backend/app/services/audit.py`)

Every security-relevant action and denial is recorded with actor, active tenant and role, resource, outcome and redacted details. Events form a SHA-256 hash chain; a database trigger rejects UPDATE and DELETE; the runtime role `civicbridge_app` has only SELECT/INSERT on `audit_events`. `python -m app.cli verify-audit` and the governance "Verify chain" button recompute the chain. `audit-anchor` prints the head hash to store externally. This is tamper-evident, not tamper-proof against a database superuser.

## Threat model (summary)

| Threat | Mitigation | Residual risk |
|---|---|---|
| Account takeover | Argon2id, lockout, rate limits, MFA for privileged roles, session revocation | Citizens are not forced to use MFA |
| CSRF / clickjacking | SameSite=Strict, CSRF token, Origin check, `frame-ancestors 'none'` | — |
| XSS | React escaping, strict CSP without inline scripts, sandboxed previews | `style-src 'unsafe-inline'` is allowed for React style attributes |
| Cross-tenant data access (IDOR) | Central authorization, 404 on denial, audited, tested | New endpoints must use `access.py` |
| Malicious uploads | Magic bytes, allowlist, ClamAV, serve only clean files, sandbox CSP | Scanner signatures depend on freshclam updates |
| Prompt injection via documents | Planner reads only the user's request; document text treated as data and flagged; tools allowlisted; consequential tools need human approval | Lexical detection of instruction-like text is heuristic |
| Over-reaching AI | Permanently forbidden tools (submit, decide, deny, release, dispatch, delete, change state); budgets and timeouts | — |
| Unauthorized meeting presence | Admission before token, 10-min room-scoped tokens, kick on removal, signed webhook, 10 s reconciliation | A removed participant could stay connected until the next reconciliation if the kick failed |
| Audit tampering | Hash chain, trigger, restricted DB role, verification, external anchor | Superuser can rewrite; anchor must be stored elsewhere |
| Secret leakage | Secrets generated at first start into a private volume, one copy per consumer, tight file modes; no secrets in the repository or `.env.example` | Host compromise exposes the volume |
| Data at rest | SeaweedFS volume encryption | Keys on the same host; PostgreSQL, backups and Docker volumes are not encrypted by CivicBridge |

## Privacy model

- **Minimisation**: incident locations are rounded on the device to about 110 m and again on the server; precise coordinates are never stored. Governance sees pseudonymised audit subjects and suppressed aggregates (groups smaller than 5 hidden).
- **Purpose binding**: consents name a recipient, purpose, categories, duration and optionally a case; delegations name scopes, categories, case and expiry. Both expire automatically (worker sweep) and can be revoked.
- **Transparency to the data subject**: share receipts for every document view, consent history, case timeline.
- **Subject rights**: export (ZIP, scanned, expires after 7 days) and deletion (erases documents, revokes grants, anonymises incidents, deactivates the account; keeps decided cases and the audit log, and says why). See [OPERATIONS.md](OPERATIONS.md#retention-and-deletion).
- **Offline storage**: the browser outbox holds only drafts the user typed, is stored unencrypted in localStorage, is keyed per user and is removed on sign-out (with a warning if items are unsent).
- **No external services by default**: AI runs in mock or rules mode; no telemetry; email stays in Mailpit.
