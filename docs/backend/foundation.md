# Foundation design and validation status

Phase 1 backend infrastructure. This document records what is implemented,
what is validated and what remains pending; it is not a roadmap for business
features.

## Package layout

```
itsm/
  config.py       # Pydantic Settings (ITSM_ env prefix, validation, redaction)
  database.py     # engine/session, portable probe, Alembic + readiness state
  logging.py      # JSON formatter, structured events, secret sanitization
  main.py         # FastAPI app factory, versioned API, error envelope, health
  tasks/
    adapter.py    # internal TaskQueue protocol: states, submission, peek reads
    runtime.py    # Huey construction, demo tasks, signals, execution logging
    cli.py        # bounded demo submission/status diagnostics
migrations/       # Alembic environment and revisions
```

Huey types exist only inside `itsm/tasks`. Future business code consumes the
`TaskQueue` protocol; replacing the execution backend must not touch business
modules. The same is intended for future external adapters (notifications,
authorization, PDF, search): they stay behind internal interfaces.

## Database access

- PostgreSQL is the default (`postgresql+psycopg`). SQLite is supported with a
  persistent local file. MariaDB (`mysql+pymysql`) is configurable.
- Microsoft SQL Server (`mssql+pyodbc`) is flagged as an extra and remains
  pending: no OS ODBC driver is installed on the development host, so it has
  not been executed.
- Queries and probes stay portable (`SELECT 1`, inspector-based table checks);
  Alembic uses batch mode for SQLite schema changes.
- The readiness probe reports the migration head as pending until the explicit
  `alembic upgrade head` command runs; application startup never migrates and
  never races replicas.
- The initial migration creates one infrastructure table only
  (`itsm_infrastructure`, a key/value with `updated_at`). No inventory or
  business tables exist in this phase.

### Validation matrix

| Engine | Role | Status |
|---|---|---|
| PostgreSQL 16.13 | Main DB, migrations, readiness | Validated live on an isolated instance |
| SQLite | Main DB and default queue file | Validated by the default test suite |
| MariaDB 10.11.19 (`mysql+pymysql`) | Main DB, migrations, readiness | Validated live on an isolated instance |
| Microsoft SQL Server (`mssql+pyodbc`) | Main DB | Driver extra only, **not validated**; no ODBC driver available |
| PostgreSQL-backed Huey | Queue | Validated live on an isolated instance |
| Redis-backed Huey | Queue | Validated live on an isolated instance |
| SQLite-backed Huey | Queue (default) | Validated by the default test suite |

Passing SQLite tests is not evidence for another engine. Each row must be
verified against its own disposable instance before it is documented as
supported.

## Task execution

- Queue storage is independent of the main database. The default is a
  persistent SQLite file (`/data/tasks/huey.db`); Redis and PostgreSQL are
  selectable through configuration.
- The worker runs as its own process and imports `itsm.tasks.runtime`, whose
  consumer instance is created lazily so the API process never opens queue
  storage just by importing the module. `itsm.main` exposes the module-level
  `app` object that `uvicorn itsm.main:app` and the container expect.
- The SQLite queue directory is created on demand before the queue opens; an
  unusable storage location yields `503 unavailable` on submission and a
  degraded readiness check instead of an unhandled error.
- The adapter stores state markers in the queue result storage before
  enqueueing, the worker overwrites `running` on execution, and reads use
  Huey's preserving peek. A `GET` never consumes the stored result.
- Failures are surfaced with bounded retry metadata; error text is sanitized and
  tracebacks stay server-side in logs.
- `POST /tasks/demo` accepts only a bounded message and an optional bounded
  delay, and requires `assets.view`. There is no endpoint or CLI flag that names
  a function or task to run. Public task reads require `assets.view` and a durable
  owner match, or current unscoped human administration. Personal keys have no
  ambient administrator visibility. Ownerless CLI/periodic queue locators are not
  exposed by the HTTP task endpoint.
- The periodic demo tick is opt-in (`ITSM_DEMO_PERIODIC_MINUTES`) and uses
  Huey cron, so its granularity is one minute; it is disabled by default. It is
  covered by registration tests, not by a one-minute wall-clock test.
- Scheduled (delayed) tasks persist in the queue storage and execute after a
  worker restart; this is covered by an automated test.

## Optional services

Redis is implemented as an optional Huey queue backend and validated live.
Optional SQL/task drivers and service profiles remain explicit choices rather than
mandatory infrastructure. Device monitoring and notifications use their implemented
internal adapters; Pydantic AI and FastMCP reuse canonical authorized services. Phase 9
adds WeasyPrint PDF rendering, Segno QR codes and existing openpyxl Excel generation in
the API/worker image, with native Pango/HarfBuzz libraries and DejaVu fonts. Generated
documents share opaque blob storage with attachments, not public static files. Advanced
search remains deferred. See `report-rendering.md` and `reports.md` for the document
security and persistence contracts.

## Docker deployment contract

The backend Dockerfile belongs to this component repository; Compose belongs
to the workspace root repository. This component exposes their shared contract:

- image source root: `backend/`;
- install: `pip install -r requirements.txt` (tests additionally use
  `requirements-dev.txt`);
- start API: `uvicorn itsm.main:app --host 0.0.0.0 --port 8000`;
- start worker: `python -m huey.bin.huey_consumer itsm.tasks.runtime.huey -w 1 -k thread`;
  Huey 3.4.0 also installs `huey_consumer`, not the old `.py` console script;
- migrate explicitly before starting replicas: `alembic upgrade head`;
- persistent paths: `/data/app/` for a SQLite main DB, `/data/tasks/` for the
  shared queue file; both must be writable by the runtime user;
- readiness: `/api/v1/health/ready` (use for orchestration), liveness:
  `/api/v1/health/live`;
- environment: only `ITSM_*` variables; secrets injected by the orchestrator.
  No `.env` file is read.

Bind published ports to loopback by default. Local PostgreSQL can be omitted
when an external database URL is configured.

## Known gaps

- Microsoft SQL Server main-database support is unverified; it additionally
  needs an OS ODBC driver in the deployment image (the `mssql` extra pins
  `pyodbc` but does not install a driver).
- Periodic task execution is verified at registration level only; a real
  multi-minute run is a manual check (Huey cron granularity is one minute).
- No backup/restore automation, release pipeline or advanced authentication
  exists in this phase.
