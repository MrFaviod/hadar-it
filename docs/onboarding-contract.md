# Setup and onboarding contract

Binding contract for the first-start wizard of a new Hadar IT installation (dev and prod). It records the decisions already taken for this branch and the existing repository facts that constrain them. It does not claim that the wizard exists yet: T1 onwards implement this contract, and `tests/onboarding_contract.py` is the structural gate for both.

Run the gate with `python3 tests/onboarding_contract.py`. It reads `tests/onboarding-contract.json` and this document; it starts nothing, opens no database and reads no secret. The backend anchors resolve to `<worktree>/backend`; set `ONBOARDING_BACKEND_DIR` to point them at another checkout (a branch worktree, a CI copy) without changing the default.

## Scope and invariants

- Setup is a separate application and CLI (`itsm.setup`). It never imports `itsm.main`, which opens the database during startup (`backend/itsm/main.py:257-259`), and it must answer while the database and the API are absent.
- Only `dev` and `prod` participate. Demo keeps its current path and never offers a claim.
- The wizard is reachable without a database. The setup service has no `depends_on` on `initialize` or `backend` (`compose.yaml:123-170`).
- No Docker socket, no shell, no host edit, no root, and no published host port: the wizard is reached only through the frontend edge (`/api/setup/v1/`).
- Anonymous callers can read a sanitized status and nothing else. The claim credential, the session token and every secret stay out of logs, URLs and responses.

## States and transitions

| State | Meaning |
|---|---|
| `unclaimed` | Fresh installation; setup is enabled and a one-time claim credential exists. |
| `claimed` | The operator consumed the claim; the setup session owns the installation. |
| `ai_configured` | A provider endpoint, model and one tool call were verified before any database existed. |
| `ai_deferred` | The operator chose manual continuation after an AI failure; the pending item stays visible at close (D1). |
| `storage_ready` | The application database is reachable, migrated and prepared. |
| `owner_ready` | The first superadmin exists, created only through `bootstrap_superadmin`. |
| `configuring` | Assisted configuration is in progress; required and postponable items are tracked separately. |
| `verifying` | Every required check for the mode reports its result. |
| `complete` | Required results are verified and the bootstrap mutation is disabled. |

| From | To | Trigger | Action | Authority |
|---|---|---|---|---|
| `unclaimed` | `claimed` | One-time claim credential presented | `claim` | claim |
| `claimed` | `ai_configured` | Provider endpoint, model and tool call verified | `configure_ai` | session |
| `claimed` | `ai_deferred` | Operator continues without AI | `defer_ai` | session |
| `ai_configured` | `storage_ready` | Database reachable, migrated, prepared | `apply_storage` | session |
| `ai_deferred` | `storage_ready` | Same, with AI still pending | `apply_storage` | session |
| `storage_ready` | `owner_ready` | First superadmin bootstrapped | `bootstrap_owner` | session |
| `owner_ready` | `configuring` | Assisted configuration starts | `start_configuration` | session |
| `configuring` | `verifying` | Required checks run | `verify` | session |
| `verifying` | `complete` | Verified results, bootstrap mutation disabled | `complete` | session |
| `complete` | `configuring` | Operator reopens configuration from the local CLI | `recover` | operator CLI |

Rules enforced by the gate:

- `unclaimed` has exactly one exit and is never reachable again. A restore of an old state snapshot cannot reopen a claimed installation.
- No transition leaves `complete` except the operator recovery command `recover`, which preserves ownership and data.
- A failed operation is an operation result, not a state loss: the last valid state holds (D1 keeps `ai_deferred` visible instead of simulating success).
- Every transition names the operation or operator command that performs it, and that action lists the source state.

## Operations

All HTTP paths live under `/api/setup/v1/`. `anonymous` endpoints are read-only GETs; non-GET requests require the `Origin` header, and session requests also require `X-CSRF-Token`.

