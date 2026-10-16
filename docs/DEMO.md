# Demo accounts and walkthroughs

All accounts, organisations and data are synthetic. Passwords and TOTP seeds are generated on first start into the `civicbridge_demo` volume and are **not** in the repository:

```bash
docker compose exec backend python -m app.cli demo-credentials   # table of accounts, passwords and current TOTP codes
docker compose exec backend python -m app.cli totp lena          # fresh code for one account
```

| Key | Role(s) | Organisation(s) | MFA |
|---|---|---|---|
| `maya` | Resident | CivicBridge Citizens | — |
| `jonas`, `alex` | Resident | CivicBridge Citizens | — |
| `lena` | Case officer | Demo Berlin Residents' Registration Office; Demo Berlin District Office (Public Space Services) | yes |
| `thomas` | Supervisor | same two Berlin tenants | yes |
| `noa` | Case officer | Demo Israeli Population Services Office | yes |
| `amir` | Case officer | Demo Tel Aviv-Yafo Municipal Services | yes |
| `dana` | Supervisor | Demo Tel Aviv-Yafo Municipal Services; Demo Israeli Population Services Office | yes |
| `sam`, `casey` | Officer / supervisor | Demo San Francisco City Services; Demo California Assistance Programs Office | yes |
| `petra` | Institution liaison | Demo German Pension Insurance Liaison Office | yes |
| `david` | Professional adviser | Demo Cross-Border Legal Aid | — |
| `rina` | Interpreter | Demo Interpreting Services | — |
| `govadmin` | Governance administrator | CivicBridge Governance Office (demo) | yes |
| `auditor` | Governance auditor | CivicBridge Governance Office (demo) | yes |
| `viewer` | Resident, **read-only** | CivicBridge Citizens | — |

Authenticator apps: `python -m app.cli totp <key> --secret` prints the seed to add to an app. Codes are single-use per 30-second step.

## Seeded scenario

- Maya's relocation from Israel to Berlin: checklist across IL, DE and Berlin; documents scanned clean; a case-scoped consent to the Berlin registration office; address registration request **in review, assigned to Lena**; an active delegation to David; a video consultation tomorrow with an interpreter.
- Alex's business-formation journey in San Francisco; the viewer account's own relocation copy.
- 78 incidents across Berlin, Tel Aviv-Yafo and San Francisco; 14 historic Berlin decisions (for transparency figures); 5 risks; one closed breach drill.

## Walkthrough 1 — cross-border relocation (≈10 min)

1. Sign in as **maya**. The overview shows deadlines, information requests and the journey's progress.
2. My cases › *Relocate from Israel to Berlin, Germany*: checklist per jurisdiction with deadlines in local time, missing evidence, dependencies and human-review steps. Requests tab: the registration request with SLA and the simulated exchange acknowledgement.
3. Consent: the active consent to the Berlin office and its access receipts.
4. Sign in as **lena** (MFA) in a private window. Request queue › the request: evidence (documents outside the consent are shown as restricted), consents, timeline with internal entries. Choose **Request information**; the SLA clock pauses.
5. Back as maya: answer in the Requests tab. As lena: **Propose decision** (use *Insert AI scaffold*, then write the rationale). Lena cannot approve her own proposal.
6. Sign in as **thomas**: approve the decision. Maya receives a notification and can **Appeal**; the appeal appears in Lena's queue as a linked request.

## Walkthrough 2 — local issue (≈5 min)

1. maya › Report an issue: choose *Demo Tel Aviv-Yafo Municipal Services*, describe a broken streetlight, optionally use your approximate location (rounded to ~110 m) and add a photo.
2. **amir**: Incident queue › the report: possible duplicates, Triage, Assign, Start work, Mark resolved with a note and a photo.
3. maya: the update appears without staff names; *Confirm it is fixed* with a rating, or *It is not fixed* to reopen.

## Walkthrough 3 — video consultation (≈5 min, two browsers)

1. maya: open the relocation case › *Schedule a meeting*, invite Lena and Rina.
2. maya › Video meetings › the meeting › *Open meeting* › *Connect*.
3. **lena** and **rina** › *Ask to join*. maya admits them; each presses *Connect*.
4. maya › *Share a document*: Lena can open it (consent), Rina sees that it is restricted.
5. maya removes Rina: her client is disconnected. *End meeting* ends it for everyone.

## Walkthrough 4 — governance (≈5 min)

**govadmin**: Overview (service health, audit head), Audit › *Verify chain*, Policies (locked recording policy), Integrations (health check, failure injection) and Jobs (dead-letter re-queue), Reporting (suppressed small groups), AI oversight.

## Walkthrough 5 — restrictions to try

- As **viewer**: every change button is disabled with a lock and the server refuses the request.
- As **amir**, paste the URL of Lena's request: "Not found".
- As **rina**, open the relocation case URL: "Not found".
- Language menu › עברית: the interface switches to right-to-left.
