# Identity, authentication and authorization

The identity module replaced the prototype login simulation with a real identity
boundary. The backend is a modular monolith: the identity module lives inside the same FastAPI app,
uses the same SQLAlchemy session and ships one new migration. No external
identity provider, broker or policy server is introduced.

Scope: identities, secure credentials, opaque server-side sessions, Casbin RBAC
evaluation, administrative user/role/settings management, machine identities and
an audit trail. Out of scope for this backend module: autonomous agents, Pydantic AI/FastMCP tool
orchestration and other business modules. The existing identity UI is integrated separately in the frontend repository.

For personal human API keys, see [issuance, expiry, revocation and intentional
public routes](personal-api-keys.md). REST and MCP share the same central
identity authority; machine credentials retain their token format with the bounded lifetime and transition below.

## Layout

| Path | Owns |
|---|---|
| `itsm/identity/models.py` | Portable SQLAlchemy 2 models for identities, roles, policies, sessions, machine credentials, login attempts, security settings and audit events |
| `itsm/identity/permissions.py` | Permission catalog, actor kinds and the seeded role definitions |
| `itsm/identity/hashing.py` | Argon2id password hashing, opaque token digests |
| `itsm/identity/policy.py` | Casbin model text, policy loading from the SQL rows and the narrow `PolicyEngine` API |
| `itsm/identity/service.py` | Business rules: login, sessions, principals, delegation, administration, authorization and audit |
| `itsm/identity/api.py` | FastAPI router, cookie/CSRF/origin guards and error handlers |
| `itsm/identity/cli.py` | Installation commands (`bootstrap-superadmin`, `adopt-superadmin`, `create-machine-identity`, `rotate-machine-token`, `revoke-machine-token`) |
| `migrations/versions/0002_identity.py` | Tables, indexes and the seeded role grant tables |
| `migrations/versions/0021_system_profiles.py` | Installs the superadmin/admin/user profiles, migrates existing readers to `user` and adds the persisted role owner |

Business modules must call `IdentityService`; they must never re-implement
authorization, read the cookie themselves or trust a caller-provided identity.

## Data model

All tables are prefixed `identity_` and use portable SQLAlchemy types only
(`String`, `Boolean`, `Integer`, `DateTime(timezone=True)`); no engine-specific
JSON, enum or UUID column is used, so the schema avoids deliberately engine-specific types. SQLite, PostgreSQL and MariaDB have executed identity checks; SQL Server remains planned and unvalidated without a live server/system ODBC driver.

- `identity_identities` — one row per actor. `actor_kind` is one of `human`,
  `internal_agent`, `external_agent`, `external_client`. `person_id` is an
  optional string reference to an inventory person; a person never needs an
  account and an identity never embeds person data. `role_id` is the single
  assigned role. `role_owner` records, at assignment time, the persisted role of
  the human superadmin who delegated a reserved system grant to a machine; it is
  revalidated on every authorization. `password_hash` is `NULL` for machine
  identities.
- `identity_roles` / `identity_role_policies` — the role and its
  `resource`/`operation` grants. These rows are the only source of permissions.
- `identity_sessions` — server-side sessions. `token_digest` stores a SHA-256
  digest of the opaque cookie token, never the token itself. `csrf_token`,
  `expires_at` and `revoked_at` live here, so expiry and revocation are checked
  on every request.
- `identity_credentials` — bearer token digests for machine identities, with an
  issuance label, mandatory `expires_at` and `revoked_at`. New credentials last
  90 days; authentication and queued workflow/report execution reject them at
  the exact expiry boundary.
- `identity_login_attempts` — durable, bounded login throttling records.
- `identity_security_settings` — the single settings row (currently
  `session_minutes`, default 480).
- `identity_audit_events` — actor id/kind/username, action, resource, outcome,
  timestamp, plus optional `execution_id`, `delegated_by` and
  `authorization_ref`. No password, token, digest or payload is stored.

Migration `0021_system_profiles` installs the `superadmin`, `admin` and `user`
profiles, preserves every existing human administrator without promotion, moves
the former `reader` role to `user`, and keeps `operator` as an ordinary custom
role. (The security settings row is created earlier by `0002_identity`.) It
creates no account: the first superadmin exists only after the installation
command runs.

## Roles and permissions

`PERMISSION_CATALOG` is the single authority for valid codes:

```
assets.view assets.edit assets.assign assets.remote
people.view people.create people.edit
config.general config.categories config.sites config.departments config.integrations
users.view users.create users.edit roles.manage sessions.manage
system.view system.providers system.modules system.configure system.backup system.update
```