| Id | Method and path | Authority | Required states | Idempotent |
|---|---|---|---|---|
| `status` | GET `/api/setup/v1/status` | anonymous | any | yes |
| `claim` | POST `/api/setup/v1/claim` | claim | `unclaimed` | no |
| `session` | GET `/api/setup/v1/session` | session | `claimed` … `verifying` | yes |
| `session_logout` | POST `/api/setup/v1/session/logout` | session | `claimed` … `verifying` | yes |
| `assistant_ask` | POST `/api/setup/v1/assistant/ask` | session | `claimed` … `configuring` | no |
| `configure_ai` | POST `/api/setup/v1/ai` | session | `claimed`, `ai_deferred` | yes |
| `defer_ai` | POST `/api/setup/v1/ai/defer` | session | `claimed` | yes |
| `check_storage` | POST `/api/setup/v1/storage/check` | session | `ai_configured`, `ai_deferred` | yes |
| `apply_storage` | POST `/api/setup/v1/storage` | session | `ai_configured`, `ai_deferred` | yes |
| `bootstrap_owner` | POST `/api/setup/v1/owner` | session | `storage_ready` | yes |
| `start_configuration` | POST `/api/setup/v1/configuration` | session | `owner_ready` | yes |
| `verify` | POST `/api/setup/v1/verify` | session | `configuring` | yes |
| `complete` | POST `/api/setup/v1/complete` | session | `verifying` | yes |
| `report` | GET `/api/setup/v1/report` | session | `configuring`, `verifying` | yes |
| `configuration_overview` | GET `/api/setup/v1/configuration` | session | `configuring` … `complete` | yes |
| `read_section` | GET `/api/setup/v1/configuration/{section}` | session | `configuring` … `complete` | yes |
| `preview_section` | POST `/api/setup/v1/configuration/{section}` | session | `configuring` | yes |
| `apply_section` | POST `/api/setup/v1/configuration/{section}/apply` | session | `configuring` | no |

- `status` returns only the sanitized allowlist: `state`, `mode`, `release_mode`, `setup_enabled`, `claim_available`, `backend`, `version`, `instance_id`. It never returns a password, token, credential, ciphertext or database URL.
- `status` must distinguish an explicit setup, an existing instance and a temporary unavailability. A `502` or `503` from `/api/v1` is never interpreted as a new installation and never offers a claim.
- `claim` consumes the one-time credential from the local operator channel. The credential is never logged and never placed in a URL. Recovering a lost claim requires a local operator action, not a second registration.
- `check_storage` probes a candidate database and drives no transition; `apply_storage` owns the transition.
- The setup session is its own cookie: name `itsm_setup_session`, path `/api/setup/v1`, HttpOnly, SameSite=Strict, Secure following `settings.auth_cookie_secure` (`backend/itsm/config.py:205-212`), TTL 60 minutes, at most 5 attempts. The identity cookie helpers close over `app.state.settings` (`backend/itsm/identity/api.py:373-392`), so the setup app declares its own session instead of importing them unchanged. `Origin` is compared exactly and `X-CSRF-Token` uses a constant-time comparison, mirroring `backend/itsm/identity/api.py:325-345`.
- `complete` re-runs every required check, writes the completion row and closes the private store; a second call returns the stored report without moving `completed_at`, and the response clears the setup session cookie. `report` exports that report and answers `409 setup_complete` once the installation is complete.
- Configuration is read through `configuration_overview` and `read_section`, previewed through `preview_section` (no write) and committed through `apply_section`, whose `action` is `apply`, `postpone`, `accept_risk` or `declare` and which requires `confirm`. Required and postponable items are tracked separately; an accepted risk is stored as a risk and never counted as a pass, and a `declare` is stored as a declaration, never as a pass either.
- `assistant_ask` only asks: it returns advice and applies nothing, so it cannot replace a preview or an apply.

## Configuration sections

`configuration_overview` and `read_section` answer one section at a time, `preview_section` writes nothing, and `apply_section` requires `confirm`. Three sections carry the behaviour this slice added:

