# Agent integrations and conversational control

The control plane lets signed-in people chat with canonical ITSM services through
a built-in Pydantic AI runtime or through installed OpenCode/Hermes engines, and
lets full administrators install and verify an external engine's ITSM profile.
All business behavior still comes from the canonical inventory, maintenance,
intervention, monitoring and document services.

Composition lives in `itsm/agent_integrations`:

| Module | Responsibility |
| --- | --- |
| `models.py` | Instances, preferences, sessions, runs, installations and module states |
| `service.py` | Engine discovery, chat turns, SSE, budgets, installation and module policy |
| `api.py` | REST/SSE router and domain-error mapping |
| `catalog.py` / `extensions.py` | Official skills, installed modules and FastMCP tool visibility |

## Identity and permissions

- Chat, preferences, sessions and the engine catalog require a signed-in human.
  Machine identities never receive an implicit human principal.
- Every administrative read or write first requires `config.integrations` on the
  requested resource **and** a live role policy that grants the complete
  permission catalog. A partial or stale administrator policy is rejected.
- An external MCP installation is bound to an integration machine identity. Its
  MCP calls use that machine's bearer credential and canonical service
  authorization; the console never injects administrator rights into chat.
- Before every external turn the service resolves the installation's
  `mcp.secretRef`, authenticates that live bearer token, requires its actor to
  be the bound identity, and requires its effective permissions to be a subset
  of the signed-in human's persistence-backed permissions. A missing, rotated,
  revoked or differently bound credential is denied before the engine runs.
- Session ownership, model changes, cancellation and history are scoped to the
  authenticated owner.

## Role ceiling and isolated execution

The transport principal never selects an engine or a privilege level. Every
turn reloads the persisted human and its active role:

- An active `admin` or `superadmin` may use the built-in Pydantic runtime in
  process or a verified external Hermes/OpenCode engine.
- Every other signed-in person — including a demoted administrator holding an
  older browser session — is limited to the built-in Pydantic engine running
  inside that person's own isolated container. External engine discovery,
  instance creation or updates, preference switching, session creation and
  turns are rejected by the service with a `403`, even when the UI is bypassed.
  Installation, catalog and module surfaces keep their existing complete-
  administrator checks; the console never injects those rights into chat.

Ordinary Pydantic turns never fall back to the in-process runtime. They require
both `ITSM_AI_BROKER_URL` and `ITSM_AI_BROKER_TOKEN` (a secret of at least 32
characters; configuration is rejected when only one is present). If the broker
is unconfigured or unreachable, the turn fails closed with `503` instead of
executing with host credentials. The fixed host broker authenticates the
backend over WebSocket and starts one bounded, read-only Docker container per
human run, with no host filesystem mount, no host database or credential, and
no additional environment beyond the run's model selection. Tool calls cross a
JSON-lines worker protocol, are validated against the tool's canonical schema
and re-execute through the same ITSM service authorization as an in-process
turn; the worker cannot widen arguments or reach another user's container.
Profiles, sessions and transcripts remain per human even when two runs use the
same engine or model.

Broker deployment variables, container flags and cleanup behavior are in
[ai-runtime-isolation.md](ai-runtime-isolation.md).

## Chat API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/agent/engines` | Enabled instances, discovered models/capabilities, preference, budget |
| `PUT` | `/agent/preferences` | Persist the effective instance/model |
| `GET/POST` | `/agent/sessions` | List or create an owner session |
| `GET/PATCH` | `/agent/sessions/{id}` | Snapshot, or switch model and optionally instance without losing the transcript |
| `DELETE` | `/agent/sessions/{id}` | Delete an owner session and its chat attachments |
| `POST` | `/agent/sessions/{id}/messages` | Send a turn; response is SSE |
| `POST` | `/agent/sessions/{id}/attachments` | Upload one owner-scoped chat attachment (raw body, `?filename=`) |
| `DELETE` | `/agent/sessions/{id}/attachments/{attachmentId}` | Delete one chat attachment and its bytes |
| `POST` | `/agent/sessions/{id}/cancel` | Request cancellation |
| `GET` | `/agent/integrations` | Compatibility admin snapshot |
| `GET/POST` | `/agent/providers` | List visible providers or create a global/personal one |
| `PATCH/DELETE` | `/agent/providers/{id}` | Update or remove an owned/administrable provider |
| `POST` | `/agent/providers/{id}/check` | Bounded models listing for an owned/administrable provider; never returns the key |

