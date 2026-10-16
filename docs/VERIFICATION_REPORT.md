# Verification report

Date: 2026-10-16. Environment: Windows 11 host, Docker Desktop, stack `civicbridge` running locally; browser tests with Playwright 1.64.1 / Chromium. All data synthetic.

## Summary

| Check | Result | How to reproduce |
|---|---|---|
| Backend tests against real PostgreSQL 16 + pgvector, SeaweedFS, ClamAV, LiveKit, Mailpit | **37 passed** | `docker compose --profile test run --rm tests` |
| Frontend type check (`tsc -b`, strict) | **0 errors** | `cd frontend && npx tsc -b` |
| Frontend production build | **ok** (Vite 6.4.4) | `cd frontend && npm run build` (also inside the Docker build) |
| Browser suite, full run | **101 passed, 0 failed, 6 skipped** (screenshot specs, on demand) in 12.6 min | `cd frontend && npx playwright test` |
| Browser tests added after the full run (role switch, sign-out purge, keyboard, translator) | **4 passed** | `npx playwright test journeys` |
| Accessibility (axe, WCAG 2.1 A/AA, serious + critical) | **20/20 pages pass**, incl. dark theme + Hebrew | `npx playwright test a11y` |
| Phone width 390 px, no horizontal scroll | **14/14 pages pass** | `npx playwright test mobile` |
| `npm audit` (prod and dev) | 0 vulnerabilities | `cd frontend && npm audit` |
| `pip-audit -r requirements.txt` | no known vulnerabilities (backend milestone) | test image |
| Secret scan of files that would be committed | no matches; `.admin-user`, `.env`, `frontend/e2e/.auth/`, `test-results/` are ignored | `git check-ignore -v <file>` |
| Web entry point smoke | `/`, SPA routes, `/api/health/{live,ready}` 200; `/api/metrics`, `/api/integrations/sandbox/*`, `/api/meetings/livekit/webhook` 404 via nginx; `/rtc/validate` reaches LiveKit (401); CSP and security headers present | curl, see [DOCKER.md](DOCKER.md) |
| Readiness | `{"database":"ok","storage":"ok","scanner":"ok","worker":"ok"}` | `curl http://localhost:8084/api/health/ready` |
| Backup + non-destructive restore drill | `ok: true` (backend milestone) | `app.cli backup`, `app.cli restore-check` |
| `verify-audit` and governance "Verify chain" | `ok: true`; UI test K passes | CLI / `journeys.spec.ts` K |
| Repeat startup | idempotent (backend milestone); frontend rebuilt and restarted repeatedly during this session without data loss | `docker compose up --build -d` |

## Browser journeys (real UI, running stack)

Every journey test also fails on uncaught page errors, console errors and HTTP 5xx responses.

| Journey | Test | What is verified through the UI |
|---|---|---|
| A + C relocation, rights and appeal | `journeys.spec.ts` A + C | start IL→DE journey, prepare and submit Berlin registration; officer accepts, assigns, starts review, requests information (SLA shows *Paused*); resident responds; officer proposes decision with rationale and **cannot approve it**; a different supervisor approves; resident sees *Version 1: Approved* and files an appeal; appeal appears in the authority queue |
| B incident | B | report to Tel Aviv-Yafo; officer triages, assigns, starts, resolves with a note; resident sees the update **without staff names**, confirms and rates |
| D delegation | D | delegation limited to one case; professional opens that case; after revocation the same URL shows "not found" |
| E offline | E; E + I | offline report queued (pill shows *Offline*), replayed on reconnect and visible in the list; unsent item → sign-out warning → local data removed, old session returns 401 |
| F multiparty video | `video.spec.ts` | schedule from case, host opens, officer and interpreter wait (token **403** while waiting), host admits, three browsers connected, **remote frames decoded**, interpreter gets 403/404 for the case, shared passport viewable by the officer and **restricted** for the interpreter, connected interpreter removed → client disconnected, server room-check shows 2 connected and no unauthorised identities, token re-request 403, host ends → officer sees ended |
| G cross-tenant | G | other authority's officer gets "not found" in the UI and 404 from the API |
| H read-only | H | disabled upload with explanation; `POST /api/cases` → 403 `read_only_account` |
| I authentication | setup project; I; role switch; E + I | 10 accounts sign in (TOTP for privileged roles, codes computed per step); wrong password message; Hebrew sets `dir="rtl"`; role switch changes tenant and back; sign-out revokes the session |
| J AI | J | supported question → answer with mode badge; unrelated question → "No supported answer" |
| K governance | K | auditor verifies the chain ("Chain intact"); auditor has no case content; policies read-only for auditors |
| Translator | Translator | mock translation shows the glossary sentence, other text *Not translated*, *Not certified* badge; human review marks it reviewed |
| Keyboard | keyboard | skip link first in tab order and moves focus to main; arrow keys move between tabs; Escape closes a modal and restores focus |
| Smoke | `smoke.spec.ts` | 47 pages across all five workspaces render without errors |

## Video verification level

**Level 2 of 3**: real LiveKit media between three Chromium instances on one host with fake camera/microphone devices (`--use-fake-device-for-media-stream`). Not verified: real devices, other browsers, other machines, LAN or internet, TURN.

## Defects found and fixed in this session

1. Offline incident reporting was impossible: the report form loaded the municipality list from the API and could not render offline. Fixed with a per-user reference cache (cleared on sign-out) and by keeping already-loaded data visible when a refetch fails.
2. Phone layout overflowed by 25 px (grid column min-content from the header). Fixed (`minmax(0, 1fr)`, compact header below 480 px); regression test added.
3. Stepper numbers were shown twice ("1. 1. Intake").
4. Authority review listed task-level evidence mixed with request evidence (duplicates). Request evidence is now shown first, other case evidence in a collapsible group.
5. AI oversight page crashed: `never_automated` is an object, not a list.
6. Accessibility: brand link name mismatch (WCAG 2.5.3), contrast of accent badges (light) and the notification count (dark).
7. Hebrew fallback strings rendered with misplaced punctuation on the overview; translations added.

## Not verified / blocked

See [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md#not-verified-do-not-claim). In particular: Ollama mode, external networks for video, browsers other than Chromium, manual screen-reader testing, the browser conflict-resolution dialog (backend conflict handling is tested), password recovery and email verification through the UI (backend tests cover them), session idle expiry in the browser (backend test covers it).

## Evidence locations

- Backend tests: `backend/tests/`
- Browser tests: `frontend/e2e/`; HTML report after a run: `frontend/playwright-report/` (not committed)
- Screenshots: `docs/screenshots/` (captured with `CB_SCREENSHOTS=1 npx playwright test screenshots video journeys`)
