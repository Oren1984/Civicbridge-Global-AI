# Operations: backup, retention, incidents, troubleshooting

All commands run from the repository root. In Git Bash on Windows, prefix commands that take container paths with `MSYS_NO_PATHCONV=1`.

## Operations CLI

```bash
docker compose exec backend python -m app.cli demo-credentials        # demo accounts, passwords, current TOTP codes
docker compose exec backend python -m app.cli totp <key>              # fresh TOTP code (add --secret for the seed)
docker compose exec backend python -m app.cli reset-demo-credentials  # regenerate demo passwords and TOTP seeds
docker compose exec backend python -m app.cli verify-audit            # recompute the audit hash chain (exit 1 if broken)
docker compose exec backend python -m app.cli audit-anchor            # print the head hash to store outside this host
docker compose exec backend python -m app.cli backup                  # database dump + object archive + manifest
docker compose exec backend python -m app.cli list-backups
docker compose exec -T backend python -m app.cli provision-admin < admin.json   # owner admin; see README
docker compose exec backend python -m app.cli restore-check /backups/<stamp>
```

## Backup and restore

`backup` writes `/backups/<UTC stamp>/` in the `civicbridge_backups` volume:

- `db.dump` — `pg_dump -Fc` of the database (PostgreSQL 16 client),
- `objects.tar` — every stored object from SeaweedFS,
- `manifest.json` — row counts per table, object count and the audit head hash.

Backups are **not encrypted** by CivicBridge; protect the volume or copy it to encrypted storage. Copy a backup off the host with `docker compose cp backend:/backups/<stamp> ./backup-<stamp>`.

`restore-check` is the restore drill. It restores the dump into a scratch database (`civicbridge_restore_check`), compares row counts and the audit chain with the manifest, checks the object count, then drops the scratch database. It never touches the live database. Last run: `ok: true` (see [VERIFICATION_REPORT.md](VERIFICATION_REPORT.md)).

A full restore into the live system is a deliberate, destructive operation and is not automated: stop `backend`, `worker` and `frontend`, restore `db.dump` with `pg_restore --clean` as `civicbridge_admin`, restore `objects.tar` into the bucket, start the services, then run `verify-audit`.

## Retention and deletion

| Item | Rule | Where |
|---|---|---|
| Consents and delegations | Expire at `valid_until` (sweep every 60 s); revocable any time | `worker.sweep_expiry` |
| Documents with `retention_until` | Soft-deleted when the date passes, files erased by a job | `worker.sweep_retention` (every 10 min) |
| Deleted documents | Hidden immediately; storage objects erased by the `erase` job | `routers/documents.py`, worker |
| Data exports | Expire 7 days after creation | `expire_export` job |
| Privacy deletion request | Erases documents, revokes consents and delegations, anonymises incident reports, deactivates the account. **Retains** cases that contain an authority decision (illustrative record-keeping rule) and lists them in the request notes. | `worker.h_privacy_deletion` |
| Audit events | Kept; append-only | database trigger |
| Meeting recordings | None: recording is disabled by a locked policy | `policies.meeting_recording` |

The retention rules are illustrative defaults for a demo, not legal advice for any jurisdiction.

## Security and privacy incident response

Governance › Security incidents tracks incidents through **open → triaged → contained → notified → closed**, with a note on every step.

1. Record the incident (kind, severity, description, whether personal data is involved). For personal data a notification deadline is set (policy `breach_notification_hours`, 72 h by default).
2. Triage and contain. Useful evidence: Governance › Audit (filter by action prefix or outcome `denied`), `verify-audit`, `docker compose logs backend worker frontend`.
3. Revoke access where needed: users can revoke their sessions; administrators can disable an integration adapter; residents can revoke consents.
4. Record the notification decision. A personal-data incident cannot be closed before the `notified` step.
5. Close with a summary. The seeded data contains one closed breach drill as an example.

## Runtime policies

Governance administrators change unlocked policies in Governance › Policies (every change is audited): session timeouts, upload size and quota, small-group threshold, AI mode, AI budget and timeout, incident SLA days, appeal window, breach notification hours, maximum consent and delegation duration. `meeting_recording` is locked.

## Integrations and jobs

- Governance › Integrations: health check per adapter, enable/disable, failure injection (`timeout`, `error`) to test retries and dead letters.
- Governance › Jobs: worker heartbeat, job list by status, re-queue of dead-lettered jobs.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Uploads stay "Scan in progress" after first start | ClamAV is still downloading signatures (2-5 min). `docker compose logs clamav`. Files are scanned automatically afterwards. |
| `/api/health/ready` reports `scanner: error` | ClamAV restarting or out of memory (needs ~1 GB). |
| "Your session ended" | Idle 30 min or absolute 12 h reached, or the session was revoked. |
| Login says too many attempts | Lockout or rate limit; wait 5 minutes. |
| MFA code rejected | Codes are single-use per 30 s step; wait for the next code. Check the host clock. |
| Emails not arriving | All mail goes to Mailpit: http://localhost:8095 |
| Port 8084 in use | Another service owns it; stop it or change the host port in `docker-compose.yml` (and `CB_PUBLIC_ORIGIN`, `CB_ALLOWED_ORIGINS`). |
| Page loads but API calls fail with 403 `csrf_failed` | You opened the app on an origin not in `CB_ALLOWED_ORIGINS`. |
| Video problems | See [VIDEO_SETUP.md](VIDEO_SETUP.md#troubleshooting). |
| Worker not processing | Governance › Jobs shows no heartbeat; `docker compose restart worker`. |
| `restore-check` path errors in Git Bash | Use `MSYS_NO_PATHCONV=1`. |