The message stream emits `data:`-only JSON frames. `session` starts the turn,
`delta` carries a new text fragment (append it, never replace), `tool` reports
canonical tool activity, `usage` distinguishes precision from provider/engine provenance,
and exactly one terminal `done` frame reports `cancelled`, and for the built-in
engine `actions`, `results` and `approvalPending`. An `error` frame is sanitized:
provider URLs, bearer values and configured secrets are redacted.

One running turn per session is enforced before the stream starts. A second
message or model change during a run returns a conflict; cancellation reaches
the engine once even if the client also disconnects.

## Attachments and multimodality

Turns accept inline attachments only. A stored attachment id is resolved on the
server; the server never fetches a URL supplied by a browser and never forwards
one to a provider.

Chat attachments (`POST /agent/sessions/{id}/attachments?filename=...`) are
owner and session scoped and reuse the asset-attachment blob store with the same
content sniffing: raster PNG/JPEG/WebP/GIF (bytes must match the extension),
PDF, and UTF-8 `.txt`/`.csv`. HTML, SVG, executables and mismatched
extension/content pairs are rejected with `validation_error`. The response is
`{"id", "filename", "mediaType", "kind", "size"}` where `kind` is `image`,
`file` or `text`; bytes, blob keys and storage paths are never returned. Both
routes are cookie mutations and need `Origin` plus `X-CSRF-Token`. Another
owner's session, attachment or asset attachment answers `404 not_found`, so
existence is not disclosed.

Limits are fixed in `itsm/agent_integrations/attachments.py`:

| Bound | Value |
| --- | --- |
| Bytes per chat attachment | `min(attachment_max_bytes, 4 MiB)` |
| Chat attachments per message | 4 |
| Decoded bytes per message | 4 MiB |
| Stored chat attachments per session | 20 |

Deleting a session (`DELETE /agent/sessions/{id}`) removes its chat attachment
rows and blobs; a running turn answers `409 conflict`. `DELETE
/agent/sessions/{id}/attachments/{attachmentId}` removes one attachment and its
bytes. Chat attachments are not asset attachments: they are never referenced
from inventory history and never downloaded through the asset download route.

`POST /agent/sessions/{id}/messages` accepts
`{"message": str, "assetId"?: uuid, "attachmentIds"?: [str],
"assetAttachmentIds"?: [str]}`. `message` may be empty when at least one
attachment id is present and is otherwise required. `attachmentIds` must belong
to that session; `assetAttachmentIds` must be live asset attachments the caller
can see through the ordinary attachments API, which requires `assets.view` on
that asset. Both lists are bounded to 4 ids and duplicate ids are ignored.

Capability gating happens before any reservation, quota hold or persisted turn:

- Images require the selected model to report `image: true`, PDFs require
  `file: true`. The provider-reported `modelCapabilities` (`source: "provider"`)
  and an owner mark (`source: "owner"`) both count; `null`, `"unknown"` and a
  model without an entry are refusals.
- Text and CSV are inlined as bounded UTF-8 text (16 000 characters, truncated
  with a marker) and are accepted by any model.
- A refusal is `422` with the stable code `model_modality_unsupported`, no
  reservation, no `AgentRun` row and no appended user message.
- The built-in Pydantic instance has no provider, so its capability is unknown:
  images and documents are refused there, and text/CSV still works.

Delivery per engine:

- Pydantic AI (built-in server model, and provider-backed personal or global
  models) receives `BinaryContent` parts built from the stored bytes plus the
  prompt text; the isolated worker receives the same content as strict base64
  inside its one bounded `run.start` line (8 MiB) and never logs it.
- Managed engines travel through the gateway. OpenCode v1 receives documented
  `{"type": "file", "mime": ..., "filename": ..., "url": "data:...;base64,..."}`
  parts; Hermes accepts text prompts only, so a binary attachment is refused
  with `422 engine_attachments_unsupported` instead of an invented field.
  OpenCode v2 and direct engine runs refuse the same way.
- `GET /agent/engines` reports the resulting support per instance and model:
  `instances[].attachmentsSupported` (boolean) and
  `instances[].models[].inputs = {"image": bool|null, "file": bool|null}`.
  A `null` mark is unknown and must be treated as unsupported by clients.

