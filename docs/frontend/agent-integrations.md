# Agent engines and integrations (frontend)

The conversation view uses one interface for the Pydantic AI, Hermes and OpenCode engines. The browser only carries messages, bounded context, the engine and model selection, and the identifier of a persisted asset. Provider URLs, tokens and session authorization stay on the server.

This guide covers the conversation routes, the streaming transport, the **Settings → AI** screens, the daily AI quota views and their limits.

## Routes

- `#/conversacion`: the conversation. Engines load from `GET /api/v1/agent/engines`; when that additive endpoint does not exist (`404`), the compatible `POST /api/v1/agent/chat` conversation is kept. Every discovery failure is shown with the instance and the server's public message; an instance without models does not replace the saved selection.
- `#/configuracion/ia`: the conversation preference and, for administrators, instances, catalog, installations and the integration wizard. The route resolves through `window.AssetAgentViews.routeOverride` without forking the main router.
- `#/configuracion/ia` requires `assets.view`: the conversation and model preference stays available to any authenticated user. Managing instances, catalog, installations and the wizard requires `system.providers`, and changing a module also requires `system.modules`. The UI neither grants nor infers permissions: it shows the server's error.

## Transport

Every call uses `window.AssetAccess.request`/`stream` with the same-origin session and the CSRF token. `EventSource` is not used because sending is a `POST` with a body and a cancellation signal.

- `PUT /api/v1/agent/preferences` `{instanceId, model}`.
- `POST /api/v1/agent/sessions` `{instanceId, model, context?, assetId?}`.
- `POST /api/v1/agent/sessions/{id}/messages` `{message, assetId?}`: `text/event-stream` response.
- `PATCH /api/v1/agent/sessions/{id}` `{model}` or `{instanceId, model}`: the server re-authorizes the target instance, rejects the change while the session is running, and keeps the conversation identifier and transcript.
- `GET /api/v1/agent/sessions/{id}`: snapshot for reconnection.
- `POST /api/v1/agent/sessions/{id}/cancel`: no body.

SSE events use `data: {json}` terminated by an empty line. `delta.text` is **a new fragment to append**; the server adapter compares the provider's accumulated responses before emitting, so a repeated accumulated response does not duplicate text. Supported types are `session`, `delta`, `tool`, `usage`, `error` and `done`. `done` keeps `actions`, `results` and `approvalPending` besides `cancelled`, so the existing cards still render.

The client:

- Accumulates fragments without interpreting HTML; text is interpolated, never rendered as markup.
- Shows tools, usage of the last call (`precision: measured|estimated|unavailable`) and engine errors without inventing an answer.
- Sends as context only the recent history (at most 20 turns) and an `assetId` UUID chosen among assets the server has already returned in this session.
- When the engine or profile changes, applies `PATCH` to the **same** ITSM session: messages, draft and identifier are kept and only the engine's native session restarts; it never starts another conversation or resends history. Changing the model without changing the instance applies the same `PATCH`.
- **Engine** shows one value per external engine and **Profile** its authorized profiles; the profile selector appears only when the server announces more than one. Options and labels come from discovered instances (name or profile), never from endpoints, directories or credentials. Each Pydantic provider, global or personal, keeps its own engine option. If the `PATCH` fails, the selection returns to the value the server confirms.
- Shows **Cancel** during the whole processing, including while the session is being created; once created it calls the cancellation endpoint. If the engine cannot be interrupted, it shows the server's reason.
- After a dropped connection it does not resend the message automatically. It offers **Reconnect and check status**, which replaces the transcript with the server snapshot; text, actions and usage are not duplicated.

The saved preference is corrected when the instance or model no longer exists. The model list always comes from the connected instance; the client has no catalog of free models. If the engine DTO does not declare a strict budget, the UI does not present one.

The `usage` event keeps `precision` and `source` (`provider|engine|estimate|none`) separate. **Last call** shows the input, output, cache read/write, reasoning and total values received, without summing them in the browser or presenting them as the total for the run. Missing or `null` components are shown as unavailable; an explicit zero stays zero. The `inputIncludesCache` and `outputIncludesReasoning` flags state whether those components are already part of input and output, so they are not counted twice. `totalSource` distinguishes the provider's total from one derived by the server; `estimationMethod` shows the reported method when there is an estimate. The daily quota and reports remain the authority for accumulated usage, not this last stream event.

## Settings → AI

