# Release modes: `dev`, `prod`, `demo`

One codebase runs in one of three release modes. The mode changes which
capabilities a process has; it never changes the code that is deployed.

## Selecting the mode

`RELEASE_MODE` is an unprefixed process environment variable, separate from the
`ITSM_` settings prefix, because it is deployment identity rather than
application configuration.

```bash
RELEASE_MODE=dev  docker compose up -d api worker
RELEASE_MODE=prod docker compose up -d api worker
RELEASE_MODE=demo docker compose up -d api worker
```

The value must be exactly `dev`, `prod` or `demo` (lowercase, no whitespace, no
alias such as `production` or `staging`). There is no default. An absent, empty
or invalid value **refuses to start**:

- the API raises before building any service, so no dependency is initialised;
- the worker logs `worker.refused` and exits with code `2` before executing any
  queued task;
- the CLI entrypoint can call the same gate (`itsm.release_identity.enforce_startup`).

Neither path grants a partial or "safest guess" configuration. A missing variable
is an operator error, not a reason to fall back to a permissive mode.

## Proxy trust

Forwarded client headers (`X-Forwarded-For`, `Forwarded`) are a trust decision,
not a convenience. `ITSM_TRUSTED_PROXY` is `false` by default, and the server must
agree with it:

- `python -m itsm.main --host … --port …` derives `proxy_headers` from
  `ITSM_TRUSTED_PROXY`; the container image and the Compose overlays use this
  launcher for the demonstration deployment;
- a bare `uvicorn itsm.main:app` trusts forwarded headers from a loopback peer by
  default, so it must be started with `--no-proxy-headers` unless a proxy is
  declared;
- behind a real proxy, set `ITSM_TRUSTED_PROXY=true` **and** name that proxy in
  `FORWARDED_ALLOW_IPS` (or `forwarded_allow_ips`), so the client address used by
  rate limits and audit entries cannot be rewritten by the caller.

## Capabilities

`itsm/release_mode.py` owns the frozen matrix. Consumers ask
`capabilities_for(mode)`; they never re-read the environment, so one process
cannot observe two modes.

| Capability | `dev` | `prod` | `demo` |
|---|---|---|---|
| `allow_system_operations` | yes | yes | no |
| `allow_extension_install` | yes | yes | no |
| `allow_external_notifications` | yes | yes | no |
| `allow_ai_providers` | yes | yes | no |
| `allow_agents_dev` | yes | no | no |
| `allow_seed` | yes | no | yes |
| `allow_destructive_reset` | yes | no | yes |
| `auto_migrate` | yes | no | no |

`prod` is conservative: no sample data, no destructive reset, no development
agents, and migrations come from the controlled upgrade procedure, not from the
API or worker startup. `demo` disables every capability that could reach real
infrastructure, real providers, external notifications or installed code. Each
flag is consumed by the feature it gates; a flag alone implements nothing.

## Deployment identity

Migrations create `deployment_identity`: a singleton row (`id = 1`) holding the
release mode that owns the database, an `instance_id` and `created_at`. A
process validates it before serving:

| Database state | `dev` | `prod` | `demo` |
|---|---|---|---|
| Empty (no accounts, no demo marker) | claims `dev` | claims `prod` | claims `demo` |
| Non-empty, unmarked | starts, warns, does **not** claim | adopts with an explicit warning | refuses |
| Marked for the same mode | starts | starts | starts |
| Marked for another mode | refuses | refuses | refuses |
| Demo dataset marker present | starts without claiming | refuses | claims `demo` |

Refusal always names both modes and never rewrites the marker, so a database can
only ever serve the mode that claimed it. A database claimed by another mode is
refused even when the process would otherwise be allowed to run.

The "non-empty, unmarked" row describes the documented installer flow, where the
first administrator is created before the API starts. Production adopts that
database once, explicitly and loudly, because an existing installation predates
the marker. Development starts without claiming it, because a dev process must
never make an irreversible ownership decision about data it did not create. Demo
only accepts an empty database or one that carries the durable demo marker.

### Development database guard

`dev` additionally requires a local database: a SQLite URL or a loopback host
(`localhost`, `127.0.0.1`, `::1`). A remote database is refused before any
connection is opened, so a development process cannot point at production and
reset it. This guard is intentionally this simple; it is not a substitute for
network separation.

### Migrations stay explicit

The gate never applies migrations. If identity cannot be inspected yet, the API
may serve liveness/readiness but blocks every business request with HTTP 503 and
`release_identity_unavailable`. Before admitting traffic it revalidates the
persisted owner against the process's fixed release mode. Readiness remains 503
when that validation fails, even if migrations and connectivity recover.
Workers require a verifiable deployment identity before consuming any task;
missing migrations or an unreachable database terminates the thread consumer
with exit code 2. Run explicit initialization/upgrade before starting workers.

## Observability

`/api/v1/health/ready` reports the effective mode as `releaseMode`, alongside the
existing readiness checks. Startup logs `release.mode.active` with the mode and
the password-free database URL, and identity decisions log
`release.identity.claimed`, `release.identity.adopted` or
`release.identity.unclaimed`.

## Not in this delivery

Sample data for `dev`, the demo reset cycle, per-mode Compose wiring and the
production upgrade/backup jobs are separate tasks. Until they land, the
capability flags describe permissions only.
