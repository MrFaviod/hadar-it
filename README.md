# Unnamed ITSM project — pre-alpha

Modular-monolith foundation for small IT teams. The project has no approved product name; “Asset Manager” is the frontend's inherited demo label. Phase 1 supplies infrastructure; Phase 2 adds real identity, sessions and service-level Casbin authorization. Inventory domain APIs and conversational agents remain future work.

## Components

Three independent Git repositories live here; root Git ignores the two components. Clone/back up each independently. No submodules or release pipeline are implied.

| Path | Scope | Internal version |
|---|---|---|
| `frontend/` | Existing React 19/TypeScript host and Vue 3 domain views; now packaged with non-root Nginx | `0.1.0`, pre-alpha |
| `backend/` | FastAPI/Pydantic v2, SQLAlchemy/Alembic, Huey and SQL-backed identity/Casbin | `0.1.0`, pre-alpha |
| root | Compose, architecture/operations docs and cross-component ODD | release `VERSION=0.0.0`, unreleased |

[Architecture amendment](docs/phase-0-amendment-01.md) records selected technologies and deferred adapters. [Operations](docs/operations.md) covers configuration, installation, updates, migration, backup and recovery. [Backend](backend/README.md) describes API/worker/native commands; [frontend](frontend/README.md) retains UI/demo boundaries.

## Start locally

Requires Docker Engine + Compose. Supply `ITSM_POSTGRES_PASSWORD` through your external environment; no `.env` file is created or read by these commands.

```bash
docker compose --env-file /dev/null --profile local-postgres up -d --wait postgres
docker compose --env-file /dev/null build backend frontend
docker compose --env-file /dev/null run --rm migrate
# Supply ITSM_BOOTSTRAP_PASSWORD externally; choose your initial username/name.
docker compose --env-file /dev/null run --rm -e ITSM_BOOTSTRAP_PASSWORD backend \
  python -m itsm.identity.cli bootstrap-admin --username YOUR_USERNAME --name 'Your administrator'
# For this local HTTP URL only (production must use HTTPS and secure cookies):
export ITSM_AUTH_ORIGIN=http://127.0.0.1:18080 ITSM_AUTH_COOKIE_SECURE=false
docker compose --env-file /dev/null up -d --wait backend worker frontend
```

- Frontend: `http://127.0.0.1:18080` (real login/identity screens; other business modules remain prototype data).
- API/OpenAPI: `http://127.0.0.1:18000/docs`.
- API health: `/api/v1/health/live` and `/api/v1/health/ready`.
- Worker: separate process, same backend image, shared persistent local queue volume. Default SQLite queue requires no Redis.
- Local PostgreSQL is optional: set `ITSM_DATABASE_URL` for external SQL and omit its profile. For local persistent SQLite main data use `sqlite:////data/app/itsm.db`; queue is a different file/volume.

Profiles `redis`, `search` and `monitoring` opt into Redis, Meilisearch and Prometheus. None is required to start the base stack. Prometheus retains metrics with configurable retention; an external instance can be used instead. Device exporters, advanced search and business notification/PDF and agent execution integrations are later phases. Agents already use the same authorization service but have no autonomous runtime.

## Verify

```bash
docker compose --env-file /dev/null config --quiet
npm --prefix frontend run check
# Backend environment and test commands: backend/README.md
curl --fail http://127.0.0.1:18000/api/v1/health/ready
```

For development run the API with the exact browser origin and explicit local HTTP cookie override, then `ITSM_DEV_API_URL=http://127.0.0.1:8000 npm --prefix frontend run dev`. Choose an unused API port when needed; never replace an existing host service. A bare Vite production preview has no API proxy: use the Nginx Compose frontend for full login checks.

See `odd/tasks/phase-2.md` and `odd/tasks/phase-1.md` for observed command exits and the tested SQL/queue matrix. Planned engine support is not the same as a verified live server. No production deployment, push, tag or release is performed by local verification.

## Development rules

Follow [AGENTS.md](AGENTS.md) plus the component instructions: ODD, all relevant skills for parent/subagents, simple solutions, related Conventional Commits, independent versions, and different worktrees for simultaneous code-writing subagents. No slogans, invented product claims or speculative infrastructure. Secrets stay outside Git and logs. Docker verification must use isolated project names, ports and volumes rather than modifying existing server stacks.
