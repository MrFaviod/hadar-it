# Conversation and AI

The authenticated conversation can stay open while you work in the modules you are allowed to use. The compact panel and the **Conversation** page share one instance, draft and transcript; changing route does not resend messages or cancel the active stream.

This guide covers the user-facing conversation, engine and model selection, AI providers in **Settings → AI**, agent profiles and installations, and the daily AI quota. The transport and API contracts are in [Agent engines and integrations](agent-integrations.md).

## Open, expand and resume

1. Use **Open conversation** in the bottom-right corner. The panel starts closed and does not block the module with a modal backdrop.
2. Type and press **Send**. **Cancel** requests cancellation of the work in progress; errors and the state reported by the server are shown in the panel.
3. Use **Expand conversation** to open `#/conversacion`. **Back to compact chat** returns to the previous module with the same state.
4. **Close conversation** or `Escape` hides the compact panel and returns focus to the open button. Hiding the panel does not cancel a response.
5. In **Your conversations**, choose one of your conversations to read its transcript from the server. **New conversation** starts another conversation without resending the previous one. If a response is active, let it finish or cancel it before switching conversations.
6. Long responses scroll inside the compact panel without overlapping the tools or the composer, which stays reachable on small screens.

Signing out, switching users or unmounting the application aborts local requests and erases the private conversation state. Late responses cannot restore it. The server keeps authority over identity, permissions and ownership of each conversation.

### Asset context and demo data

- Using an asset as context requires a canonical record received from the server. You can also choose a known asset in **Asset in context (optional)** or open its explicit conversation route.
- A URL with a UUID does not, on its own, turn a demo record into valid context. The record is read through the existing inventory adapter.
- Demo alerts are not presented as an integration with the agent or with a monitoring backend.

## Engines, models and preferences

Choose an enabled engine and one of its explicitly announced models. If a conversation already exists, the change uses `PATCH /agent/sessions/{id}` on the same identifier and keeps the transcript. No new conversation is created to hide a server rejection. Earlier tool calls are not replayed.

**Engine** shows one option per external engine and **Profile** chooses an authorized profile of that engine, only when the server announces more than one. Options are derived from authorized instances (name or profile), never from client paths, endpoints or credentials. Changing profile applies the same `PATCH` to the same ITSM session: it keeps messages, draft and identifier, and restarts only the engine's native session; it does not change the global Hermes profile. The conversation preference in **Settings → AI** uses the same Engine/Profile grouping and applies only to new conversations. Each Pydantic provider, global or personal, keeps its own engine option.

The user's saved preference is the starting value for a new conversation. Resuming a conversation keeps its own engine and model without replacing that preference; it also does not silently switch to another model if the conversation's model becomes unavailable. The selection does not widen the user's permissions or the integration profile's limits.

The compact panel gives priority to the transcript and the composer. Capabilities and the budget explanation stay in the full view. Engines without models, discovery failures, missing credentials and rejections are shown as such; a successful response is never simulated. If the server does not offer the sessions API, the existing earlier chat route is kept, without inventing an engine's availability.

### Usage of the last call

`#conversation-usage` shows only the last usage event received, not the total for
the run. Precision (`measured`, `estimated`, `unavailable`) is shown separately
from source (`provider`, `engine`, `estimate`, `none`); provider and engine are
valid sources, not unknown precisions. Input, output, cache read, cache written,
reasoning and total keep their null values as **Not available**, without turning
them into zero or adding already-included components again. The server's flags
state whether cache is already included in input and reasoning in output; the
total states its source and an estimate shows its method. Daily balances and
reports, not the last stream event, represent accumulated usage.

## Providers in Settings → AI

OpenAI-compatible providers are shown in the existing AI panel and used through the **Pydantic AI** engine; they are not a separate engine. Their configuration does not replace the existing profile and installation wizard.

| Effective authority | Available controls |
| --- | --- |
| User without administration permission | Public status authorized by the server; no buttons to add, edit or delete. |
| `system.providers` permission and `canManageGlobal` capability | **Add global provider** and editing global providers. |
| Explicit `agents.providers.personal` permission and `canManagePersonal` capability | **Add personal provider** and editing your own providers. Not granted to the User role by default. |

The form asks for a name, endpoint, model identifiers — one per line —, enabled state and an optional write-only credential. There is no fictitious model discovery. The server validates the URL and the authority: personal endpoints must be public HTTPS, with no private destinations or redirects; global configuration keeps the operator's policy.

