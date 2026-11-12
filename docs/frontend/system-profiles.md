# System profiles (frontend)

Running the business and owning the installation are different roles. The browser only presents what the server authorizes: effective permissions, roles and their labels come from the identity API; there is no authority in `localStorage`/`sessionStorage` and no role promotion on the client.

## Profiles

- **Superadmin**: owner of the installation. Receives the six reserved `system.*` permissions and keeps the business permissions. Only a human with `superadmin` can exercise them; a machine identity needs an active human superadmin as its delegator.
- **Admin**: manages the business (including `config.integrations`), but receives no `system.*` permissions and cannot grant itself reserved roles. The existing `canAssignRole` ceiling still applies: a role is assignable only if the editor already holds all its permissions.
- **User**: read access by default (`assets.view`, `people.view`) with bounded business grants.

The first Superadmin is created from the CLI (`bootstrap-superadmin`); the web interface never elevates roles. Built-in roles are recognized by the server's `builtIn`/`system` flags, not by their identifier.

## System section

`#/configuracion/sistema` is one more section of the Settings navigation, visible only with `system.view`. Admin and User get the denied route; direct API requests answer `403`.

Each control is enabled by its own permission:

| Control | Permission |
| --- | --- |
| Status, configuration and providers (read) | `system.view` |
| Save deployment classification and maintenance window | `system.configure` |
| Choose the default provider and model | `system.providers` |
| View and enable/disable modules | `system.modules` |
| Create a backup | `system.backup` |
| Prepare an update | `system.update` |
| Check the deployment | `system.view` |

AI administration (`#/configuracion/ia`): the conversation and model preference stays available with `assets.view`; instances, catalog, installations and the wizard require `system.providers`, and changing a module from the catalog also requires `system.modules`.

## API contract

Base `/api/v1/system`, with the same transport as the rest of the application (same-origin session, CSRF on writes, cancellation by signal):

- `GET /status` → `{ready, checkedAt, app:{name,version,mode,database}, readiness:{database,migrations,current,head}, executor:{configured,available,actions,detail}}`.
- `GET /configuration` → `{deployment:{classification,maintenanceWindow,database}, executor:{configured}}`.
- `PATCH /configuration` with `{deployment:{classification?,maintenanceWindow?}}`; no other keys are sent. The configured deployment classification is a preference and does not change the process's real environment.
- `GET /providers` → `{selected, selection, providers:[{id,label,credentialConfigured,credentialEnv}]}`. `PUT /providers` sends only `{provider,model}`; credentials never travel.
- `GET /modules` → `{modules:[...]}`; `PATCH /modules/{id}` with `{enabled}`. The official module cannot be disabled (`409`).
- `POST /operations` with `{action:"deployment.status"|"update.prepare"|"backup.create"}` → `{action,state,result,reference,exitCode,startedAt,durationMs,message}`. The server chooses the executor; the UI sends no paths, commands or endpoints.

## External executor

An unconfigured or unreachable executor is shown as not configured or not available, with the server's public detail. Actions that depend on it are disabled and an invented result is never shown. A `state:"unavailable"` response is shown as such; only `state:"completed"` with a server `reference` is presented as a completed backup.

## Focused tests

From `frontend/`:

```bash
node --test tests/system-profiles.test.mjs
```

They cover catalog and permissions, route and denial, minimal read access, nested configuration saving, provider selection without secrets, modules including the official one, completed and unavailable operations, cleanup on sign-out, server role metadata and the assignment ceiling.
