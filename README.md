# Unnamed ITSM project — pre-alpha

Modular-monolith foundation for small IT teams. The project has no approved product name; “Asset Manager” is the frontend's inherited demo label. Phase 1 supplies infrastructure; Phase 2 adds real identity, sessions and service-level Casbin authorization. Phase 3 adds the first SQL inventory and shared REST/agent/MCP vertical slice. Phase 4 completes the asset core with configurable forms, atomic identification, lifecycle/history and images in the existing Vue views. Phase 5 adds inventory people and departments, hierarchical locations, assignments and transfers, directed physical/virtual relationships, structured history, bounded maps/graphs and descriptive replica groups (active/passive or configured workload shares such as 40:60). See [Phase 5 verification](docs/phase-5-validation.md) and its [implementation record](odd/tasks/phase-5.md) for executed checks, corrections and explicit limits. [Phase 4 verification](docs/phase-4-validation.md) records the earlier asset-core foundation.

## Phase 6 verified integration

SQL-backed CSV/XLSX import inspection and profiles, conservative duplicate review,
fixed human-approved bulk previews, real CSV export, independent attachments and
individual warranties are connected to the existing Vue interfaces. Long-running
operations use the existing Huey adapter with persisted progress and retry receipts;
REST, Pydantic AI and FastMCP share canonical services.

See the [Phase 6 implementation record](odd/tasks/phase-6.md),
[executed evidence and limits](docs/phase-6-validation.md),
[backend contracts](backend/docs/phase6-workflows.md) and
[incumbent frontend integration](frontend/docs/phase6-workflows.md).
The backend checkpoint is `af4cc27`: 549 tests passed, six gated skips and two known
SQLite warnings. Frontend checks passed Node tests, TypeScript and build;
the fresh-state real browser passed original import/approval/export/bulk/receipt/
warranty/reload flows without overflow at 390 and 1440 px. Frontend checkpoint
`0c7ece0` includes the advisory concurrency correction; its final checks passed
**296** Node tests, TypeScript and build, followed by the real browser pass.
Localized independent reviews and remaining proof limits are recorded in the implementation record.
This remains pre-alpha, not production or external-engine certification.

