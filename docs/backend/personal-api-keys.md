# Personal API keys for REST and MCP

A signed-in human can issue, list and revoke their own keys without creating a
machine identity. External clients send `Authorization: Bearer <API_KEY>` to REST or
to the mounted Streamable HTTP MCP endpoint, `/api/v1/mcp`. They do not need a
frontend, session cookie, Origin or CSRF header to use a key.

## Issue and manage a key

Apply the explicit Alembic migration `0044_personal_api_keys` through the normal
operator upgrade procedure before running this code. Startup never migrates.
Existing machine credentials are unchanged. This migration adds a separate
`identity_api_keys` table; it does not rewrite identities, sessions or machine
credentials. This change was exercised on disposable SQLite only, not live
PostgreSQL, MariaDB or SQL Server.

1. Sign in with `POST /api/v1/auth/login`, your username/password and the configured
   `Origin`. Keep the returned HttpOnly session cookie and `csrfToken` privately.
2. With that cookie, Origin and `X-CSRF-Token`, send:

   ```http
   POST /api/v1/auth/api-keys
   Content-Type: application/json

   {"label":"External inventory reader","permissions":["assets.view"]}
   ```

3. Store the response's `token` in your client's secret store. It is returned
   **only by issuance**, never by listing or revocation. Do not print it or put it
   in a URL, shell history, committed file or shared log.
4. Use the same browser session for `GET /api/v1/auth/api-keys` to list metadata
   and `DELETE /api/v1/auth/api-keys/{id}` to revoke a key. DELETE also requires
   Origin and CSRF. Revoking an already revoked own key is idempotent.

Issuance returns `201`; list and revoke return `200`. Responses use
`Cache-Control: no-store`. Metadata contains `id`, `label`, `permissions`,
`createdAt`, `expiresAt` and `revokedAt`; list wraps it in `{"items":[...]}`.
Unknown IDs and keys belonging to another user both return `404`. There is no
cross-user key administration, including for Superadmins. Bearers, whether
personal or machine, cannot mint, list or revoke keys (`403`). Management requires
a current human cookie session, not an additional identity permission.

| Request field | Policy |
| --- | --- |
| `label` | Required, 1 to 64 characters after trimming |
| `permissions` omitted or `null` | Snapshot all current effective creator permissions |
| `permissions: []` | No permission grants, never unrestricted access |
| Explicit permission list | Known codes, all currently held by the creator; excess grants return `403`, unknown codes `400` |
| `expiresAt` omitted | 90 days from issuance |
| `expiresAt: null` | No fixed expiry; prefer the default unless a rotation process requires otherwise |
| Explicit `expiresAt` | Future ISO 8601 datetime with timezone; past/naive values rejected |
| Any other field | Rejected (`422`), including owner, role and scope injection |

Malformed request bodies return `422`; domain validation returns `400`. A failed
issuance does not create a key. There is no key update operation: rotate by
issuing a replacement and revoking the old key.

## External use

The example reads an ephemeral in-process value or a secret injected by your
operator. It deliberately never prints the key or sends browser credentials.
Use TLS for external traffic; a bearer secret grants access to anyone holding it.

```python
import asyncio
import os

import httpx
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

base_url = os.environ["ITSM_BASE_URL"].rstrip("/")
headers = {"Authorization": "Bearer " + os.environ["ITSM_PERSONAL_KEY"]}
response = httpx.get(base_url + "/api/v1/assets", headers=headers)
response.raise_for_status()

async def inventory():
    transport = StreamableHttpTransport(base_url + "/api/v1/mcp", headers=headers)
    async with Client(transport) as client:
        tools = await client.list_tools()
        result = await client.call_tool("search_assets", {"query": "switch"})
        return tools, result

asyncio.run(inventory())
```

MCP rejects a cookie alone, a missing bearer or an invalid/expired/revoked key.
Tool discovery is not an authorization grant: core tools may remain listed when
the key cannot invoke them; registered module tools additionally filter declared
permissions. Every call resolves the trusted bearer again. Tool arguments cannot
supply identity, permission, owner or authorization context.

## Authority and revocation

