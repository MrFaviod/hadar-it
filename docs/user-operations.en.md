Español: [user-operations.md](user-operations.md)

# Advanced operation of the installation

A short guide for whoever administers the server: installation, backups, external modules and Superadmin operations. For day-to-day use of inventory, incidents and reports, the [in-app help](../frontend/docs/user-help.md) is enough; this document does not repeat it. Infrastructure details, variables and verifications already executed live in [operations.md](operations.md), which is the operational source of truth.

## Before you start

### Three independent repositories

The product is three different Git repositories, not a monorepo and not submodules. The root ignores `frontend/` and `backend/`: it does not see their commits, changes or backups.

| Path | Content | Verification |
|---|---|---|
| `asset/` (root) | Coordination documentation, `compose.yaml`, product version | `git status --short --branch` |
| `frontend/` | Interface, tests and help in Spanish | `git -C frontend status --short --branch` |
| `backend/` | API, persistence, worker and identity CLI | `git -C backend status --short --branch` |

Review each repository where you are going to work before editing and before confirming changes. Component versions evolve separately from `VERSION`.

### Product identity: Hadar IT

**Hadar IT** is the temporary official name, with the tagline "Bring your own department." The name the interface shows is a separate setting, under **Configuración → Apariencia** (`#/configuracion/apariencia`), in the field **Nombre visible de la aplicación** (`appName` of the active appearance): the shell and the document title take it from there. "Asset Manager" is only the label the interface inherited, not the product name. Do not rename packages, identifiers, storage paths or the database to change the presentation. See [phase10-appearance.md](../backend/docs/phase10-appearance.md).

## Installation

1. **Release mode first.** `RELEASE_MODE` is mandatory: it names the Compose project and its volumes, and every process refuses to start without it. Export it together with that mode's overlay and keep both in the installation shell.

   ```bash
   export RELEASE_MODE=prod
   export COMPOSE_FILE=compose.yaml:deploy/compose.prod.yaml
   ```

   Use `deploy/compose.dev.yaml` (`RELEASE_MODE=dev`) for an isolated local trial or `deploy/compose.demo.yaml` (`RELEASE_MODE=demo`) for the public fictional demonstration. Each mode is a separate project, network and volume set; `dev` and `demo` replace the shared data mounts with one owned directory. Variables, TLS and limits per mode: [release-modes-deployment.md](release-modes-deployment.md).