Company-funded runs reserve a conservative attachment estimate
(`2048` tokens per image, `4096` per document, `8 + ceil(bytes / 4)` per inlined
text) on top of the one-token admission sentinel; measured provider usage
replaces it on settlement. Personal funding stays record-only.

## Quota policy and managed engines

`GET /agent/usage/me` returns the owner's current IANA-day company and personal
balances: consumed, reserved, legacy carry and nullable available tokens. The
`budget` field on the engine catalog uses that same shape. `null` limits are
unlimited; zero denies admission. Human `system.providers` authority controls
installation defaults, per-user overrides, reports and audited resolution.
See [ai-usage.md](ai-usage.md) for policy, day boundaries and reconciliation.

Before each built-in provider request, SQL atomically reserves the configured
input-context bound plus enforced output maximum. Without a declared context
bound, enforcement is explicitly admission-only; the output cap is not a claim
that arbitrary input is bounded. Model retries and tool loops obtain separate
reservations. SDK cache and reasoning counters remain subsets, not additional
tokens. Ordinary users retain the isolated worker; quota messages cross its
validated broker protocol without granting database or actor authority.

External instances choose `quotaMode: managed|direct`. Company-funded direct
execution requires the administrator's explicit `directCompanyException`.
Managed execution requires an enabled global provider, allowlisted model and
positive `managedContextTokens`; its generated disposable profile/environment
contains opaque gateway/MCP credentials, not the upstream key. This is not a
host-filesystem sandbox. Configure `ITSM_AI_MANAGED_GATEWAY_URL` to the reachable gateway
base ending `/api/v1/agent/gateway/v1`, `ITSM_AI_MANAGED_HERMES_BINARY` and/or
`ITSM_AI_MANAGED_OPENCODE_BINARY`; optional `ITSM_AI_MANAGED_PROFILE_ROOT`,
`ITSM_AI_MANAGED_STARTUP_TIMEOUT_SECONDS` and
`ITSM_AI_MANAGED_SHUTDOWN_TIMEOUT_SECONDS` govern owned profiles and lifecycle.
No missing configuration falls back to a shared or direct engine.

The instance `quota` DTO states the actual enforcement and its reason. Managed
native execution is **admission-only**, not network-strict: gateway-only egress
is not established by a fresh profile. See [ai-gateway.md](ai-gateway.md) and
[ai-managed.md](ai-managed.md). Cancellation, disconnect and elapsed time never
prove an unbilled outcome and never automatically refund unresolved holds.
Usage events retain nullable input/output/cache/reasoning counts, precision,
provenance, inclusion flags and estimation method; see
[ai-usage-evidence.md](ai-usage-evidence.md).

## AI providers

A signed-in person can select the built-in Pydantic instance or an enabled
OpenAI-compatible provider record. A provider is never a new engine: the
existing `pydantic` engine lists it as another selectable instance, and the
session keeps its transcript when the instance or model changes.

Provider DTOs expose `id`, `name`, `scope` (`global` or `personal`), `baseUrl`,
`models` (the offered list a session may select), `modelSelection`,
`discoveredModels`, `modelCapabilities`, `discovery`, `credentialConfigured`,
`credentialStatus` and `enabled`; the API key is write-only in `POST`/`PATCH` and
is never read back or included in errors. The list
response also reports `canManageGlobal`, `canManagePersonal` and
`credentialStorageAvailable`. `credentialStatus` is `missing` (no stored key),
`primary` (readable with the active key), `older` (readable only through an older
ring key), `unreadable` (no configured key reads it) or `unavailable` (this process
has no key ring). It reports readability only; no key, plaintext or ciphertext is
returned.

- Global records require complete administrator authority and are visible to
  every signed-in person. Personal records require the
  `agents.providers.personal` permission, held by the built-in Admin and User
  profiles (operator and custom roles only when granted explicitly), are
  visible only to their owner and cannot be modified or deleted by another
  person. Calls funded by a personal provider are record-only for the quota
  ledger: they are attributed and reported but never denied by a daily token
  limit (see `docs/backend/ai-usage.md`).
- A personal `baseUrl` must be public HTTPS. The guarded transport resolves and
  pins a public address on every connect, keeps TLS hostname verification on
  the original host, and disables redirects and environment proxies. A global
  record may target a trusted loopback/private endpoint.