| Section | Reports | Applies |
|---|---|---|
| `agent` | `provider_record` (bool: the persisted selection is linked to a global `AgentProvider` row) beside provider, model, credential, capability and tool | promotes the verified setup key to a global provider record (reused on re-apply) and links it; the receipt adds `provider_record`. No request field changes and the key never appears in a response. |
| `appearance` | `organizationName` from the persisted appearance state | `values.organizationName`, normalized to 1..120 characters and read back before the section turns `passed`. |
| `operational` | `origin`, `cookie_secure`, `worker`, per-key `settings` provenance, `restart_required`, `restart_scope` and `backup_policy` | `action: "declare"` with the backup policy fields, or the settings `auth_origin`, `auth_cookie_secure`, `auth_cookie_name` and `auth_session_minutes_default`. |

- `declare` is a fourth `action` beside `apply`, `postpone` and `accept_risk`, and it only accepts the backup policy: `target`, `location_kind`, `schedule`, `retention` and `responsible` land in `installation_backup_policy` (migration `0049_setup_backup_policy`) with `source: "declaration"` and `status: "declared"`. `declared` outranks `risk` and never becomes `passed`: an observed or published backup status still decides `passed` and wins over the declaration. Validation rejects empty fields, a `location_kind` outside `local|remote|object_storage|managed_service|other`, a `retention` without a digit, control characters and an unconfirmed apply.
- The operational settings are written into the private installation file through the same atomic writer (`0600` file, `0700` directory, symlink refused, existing keys preserved) and validated by the settings resolver before publication. The receipt reports `source: "installation_file"`, `written`, `effective` per key with its source, `overridden_by` (the environment variable names that shadowed a value), `restart_required: true` and `restart_scope: ["backend", "worker"]`. A file value applies only after a restart, and only while the matching `ITSM_*` variable stays unset.
- `provider_record` is `true` only when the selection is linked to a global row; the runtime runs on that encrypted row when the environment carries no `OPENAI_API_KEY`/`ANTHROPIC_*`, and an environment credential still wins. Migrations: `0047_agent_provider_link`, `0048_appearance_organization`, `0049_setup_backup_policy`.
- `GET /api/v1/appearance/organization` returns only `{"organizationName": ...}` to an authenticated caller, while the public `GET /api/v1/appearance/active` keeps its envelope and now carries the persisted name in `branding.organizationName`. The write path stays inside the wizard (`POST /api/setup/v1/configuration/appearance/apply`); `preset` remains optional and a combined apply reports `apply_preset+set_organization`.

## Ownership and existing databases

Installation ownership is the `deployment_identity` row (singleton `id=1`) written by `backend/itsm/release_identity.py:83-91`. The human owner is a separate identity row.

- The first owner is created only through `IdentityService.bootstrap_superadmin` (`backend/itsm/identity/service.py:1304-1349`). There is no second implementation.
- Setup never adopts an unmarked non-empty database. `ensure_identity` currently adopts one in prod (`backend/itsm/release_identity.py:221-230`); the wizard therefore treats an existing database as read-only and requires an explicit operator action before any claim or migration.
- `ITSM_DEV_ADMIN_PASSWORD` remains the explicit headless path and keeps today's seeding (`backend/itsm/deployment.py:40-45`, `backend/itsm/devtools/cli.py:88-100`). The dev wizard is the default; both paths must never produce two owners for the same installation.
- `bootstrap_superadmin` refuses when any human identity already exists and audits the creation, so a replayed wizard cannot register a second owner.

## Settings

Settings stay a pydantic-settings object built by `get_settings` (`backend/itsm/config.py:147-154`, `backend/itsm/config.py:752-754`). The seam only adds a resolver:

