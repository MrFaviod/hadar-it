# Unnamed ITSM project — pre-alpha

Modular-monolith foundation for small IT teams. The project has no approved product name; “Asset Manager” is the frontend's inherited demo label. Phase 1 supplies infrastructure; Phase 2 adds real identity, sessions and service-level Casbin authorization. Phase 3 adds the first SQL inventory and shared REST/agent/MCP vertical slice. Phase 4 completes the asset core with configurable forms, atomic identification, lifecycle/history and images in the existing Vue views. Phase 5 adds inventory people and departments, hierarchical locations, assignments and transfers, directed physical/virtual relationships, structured history, bounded maps/graphs and descriptive replica groups (active/passive or configured workload shares such as 40:60). See [Phase 5 verification](docs/phase-5-validation.md) for executed checks, corrections and explicit limits. [Phase 4 verification](docs/phase-4-validation.md) records the earlier asset-core foundation.

## Phase 6 verified integration

SQL-backed CSV/XLSX import inspection and profiles, conservative duplicate review,
fixed human-approved bulk previews, real CSV export, independent attachments and
individual warranties are connected to the existing Vue interfaces. Long-running
operations use the existing Huey adapter with persisted progress and retry receipts;
REST, Pydantic AI and FastMCP share canonical services.

See [executed evidence and limits](docs/phase-6-validation.md),
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

See [executed validation and limits](docs/phase-10-validation.md) and
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
See [executed evidence, known failures and operating prerequisites](docs/ai-usage-quotas-validation.md).

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

