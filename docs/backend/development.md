# Backend development

[Back to the README](../../README.md) · [Install the full application](https://github.com/MrFaviod/hadar-it/blob/master/INSTALL.md) · [Root technical guide](https://github.com/MrFaviod/hadar-it/blob/master/docs/technical-guide.md)

Use Docker and the central guide for your first run. This page is the shorter route for developers working on Python services. Hadar is alpha, not production-certified.

## Install dependencies

From the `backend/` repository, with **Python 3.14+**:

```bash
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt -r requirements-dev.txt
```

The checked-in requirements files pin the development environment. Installing them does not create accounts or initialize the database. Native development also needs the platform libraries used by WeasyPrint (Pango, font support and HarfBuzz); the backend Dockerfile records the Debian packages and Docker supplies them for the central installation. If the native dependencies are unavailable, use Docker rather than treating a successful pip install as a working runtime.

## Start an isolated local workspace

Use a **new local development directory**, never a real installation's storage. In the same Bash shell:

```bash
export RELEASE_MODE=dev
export ITSM_DEV_DATA_DIR="$HOME/.local/share/hadar-it/dev"
export ITSM_DATABASE_URL="sqlite:///$ITSM_DEV_DATA_DIR/dev.db"
export ITSM_ATTACHMENT_STORAGE_PATH="$ITSM_DEV_DATA_DIR/attachments"
export ITSM_TASK_STORAGE=sqlite
export ITSM_TASK_SQLITE_PATH="$ITSM_DEV_DATA_DIR/tasks/huey.db"
export ITSM_AUTH_ORIGIN=http://127.0.0.1:5173
export ITSM_AUTH_COOKIE_SECURE=false
read -rsp 'New dev administrator password: ' ITSM_DEV_ADMIN_PASSWORD
printf '\n'
export ITSM_DEV_ADMIN_PASSWORD
mkdir -p "$ITSM_DEV_DATA_DIR"
.venv/bin/python -m itsm.devtools init --username dev.admin
.venv/bin/python -m itsm.devtools status
.venv/bin/python -m itsm.main --host 127.0.0.1 --port 8000
```

Use a password of 12–128 characters. It is entered without echo or shell-history exposure. The seeded account is `dev.admin`, not the demo's `admin/admin`. A second `init` is idempotent and does not change the existing password. The data directory above stays outside the repository; use a different empty directory for each independent installation. The origin above matches the frontend's local Vite server; change it when the browser URL changes. Insecure cookies are for loopback HTTP only.

Start the worker in a second terminal with the **same storage and mode exports**:

```bash
.venv/bin/python -m huey.bin.huey_consumer itsm.tasks.runtime.huey -w 1 -k thread
```

The API does not apply migrations on startup. Development initialization applies them explicitly; deployment uses `python -m itsm.deployment prepare`. Do not substitute the manual migration helper for the deployment preparation gate. Reset commands are destructive and have additional safeguards; read [development database operations](dev-mode.md) before using them.

## Configuration and health

Settings come from process environment variables; the application does not load `.env`. Keep database passwords, provider credentials and destination secrets outside Git, screenshots and issue reports.

| Setting | Meaning |
|---|---|
| `RELEASE_MODE` | Mandatory `dev`, `prod` or `demo`; separate installation identities |
| `ITSM_DATABASE_URL` | Canonical SQL database; PostgreSQL default, isolated SQLite for this walkthrough |
| `ITSM_ATTACHMENT_STORAGE_PATH` | Persistent attachment bytes, independent of the SQL database |
| `ITSM_TASK_STORAGE` | Queue backend: SQLite, Redis or PostgreSQL |
| `ITSM_TASK_SQLITE_PATH` | Persistent queue file; must differ from the application database |
| `ITSM_AUTH_ORIGIN` | Exact browser origin for session/CSRF checks |
| `ITSM_AUTH_COOKIE_SECURE` | Keep true except explicit loopback HTTP development |
| `ITSM_AGENT_MODEL` | Configured model; leaving it unset is not a working AI setup |

This is an orientation table, not the full settings schema. See `itsm/config.py` and the topic contracts below for current defaults and validation. Provider credentials use the provider SDK environment; do not send them in browser requests. Regular User inference also requires the separate host runtime broker described in [AI isolation](ai-runtime-isolation.md).

With the API running:

```bash
curl --fail http://127.0.0.1:8000/api/v1/health/live
curl --fail http://127.0.0.1:8000/api/v1/health/ready
```

OpenAPI is at <http://127.0.0.1:8000/docs>. Readiness checks required application dependencies, not successful job execution or every optional integration. Verify worker-backed work by observing a completed job, not merely an HTTP `202`.

## Identity and service boundaries

REST, Pydantic AI and MCP call the same canonical services. Authorization is enforced in services, not just routes or the browser. Cookie-authenticated mutations require the configured Origin and CSRF token. Personal API keys have issuance ceilings intersected with the creator's current permissions; MCP revalidates bearer access for each operation.

Production creates no default account. Its `initialize` phase precedes `bootstrap-superadmin`; follow the [operations guide](https://github.com/MrFaviod/hadar-it/blob/master/docs/operations.md) rather than reusing development seed commands. Public demo data and its credentials belong only to the separate demo mode.

## Topic map

- **Data:** [inventory](inventory.md), [catalog](inventory-catalog.md), [directory](directory.md), [relationships](relationships.md), [redundancy](redundancy.md), [attachments](attachments.md).
- **Operations:** [maintenance](maintenance.md), [interventions](interventions.md), [monitoring](monitoring.md), [notifications](notifications.md), [reports](reports.md), [rendering](report-rendering.md).
- **Access:** [identity](identity.md), [personal keys](personal-api-keys.md).
- **Agents:** [tools](agent-tools.md), [integrations](agent-integrations.md), [runtime isolation](ai-runtime-isolation.md), [engine verification](engine-profile-verification.md).
- **Extensions:** [SDK](extensions-sdk.md), [current SDK v2 host and restricted runner](extensions-host.md). Executable Python is not loaded into the API or worker; missing sandbox support fails closed. A human Superadmin approves the exact module digest.
- **Deployment:** [preparation](deployment-preparation.md), [modes](release-modes.md), [development](dev-mode.md), [demo](demo-public.md), [backup/restore](ops-backup-restore.md).

Earlier phase documents are historical context. Current code and the dedicated contracts take precedence when those pages disagree. The root project and the backend package are both MIT-licensed; this documentation change does not alter licenses.