- `resolve_settings_sources(environ, installation_path=...)` builds init kwargs from the installation file minus every field whose `ITSM_*` variable is present in the environment; `get_settings()` calls it.
- `ITSM_INSTALLATION_CONFIG` names the file (absolute path). It stays `ITSM_`-prefixed because `tests/conftest.py:56-96` strips every `ITSM_*` variable from subprocess environments; an unprefixed pointer would leak a developer installation into worker, Alembic and CLI tests.
- The file lives on a private volume: directory `0700`, file `0600`, no symlinks, one JSON object. A missing file means "no persisted value".
- Precedence is `env` > `installation` > `default`. Precedence is by presence, not truthiness: an explicitly empty environment variable still wins over the file, and `unset`, `empty` and `applied` stay distinguishable.
- A value written to the file is validated with the same resolver before publication; a bad value would otherwise stop the API and the worker from booting.

| Setting | Owner | Environment | Secret |
|---|---|---|---|
| `database_url` | installation | `ITSM_DATABASE_URL` | yes |
| `auth_origin` | installation | `ITSM_AUTH_ORIGIN` | no |
| `auth_cookie_secure` | installation | `ITSM_AUTH_COOKIE_SECURE` | no |
| `auth_cookie_name` | installation | `ITSM_AUTH_COOKIE_NAME` | no |
| `auth_session_minutes_default` | installation | `ITSM_AUTH_SESSION_MINUTES_DEFAULT` | no |
| `task_storage` | installation | `ITSM_TASK_STORAGE` | no |
| `agent_model` | installation | `ITSM_AGENT_MODEL` | no |
| `ai_credential_keys` | env | `ITSM_AI_CREDENTIAL_KEYS` | yes |
| `dev_admin_password` | env | `ITSM_DEV_ADMIN_PASSWORD` | yes |
| `release_mode` | env | `RELEASE_MODE` | no |
| `monitoring_public_url` | env | `ITSM_MONITORING_PUBLIC_URL` | no |
| `appearance_default_theme` | domain service | `ITSM_APPEARANCE_DEFAULT_THEME` | no |
| `smtp_host` | domain service | `ITSM_SMTP_HOST` | no |
| `backup_policy` | domain service | `ITSM_BACKUP_POLICY` | no |

Domain settings are applied after `storage_ready` through the existing domain services; they are not written into the installation file. Secret settings never appear in the sanitized status.

## AI provider before the database

The pre-DB step reuses the DB-free surface of `backend/itsm/agent_integrations/providers.py`:

- `validate_provider_endpoint` with `scope="personal"` and the `ProviderNetworkPolicy` allowlist (`providers.py:316-366`), because global scope skips the private-address ban.
- `seal_credential` / `unseal_credential` with the operator key ring `ITSM_AI_CREDENTIAL_KEYS` (`providers.py:459-537`). No key ring means the credentials form is blocked with a diagnosis, never a silently disabled field.
- `discover_provider_models` for the model list (`providers.py:651-745`), then one tool call as the real proof: discovery returning `ok` does not prove tool calling.
- The transient local record holds ciphertext, normalized base URL, model, scope, credential fingerprint and discovery result, never the raw key. After `storage_ready`, the record is transferred to the database provider row through the canonical service, verified by unsealing and reading the row, and only then is the transient copy deleted. A retry looks up the destination first; a key rotation makes the token unreadable and fails closed.

## Required to complete

| Requirement | dev | prod |
|---|---|---|
| Setup enabled and claim completed | required | required |
| AI explicit (`ai_configured` or `ai_deferred`) | required | required |
| Database reachable, migrated, prepared | required | required |
| First owner present | required | required |
| Origin and sessions valid | required | required |
| Worker and queue operational | required | required |
| Appearance chosen explicitly or base value accepted | required | required |
| Backup policy declared and checked when configured | postponable | required |

Postponable in both modes, recorded as pending and never reported as ready: SMTP and channels, monitoring, external search, external engines and integrations. A conscious exclusion stays a risk, not a success.

## Documentation pack and tools