One codebase runs in one of three release modes. The mode is part of the Compose project
name, so `dev`, `prod` and `demo` never share containers, networks or volumes, and every
application process refuses to start without it. Requires Docker Engine + Compose and an
operator-reserved per-installation `ITSM_SELINUX_LEVEL`; see
[shared-volume security](docs/operations.md#reserve-the-shared-volume-selinux-domain).
No `.env` file is created or read: variables come from the process environment.

| Mode | Intended use | First owner |
|---|---|---|
| `dev` | trying the product on one machine; fictional data, loopback HTTP | `dev.admin`, created by preparation from `ITSM_DEV_ADMIN_PASSWORD` |
| `prod` | a real installation; empty database, guarded upgrade before migrations, scheduled backups | you create it explicitly with `bootstrap-superadmin` |
| `demo` | a public fictional demonstration with an hourly in-process reset | public `admin`/`admin`, isolated by design |

Each mode is a Compose overlay on `compose.yaml`: `deploy/compose.dev.yaml`,
`deploy/compose.prod.yaml`, `deploy/compose.demo.yaml`. Full wiring, per-mode variables,
the TLS entrypoint and the unproven parts are in
[release-mode deployment](docs/release-modes-deployment.md).

### Local trial: `dev`

Persistent SQLite needs no separate database service; preparation migrates, claims the
database for `dev`, creates `dev.admin` and seeds the fictional dataset. Loopback HTTP
only, with cookies deliberately not `Secure`.

```bash
export RELEASE_MODE=dev
export ITSM_SELINUX_LEVEL=s0:c500,c501      # reserve your own unused categories
export ITSM_DEV_ADMIN_PASSWORD='<local dev password>'
docker compose --env-file /dev/null -f compose.yaml -f deploy/compose.dev.yaml up -d
```

- Frontend: `http://127.0.0.1:18080`; implemented domains use authenticated canonical services. Explicitly labeled future/demo integrations are not functional claims.
- API/OpenAPI: `http://127.0.0.1:18000/docs`.
- API health: `/api/v1/health/live` and `/api/v1/health/ready`.
- Worker: separate process, same backend image, shared persistent local queue volume. Default SQLite queue requires no Redis.
- `initialize` is the preparation gate (`python -m itsm.deployment prepare`). `backend` and `worker` wait for it, and a failed preparation stops the project instead of serving unprepared data. The `migrate` service stays a manual `tools`-profile command, not an installation step.
- Local PostgreSQL is optional: set `ITSM_DATABASE_URL` for external SQL and omit its profile. For local persistent SQLite main data use `sqlite:////data/app/itsm.db`; queue is a different file/volume.

### Production first installation: `prod`

`prod` requires an explicit database URL and the exact browser origin; cookies stay
`Secure`, so a real installation needs HTTPS. Set `ITSM_AUTH_ORIGIN=https://…` and, for a
public host, serve it through the `tls` profile or your own TLS proxy (section 7 of the
mode document). The production `initialize` image is `itsm-ops:0.1.0`, built from
`itsm-backend:0.1.0` for the guarded upgrade and its verified backup, so build `backend`
first.

```bash
export RELEASE_MODE=prod
export ITSM_SELINUX_LEVEL=<reserved MCS level>
export ITSM_DATABASE_URL='postgresql+psycopg://itsm:<password>@<host>:5432/itsm'
export ITSM_AUTH_ORIGIN=https://itsm.example.com
docker compose --env-file /dev/null -f compose.yaml -f deploy/compose.prod.yaml build backend frontend
docker compose --env-file /dev/null -f compose.yaml -f deploy/compose.prod.yaml build initialize
docker compose --env-file /dev/null -f compose.yaml -f deploy/compose.prod.yaml up -d
# After `initialize` reports success, create the installation's first Superadmin.
# Supply ITSM_BOOTSTRAP_PASSWORD externally; choose the account details.
docker compose --env-file /dev/null -f compose.yaml -f deploy/compose.prod.yaml \
  run --rm -e ITSM_BOOTSTRAP_PASSWORD backend \
  python -m itsm.identity.cli bootstrap-superadmin --username YOUR_USERNAME --name 'Your installation owner'
```

Scheduled backups are the separate `backup` profile (`RELEASE_MODE=prod` is enforced by
the command itself). Production keeps its data when preparation fails; see
[upgrade and backup limits](docs/release-modes-deployment.md#6-production-upgrade-and-backups).

### Public demonstration: `demo`

```bash
export RELEASE_MODE=demo
export ITSM_SELINUX_LEVEL=<reserved MCS level>
export ITSM_AUTH_ORIGIN=https://demo.example.com
docker compose --env-file /dev/null -f compose.yaml -f deploy/compose.demo.yaml --profile tls up -d
```

The demonstration seeds its own fictional dataset plus the public `admin`/`admin` visitor,
blanks inherited provider/executor/search credentials and resets itself every 60 minutes
in-process. Publish it only through TLS with `ITSM_AUTH_ORIGIN` set to that exact public
origin; see [demo public surfaces](backend/docs/demo-public.md).

Profiles `redis`, `search` and `monitoring` opt into Redis, Meilisearch and Prometheus.
None is required for basic inventory or SQL search. Monitoring uses the existing
Prometheus adapter. Pydantic AI and FastMCP reuse canonical services and effective
identity permissions; no multiagent orchestrator is introduced.

The conversation route uses a server-configured model, not browser API keys. Without
`ITSM_AGENT_MODEL` and its provider credentials, the UI reports agent unavailability;
SQL inventory remains functional. Deterministic agent tests use simulated inference,
not a production demo chatbot. Configuration and MCP connection instructions are in
[operations](docs/operations.md).

Agent engines run outside the application containers: Pydantic AI is the in-process
default for ordinary users, while OpenCode and Hermes are operator-installed host
services reached through a restricted listener; the extension validator is a separate
fixed broker image. Prerequisites, credentials and trust boundaries:
[agent integrations](backend/docs/agent-integrations.md),
[agent tools](backend/docs/agent-tools.md),
[extension SDK guide](backend/docs/extensions-sdk.md) and
[fixed validation broker](docs/operations.md#fixed-validation-broker). None of them is
required for inventory, SQL search or readiness.

## Verify

```bash
# Every mode renders its own project; substitute the overlay you installed.
RELEASE_MODE=dev ITSM_SELINUX_LEVEL=s0:c500,c501 ITSM_DEV_ADMIN_PASSWORD=test-only \
  docker compose --env-file /dev/null -f compose.yaml -f deploy/compose.dev.yaml config --quiet
RELEASE_MODE=prod ITSM_SELINUX_LEVEL=s0:c500,c501 \
  ITSM_DATABASE_URL=postgresql+psycopg://itsm:test-only@localhost:5432/itsm \
  ITSM_AUTH_ORIGIN=https://itsm.test.invalid \
  docker compose --env-file /dev/null -f compose.yaml -f deploy/compose.prod.yaml config --quiet
RELEASE_MODE=demo ITSM_SELINUX_LEVEL=s0:c500,c501 ITSM_AUTH_ORIGIN=https://demo.test.invalid \
  docker compose --env-file /dev/null -f compose.yaml -f deploy/compose.demo.yaml config --quiet
# A bare command must fail: the mode is mandatory.
docker compose --env-file /dev/null config --quiet
npm --prefix frontend run check
# Backend environment and test commands: backend/README.md
curl --fail http://127.0.0.1:18000/api/v1/health/ready
python3 tests/prealpha_docs.py   # documented commands and ES/EN command parity
```

For development run the API with the exact browser origin and explicit local HTTP cookie override, then `ITSM_DEV_API_URL=http://127.0.0.1:8000 npm --prefix frontend run dev`. Choose an unused API port when needed; never replace an existing host service. A bare Vite production preview has no API proxy: use the Nginx Compose frontend for full login checks.

See [Phase 11](docs/phase-11-validation.md) for the current executed SQL/queue matrix and operational limits; earlier phase records remain historical evidence. Planned engine support is not a verified live server. No production deployment, push, tag or release is performed by local verification.

## Development rules

Contributor and agent workflow instructions are kept locally and are not part of the published repository. In short: ODD, all relevant skills for parent/subagents, simple solutions, related Conventional Commits, independent versions, and different worktrees for simultaneous code-writing subagents. No slogans, invented product claims or speculative infrastructure. Secrets stay outside Git and logs. Docker verification must use isolated project names, ports and volumes rather than modifying existing server stacks.