- `GET /api/v1/agent/integrations` returns instances, installations with `target:{engine,path,profile,version,remote}`, verification status, bindings and defaults. The UI consumes that canonical shape; `verified` is only taken from the server.
- `GET /api/v1/agent/integrations/catalog` returns skills and modules. The official classification comes from `module.official === true` and from the `module` each skill declares: the canonical module is `itsm`. The **Official package** section groups those skills; **Modules** shows only external modules, and the official module offers no disable action. Only enabled modules offer their skills.
- `POST/PUT /api/v1/agent/integrations/instances` sends `{name,engine,baseUrl,secretRef,username?,profile?,directory?,defaultModel?,integrationIdentityId?,enabled}`. Only the **name** of the secret reference travels, never its value. If the server rejects the configuration, the UI shows the safe message and the fields the server reports (for example, an unconfigured secret reference), without secret values.
- `PUT /api/v1/agent/integrations/modules/{id}` `{enabled}`. Requires `system.modules`; the official module cannot be disabled (`409`).
- `POST /api/v1/agent/integrations/targets` `{engine,path,profile?,version?}`: an explicit absolute path; the server does not scan the home directory. The canonical response is `{target:{engine,path,profile,version,remote},detection:{engine,format,version,profile,targetPath,configFile,configExists,skillsDirectory,limitations}}`. The wizard only accepts that complete envelope: it requires a matching engine, absolute paths, version/format, config file and skills directory, a boolean `configExists` and text limitations. `configExists:false` is a valid target whose configuration will be created. A `200` without those fields is shown as an error and is never turned into an installable target by inventing `detected:true`.
- `POST /api/v1/agent/integrations/install` with `{instanceId,target:{engine,path,profile?,version?,remote?},mcp:{url,secretRef,identityId},skills,operation:"install"}`. A remote target also sends `mode:"remote"`; that field, not `target.remote`, selects the flow on the server. An OpenCode `profile` is never typed in the wizard: the one registered on the instance is reused (`null` if it declares none), while the Hermes profile stays editable. The response is the canonical installation DTO (`id,instanceId,target,skills,mcp,status,verified,mcpVerified,profileSafetyVerified,checks,conflicts,binding,requestDigest,operation,managedFiles,createdAt,updatedAt`, plus `request` when applicable and `error:{code,message}`/`limitations` when the server sanitizes a failure). The UI keeps it as is, shows that message and those limitations instead of a generic sentence when they exist, keeps the generic sentence when there is no `error`, reads the version from `target.version` and never infers `verified`. A remote installation returns `status:"exported"`, `verified:false`, `request` and `requestDigest`.
- Local inspection belongs to one concrete target: the wizard stores a snapshot of `engine`, `path`, `profile` (normalized as in the request), `version` and `remote`. Installing locally requires that snapshot to still match the current target and to come from `POST /targets`, not from a hand-assigned `detection`. Changing any of those fields invalidates the inspection and requires repeating it; step 2's `canNext` applies the same rule. Each inspection carries a generation counter: a late response is discarded without setting `detection`, `version` or a valid-envelope error, and cannot enable a later installation. A remote target still exports the request without local inspection; switching back to local requires a new inspection.
- Lifecycle operations (`verify`, `update`, `repair`, `disable`, `uninstall`) send only `{instanceId,target,operation}`: the server resolves the saved binding and secret; the UI does not resend tokens or skills.
- `GET /api/v1/agent/integrations/installations/{id}/request` retrieves the remote request.
- `POST /api/v1/agent/integrations/receipts` `{instanceId,requestDigest,receipt}` imports the receipt issued on the remote host. The server rejects a non-matching digest and only returns `verified: true` after validating the receipt and independently checking MCP and profile safety.

The five-step wizard opens automatically only on first registration (no installations and no external instances). It supports a new or existing instance, profile/environment, a real check of the target, an MCP server with a machine identity, and explicit skill selection. A remote installation generates a JSON request and does **not** claim the target is installed: only a receipt verified by the server can show `verified: true`. The helper command is:

```bash
python -m itsm.agent_integrations --request <ruta del archivo>
```

"Installed" is never shown on the strength of the request, of files being written, or of a receipt without MCP connection verification.

## Security and limits

- The browser receives no engine tokens, MCP secrets or provider configuration, and stores none of them in local storage.
- Conversation requests carry no arbitrary endpoint URL: the `instanceId` is resolved on the server.
- Effective permissions are those of the integration identity; changing engine, model or skill does not widen privileges.
- The daily token quota is presented with the server's classification. External engine usage is shown separately because it may not be interruptible before processing.
- Server errors are shown with their public message; raw provider exceptions are not exposed.

## Focused tests

From `frontend/`:

```bash
node --test tests/conversation.test.cjs tests/agent-integrations.test.cjs
```

