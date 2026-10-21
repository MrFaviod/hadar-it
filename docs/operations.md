# Infrastructure and identity operations

Run commands from `asset/`. Root Compose references the two independent component checkouts; cloning root alone does not fetch them. Read backend/README.md for API/task payloads and native Python commands. The React/Vue renderer uses real FastAPI login, users, roles and sessions. Other domain data remains prototype-only.

## Configuration without secret files

The human selected documentation of variables instead of creating `.env` / `.env.example`. Commands explicitly disable Compose's implicit `.env` loading. Supply variables via the calling environment or your approved external secret-management mechanism; do not put production credentials in Git, terminal transcripts or example files. URL-encode credentials in database URLs. Container environment is visible to Docker administrators: this is not a secret vault.

| Variable | Default / meaning |
|---|---|
| `ITSM_AUTH_ORIGIN` | Exact browser origin; Compose default http://localhost:18080. Match the browser hostname. |
| `ITSM_AUTH_COOKIE_SECURE` | true; explicitly false only for isolated/local HTTP. Use HTTPS otherwise. |
| `ITSM_BOOTSTRAP_PASSWORD` | External initial password for explicit administrator CLI; no default account. |
| `ITSM_DATABASE_URL` | PostgreSQL SQLAlchemy URL, defaults to local `postgres` with user/database `itsm` and externally supplied `ITSM_POSTGRES_PASSWORD` |
| `ITSM_POSTGRES_PASSWORD` | No built-in password; required for the local PostgreSQL profile |
| `ITSM_TASK_STORAGE` | `sqlite`; alternatives `redis` / `postgres` |
| `ITSM_TASK_SQLITE_PATH` | Compose sets `/data/tasks/huey.db`, separate from `/data/app/itsm.db` |
| `ITSM_TASK_REDIS_URL` | `redis://redis:6379/0`; optional profile or external Redis |
| `ITSM_TASK_POSTGRES_DSN` | Separate Huey PostgreSQL DSN; never infer queue choice from main SQL engine |
| `ITSM_TASK_RETRIES` / `ITSM_TASK_RETRY_DELAY_SECONDS` | `2` / `1`; bounded demo retry policy |
| `ITSM_DEMO_PERIODIC_MINUTES` | `0` disables the periodic demo; 1–60 enables a worker schedule |
| `ITSM_LOG_LEVEL` | `INFO`; structured application/worker logs |
| `ITSM_PROMETHEUS_URL` / `ITSM_MEILISEARCH_URL` / `ITSM_SERVICE_REDIS_URL` | Optional external service descriptors, informational in F1, not readiness dependencies |
| `ITSM_API_PORT` / `ITSM_FRONTEND_PORT` | Loopback `18000` / `18080` |
| `ITSM_PROMETHEUS_PORT` | Loopback `19090` |
| `ITSM_PROMETHEUS_RETENTION` | `7d`; valid Prometheus retention duration |
| `ITSM_MEILI_MASTER_KEY` | Required only for optional search profile, externally supplied; functional integration deferred |

### Local PostgreSQL

Supply `ITSM_POSTGRES_PASSWORD` externally first, then:

```bash
docker compose --env-file /dev/null --profile local-postgres up -d --wait postgres
docker compose --env-file /dev/null build backend frontend
docker compose --env-file /dev/null run --rm migrate
# Supply ITSM_BOOTSTRAP_PASSWORD externally; choose account details:
docker compose --env-file /dev/null run --rm -e ITSM_BOOTSTRAP_PASSWORD backend \
  python -m itsm.identity.cli bootstrap-admin --username YOUR_USERNAME --name 'Your administrator'
# Only for local plain HTTP; production must retain secure cookies with HTTPS:
export ITSM_AUTH_ORIGIN=http://127.0.0.1:18080 ITSM_AUTH_COOKIE_SECURE=false
docker compose --env-file /dev/null up -d --wait backend worker frontend
```

Migrations run explicitly once before API readiness, not concurrently from API/worker entrypoints. Frontend: `http://127.0.0.1:18080`; API OpenAPI: `http://127.0.0.1:18000/docs`. Basic services do not require Redis, Meilisearch or Prometheus.

### External main SQL / persistent SQLite

Provide `ITSM_DATABASE_URL` for the chosen external database; omit `local-postgres`. Example non-secret local SQLite selection:

```bash
export ITSM_DATABASE_URL=sqlite:////data/app/itsm.db
docker compose --env-file /dev/null build backend frontend
docker compose --env-file /dev/null run --rm migrate
# Supply ITSM_BOOTSTRAP_PASSWORD externally; choose account details:
docker compose --env-file /dev/null run --rm -e ITSM_BOOTSTRAP_PASSWORD backend \
  python -m itsm.identity.cli bootstrap-admin --username YOUR_USERNAME --name 'Your administrator'
# Only for local plain HTTP; production must retain secure cookies with HTTPS:
export ITSM_AUTH_ORIGIN=http://127.0.0.1:18080 ITSM_AUTH_COOKIE_SECURE=false
docker compose --env-file /dev/null up -d --wait backend worker frontend
```

