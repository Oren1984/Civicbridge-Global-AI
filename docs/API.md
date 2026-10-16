# API

The backend exposes 140 operations under `/api`, documented by OpenAPI:

- Schema: http://localhost:8084/api/openapi.json
- Interactive docs: http://localhost:8084/api/docs (Swagger UI loads its assets from a CDN, so it needs internet access)

## Calling the API

The API uses the same session cookie as the web app.

```bash
B=http://localhost:8084
curl -s -c jar -H "Content-Type: application/json" -H "Origin: $B" \
  -d '{"email":"maya.cohen@demo.civicbridge.local","password":"<from demo-credentials>"}' $B/api/auth/login > me.json
CSRF=$(python -c "import json;print(json.load(open('me.json'))['csrf_token'])")
curl -s -b jar $B/api/cases | head -c 400
curl -s -b jar -H "X-CSRF-Token: $CSRF" -H "Origin: $B" -H "Content-Type: application/json" \
  -d '{"title":"API test case"}' $B/api/cases
```

Every non-GET request needs `X-CSRF-Token` and an allowed `Origin`. Accounts with privileged roles must complete `POST /api/auth/mfa/verify` with a TOTP code before other calls succeed (`403 mfa_required`).

## Errors

```json
{"error": {"code": "consent_required", "message": "…", "fields": [{"field": "purpose", "message": "…"}]}}
```

Common codes: `not_authenticated`/`session_expired` (401), `mfa_required`, `read_only_account`, `role_not_permitted`, `transition_not_permitted`, `four_eyes_required`, `consent_required` (403), `not_found` (404, also for records outside your tenant), `invalid_transition`, `stale_version`, `draft_conflict` (409), `file_not_available` (423), `rate_limited` (429), `validation_error` (422).

## Areas

| Prefix | Purpose |
|---|---|
| `/api/auth` | login, logout, me, context switch, MFA, recovery, registration, sessions, profile |
| `/api/overview` | per-workspace overviews, tenant directory |
| `/api/life-events` | templates, start journey, progress |
| `/api/cases` | cases, tasks, messages, evidence, requests and actions, export |
| `/api/documents` | wallet, versions, download/preview, redaction, receipts |
| `/api/consents`, `/api/delegations` | consent grants and requests, approval, revocation; delegations |
| `/api/rights` | rule sets, screening, review requests, source-cited questions |
| `/api/translations` | assisted translation and review |
| `/api/incidents` | report, media, queue, actions |
| `/api/authority` | queue, request review, actions, evidence review, stats |
| `/api/meetings` | scheduling, admission, tokens, removal, shared documents |
| `/api/drafts`, `/api/sync/replay`, `/api/emergency/notices` | continuity |
| `/api/notifications` | list, read, preferences |
| `/api/privacy` | export and deletion requests |
| `/api/ai` | status, tool invocation and approval, assist |
| `/api/governance` | overview, audit, policies, risks, security incidents, integrations, jobs, data quality, analytics, AI and consent oversight, operations |
| `/api/public` | transparency aggregates, emergency notices, jurisdictions (no login) |
| `/api/health/live`, `/api/health/ready` | health and readiness |

`/api/metrics`, `/api/integrations/sandbox/*` and `/api/meetings/livekit/webhook` exist only on the internal network; nginx answers 404 for them.