Every operation uses the intersection of the creator's **current persisted
permissions** and the **immutable issuance ceiling**. A promotion cannot silently
expand an old key; demotion removes grants immediately on the next operation.
Account deactivation, key revocation and expiration also apply on the next
operation, including an already open MCP connection. A retained principal and
queued workflow/report executor keep the key ID, never its raw secret, and
revalidate key validity and current creator grants. Already completed operations
are not undone. In-flight operations are not forcibly interrupted.

Only a SHA-256 digest of the cryptographically random `itsm_pk_` secret is stored.
Audit records use key IDs, not tokens. System and extension SDK operations use
the same central ceiling; a creator's Superadmin role does not bypass it.
Installed native integration handlers remain trusted code, not a hostile-code
sandbox. Canonical domain/SDK capabilities must retain the trusted principal.
Machine credentials retain their existing CLI issuance, delegation restrictions,
permission ceilings and sensitive-operation authorization-reference checks.

Personal keys never select the owner's ambient privileged in-process agent runtime
or external administrator engine. They use the ordinary isolated-runtime path;
missing isolation remains unavailable rather than falling back to owner privilege.
Report job/document access stays owner-only for personal keys. Current unscoped
human administrators retain the existing cross-owner browser access.

Extension development and candidate submission remain permission-bound. Personal
keys cannot approve installation, toggle enabled state, roll back, or use other
human-Superadmin lifecycle gates, even with `system.modules`. Public approval must
come from the human browser flow. Installed versions, schedules and events retain
an explicitly approved owner and recheck that owner's current authority. They do
not inherit a restricted key and must not be created or resumed through one.
The internal trusted-host principal path remains available for existing host tests
and orchestration; it is not a client-selectable identity.

`POST /api/v1/tasks/demo` requires `assets.view`. Reading `/api/v1/tasks/{task_id}`
requires that permission plus a durable owner match, or current unscoped human
administration. Personal keys cannot use the creator's ambient administrator role
to read someone else's tasks. Unknown or ownerless queue locators return `404`
before reading queue contents; no task credential is placed in the URL.

Cookies retain exact Origin and CSRF mutation checks. Bearers are exempt only
from browser controls, never from persisted authorization. An explicit invalid
Authorization header, including an empty or malformed bearer or another scheme,
does not fall back to an otherwise valid cookie.

## Intentionally anonymous routes

Do not interpret these routes as private API authentication failures:

| Route | Why it is reachable before login |
| --- | --- |
| `POST /api/v1/auth/login` | Establishes a session; still validates Origin and human credentials |
| `GET /api/v1/health/live`, `/api/v1/health/ready` | Liveness and dependency readiness; readiness may return `503` |
| `GET /api/v1/demo/status` | Reports whether demo mode is enabled; grants no authority |
| `GET /api/v1/appearance/active`, `/api/v1/appearance/resources/{resource_id}`, `/api/v1/appearance/assets/{key}` | Branding/resources needed by the login screen; missing resources still fail normally |
| `GET /api/v1/i18n/locales`, `/api/v1/i18n/bundle?locale=...` | Login language choices and translated messages |
| `GET /api/v1/reports/public/{token}` | Explicit capability-link download; validates its independent token and lifecycle |
| `/docs`, `/redoc`, `/openapi.json` when enabled | FastAPI development API documentation; disabled in public demo |
| `GET /api/v1/demo/telemetry/targets`, `/api/v1/demo/telemetry/metrics/{asset_id}` | Synthetic telemetry only when the release and database are both marked demo; normal installations return `404` |

Monitoring ingestion/discovery routes do not use human sessions or personal keys:
`POST /api/v1/monitoring/alertmanager` requires the dedicated ingestion bearer;
`GET /api/v1/monitoring/discovery` and `/api/v1/monitoring/prometheus-metrics`
require the dedicated discovery bearer. Missing configuration returns `503`;
missing or incorrect credentials return `401`. The AI gateway's supported
chat/model routes likewise require a server-issued gateway lease, not a browser
cookie. Unsupported gateway response routes return `404` without executing work.

`/api/v1/i18n/docs` requires authentication despite describing documentation.
Inventory, identity state, tasks, system and extension operations are private.
The anonymous report capability is not an API key and grants no general API or
MCP access.