2. **SELinux level per installation.** Reserve your own MCS categories and export them as `ITSM_SELINUX_LEVEL` before any Compose command; each installation uses a different level. See [operations.md](operations.md#reserve-the-shared-volume-selinux-domain).
3. **Secrets outside files.** There is no `.env` and no `.env.example`: export the variables from the environment or from your approved secrets manager and run Compose with `--env-file /dev/null`. Never put credentials in Git, in terminal captures or in documentation.
4. **Preparation before the API and the worker.** The `initialize` service runs `python -m itsm.deployment prepare` once, and `backend` and `worker` wait for it with `service_completed_successfully`. In `dev` it migrates, claims the database, creates the explicit dev administrator and seeds fictional data; in `prod` it migrates an empty database or runs the guarded upgrade (preflight, verified backup, Alembic, post-upgrade verification); in `demo` it migrates, claims the database for the demonstration and seeds it. A failed preparation stops the project. The `migrate` service (`alembic upgrade head`, profile `tools`) is a manual fallback, not the installation path, and no process migrates at startup. Do not use `downgrade` or restore over live data without an explicit recovery decision.
5. **Explicit first owner.** `prod` creates no accounts: `bootstrap-superadmin` creates the initial account and is rejected if any human identity already exists; there is no fixed account and no default password. The password arrives through `getpass` or `ITSM_BOOTSTRAP_PASSWORD`, never as an argument. After `initialize` succeeds:

   ```bash
   docker compose --env-file /dev/null run --rm -e ITSM_BOOTSTRAP_PASSWORD backend \
     python -m itsm.identity.cli bootstrap-superadmin --username TU_USUARIO --name 'Tu nombre'
   ```

   `dev` and `demo` are prepared automatically (`dev.admin`, and the public `admin`/`admin` visitor of a fictional installation), so they require no bootstrap. In an existing installation without an active owner, the claim is `adopt-superadmin --username CUENTA_EXISTENTE`. See [identity.md](../backend/docs/identity.md#installation).
6. **Origin and cookies.** `ITSM_AUTH_ORIGIN` must match the browser origin exactly; cookies are `HttpOnly`, `SameSite=Strict` and `Secure` except for the explicit `false` of the `dev` overlay on loopback HTTP. A public installation needs TLS (`--profile tls` or your own proxy) and an `https` origin. Every cookie-authenticated mutation requires Origin and a CSRF token; bearer clients carry no CSRF, but keep the same permissions.

Roles: **Superadmin** also exercises the `system.*` codes; **Admin** administers the business without `system.*`; **User** is read-only by default. Administration never grants above the effective permissions of whoever performs it, and the last active Superadmin and changes to one's own role are protected.

## Demo mode

The publishable form is the Compose demo overlay: `RELEASE_MODE=demo` with `deploy/compose.demo.yaml`, one shared fictional installation whose public `admin`/`admin` visitor is documented, whose inherited provider, executor, notification and search credentials are blanked, and which resets itself every 60 minutes in-process. Publish it only through TLS with the exact public origin in `ITSM_AUTH_ORIGIN`; see [release-modes-deployment.md](release-modes-deployment.md) and [demo-public.md](../backend/docs/demo-public.md).

The isolated initializer below remains the developer path for a private demonstration, never a production seed. It requires a **new** directory whose parent already exists: it rejects any existing directory, including an empty one, and offers neither overwrite nor restart. It can only use its own `demo.db` database, ignores `ITSM_DATABASE_URL` and refuses with `ITSM_ENVIRONMENT=production`.

From `backend/`, with `ITSM_BOOTSTRAP_PASSWORD` supplied explicitly in the environment and the parent directory already created:

```bash
.venv/bin/python -m itsm.demo init --directory ../<local-artifacts> --username demo.owner
```

It leaves a durable marker before confirming the data: external notification stays suppressed even if you restart, and no configuration API deletes it. Do not clean it by hand or reuse the demo database as production, and do not delete volumes to "start over": choose another directory. It does not modify foreign services. Synthetic telemetry is a separate and optional step; at this stage it has already been verified with isolated Prometheus and that long run does not need repeating. See [demo.md](../backend/docs/demo.md).

## Backups and recovery

A complete backup combines pieces that are not recovered from each other:

| Piece | What to include |
|---|---|
| Main SQL | Dump consistent with the engine's tool: `pg_dump -Fc` + `pg_restore --list`; `mariadb-dump --single-transaction`; SQLite with `.backup` or the online API, never copy a WAL database while hot; SQL Server with the operator's native procedure, including encryption keys |
| External bytes | `attachment-data` volume (attachments, logos, documents) together with the same SQL cut; SQL alone or volume alone is incomplete |
| Queue | Complete and consistent Huey volume; restoring it may repeat jobs |
| Extensions | SQL database (versions, revisions, schedule) and `/data/app/extension-workspaces` |
| Configuration | Published appearance, settings and integrations in SQL, plus the external URLs/origins reapplied by hand |
| Secrets | Keep the external keys and the credentials supplied by the operator separately. Some provider credentials are stored encrypted in SQL: they also require the external key `ITSM_AI_CREDENTIAL_KEY` to be recovered. Reapply references from the approved mechanism; do not rotate keys during the rehearsal |

Engine warnings: do not infer compatibility from the SQLAlchemy URL. SQL Server was not installed or restored in this environment; do not present it as verified.

To rehearse a recovery: choose a maintenance window, coordinate writes and uploads during the cut, restore into a **new and isolated destination** (another Compose project and new volumes), apply explicit migrations and verify readiness, sign-in and authenticated downloads. Never overwrite the live installation or delete volumes to free space. See [operations.md](operations.md#backups-and-recovery).

## External modules

SDK v2 separates declarative modules from executable packages. Executable code uses a restricted runner and isolated frontend rendering. A human owner must approve the exact package digest, requested permissions, migration plan and validation result. Changed code needs new validation and approval. Disabling a module does not delete its data.

SDK interface composition allows adding, hiding or replacing navigation, pages, widgets, panels and business actions through declared contributions. It is integrated in this development branch and requires a validated, approved and enabled extension; it does not imply a deployment or a publication. Login, permissions, extension recovery and system operations remain core surfaces. See [extensions-sdk.md](../backend/docs/extensions-sdk.md) and [frontend/docs/extensions-sdk.md](../frontend/docs/extensions-sdk.md).

## Superadmin operations

Only a persisted person with the `superadmin` role exercises `system.*`. An Admin cannot grant itself reserved permissions or promote anyone above itself, and a machine identity obtains them only through explicit delegation by an active human Superadmin: no agent receives permissions by itself or by indication in a chat.

System operations are limited to fixed actions (`deployment.status`, `update.prepare`, `backup.create`) that an external operator executes under its own least-privilege account. ITSM authorizes and audits each one; neither prompts nor tool arguments choose commands, paths or credentials. Without a configured and reachable executor, the operation is reported as **not available**, never as successful. Every approval is human and explicit. See [system-operations.md](../backend/docs/system-operations.md).

## Limits of this stage

Installation, backups and external modules remain integrations owned by each operator: this guide includes no backup scripts, automations or production certification. If a check was not executed, the corresponding document must say "not verified" instead of inferring it.