The last line is the reserved installation authority. Only a persisted human
whose role is `superadmin` exercises it; an administrator, a custom human role
that copies those codes, a renamed role or a machine without an explicit
delegation never gains it.

| Profile | Id | Built in | Grants |
|---|---|---|---|
| Superadministrador | `superadmin` | yes | every catalog code, including `system.*` |
| Administrador | `admin` | yes | every business code; no `system.*` |
| Usuario | `user` | yes | `assets.view`, `people.view` |
| Operador | `operator` | no | `assets.view/edit/assign/remote`, `people.view/create/edit` |

`operator` is preserved from earlier installations as an ordinary custom role:
it is no longer built in, so an installation that never used it can edit or
delete it like any custom role. Custom roles may carry `system.*` codes, but the
service refuses to assign such a role to a human, and machine assignment
requires an explicit active-human-superadmin delegation. Built-in profiles are
immutable through the API (`409`); their grants can only change through a
reviewed migration.

## Authorization model

Casbin is the evaluation engine with an RBAC model:

```
r = sub, obj, act
p = sub, obj, act
g = _, _
e = some(where (p.eft == allow))
m = g(r.sub, p.sub) && r.obj == p.obj && r.act == p.act
```

`PolicyEngine.load(session)` reads the `identity_role_policies` rows and builds
a fresh enforcer, so a database change is effective on the next load without a
restart and without a hidden in-code permission table. `PolicyEngine.allowed()`
is the only place a permission decision is made.

**Adapter decision.** The vendor SQLAlchemy adapter (`casbin-sqlalchemy-adapter`
1.4.0) was evaluated and rejected as the persistence layer: its published test
matrix covers only SQLite on one CI image, it has no live SQL matrix for
PostgreSQL, MariaDB or SQL Server, and it would own tables this project must keep
portable. This module therefore stores policies in ITSM-owned SQLAlchemy models
and loads them into Casbin behind the narrow service interface. Casbin is pinned
to `1.43.0`; the adapter package is not a dependency.

Authorization is enforced inside `IdentityService`, not only by endpoint
dependencies, so the same rules apply to API handlers, machine clients and
future Pydantic AI/FastMCP tool adapters.

### Principals

`Principal` is constructed by the service from a persisted identity and is never
taken from a request header: `actor_id`, `kind`, `delegated_by`, `scopes`,
`execution_id`, `authorization_ref`. Resolution denies by default:

- unknown, inactive or role-less identities are denied;
- machine actors never receive the `admin` or `superadmin` role, even if a row
  is changed manually, and are denied `users.view`, `users.create`, `users.edit`,
  `roles.manage` and `sessions.manage` in this phase;
- delegated machine authority is the intersection of the machine role, the
  active human delegator's role, the persisted `role_owner` recorded at
  assignment and the requested scopes;
- a machine may hold a reserved `system.*` grant only when it was created or
  updated with an explicit active human superadmin delegation; removing the
  grant, demoting the delegator or deactivating the owner denies the same bearer
  token on its next authorization;
- sensitive machine permissions (currently `assets.remote`) require an explicit
  `authorization_ref`, which is recorded in the audit trail.

### Permission ceiling for administration

Administration never exceeds what the caller itself holds. Before any user or
role change the service compares the request with the caller's own effective,
persisted permissions (`PolicyEngine`, not a cached copy or a header):

- `create_user` requires the caller to cover the role being assigned;
- `update_user` and `set_active` require the caller to cover the target's
  current role, and `update_user` also the requested role — so a limited
  administrator cannot reset an administrator password, deactivate an
  administrator or promote anyone above itself;
- `create_role` requires the granted codes to be a subset of the caller's
  grants, so `roles.manage` alone cannot mint permissions it does not hold;
- `update_role` requires both the existing grants of the target role and the
  requested grants to be subsets of the caller's grants, so a limited manager
  can neither edit a role above itself nor lower it into a grant it lacks.

A superadmin passes because its role covers the whole catalog, never through a
bypass. An administrator covers every business code but not `system.*`, so it
cannot edit, reset, deactivate or promote a superadmin, cannot assign a role
carrying a reserved grant, and cannot use the system operations API. The
independent safeguards stay in place: self-role changes, last-active-superadmin
protection, built-in role immutability and the machine restrictions. A refused
change records a `denied` audit event and leaves target users, roles, passwords
and sessions untouched.

