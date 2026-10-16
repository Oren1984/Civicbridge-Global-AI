# Docker and configuration

## Requirements

- Docker Engine or Docker Desktop with Compose v2. No other host tools are needed to run the application.
- Node.js 22 only if you want to run the browser tests or the Vite dev server on the host.
- Disk: several GB for the images on first build (not measured separately on this machine), plus ~300 MB of ClamAV signatures downloaded on first start.
- Memory: about 1.7 GB in use when idle (measured: ClamAV ~1.0 GB, storage ~150 MB, backend ~135 MB, database ~100 MB, worker ~95 MB, LiveKit ~55 MB, nginx and Mailpit < 15 MB each).

## Start, stop, reset

```bash
docker compose up --build -d     # start everything (first run: 2-5 min until ClamAV signatures are loaded)
docker compose ps                # all services Up; backend, worker, frontend, db, storage, clamav, mailpit report healthy
docker compose logs -f backend   # follow logs
docker compose down              # stop; keeps all volumes and data
```

Data reset is **destructive**: it deletes all cases, documents, audit history and the generated credentials. Run it only when you intend to start over:

```bash
docker compose down -v
```

## Services

| Service | Image | Purpose | Health |
|---|---|---|---|
| `init-secrets` | `python:3.12-slim` | Generates secrets once into the `secrets` volume, then exits | must exit 0 |
| `db` | `pgvector/pgvector:0.8.1-pg16` | PostgreSQL 16 + pgvector | `pg_isready` |
| `storage` | `chrislusf/seaweedfs:4.48` | S3 object storage with auth and volume encryption | `/healthz` |
| `clamav` | `clamav/clamav:1.5.3` | Malware scanning | image healthcheck |
| `mailpit` | `axllent/mailpit:v1.31.2` | Local mail sink, UI on 8095 | image healthcheck |
| `livekit` | `livekit/livekit-server:v1.13.8` | Video SFU | — |
| `backend` | built from `backend/` | API; runs `app.cli bootstrap` (migrations, grants, packs, seed) before starting | `/api/health/live` |
| `worker` | built from `backend/` | Jobs and sweeps | process |
| `frontend` | built from `frontend/` | nginx: app + proxy, port 8084 | `/healthz` |
| `ollama` | `ollama/ollama:latest` | Optional local model (`--profile ollama`) | — |
| `tests` | built from `backend/` with dev deps | Backend test runner (`--profile test`) | — |

Readiness: `GET http://localhost:8084/api/health/ready` reports database, storage, scanner and worker status.

## Ports (all bound to 127.0.0.1 by default)

| Host port | Service |
|---|---|
| 8084 | Web app and API (`/api`), LiveKit signalling (`/rtc`) |
| 8095 | Mailpit UI |
| 7891/tcp, 50100-50160/udp | LiveKit media |

Backend, database, storage, ClamAV and LiveKit signalling are not published.

## Volumes

`civicbridge_secrets`, `civicbridge_pgdata`, `civicbridge_s3data`, `civicbridge_clamdb`, `civicbridge_demo` (generated demo credentials), `civicbridge_backups`, `civicbridge_ollama`. They survive `docker compose down` and rebuilds.

## Configuration

All settings have working defaults; copy `.env.example` to `.env` only to change them. No secret belongs in `.env`.

| Variable | Default | Meaning |
|---|---|---|
| `CB_PUBLIC_ORIGIN` | `http://localhost:8084` | Origin used in links and emails |
| `CB_ALLOWED_ORIGINS` | `http://localhost:8084,http://127.0.0.1:8084` | Origins accepted by the CSRF Origin check |
| `WEB_BIND_IP` | `127.0.0.1` | Host interface for port 8084 |
| `CB_LIVEKIT_PUBLIC_URL` | `ws://localhost:8084` | LiveKit URL given to browsers |
| `CB_CSP_CONNECT_EXTRA` | `ws://localhost:8084 ws://127.0.0.1:8084` | Extra websocket origins in the CSP |
| `LIVEKIT_NODE_IP`, `LIVEKIT_BIND_IP` | `127.0.0.1` | Media address announced / bound (see [VIDEO_SETUP.md](VIDEO_SETUP.md)) |
| `CB_AI_MODE` | `mock` | `rules`, `mock` or `ollama` |
| `CB_OLLAMA_MODEL` | `llama3.2:3b` | Model name when `ollama` mode is used |
| `CB_COOKIE_SECURE` | `false` | Set `true` behind HTTPS |
| `CB_SEED_DEMO` | `true` | Seed synthetic tenants, accounts and data on first start |

Runtime policies (session timeouts, upload limit, AI mode and budgets, SLA defaults, suppression threshold) can also be changed by a governance administrator in the app; see [OPERATIONS.md](OPERATIONS.md).

## Secrets

`infra/init_secrets.py` creates random values on first start: PostgreSQL admin and app passwords, S3 credentials, LiveKit API secret, application secret key and MFA encryption key. Each consumer gets its own copy with restrictive ownership and mode. Re-running never overwrites existing secrets.

## Optional local model (Ollama)

```bash
docker compose --profile ollama up -d
docker compose exec ollama ollama pull llama3.2:3b     # downloads model weights (~2 GB); your decision
# then set ai_mode to "ollama" in Governance › Policies, or CB_AI_MODE=ollama in .env
```

The default build never downloads model weights. Ollama mode has not been verified in this installation.

## Repeat startup

`app.cli bootstrap` is idempotent: migrations run once, grants are re-applied, packs load only when their checksum changes (a changed pack requires a version bump) and the demo scenario is seeded only into an empty database.