The credential is never returned in the response or preloaded when editing. Leaving it empty when editing keeps the existing one. Only **Credential configured** or **No credential** is shown. If `credentialStorageAvailable` is false, the field is disabled with an explanation that `ITSM_AI_CREDENTIAL_KEY` is missing on the server. The server's specific error messages stay visible. Switching users erases the metadata, interface permissions and any credential still typed in the form.

Deleting requires explicit confirmation. The panel refreshes from the server after saving or deleting; it never shows a local success when the operation failed.

## Profiles and installations

The existing wizard is kept: instance and profile choice, target detection, MCP configuration, skill selection and installation/verification. A configured profile or an exported remote request is not a verified profile. The interface shows the server's and the receipt's verification result and limits, without fabricating a verified result.

OpenCode selects a workspace, and the **Profile** field shows, disabled, the profile registered on that instance: the wizard sends exactly that profile, or none if the instance declares no profile, and never substitutes another. Hermes keeps the editable selection of named profiles. The expected version must match the engine being verified.

An isolated check on 27 October 2026 ran the wizard from Settings for OpenCode 2.1.2 and two dedicated Hermes 0.22.5 profiles. All three results persisted **MCP: verified · Profile: verified**, the `itsm-inventory` skill, 63 authorized tools and a non-mutating `search_assets` query. In addition, with the real provider configured, one conversation moved from Hermes to OpenCode and to the second Hermes profile, completed an authorized query at each step and kept its six turns. A regular user completed the flow with Pydantic AI 2.59.0 and was offered no external engines. These are isolated development checks, not a production certification.

## Checks and selectors

The focused component command is:

```sh
node --test tests/conversation.test.cjs tests/agent-integrations.test.cjs tests/contextual-chat.test.cjs
```

These tests run the real Vue components and simulate only the HTTP boundary. They cover continuity while navigating, isolation by identity, resuming and switching session/engine/model, provider authority, and handling of credentials and errors. On their own they do not test the visual layout, a real external engine, the security of backend storage or an installation on a real profile.

For the browser check in both themes and on small screens:

- Open/close and focus: `#conversation-opener`, `#conversation-surface`; after `Escape`, wait for the next render before checking focus.
- Format change: `#conversation-expand`, `#conversation-collapse`; keep draft, transcript and active response while navigating.
- Selection: `#conversation-session`, `#conversation-engine`, `#conversation-profile`, `#conversation-model`, `#conversation-asset`, `#conversation-input`.
- Canonical context: `#conversation-use-asset` on the record of an asset received from the server.
- Provider authority: `#provider-new-global`, `#provider-new-personal`; missing buttons must not reappear when switching accounts.
- Form: `#provider-form`, `#provider-name`, `#provider-url`, `#provider-models`, `#provider-key`; the credential field must be empty when editing and absent from the read state.

Browser verification, the full suite and real engines/profiles are separate checks. Their success is not inferred from these component tests.

## Daily AI quota

The conversation and the preferences panel show your own daily balance as
returned by `GET /api/v1/agent/usage/me`: company and personal funding
separately, with consumed, reserved, available, pending holds, unattributed
legacy and precision. **Unlimited** and zero tokens with no admission are
distinct states; missing data is shown as **Not available**, never as zero. The
active context highlights only the funding the server declares for the provider
scope of the instance: a personal key is not presented as company and, without
a scope, the balance is not attributed. The **Refresh quota** button, the end,
cancellation or failure of a stream, window focus and returning to the tab query
again; there is no continuous polling and the browser never rolls the day over
on its own. Signing out or receiving `401` clears the balances, and a late
response for the previous account is discarded.

In **Settings → AI**, the daily policy, overrides and report require
`system.providers` on a human account. You can set a company limit and a
personal one, choose unlimited or zero, change the time zone and cancel a
pending change before it applies. Overrides apply to a real account and one
funding source; **Inherit** removes the override and is different from setting
an explicit unlimited or zero. The account picker uses the existing list with
`users.view`; without that permission the interface asks for the UUID and warns
that a username does not work as an identifier. The report respects the
server's filters, grouping and totals, shows nulls as not available, does not
sum cache on the client, does not paginate locally, and separates pending holds
from settled usage and unattributed legacy.

An engine's strict state is shown only if its DTO declares `mode: managed` and
`enforcement: strict`; if the DTO is missing it is shown as unavailable and not
strict, never deduced from the engine name or the proxy mode. Holds are not
released from this interface. The instance editor and the wizard let you choose,
only with `system.providers`, managed mode with an enabled global provider, an
exact default model and a positive input context limit declared by the
operator; or direct mode with an explicit company exception. That exception does
not make direct mode strict. The output limit stays configured on the server;
the interface neither deduces it from the model nor claims network isolation.