- A deployment may authorize specific private personal destinations with
  `ITSM_AI_PERSONAL_PRIVATE_ENDPOINTS`; see
  [Private personal endpoints](#private-personal-endpoints). Entries are
  opt-in, and the default (blank) setting keeps personal providers public-only.
- Provider credentials are sealed with Fernet through a key ring supplied only
  by the process environment (`ITSM_AI_CREDENTIAL_KEYS`, legacy
  `ITSM_AI_CREDENTIAL_KEY`). The first ring entry encrypts, later entries only
  decrypt; the legacy key is appended as a decryption-only entry when it is not
  already listed. Keys are never stored in the database, logged or returned.
  Without a ring, provider records with a credential cannot be created or
  rotated and the API returns a clear `503` unavailable error; keyless provider
  records remain usable and stored credentials are reported as unreadable.
- Rotation, status and backups are operator commands, described below. A backup
  records key *fingerprints* only, so a restore can tell an operator that the
  current ring no longer reads the restored credentials.
- The server resolves the endpoint and credential when a turn starts; chat
  requests never accept provider URLs, models or keys. Each turn builds a
  transport matched to that selection's authority (guarded for personal,
  private-capable only for global) and closes it on success, error or
  cancellation, so a personal turn can never reuse a global provider's pool.

```json
{
  "id": "...",
  "name": "NOC gateway",
  "scope": "global",
  "baseUrl": "https://gateway.example/v1",
  "models": ["model-a"],
  "modelSelection": "auto",
  "discoveredModels": [{ "id": "model-a", "inputModalities": ["text", "image"] }],
  "modelCapabilities": {
    "model-a": { "image": true, "file": null, "source": "provider" }
  },
  "discovery": { "code": "ok", "checkedAt": "2026-02-01T10:00:00Z", "count": 1 },
  "credentialConfigured": true,
  "credentialStatus": "primary",
  "enabled": true
}
```

### Model discovery

