# Technical guide

[Project overview](../README.md) · [Install the whole application](../INSTALL.md) · [All documentation](README.md)

How Hadar IT is built, what each capability needs before it works, and where to go next for operations and development. It is a map, not an installation checklist: to get a running instance, use the [installation guide](../INSTALL.md).

Hadar IT is **alpha**. Configuration support and isolated tests do not certify a production deployment.

## How the pieces fit

```text
Browser UI ───────┐
                 │
Pydantic AI ──────┼── Authorized domain services ── SQL + attachment storage
                 │              │
MCP clients ──────┘              └── Huey worker: queued work
```

The browser, built-in agent and MCP call the same domain services. Identity and permissions are enforced on the server, not inferred from a prompt or a hidden UI control. Personal API keys have an issuance ceiling and remain limited by their creator's current permissions; MCP revalidates its bearer on each operation.

### Repository ownership

| Repository | Responsibility | Version |
|---|---|---|
| [hadar-it](https://github.com/MrFaviod/hadar-it) | Compose, deployment modes, installation and shared documentation | `0.0.0`, unreleased |
| [hadar-it-frontend](https://github.com/MrFaviod/hadar-it-frontend) | Browser application, design system, frontend tests | `0.1.0` |
| [hadar-it-backend](https://github.com/MrFaviod/hadar-it-backend) | API, services, persistence, worker, agents and extension host | `0.1.0` |

The root ignores the two component directories. They are independent repositories, not submodules. The installation guide clones all three into one workspace. Record all three revisions when investigating an issue or preparing an upgrade; a root commit does not include component changes.

## Stack

| Layer | Implementation |
|---|---|
| Browser | React 19 + TypeScript + Vite 6 host; locally vendored Vue 3 renders domain views. No runtime OpenDesign dependency or iframe for the main application. |
| API and services | Python 3.14+, FastAPI, Pydantic v2, SQLAlchemy 2 and Alembic |
| Identity | Argon2id passwords, server-side sessions, Casbin policies, audit and personal API keys |
| Background work | Huey; SQLite queue by default, separately configurable Redis or PostgreSQL queue |
| Agents | Pydantic AI; operator-installed Hermes Agent and OpenCode connectors; Streamable HTTP FastMCP |
| Optional services | Prometheus/exporters, Alertmanager and Meilisearch |
| Deployment | Docker Compose; Nginx serves the frontend and proxies the API |

PostgreSQL is the default application database; the local walkthrough deliberately uses SQLite. The application targets PostgreSQL, SQLite and MariaDB. SQL Server configuration is preparation-only, **not validated compatibility**. See the [database matrix](backend/foundation.md).

## Deployment modes

| Mode | Overlay | Data and access |
|---|---|---|
| `dev` | `deploy/compose.dev.yaml` | Local SQLite, fictional data, explicit `dev.admin` password, loopback HTTP |
| `prod` | `deploy/compose.prod.yaml` | Explicit database and HTTPS origin; no seeded accounts; guarded upgrades |
| `demo` | `deploy/compose.demo.yaml` | Shared fictional data, `admin/admin`, periodic reset, integrations disabled |

`RELEASE_MODE` is mandatory. The default project names are `itsm-dev`, `itsm-prod` and `itsm-demo`; the installation walkthrough explicitly uses `hadar-local`. Separate installations need distinct project names, ports and reserved SELinux MCS levels.

Every startup depends on `initialize`, which runs `python -m itsm.deployment prepare` before the API and worker. Do not bypass this gate or use the manual `migrate` service as a replacement installer. In `prod`, create the first owner explicitly with `bootstrap-superadmin` after preparation; it is not a default account.

The application reads process environment variables, not `.env` directly. The installation guide uses the checked-in `.env.example` to create a private Compose `.env`; the alternative operations commands use exported variables with `--env-file /dev/null`. Never commit the private file or put credentials in clone URLs. For all variables, TLS, storage labels and upgrade ordering, use [operations](operations.md) and the [mode reference](release-modes-deployment.md).

## What needs configuration

| Capability | Required setup |
|---|---|
| Inventory, directory, dashboard, maintenance and SQL search | The basic installed stack and an authorized account |
| Reports and queued workflows | A running Huey consumer and shared persistent storage |
| AI conversation | Configured provider/model, credentials and the selected runtime's prerequisites. Ordinary User inference needs the separate runtime broker. |
| Hermes / OpenCode | Separately installed host services, reachable authenticated endpoints, restricted profiles, MCP identity and verification |
| Live monitoring | Prometheus or the chosen monitoring engine, real targets/exporters and dedicated tokens where required |
| External notifications | Configured destinations and externally supplied secret references; queued is not delivered |
| Meilisearch | Optional engine and credentials; SQL stays authoritative and provides fallback |
| Extension validation and installation | SDK v2 package, host prerequisites, configured validator and explicit human Superadmin approval |

A healthy API does not prove that a worker completed a job, a provider answered or an external notification arrived. Missing telemetry is not device downtime. Descriptive redundancy groups do not perform load balancing, replication or failover.

## Extension SDK v2

Extensions can add data collections, pages, panels and agent tools. Declarative modules ship no executable code; executable SDK v2 modules use a restricted runner process and isolated frontend rendering. The lifecycle binds validation and human approval to the exact package digest. An agent can prepare a candidate, not approve its own installation.

Host/kernel prerequisites and validator availability matter; “sandboxed” is not a guarantee against every hostile package or host configuration.

- [Agent engine prerequisites](backend/agent-integrations.md)
- [SDK quickstart and tools](backend/extensions-sdk.md)
- [Host, lifecycle and runtime boundaries](backend/extensions-host.md)
- [Frontend extension contract](frontend/extensions-sdk.md)

## Development and verification

From the complete workspace:

```bash
npm --prefix frontend ci
npm --prefix frontend run check
python3 tests/prealpha_docs.py
```

Backend development needs its own Python 3.14 environment and pinned requirements. Run these from `backend/`, after installing its development dependencies:

```bash
.venv/bin/python -m pytest
.venv/bin/python -m ruff check itsm tests migrations
.venv/bin/python -m ruff format --check itsm tests migrations
```

Component setup and test prerequisites: [frontend development](frontend/development.md) and [backend development](backend/development.md). Browser checks need Playwright/Chromium and isolated accounts; live engine checks need disposable services. Never target an existing business database with tests or migrations.

## Roadmap

**Work in progress, not shipped promises:** fewer dependencies and backend optimization; Windows/Linux monitoring nodes; ticketing with a small endpoint interface; Tactical RMM, AnyDesk and Zammad integrations; SSO; agent-authored extensions; and a mobile app for notifications, alerts and QR workflows. Configurable remote-access links do not establish working remote-control integrations.

## Identity and licensing

**Hadar IT** is the current product name, with the tagline **Bring your own department.** The visible installation name is configurable in **Settings → Appearance**; changing that name does not require renaming packages, database objects or storage paths. Preserve installation-specific names.

The root project is distributed under [MIT](../LICENSE). Backend packaging still declares `LicenseRef-Proprietary`; that metadata discrepancy must be resolved before a release. Documentation does not change licensing metadata.