### Sessions, cookies and CSRF

- Login creates a 32-byte random token (`secrets.token_urlsafe`); only its
  SHA-256 digest is stored. The cookie is `HttpOnly`, `SameSite=Strict`,
  `Path=/`, `Secure` by default (`ITSM_AUTH_COOKIE_SECURE=false` is the explicit
  local plain-HTTP override).
- Every request re-checks session expiry, revocation and identity status. The
  access timestamp on the session and the identity is written only when the
  stored value is older than `SESSION_ACCESS_WRITE_INTERVAL` (60 s); a read
  inside that window keeps the stored value and rolls the read transaction back
  instead of committing, so authenticated GETs cannot hold a write lock while a
  background import commits row by row. Expiry does not depend on it: a session
  ends at the fixed `expires_at` set at login, and machine bearer requests use
  the same throttle on the identity timestamp.
- CSRF uses a synchronizer token bound to the session: `/auth/me` and
  `/auth/login` return `csrfToken`, and cookie-authenticated mutations require
  the `X-CSRF-Token` header with a constant-time comparison.
- Login requires the browser `Origin` header to equal `ITSM_AUTH_ORIGIN`;
  authenticated cookie mutations require the same origin even with a valid CSRF
  token. Machine bearer clients are exempt from CSRF/origin but keep every
  permission restriction.
- `401` responses clear the cookie; `logout` revokes the session and clears it.
- Every cookie-authenticated mutation, including `POST /tasks/demo`, uses the
  same guard (origin plus CSRF) and records its audit event before enqueueing
  work; machine bearer clients are exempt from CSRF/origin only.

### Passwords and throttling

- Argon2id (`argon2-cffi` 25.1.0) with explicit cost parameters; passwords are
  12-128 characters. No password, hash or token is returned, logged or audited.
- Login failures are generic (`invalid credentials`), whether the username is
  unknown, the password is wrong, the identity is inactive or it is not a human
  identity. Unknown usernames still perform a dummy hash verification to keep
  timings comparable.
- Attempts are persisted in SQL, bounded by a 15-minute window (5 failures), so
  throttling survives process restarts. Successful login clears the budget.

## HTTP API

Base prefix `/api/v1` (existing `ITSM_API_PREFIX`).

| Method | Path | Permission | Notes |
|---|---|---|---|
| POST | `/auth/login` | none | `{username, password}` → `{user, permissions, csrfToken, sessionMinutes}` + cookie |
| GET | `/auth/me` | session | same envelope; `401` clears the cookie |
| POST | `/auth/logout` | session + CSRF | revokes the session, clears the cookie |
| GET | `/identity/state` | session | `{users, roles, sessionMinutes}` with authorized subsets |
| GET | `/identity/catalog` | `roles.manage` | permission codes and actor kinds |
| GET | `/identity/audit` | `sessions.manage` | sanitized recent events, `limit` 1-200 |
| POST | `/identity/users` | `users.create` | creates a human or machine identity |
| PUT | `/identity/users/{id}` | `users.edit` | full edit; omitted password keeps the current one |
| PATCH | `/identity/users/{id}/active` | `users.edit` | activate/deactivate; deactivation revokes sessions |
| POST | `/identity/roles` | `roles.manage` | custom role with an explicit permission subset |
| PUT | `/identity/roles/{id}` | `roles.manage` | custom roles only; built-ins return `409` |
| PUT | `/identity/settings` | `sessions.manage` | `{sessionMinutes}` 5-1440 |

`user` DTO: `{id, username, name, email, roleId, active, lastAccess, personId,
actorKind}`. `role` DTO: `{id, name, permissions, builtIn}`. Machine clients
authenticate with `Authorization: Bearer <token>`; their envelope has
`csrfToken: null`.

`GET /identity/state` answers `200` for any authenticated actor: `sessionMinutes`
always, `users` only with `users.view`, `roles` only with `users.view` or
`roles.manage` (so a `user` receives empty lists and a settings-only role still
loads the session timer).

## Installation

