# Known limitations

CivicBridge here is a **local demonstration with synthetic data**. It is not production-ready, not legally certified and not connected to any government system.

## Content and AI

- All jurisdictions, rules, holidays, authorities, sources and exchanges are synthetic. Authority "decisions" are demo decisions, not legal acts. No official URLs are included.
- Retrieval is lexical (hash embeddings), not semantic. Abstention thresholds are calibrated on the bundled corpus only.
- Mock translation covers only the 10-entry demo glossary. There is no OCR (images yield no text). Audio transcription exists only for one demo fixture matched by hash.
- Ollama mode is implemented but **not verified**; `ollama/ollama:latest` is unpinned (optional profile only).

## Security and integrity

- The audit chain is tamper-evident, not tamper-proof: a database superuser can disable the trigger and rewrite the chain. Store `audit-anchor` output outside the host to detect that.
- SeaweedFS `-s3.encryptVolumeData` keys live in the filer metadata on the same host. PostgreSQL data, backups and Docker volumes are not encrypted by CivicBridge.
- Rate limiting is in-process (single backend replica). Scaling out needs a shared limiter.
- Small-group suppression is primary only; no complementary suppression.
- Citizens are not required to use MFA (privileged roles are).
- The CSP allows `'unsafe-inline'` for styles (React style attributes); scripts are `'self'` only.
- Interpreter candidates come from a global directory; an invitation is the authorization.
- The browser outbox (offline drafts) is stored unencrypted in localStorage.

## Video

- Verified only with Chromium and fake media devices on one host (three participants). Real cameras, other browsers, LAN, internet, TURN and NAT traversal are **not** verified. See [VIDEO_SETUP.md](VIDEO_SETUP.md).
- Removal is enforced by an immediate kick, a signed webhook and a 10-second reconciliation. If the kick failed, a removed participant with a still-valid token could stay connected up to the reconciliation interval. In the automated test the client was disconnected immediately.
- Rejoining with an old token after removal was not tested directly (the client discards tokens); new token requests after removal are refused (tested).
- Recording is disabled; there is no recording workflow.

## Offline

- Only the app shell is cached. A page reload without a connection cannot restore the session, so offline work is possible only in an already open session.
- Offline queueing covers incident reports and drafts; uploads and case actions need a connection.
- Conflict resolution is covered by backend tests (idempotent replay, conflict detection); the browser conflict dialog was not exercised by an automated test.

## Frontend

- Hebrew and German translations are partial (shell, sign-in, main resident and meeting flows); other text falls back to English. Help articles are English only.
- Automated accessibility checks (axe, WCAG 2.1 A/AA) pass on 20 pages; this is not a full manual accessibility audit (no screen-reader testing).
- The main bundle is ~480 kB (150 kB gzip); the meeting room chunk with livekit-client is ~580 kB and loads only on meeting pages.
- Swagger UI at `/api/docs` loads its assets from a CDN.

## Data and operations

- The deletion workflow retains decided cases (illustrative record-keeping rule) and the audit trail.
- Retention rules and periods are illustrative, not legal advice.
- A full restore into the live database is manual (the automated drill restores into a scratch database).
- Browser tests run against the live demo database and add records (cases, reports, meetings, delegations) on every run. `docker compose down -v` resets everything, including credentials.

## Not verified (do not claim)

- Any production, cloud or multi-host deployment; HTTPS setup.
- Browsers other than Chromium; real media devices; external networks.
- Ollama mode.
- Load or performance testing.