They cover, among others: dynamic discovery and correction of a vanished model, streaming by exact fragments, classified usage, action/result cards, engine/model changes, cancellation, reconnection without duplication, budget and its warning, the `#/configuracion/ia` route, permissions, the wizard, the canonical `{target,detection}` envelope and rejection of an incomplete `200`, exact installation, the canonical DTO in installation and lifecycle, remote request/receipt, and a server rejection without claiming installation. The code lives in `assets/js/{conversation,agent-integrations,access,app}.js` and `assets/css/{conversation,agent-integrations}.css`.

## Daily AI quota

The client uses only the server's quota endpoints through `AssetAccess.request` (existing cookie, `Origin` and CSRF); it stores no quotas, balances or keys in local storage and does not roll the day over in the browser.

| Endpoint | Use |
| --- | --- |
| `GET /api/v1/agent/usage/me` | Own balance per `company`/`personal` funding, with the day and time zone reported by the server. |
| `GET /api/v1/agent/usage/policy` | Daily policy, pending time zone and overrides. Authority: `system.providers` on a human account. |
| `PUT /api/v1/agent/usage/policy` | Company and personal limits, time zone and `{cancelTimezoneChange:true}`. |
| `PUT /api/v1/agent/usage/overrides/{userId}` | Override per real account and funding; `{dailyLimit:null}` is explicit unlimited and `0` denies sending. |
| `DELETE /api/v1/agent/usage/overrides/{userId}?scope=company\|personal` | Inherits the policy; different from an unlimited or zero override. |
| `GET /api/v1/agent/usage/report` | Report with filters, grouping, totals and provenance reported by the server. |
| `GET /api/v1/agent/usage/pending?limit=100` | Pending or unresolved holds; they are not settled usage. |

Policy and report are offered only with `system.providers` and a human identity; the administrator role or `users.edit` do not grant that authority. To choose the account for an override, the existing user list is used when the session has `users.view`; without that permission a bounded UUID is requested, with a warning that a username does not identify the account. A name is never sent as if it were an identifier.

`null` means unlimited and `0` means explicit denial; a missing value means not reported, not zero. The interface forces a choice between unlimited and a non-negative integer and keeps both as distinct states. Usage, reserved, pending, available, legacy and precision fields reflect exactly what is returned: nulls are shown as **Not available**. The cache total is not summed on the client, the report is neither paginated nor recalculated locally, and unattributed legacy rows are marked as such instead of being assigned to a company or person.

A time zone change stays pending until the next safe daily boundary and can be cancelled; the client does not simulate the day change. The personal view shows both balances when the server returns them, but highlights only the funding declared by the provider scope of the active instance. Company is not assumed for a personal key. If the server does not report the scope, the balance is not attributed. The balance refreshes when a stream finishes, is cancelled or fails, when the window gains focus, when returning to the tab, and through the **Refresh quota** button; there is no continuous polling. Signing out, a `401` or unmounting discard the data, and a late response for a previous account cannot restore it.

The engine quota state is read only from `engineDTO.quota`: `{mode: managed\|direct\|builtin, enforcement: strict\|admission_only\|observed\|unavailable, reason, directException}`. Only `managed` + `strict` is presented as strict before sending. A missing DTO is shown as unavailable and not strict; it is never deduced from the engine name, the proxy mode or an aggregate SDK limit.

The existing instance editor and the wizard's new-instance step offer **Quota and routing** only with `system.providers` on a human account. `managed` mode requires an enabled global provider from the existing administrative list, the exact identifier of the default model, and a positive integer **Input context limit** declared by the operator within what the model and provider support. No ceiling is deduced from model metadata. The output limit stays in the server's installation configuration (`ITSM_AGENT_MAX_OUTPUT_TOKENS`), with no new browser control. `direct` mode offers an explicit exception checkbox for company work; leaving it unchecked does not authorize a paid company run. Direct quota is presented as observed, not strict. Choosing a mode does not prove network isolation and never replaces the server's `quota.enforcement` state. The four fields (`quotaMode`, `directCompanyException`, `managedProviderId`, `managedContextTokens`) travel through the existing instance transport; choosing direct clears the managed provider and limit with `null`, and choosing managed disables the direct exception. Without that authority the fields are neither offered nor added to the request body.

Current limits: there is no UI to release or reconcile holds, the report is not paginated on the client, and no network-isolation certification state is shown. Component tests cover permissions, zero versus unlimited versus missing, inheritance, real users, nulls, legacy rows, unsummed cache, pending holds, engine state, refresh and late responses; they do not replace browser verification or the full suite.