```bash
# 1. Explicit migration (never on startup)
.venv/bin/python -m alembic upgrade head

# 2. First owner: password from getpass or ITSM_BOOTSTRAP_PASSWORD
.venv/bin/python -m itsm.identity.cli bootstrap-superadmin --username ana.admin --name 'Ana Admin'

# Existing installation with no active owner: explicit first-owner claim
.venv/bin/python -m itsm.identity.cli adopt-superadmin --username ana.admin

# 3. Optional machine identity; the bearer token is printed exactly once.
#    A role with system.* codes also needs --delegated-by <active owner username>.
.venv/bin/python -m itsm.identity.cli create-machine-identity \
  --username agent.collector --name 'Collector' \
  --actor-kind internal_agent --role user

# 4. Rotate atomically: revoke all old credentials and print a 90-day replacement
.venv/bin/python -m itsm.identity.cli rotate-machine-token --username agent.collector

# 5. Revoke every active machine credential of an identity
.venv/bin/python -m itsm.identity.cli revoke-machine-token --username agent.collector
```

`bootstrap-superadmin` refuses to run once any human identity exists;
`adopt-superadmin` is the explicit claim for an existing installation and
refuses when an active superadmin already exists. `create-machine-identity`
refuses when no active human superadmin exists, when the requested role is
`admin`/`superadmin`, or when a role carrying reserved grants lacks
`--delegated-by` naming an active human superadmin. There is no default
credential, no startup bootstrap, no web self-elevation and no `.env` file.

These commands trust the local operator's process/database access. They are not
HTTP-authenticated operations: `--delegated-by` selects a persisted delegation,
not proof that the named human logged in. Audit attributes bootstrap, adoption,
machine creation, issuance, rotation and revocation to `local_operator` with no
human actor id/username. The target remains the resource and the persisted
machine delegator is recorded separately. No `--actor` label can establish identity.

### Machine credential transition and rollback

Apply `0045_machine_expiry` explicitly with API and worker stopped on the old
release. It adds the single indispensable `expires_at` field and assigns existing
credentials one 90-day grace window measured from migration time, including old
credentials that would otherwise be immediately expired by age. Digests, identity
links and revocation state are preserved; no secret is recovered or rewritten.
Rotate during this window. Creation/rotation JSON includes `credentialId` and
`expiresAt`; token output remains one-time. Rotation revokes all older tokens and
issues the replacement in the same transaction. No extra configuration,
dependency, scheduler or refresh-token protocol is introduced.

A downgrade to `0044_personal_api_keys` removes only the expiry column; it preserves
digests and revocations, but **old application code no longer enforces expiry**.
It is not a security-equivalent rollback. Do not downgrade schema under running
new code. Re-upgrade starts a new legacy grace window; use explicit revocation
before rollback when retaining a token would be unsafe. Verification uses only
disposable databases; PostgreSQL/MariaDB execution needs separate disposable
engine evidence, and SQL Server is not certified.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `ITSM_AUTH_ORIGIN` | `http://localhost:18080` | Exact browser origin allowed for login and cookie mutations |
| `ITSM_AUTH_COOKIE_SECURE` | `true` | `false` only for explicit local plain-HTTP development |
| `ITSM_AUTH_COOKIE_NAME` | `itsm_session` | Session cookie name |
| `ITSM_AUTH_SESSION_MINUTES_DEFAULT` | `480` | Initial session lifetime before an administrator changes it |
| `ITSM_AUTH_LOGIN_MAX_ATTEMPTS` | `5` | Failures allowed inside the throttling window |
| `ITSM_AUTH_LOGIN_WINDOW_MINUTES` | `15` | Throttling window |
| `ITSM_AUTH_PASSWORD_MIN_LENGTH` | `12` | Minimum password length |
| `ITSM_AUTH_PASSWORD_MAX_LENGTH` | `128` | Maximum password length |

## Audit trail

Every authentication and administration operation records actor id/kind/
username, action, resource, outcome, timestamp and — when applicable —
`execution_id`, `delegated_by` and `authorization_ref`. Denied operations are
recorded too, and they intentionally add only an audit row (plus a throttling row
for failed logins); they never modify their target. Records never contain
passwords, tokens, digests or request payloads.

## Known limits

- Engine claims are limited to the engines actually executed in tests: SQLite
  runs in the default suite; PostgreSQL/MariaDB live checks stay opt-in, and SQL
  Server remains unavailable until validated.
- Authorization codes and roles are phase-2 scope; no per-resource instance
  permissions, attribute policies or approval workflows are implemented.
- Agents are identities and credentials only: no agent runtime, tool framework or
  autonomous behavior exists.

## Account form ceiling

The client chooses the first assignable role (or none) for a new account and rechecks it on submission and at the save adapter. Missing or no-longer-assignable roles are rejected before transport using the existing role-field error. These presentation checks do not replace the server's effective-permission ceiling, last-admin or self-role safeguards.