Every provider, global or personal, discovers its models from the endpoint itself
instead of relying on a hand-written list. Discovery performs the same bounded
`GET {baseUrl}/models` request as
[Checking a provider](#checking-a-provider): one 10 s timeout, a 64 KiB response
cap, no redirects, no environment proxies, and the same destination policy a chat
turn would use (guarded for a personal record, owner-trusted for a global one).
It runs when a provider is created, when `PATCH` changes `baseUrl` or `apiKey`,
and on every check request.

A failed discovery never blocks saving. The row keeps the closed code in
`discovery.code`, the time in `discovery.checkedAt` and no ids; the credential,
the upstream body and the resolved address stay internal.

- `modelSelection` is `auto` (default when the request sends no `models`) or
  `manual`. A request that still sends only the historical `models` list keeps
  the manual behavior it meant before discovery existed, so an existing client
  and a migrated row behave exactly as before.
- `models` is always the offered list used by sessions, the built-in instance,
  managed leases and the agent tools. In `auto` mode it is the first 50 discovered
  ids in endpoint order; in `manual` mode it is the owner's stored list.
- `discoveredModels` holds up to 500 entries of `{ "id": ..., "inputModalities":
  [...] | null }`. `inputModalities` is what the endpoint reports (OpenRouter's
  `architecture.input_modalities`, or a flat `input_modalities`/`modalities`
  list), or `null` when it reports none. Ids are trimmed, deduplicated
  case-insensitively and bounded in length.
- `modelCapabilities` maps each offered or discovered model id to
  `{ "image": bool | null, "file": bool | null, "source": ... }`. `source` is
  `owner` when the owner set a mark, `provider` when the mark comes from the
  reported modalities, and `unknown` when neither exists. Reported modalities win
  unless the owner overrides them.
- In `manual` mode a submitted list must stay a subset of the discovered ids
  whenever the last discovery succeeded; otherwise the API answers `422`. When
  discovery did not succeed, free ids are accepted so a temporarily unreachable
  endpoint does not lock an owner out.

`POST`/`PATCH` accept `modelSelection` and owner marks in
`modelCapabilities` (bounded to the same model ids, booleans or `null` for
`image` and `file`) next to the existing fields; unknown fields are still
rejected. Migration `0033_provider_model_discovery` adds the discovery columns and
moves every provider that existed before it to `modelSelection: "manual"`, so
pre-existing configured lists keep working.

### Credential key ring and rotation

`ITSM_AI_CREDENTIAL_KEYS` is a comma-separated Fernet key list; the first entry
encrypts and every later entry only decrypts. `ITSM_AI_CREDENTIAL_KEY` remains a
supported single-key setting: when both are configured the legacy key is
appended to the ring for decryption without becoming the encrypting key. An
exactly blank value (for example a Compose variable exported empty) disables
credential storage; a malformed entry fails configuration with a message naming
its position and never echoing the key text.

Generate a key with the maintained library, never a hand-rolled secret:

```bash
python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

Rotate without downtime: the old key stays in the ring for decryption while the
new key encrypts.

```bash
# 1. add the new key first and inspect what the ring can read
ITSM_AI_CREDENTIAL_KEYS="<new>,<previous>" python -m itsm.credentials status
# 2. preview, then re-encrypt every stored provider key and unexpired managed
#    gateway lease onto the new primary key
ITSM_AI_CREDENTIAL_KEYS="<new>,<previous>" python -m itsm.credentials rotate --dry-run
ITSM_AI_CREDENTIAL_KEYS="<new>,<previous>" python -m itsm.credentials rotate
# 3. drop the previous key once status reports no "older" rows
ITSM_AI_CREDENTIAL_KEYS="<new>" python -m itsm.credentials status
```

`status` counts stored ciphertext per table and scope as `primary`, `older` or
`unreadable`, prints the active key fingerprints and exits `1` while any row is
unreadable. `rotate` is transactional and idempotent: rows already readable with
the primary key are left byte-identical, and a row no configured key can read is
reported and left untouched, never deleted. Neither command prints a key, a
plaintext credential or a ciphertext. Back up the key ring separately from the
database, as described in
[ops-backup-restore.md](ops-backup-restore.md#ai-credential-keys).

`PATCH /agent/providers/{id}` updates the name, endpoint, models, enabled flag
or credential. The scope is immutable: sending a `scope` different from the
stored value is rejected with `422` instead of being silently ignored, while
echoing the current scope is accepted. The same endpoints therefore cannot be
promoted from personal to global or demoted from global to personal in place;
create a new record with the required authority instead.

### Private personal endpoints

Personal providers reach public HTTPS destinations only, unless the deployment
authorizes specific private destinations with
`ITSM_AI_PERSONAL_PRIVATE_ENDPOINTS`. The value is a comma-separated list of
CIDRs and/or exact `hostname[:port]` entries; an exactly blank value (for
example a Compose variable exported empty) means the allowlist is disabled.

```bash
ITSM_AI_PERSONAL_PRIVATE_ENDPOINTS="192.168.50.0/24,ollama.internal:11434"
```

- A malformed entry (`10.0.0.0/33`, `models.internal:0`, a URL, a wildcard or
  `*.local`) fails configuration at startup instead of being ignored.
- Allowlisted entries may use `http` as well as `https`. Ordinary public
  endpoints keep requiring HTTPS.
- A CIDR entry authorizes resolved addresses inside it. An exact hostname entry
  authorizes that host on the listed port (or any port when omitted), but the
  resolved address must still be private or public rather than loopback,
  link-local or cloud metadata.
- Loopback (`127.0.0.0/8`, `::1`), link-local and cloud metadata
  (`169.254.169.254`, `fd00:ec2::254`, `100.100.100.200`) are refused unless a
  CIDR entry explicitly includes that exact range. Do not add `0.0.0.0/0`,
  `169.254.0.0/16` or `::/0`: that hands every personal provider the host
  network and the instance metadata service.
- The decision is made at connection time on the resolved addresses. Every
  resolved IP must be public, inside an allowlisted CIDR, or covered by an
  allowed hostname entry and not loopback/link-local/metadata. TLS hostname
  verification stays on the original host name, redirects are never followed
  and environment proxies are ignored.
- Global providers keep the owner-trusted behavior: an administrator may point
  one at a loopback or private endpoint without any allowlist entry.
- Managed gateway leases for the personal scope carry no private-network
  authority of their own. The gateway re-derives the policy from the current
  settings each time it forwards, so removing an entry also stops an
  already-issued lease from reaching that destination.
- The isolated worker receives the resolved allowlist as part of the start
  message and re-applies the same policy before connecting, so moving execution
  into a container does not widen what a personal provider may reach.

### Checking a provider

`POST /agent/providers/{id}/check` verifies a stored credential and endpoint
without re-showing or changing the key, and stores the discovery result described
in [Model discovery](#model-discovery). It performs one bounded `GET
{baseUrl}/models` (10 s timeout, 64 KiB response cap) through the same guarded
transport as a chat turn. Authorization matches reading the provider: the owner
for a personal record, the provider-management permission for a global one.
Another person's personal provider answers `404` exactly like a nonexistent id.

```json
{
  "ok": true,
  "code": "ok",
  "modelCount": 2,
  "checkedAt": "2026-02-01T10:00:00Z",
  "provider": { "id": "...", "models": ["model-a", "model-b"], "discovery": { "code": "ok" } }
}
```

`provider` is the refreshed provider DTO, so a client sees the new offered list
without a second request. `code` is one of `ok`, `unauthorized`, `unreachable`, `blocked_address`,
`redirect`, `invalid_response`, `credential_unavailable` or `timeout`;
`ok`/`code`/`checkedAt` are always present and `modelCount` only for `ok`. The
response never contains the credential, an upstream response body or a resolved
address, and a check records no usage or quota: it sends no tokens and only
echoes the closed status code. The route is a CSRF/origin-guarded mutation and
requires a signed-in person; a missing credential storage or stored secret
answers `200` with `ok: false` and `code: credential_unavailable`.

`PATCH /agent/sessions/{id}` accepts `{"model": "..."}`, `{"instanceId": "..."}`
or both. Switching between the built-in instance and a provider starts a fresh
external engine identity while reusing the same ITSM session id and persisted
transcript; switching only the model keeps the current instance. An
instance-only switch resolves the model from the target: a provider keeps the
current model when the target declares it and otherwise uses its first declared
model; the built-in instance uses the server-configured model; an external
instance prefers its configured `defaultModel`, then the current model when the
target exposes it, then the first exposed model. Unknown or disabled instances
and models outside the provider's offered list are rejected.

The switch is applied with an atomic conditional update against the original
instance, model, status and version. If a turn reservation or another switch
commits first, the request returns `409` and leaves both the session and the
turn untouched. Starting a turn uses the same conditional reservation, so a
switch and a turn can never both claim stale session state.

## Installation API

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/agent/integrations/targets` | Detect engine/version/profile at a local path |
| `POST` | `/agent/integrations/install` | Install/verify/export; body has `mode` `local` or `remote` |
| `GET` | `/agent/integrations/installations/{id}/request` | Read an exported remote request |
| `POST` | `/agent/integrations/receipts` | Import a helper receipt and re-verify |
| `GET` | `/agent/integrations/catalog` | Official skills and registered modules |
| `GET` | `/agent/integrations/modules` | Module state |
| `PUT` | `/agent/integrations/modules/{id}` | Enable/disable a module |

Installation records expose a canonical shape:

```json
{
  "id": "...",
  "instanceId": "...",
  "target": {"engine": "opencode", "path": "/srv/opencode", "profile": "itsm", "version": "2.1.2", "remote": false},
  "skills": ["itsm-inventory"],
  "mcp": {"url": "http://127.0.0.1:18080/api/v1/mcp", "secretRef": "ITSM_MCP_TOKEN", "identityId": "..."},
  "status": "verified",
  "verified": true,
  "mcpVerified": true,
  "profileSafetyVerified": true,
  "checks": [],
  "conflicts": [],
  "binding": {"identityId": "...", "requestDigest": "..."},
  "requestDigest": null,
  "operation": "install",
  "managedFiles": [],
  "createdAt": "...",
  "updatedAt": "..."
}
```

`secretRef` is an environment variable name, never the secret value.

### Local installation

Local `mode` (the default) runs the installer in-process for one operation:
`install`, `update`, `repair`, `verify` or `uninstall`. The backend supplies an
in-process profile inspector; the installer invokes it after its managed writes
and trusts only that live evidence. A receipt is accepted as `verified` only
when the installer validates it, its MCP connection probe passes, and every
required profile-safety check passes. A caller-supplied safety mapping is never
treated as proof. OpenCode additionally must prove through its authenticated API
that the selected workspace has the `itsm` primary, non-hidden agent, the ITSM
MCP server URL, configured skills, deny-all permissions restricted to the exact
selected ITSM skills, no unsafe saved override, and the expected version.

OpenCode runtime inspection uses the instance's Basic-auth credential: the
configured `username` (default `opencode`) and the password resolved from the
instance `secretRef`. It requests `/api/config` and `/api/agent/itsm` for the
selected workspace location, `/api/permission/saved` and the location-scoped
`/api/skill`, and rejects a profile unless the evidence binds the active
configuration digest, workspace path, exact lowercase `mcp.servers.itsm` and
`itsm_*` tool actions. The config evidence must be exactly the selected
workspace's `.opencode` directory source plus its `opencode.json`/`opencode.jsonc`
document; system, global, ancestor or unrelated sources are rejected. The agent
must be `hidden: false`, and the selected skill inventory must include every
installed ITSM skill at its expected `.opencode/skills/<id>/SKILL.md` path.
OpenCode merges lower-priority and builtin rules ahead of agent rules and
evaluates the ordered list with last-match-wins semantics, so an earlier
builtin `allow` or `ask` is harmless when a later exact `*`/`*` deny shadows
it. Inspection therefore locates the last exact deny-all and validates only
the suffix that can still win: no ITSM or skill grant may follow it except the
configured `itsm_*` allow and the exact selected skill allows; any later
unselected grant or ask is rejected.
When OpenCode has not yet initialized its agent registry, inspection creates an
empty session for the selected workspace and deletes it immediately; it never
submits a prompt or model request. Receipt evidence contains only the projected
agent rules, workspace config keys, selected skill inventory and saved grants,
never provider or engine credentials.

A failed or incomplete install remains `configured` or `failed`; it is never
presented as verified.

`install`, `update`, `repair` and `verify` reuse the canonical skill names kept
in the installation binding when the request omits `skills`. Installer receipts
report selections as `{name, version, digest}` objects, so the binding and the
installation DTO normalize both that shape and plain name lists to the same
selected names; verification still compares those exact names with the managed
manifest. When a lifecycle operation fails or conflicts it reports that status
but keeps the previous binding, including skills, identity and integrity
digests, so an immediate retry verifies the same managed installation.

### Remote export and helper receipt

Remote mode applies the installer on another host. The backend never treats a
YAML-only claim as verified:

1. `POST /agent/integrations/install` with `"mode": "remote"` builds a signed,
   digest-bound request and returns the installation DTO with
   `status: "exported"`, `verified: false`, `request` and `requestDigest`.
   Nothing on the target host is modified.
2. The target-host helper applies the request, authenticates to the engine and
   inspects its live state. It returns a receipt containing at least
   `requestDigest`, `engine`, `profile`, `identityId`, `status`, `verified`,
   `profileSafetyVerified`, `checks`, and engine-specific evidence.
3. `POST /agent/integrations/receipts` with
   `{"instanceId": "...", "requestDigest": "...", "receipt": {...}}` binds the
   receipt to the exported installation (`installationId` remains accepted for a
   specific record). A digest or identity mismatch is rejected, then installer
   validation and the independent MCP probe run again.
4. Receipts are untrusted claims. The backend ignores claimed
   `profileSafetyVerified` and `profile.safety` checks and independently inspects
   the engine runtime for the selected profile before storing a receipt as
   verified. OpenCode inspection uses the authenticated `/api/config`,
   `/api/agent/itsm` and `/api/permission/saved` runtime endpoints. A receipt is
   stored as `verified` only when its bound validation, the independent MCP probe
   and this independent runtime inspection all pass; otherwise it is stored as
   `configured` with an explicit failing `control.profile` check. If the backend
   cannot inspect a remote engine (for example a remote Hermes runtime), it never
   promotes the receipt to verified based on receipt evidence alone.

Remote helper credentials are process-environment references. Receipts are
sanitized before storage; secret values never enter the database or API.

## Engine isolation and timeouts

`ITSM_AGENT_ENGINE_TIMEOUT_SECONDS` bounds discovery and short engine calls;
`ITSM_AGENT_RUN_TIMEOUT_SECONDS` bounds an external engine turn and sets the
stale-run threshold with a 60-second grace; `ITSM_AGENT_INSTALL_TIMEOUT_SECONDS`
bounds installer and remote-request work.
Timeouts and transport errors become sanitized availability errors. External
engine processes are never granted the backend's database, filesystem or
administrator credentials.

## Skills, modules and MCP visibility

The built-in catalog is the canonical `itsm-inventory` module with its declared
skills and tools. Every core and module tool calls canonical services and live
authorization; listing is not an authorization grant. Reader identities can
list the ordinary inventory operations their `assets.view` permissions support.
Authorized extension tools are gated at list time by their required permissions,
while a direct call still goes through the canonical authorization and audit.

Trusted deployment modules are exact dotted names, never browser input:

```text
ITSM_AGENT_EXTENSION_MODULES='["acceptance_extension"]'
PYTHONPATH=/opt/itsm/modules
```

Each installed distribution exposes one synchronous `register_extensions` entry
point. Invalid, duplicate, async or non-registering modules fail startup instead
of appearing installed. Persisted module disable is applied at startup and on
change through `SkillCatalog`, `ExtensionRegistry` and the FastMCP extension
mount, so skill and tool visibility change without restarting the process; the
official ITSM module cannot be disabled.

Installation resolves selected skills through that same live `SkillCatalog`
instance for both local application and remote request generation. A skill from
a registered module is therefore installable only while its module is enabled;
disabling the module hides it from the catalog and rejects new installs that
select it, without pretending earlier target files disappeared.

## Configuration

| Setting | Default | Meaning |
| --- | --- | --- |
| `ITSM_AGENT_ENGINE_TIMEOUT_SECONDS` | `15` | Discovery/engine call timeout |
| `ITSM_AGENT_RUN_TIMEOUT_SECONDS` | `180` | Stale-run recovery window (plus 60s grace) |
| `ITSM_AGENT_INSTALL_TIMEOUT_SECONDS` | `120` | Installer/remote request timeout |
| `ITSM_AGENT_DAILY_TOKEN_BUDGET` | `200000` | Initial company daily default until SQL policy is configured; `0` denies new company admissions |
| `ITSM_AGENT_SESSION_MAX_CONTEXT_MESSAGES` | `40` | Persisted context cap, `0`–`50` |
| `ITSM_AGENT_EXTENSION_MODULES` | `[]` | Trusted dotted module names |
| `ITSM_AI_CREDENTIAL_KEYS` | none | Comma-separated Fernet key ring sealing provider API keys; first encrypts, rest decrypt only. Absent/blank disables credential writes |
| `ITSM_AI_CREDENTIAL_KEY` | none | Legacy single Fernet key; appended to the ring for decryption when not already listed |
| `ITSM_AI_PERSONAL_PRIVATE_ENDPOINTS` | blank | Comma-separated CIDRs and/or exact `hostname[:port]` entries that authorize a personal provider to reach a private destination. Blank keeps personal providers public-HTTPS-only |
| `ITSM_AGENT_CONTEXT_TOKEN_BOUND` | none | Declared input billed-token bound per built-in/isolated call; absent means output-only admission, not strict counting |
| `ITSM_AI_MANAGED_GATEWAY_URL` | none | Opt-in managed native gateway base ending in `/v1` |
| `ITSM_AI_MANAGED_OPENCODE_BINARY` / `ITSM_AI_MANAGED_HERMES_BINARY` | none | Operator-supplied native executables; no install or fallback |
| `ITSM_AI_MANAGED_PROFILE_ROOT` | system temporary directory | Root for private disposable native profiles |
| `ITSM_AI_MANAGED_STARTUP_TIMEOUT_SECONDS` | `30` | Native startup deadline |
| `ITSM_AI_MANAGED_SHUTDOWN_TIMEOUT_SECONDS` | `10` | Each process-group termination wait |

Engine base URLs and credentials are stored as references, not values. OpenCode
uses HTTP Basic auth with `username` (default `opencode`) and the password
resolved from `secretRef`; Hermes uses the same `secretRef` as a bearer token.
Provider credentials are different: they are write-only API inputs sealed in the
provider row with the externally supplied key ring, never placed in the process
environment or in engine profile files.

## Effective runtime permission attestation

Independent OpenCode inspection evaluates agent rules followed by saved grants using last-match-wins semantics. Later denies of the required ITSM tools or selected skills prevent verification. Saved asks, malformed entries and broad allows also prevent verification; safe unrelated denies and narrow selected grants remain valid. This applies to fresh inspection used by receipt import without trusting a receipt alone.