Compose declares a separate `attachment-data` volume shared by the API and worker.
Attachment SQL metadata and bytes must be backed up together; see
[operations](docs/operations.md#backups-and-recovery).
No deployment or existing-container change is implied by this configuration.

## Phase 10 operational integration

The original Vue NOC Dashboard, MapLibre explorer, relationship graph and Ctrl+K
palette now use canonical authorized services. User workspace state is durable;
installation branding is shared while light/dark/automatic mode stays personal.
Appearance presets export real self-contained ZIPs with staged preview, explicit
application, generic restore and rollback.

SQL search is the default. Optional Meilisearch adds relevance with a durable
outbox, Huey synchronization/retries and rebuild; results are reauthorized from
SQL and engine loss falls back to SQL. It is not a primary data source.

See [Phase 10 implementation](odd/tasks/phase-10.md),
[executed validation and limits](docs/phase-10-validation.md), and
[optional-service configuration](docs/operations.md).

## Phase 11 integration and operational validation

The [Phase 11 evidence and limitations](docs/phase-11-validation.md) distinguishes
executed checks from missing proof. Actual SQLite/PostgreSQL/MariaDB integration,
native recovery, original-interface flows, worker jobs and shared REST/agent/MCP
authorization are checked. SQL Server is preparation-only by user decision because
non-production licenses are unavailable; it remains unvalidated and does not block
Phase 11 closure. Confirmed corrections stay localized:
import transaction occupancy, directory states, warranty queries/refresh and shared
Docker-volume SELinux labeling. This remains pre-alpha, not a production certification.

## Daily AI quotas

Company and personal daily policies, user exceptions and SQL-backed admission
now feed the existing IA configuration and conversation balances. Usage reports
preserve measured/estimated/unavailable evidence; unknown outcomes retain holds.
Managed native runs use a scoped gateway and disposable profiles, but remain
honestly admission-only without verified input bounds and network isolation.
See [executed evidence, known failures and operating prerequisites](docs/ai-usage-quotas-validation.md)
and the [approved feature record](odd/tasks/ai-usage-quotas.md).

## Native application extensions

The versioned SDK supports independent backend operations and durable collections,
explicit migrations, native Vue pages and asset panels, namespaced permissions,
scheduled inbox notices and shared chat/MCP tools. Start with the
[human and agent SDK guide](backend/docs/extensions-sdk.md), the
[native frontend contract](frontend/docs/extensions-sdk.md) and the
[host lifecycle and trust boundary](backend/docs/extensions-host.md).

Packages are validated offline before a persisted human Superadmin reviews the
exact digest and approves installation. Installed Python and same-origin Vue are
trusted native code, **not a hostile-code sandbox**. The
[executed evidence and remaining proof](docs/native-extension-sdk-validation.md)
distinguish SDK implementation from the still-pending full
[software-license experiment](docs/software-license-extension-experiment.md).

## Components

Three independent Git repositories live here; root Git ignores the two components. Clone/back up each independently. No submodules or release pipeline are implied.

| Path | Scope | Internal version |
|---|---|---|
| `frontend/` | Existing React 19/TypeScript host and Vue 3 domain views; now packaged with non-root Nginx | `0.1.0`, pre-alpha |
| `backend/` | FastAPI/Pydantic v2, SQLAlchemy/Alembic, Huey and SQL-backed identity/Casbin | `0.1.0`, pre-alpha |
| root | Compose, architecture/operations docs and cross-component ODD | release `VERSION=0.0.0`, unreleased |

[Architecture amendment](docs/phase-0-amendment-01.md) records selected technologies and deferred adapters. [Operations](docs/operations.md) covers configuration, installation, updates, migration, backup and recovery. [Backend](backend/README.md) describes API/worker/native commands; [frontend](frontend/README.md) retains UI/demo boundaries.

## Start locally

Persistent SQLite needs no separate database service. Local PostgreSQL and externally
managed SQL are alternative installation modes; consult the current Phase 11 matrix
before selecting an engine. Requires Docker Engine + Compose and an operator-reserved
per-installation `ITSM_SELINUX_LEVEL`, exported before the commands below; see
[shared-volume security](docs/operations.md#reserve-the-shared-volume-selinux-domain).
No `.env` file is created or read.

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

- Frontend: `http://127.0.0.1:18080`; implemented domains use authenticated canonical services. Explicitly labeled future/demo integrations are not functional claims.
- API/OpenAPI: `http://127.0.0.1:18000/docs`.
- API health: `/api/v1/health/live` and `/api/v1/health/ready`.
- Worker: separate process, same backend image, shared persistent local queue volume. Default SQLite queue requires no Redis.
- Local PostgreSQL is optional: set `ITSM_DATABASE_URL` for external SQL and omit its profile. For local persistent SQLite main data use `sqlite:////data/app/itsm.db`; queue is a different file/volume.

Profiles `redis`, `search` and `monitoring` opt into Redis, Meilisearch and Prometheus.
None is required for basic inventory or SQL search. Monitoring uses the existing
Prometheus adapter. Pydantic AI and FastMCP reuse canonical services and effective
identity permissions; no multiagent orchestrator is introduced.

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

See [Phase 11](docs/phase-11-validation.md) for the current executed SQL/queue matrix and operational limits; earlier phase records remain historical evidence. Planned engine support is not a verified live server. No production deployment, push, tag or release is performed by local verification.

## Development rules

Follow [AGENTS.md](AGENTS.md) plus the component instructions: ODD, all relevant skills for parent/subagents, simple solutions, related Conventional Commits, independent versions, and different worktrees for simultaneous code-writing subagents. No slogans, invented product claims or speculative infrastructure. Secrets stay outside Git and logs. Docker verification must use isolated project names, ports and volumes rather than modifying existing server stacks.