- The runtime pack is a generated JSON file committed at `backend/itsm/project_context/pack.json`, built by `tools/build-project-context.py` from the allowlist below. A drift check fails when a listed document changes and the pack was not regenerated.
- Allowlist: `docs/README.md`, `docs/features.md`, `docs/technical-guide.md`, `docs/operations.md`, `docs/operations.es.md`, `docs/user-operations.md`, `docs/user-operations.en.md`, `docs/release-modes-deployment.md`. Excluded: private task records, review folders, local agent notes and `.env*`.
- The generated file is committed inside the backend package because `backend/Dockerfile:19-20` copies only `itsm/` and `migrations/`, and `backend/Dockerfile.ops:60` builds on the `itsm-backend:0.1.0` tag. No build context moves.
- Four mandatory core tools, registered in both runtimes (`backend/itsm/agents/runtime.py:76-134`, `backend/itsm/mcp/server.py:59-117`): `get_project_context`, `list_project_capabilities`, `search_project_docs`, `read_project_doc`. The names had zero collisions across the worktree, so `main.py:170` reserves them without an exception.

## Compose and edge routing

- New `setup` service, image `itsm-backend:0.1.0` with `command: python -m itsm.setup`, no dependency on `initialize` or `backend`, no published host port, read-only root filesystem, dropped capabilities and SELinux level. It is implemented: `python -m itsm.setup` binds `0.0.0.0:8100` inside the container, and no Compose file publishes a host port for it, so it is reachable only through the frontend edge (`backend/itsm/setup/__main__.py`, `frontend/nginx.conf:49`).
- Demo keeps setup out with a dedicated Compose profile, the same technique that keeps `worker` out of the default demo (`deploy/compose.demo.yaml:100-101`).
- `frontend` loses `depends_on: backend` (`compose.yaml:160-162`). `nginx.conf` gets `resolver 127.0.0.11` and variable `proxy_pass`: `/api/setup/v1/` to `setup:8100`, `/api/` to `backend:8000` with `502`/`503` when the API is absent (`frontend/nginx.conf:37-44`). `deploy/nginx-tls.conf:57-65` drops the static `itsm_api` upstream for the same reason.
- The exact service set in `tests/release_modes_runtime.py:77-81` changes with the new service; that update belongs to T1, not to this contract slice.

## Frontend mount

`AssetApp` probes `GET /api/setup/v1/status` with a small fetch in `frontend/src/setup/client.ts` and branches before `mountLegacy` (`frontend/src/main.tsx:8-10`). Explicit setup renders `SetupApp` and returns without mounting the legacy host; any other answer keeps today's path. No hash route and no Vue view: the hash router normalizes unknown routes to panel or login (`frontend/assets/js/methods.js:160`) and `AssetAccess.start` clears identity on a failing `/auth/me` (`frontend/assets/js/access.js:717-738`). `AssetReactHost` stays unset until the legacy mount, so a half-initialized page cannot auto-mount Vue.

## Recovery

The operator command `recover` reopens configuration from `complete` without resetting the database and without depending on a browser cookie. It preserves installation ownership and the first owner; it is the only transition out of `complete`. The command family is `python -m itsm.setup.cli recover`, `enable-claim` and `rotate-claim`.

## Known gaps

Recorded limits that stay open. Each one is a behaviour the contract does not promise, so a later task closes it deliberately instead of inheriting a false green.

- **Production requires `ITSM_DATABASE_URL` in the environment.** The installation file is read by every process, but an environment value wins over it, so prod Compose refuses to start without the explicit variable (`backend/itsm/config.py:resolve_settings_sources`, `deploy/compose.prod.yaml`).

## Resolved gaps

Four limits this contract used to record are closed in the backend (`feat/onboarding-gaps`, `ca97222`) and the frontend (`feat/onboarding`). They stay listed with the limit that remains, so the closure is visible and a regression re-opens a recorded gap instead of passing silently.