SQLite main data persists in `app-data`; task queue/results in `task-data`. These are separate files and volumes. Both backend mounts use lowercase `:z`: API, migration and worker intentionally share their SELinux label. Do not substitute private `:Z` or disable SELinux. A private MCS label can make SQLite fail with `unable to open database file` despite correct UID/mode, depending on which container starts first. Queue SQLite must remain local to one Docker host, shared between API and worker, not NFS or a multi-host cluster. The default worker has one thread/process; scale only after testing queue/storage and business idempotency. Main SQL dialect configuration is not proof of live engine compatibility; consult the backend validation matrix.

### Optional services

```bash
docker compose --env-file /dev/null --profile monitoring up -d prometheus
docker compose --env-file /dev/null --profile redis up -d redis
# Only when ITSM_MEILI_MASTER_KEY is supplied externally:
docker compose --env-file /dev/null --profile search up -d meilisearch
```

Selecting the Redis profile alone does **not** change the queue; set `ITSM_TASK_STORAGE=redis` and its URL, then recreate API/worker intentionally. Likewise PostgreSQL queue uses `ITSM_TASK_STORAGE=postgres` plus its own DSN. Queue tables/storage lifecycle belongs to Huey, separate from main Alembic migrations.

Prometheus retains data in `prometheus-data`, using `deploy/prometheus.yml` and configurable retention. Initial scrape only monitors Prometheus itself; device exporters and ITSM monitoring UI integration are later phases. If using an external Prometheus, omit the local profile; the external instance and its storage/retention are managed by its owner. F1 does not call it or gate readiness on it.

Meilisearch's profile reserves operational infrastructure only; SQL/advanced-search business features are not yet implemented. Casbin now evaluates identity permissions through owned portable SQL policy storage. Apprise/WeasyPrint/Pydantic AI/FastMCP execution integrations remain deferred; no unused server or agent runtime is added.

## Upgrade and rollback

1. Record all three Git revisions, component versions and image digests. Back up main DB and queue before schema/library changes.
2. Review release/security notes, update related pinned dependencies/base image digest, rebuild and run adapter/API/worker/migration tests in isolated state.
3. Test migrations against available SQL engines; do not advertise untested engines as verified. Apply a maintenance window when schema changes are not backward-compatible.
4. Run migrations explicitly, then recreate API/worker together using the tested image. Check readiness and demo task/result.
5. Keep prior image/lock. Reverting the image does not undo an irreversible migration; recover the backup if the migration cannot be safely reversed. Never run `downgrade` or restore into live data without an explicit recovery decision.

Images use exact version tags and registry digests, not `latest`. Dependencies are pinned by the backend lock and frontend package lock. No automatic updater, orchestrator, release pipeline or business microservices are required.

## Backups and recovery

- PostgreSQL: run `pg_dump -Fc` using your approved credentials to a protected destination. Check `pg_restore --list`, then rehearse restoration to a fresh database and run migrations/readiness. External database backups belong to the external operator; local Docker volumes are not backups.
- SQLite main DB: use SQLite's online backup API/`.backup`, not a casual copy of a live WAL database. For a cold file backup, stop the owned API/worker first and include a consistent database/WAL state.
- Huey SQLite: pause this workspace's API enqueue/worker, back up the entire queue volume consistently; restoring it may replay jobs. Future business jobs must be idempotent. Do not restore queue state independently of related business data without considering duplicate effects.
- Optional Redis: persist AOF and back up consistently using Redis procedures. Prometheus: use its supported snapshot/TSDB procedure or a cold backup of its owned volume; restoring metrics is independent of inventory availability.
- Back up root/frontend/backend repositories separately, external settings and named volumes. Never commit backup files or secrets.
- Rehearse recovery in a new isolated Compose project/volumes before replacing production. No backup/restore against existing server services is performed by this phase.

## Checks and inspection

```bash
docker compose --env-file /dev/null config --quiet
curl --fail http://127.0.0.1:18000/api/v1/health/live
curl --fail http://127.0.0.1:18000/api/v1/health/ready
docker compose --env-file /dev/null ps
docker compose --env-file /dev/null logs --tail=100 backend worker
npm --prefix frontend run check
# Opt-in cold-start regression: isolated PostgreSQL projects, both startup orders.
# Creates volumes, stops its containers, does not delete volumes or touch other services.
python3 tests/worker_cold_start.py
# With an isolated, migrated stack and worker running:
# Requires an isolated installed account via ITSM_TEST_USERNAME / ITSM_TEST_PASSWORD.
ITSM_TEST_API_URL=http://127.0.0.1:18000 python3 tests/infrastructure.py
```

Backend tests and integration evidence are documented in backend/README.md and `odd/tasks/phase-1.md`. Demo task submission is development-only, not a public unauthenticated task-execution service. Bind loopback and require a proper authorization boundary before exposing real business data/actions. No automatic schema migration on health checks and no sensitive URL/secret values in logs or errors.

To stop only this stack, use its explicit Compose project and `down` **without `--volumes`**. Persistent-volume deletion, changing existing services and production deployment require separate authorization.
