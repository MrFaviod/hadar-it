# Unnamed ITSM project — pre-alpha

Modular-monolith foundation for small IT teams. The project has no approved product name; “Asset Manager” is the frontend's inherited demo label. Phase 1 supplies infrastructure; Phase 2 adds real identity, sessions and service-level Casbin authorization. Phase 3 adds the first SQL inventory and shared REST/agent/MCP vertical slice. Phase 4 completes the asset core with configurable forms, atomic identification, lifecycle/history and images in the existing Vue views. See [Phase 4 verification](docs/phase-4-validation.md) for executed checks and explicit limits, and its [implementation record](odd/tasks/phase-4.md) for requirements and work units.

## Components

Three independent Git repositories live here; root Git ignores the two components. Clone/back up each independently. No submodules or release pipeline are implied.

| Path | Scope | Internal version |
|---|---|---|
| `frontend/` | Existing React 19/TypeScript host and Vue 3 domain views; now packaged with non-root Nginx | `0.1.0`, pre-alpha |
| `backend/` | FastAPI/Pydantic v2, SQLAlchemy/Alembic, Huey and SQL-backed identity/Casbin | `0.1.0`, pre-alpha |
| root | Compose, architecture/operations docs and cross-component ODD | release `VERSION=0.0.0`, unreleased |

[Architecture amendment](docs/phase-0-amendment-01.md) records selected technologies and deferred adapters. [Operations](docs/operations.md) covers configuration, installation, updates, migration, backup and recovery. [Backend](backend/README.md) describes API/worker/native commands; [frontend](frontend/README.md) retains UI/demo boundaries.

## Start locally

The implemented inventory prioritizes verification against the integrated local database, not external SQL engines. Use persistent
SQLite with the existing named volume; optional local PostgreSQL remains available but is
not required. Requires Docker Engine + Compose; no `.env` file is created or read.

```bash
export ITSM_DATABASE_URL=sqlite:////data/app/itsm.db
docker compose --env-file /dev/null build backend frontend
docker compose --env-file /dev/null run --rm migrate
# Supply ITSM_BOOTSTRAP_PASSWORD externally; choose your initial username/name.
docker compose --env-file /dev/null run --rm -e ITSM_BOOTSTRAP_PASSWORD backend \
  python -m itsm.identity.cli bootstrap-admin --username YOUR_USERNAME --name 'Your administrator'
# For this local HTTP URL only (production must use HTTPS and secure cookies):
export ITSM_AUTH_ORIGIN=http://127.0.0.1:18080 ITSM_AUTH_COOKIE_SECURE=false
docker compose --env-file /dev/null up -d --wait backend worker frontend
```

- Frontend: `http://127.0.0.1:18080` (identity and asset core; unimplemented business modules remain prototypes).
- API/OpenAPI: `http://127.0.0.1:18000/docs`.
- API health: `/api/v1/health/live` and `/api/v1/health/ready`.
- Worker: separate process, same backend image, shared persistent local queue volume. Default SQLite queue requires no Redis.
- Local PostgreSQL is optional: set `ITSM_DATABASE_URL` for external SQL and omit its profile. For local persistent SQLite main data use `sqlite:////data/app/itsm.db`; queue is a different file/volume.

Profiles `redis`, `search` and `monitoring` opt into Redis, Meilisearch and Prometheus. None
is required for basic inventory/search. Device exporters, advanced search, notifications
and PDF remain later phases. The integrated Pydantic AI agent and selected FastMCP tools
reuse the inventory service and F2 identities; no multiagent orchestrator is introduced.

The conversation route uses a server-configured model, not browser API keys. Without
`ITSM_AGENT_MODEL` and its provider credentials, the UI reports agent unavailability;
SQL inventory remains functional. Deterministic agent tests use simulated inference,
not a production demo chatbot. Configuration and MCP connection instructions are in
[operations](docs/operations.md).

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