- **Agent credentials are no longer environment-only.** The agent section reports `provider_record`: the wizard promotes the verified setup key to a global `AgentProvider` record, links it to the installation selection and reuses it on re-apply, and the runtime runs on that encrypted record when no provider credential is in the environment (`backend/itsm/setup/configuration.py:_agent_current`, `_promote_setup_provider`; migration `0047_agent_provider_link`). Limit: the environment still wins — `OPENAI_API_KEY` or `ANTHROPIC_*` shadow the record, and a deferred AI step leaves `provider_record` false.
- **The organization name is durable, still without an organization table.** `appearance_state.organization_name` carries `organizationName` (migration `0048_appearance_organization`); the appearance section applies it as `values.organizationName` with 1..120 characters and a restricted character set, the name is overlaid on every preset so apply, restore and revert keep it, and `GET /api/v1/appearance/organization` reads it back to an authenticated caller (`backend/itsm/appearance/service.py:normalize_organization_name`, `_active`). Limit: no organization table, slug, membership or tenancy — appearance keeps nothing but branding.
- **The operational section writes a backup declaration.** `apply_section` accepts `action: "declare"` with `target`, `location_kind`, `schedule`, `retention` and `responsible`, stores the row in `installation_backup_policy` (migration `0049_setup_backup_policy`) and returns `status: "declared"` with the row read back, so production clears `backup_policy_declared` without `accept_risk` (`backend/itsm/setup/configuration.py:_declare_backup_policy`). Limit: a declaration is a declaration, not an observation — nothing verifies that a backup ran, and an observed or published backup status still decides `passed` and wins.
- **Origin and session settings are applied, and a restart is required.** The operational section writes `auth_origin`, `auth_cookie_secure`, `auth_cookie_name` and `auth_session_minutes_default` into the private installation file and reports `source: "installation_file"`, `written`, `effective` with per-key provenance, `overridden_by`, `restart_required: true` and `restart_scope: ["backend", "worker"]` (`backend/itsm/setup/configuration.py:_apply_operational`, `backend/itsm/setup/storage.py:write_installation_values`). Limit: the environment still wins over the file, and the values take effect only after a restart of the backend and the worker.

## Deviations from plan

1. **Documentation packaging.** The plan allowed a build context that reaches the repository root or a generated artifact. This contract takes the generated artifact: `tools/build-project-context.py` writes `backend/itsm/project_context/pack.json`, which is committed and checked for drift. No Dockerfile or build context changes, so the `itsm-ops` tag chain stays valid.
2. **Task record.** The plan lists a private task record in this slice's write set. This slice's write scope is limited to the contract documents and the gate, so that record is maintained outside it.
3. **Setup port.** `8100` is implemented: `python -m itsm.setup` binds `0.0.0.0:8100` inside the container and the edge proxies `/api/setup/v1/` to `setup:8100` (`backend/itsm/setup/__main__.py`, `frontend/nginx.conf:49`, `deploy/nginx-tls.conf:115`). No Compose file publishes a host port for it, so the wizard is unpublished and reachable only through the frontend edge.
4. **Baseline.** D2 is satisfied by the current master line with the audit fixes already merged, so T0 branches from it instead of waiting.
5. **Settings seam.** The plan states the precedence rule; the concrete names `resolve_settings_sources` and `ITSM_INSTALLATION_CONFIG`, the `0600`/`0700` modes and the tri-state vocabulary are fixed here.
6. **AI evidence.** D4 records that no real provider is available. T2 and T8 stay open with "implemented, external verification pending"; a fixture is not a provider observation.

## Baseline

Pre-existing failures recorded before this slice; none is caused by it and none is claimed as passing:

- Backend `ruff format --check` reports that `tests/test_extension_development.py` would be reformatted.
- The frontend `m5-frame-headers` test expects `../deploy` beside the frontend checkout. In a component worktree that path is a worktree artifact; the test passes in the main checkout.
- The full backend `pytest` run takes more than 28 minutes on 4 cores; the full run was still in progress when this contract was written, so no result is claimed.
