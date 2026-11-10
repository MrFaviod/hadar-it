# External agent engines

`itsm.agents` is the transport-only boundary between ITSM chat and external agent
runtimes. It does not persist conversations, authorize people, execute tools, or
decide budgets. The runtime/service layer owns those concerns.

## Public contract

`EngineConfig` carries server-resolved connection settings:

- `base_url`: absolute `http`/`https` URL of the engine.
- `token`: bearer token. When set it takes precedence over basic auth.
- `username`/`password`: HTTP Basic auth credentials.
- `directory`: OpenCode workspace/location. Never supplied by chat input.
- `profile`: expected integration profile metadata. Hermes binds profiles through
  the authenticated API credential; there is no wire `profile` field.
- `agent`: OpenCode dedicated agent name, default `itsm` (additive). Set it to
  `None` only to let the server choose its default agent.

`EngineInfo` contains the discovered `version`, the live `EngineModel` list, and a
truthful `capabilities` mapping with the keys `streaming`, `sessions`,
`model_switch`, `cancel`, `tools`, `usage`, and `history`.

Neutral stream events are JSON objects with `type` set to `session`, `delta`,
`tool`, `usage`, `error`, or `done`. A `delta.text` is a new fragment to append,
not a cumulative snapshot: repeated fragments such as `"ha"` + `"ha"` represent
`"haha"` and are emitted verbatim. A `usage` event carries `precision` as
`measured`, `estimated`, or `unavailable`, and `source` as `provider`, `engine`,
`estimate`, or `none`. External-engine counts use `source: "engine"`; they are
reported by the engine, never provider-billed provider evidence. Unknown token
components are `null`, not zero. `totalTokens` carries `totalSource` as
`provider` when the engine supplied a total or `derived` when ITSM summed known
disjoint components. At most one usage event is emitted after a submitted turn,
including cancellation, disconnect, or failure. Tool events report `tool`,
`status`, optional `input`/`output`. The
adapter status values are `running`, `completed`, and `failed`; a failed tool is
never encoded as `error`, because the ITSM service treats `error` as a transient
state and rewrites it to `running`. The final event is `done` with `cancelled`.

Engine failures raise `EngineError(code, message, retryable)`. Public codes are
`unreachable`, `unauthorized`, `not_found`, `conflict`, `upstream`, `protocol`,
`model_unavailable`, and `unsupported`. Messages never include credentials,
provider response bodies, or raw exception text. Auth, base URLs, and paths are
validated before use; non-JSON `200` responses (for example the OpenCode SPA
fallback) are `protocol` failures, not a successful connection.

## Provider credentials per engine

External engines never receive a personal provider credential directly. The
engine matrix is:

| Path | Provider key location | Personal provider |
| --- | --- | --- |
| Pydantic AI (built-in) | resolved by `AgentIntegrationService` and used in-process or in the isolated worker's own client | yes, the owner's key only |
| Managed Hermes/OpenCode (`quotaMode=managed`) | sealed in the ITSM gateway lease; the disposable child holds only the run-scoped gateway key | yes, through the gateway, still per-run |
| Direct Hermes/OpenCode (shared instance) | the shared instance's own server-side credential/profile | never; a `providerId` selection is rejected with `422 validation_error` |

A managed session without a `providerId` uses the instance's managed global
provider. A personal selection is authorized against the session owner, so
another person's provider id is indistinguishable from a nonexistent one. The
shared-instance profile is never edited, copied or extended with a personal key,
and the disposable managed profile contains only gateway/MCP identities.

## OpenCode

The adapter selects a protocol from discovery:

- v2: `GET /api/info` must return JSON with a version and `capabilities`.
  Models come from `GET /api/model?location[directory]=...` (OpenAPI deepObject
  form). `free` comes only from the reported `cost` tiers, with no provider
  allowlist: every tier must report `input` and `output` plus the v2-required
  `cache.read` and `cache.write` prices, and any explicit `reasoning` price. All
  reported prices zero means `true`; any positive price means `false`; missing
  or malformed required metadata means `null`.
- v1: a 404 from `/api/info` falls back to `GET /global/health` and
  `GET /config/providers`. Health must be JSON, not the SPA HTML shell. The v1
  cost record requires `input` and `output`; optional `cache.read`/`cache.write`
  and explicit `reasoning` prices are included when present. v1 cache objects may
  validly contain only one of `read`/`write`; v2 cost tiers require both. The
  zero/positive/unknown classification is otherwise identical.

Authentication is bearer when `token` is set, otherwise Basic when both username
and password are set. OpenCode's dedicated server password uses Basic auth with
the `opencode` username. `directory` is sent only as OpenCode's location query
or session location.

### Sessions and agents

`create_session()` first tries the v2 `POST /api/session` shape and accepts its
nested `data.id`; v1 uses `POST /session`. For v2, the optional `agent` is sent in
the session-create body. Before every prompt the adapter explicitly posts
`{"agent": ...}` to `POST /api/session/{session_id}/agent` and requires `204`.
Agent binding failure aborts before the prompt is sent. A v1 message body also
includes the configured agent. This prevents a mutable session default from
silently changing the tool boundary.

`cancel(session_id)` posts the v2 interrupt endpoint or the v1 abort endpoint.
Only an explicit engine acknowledgment is reported as cancelled; client-side
cancellation is also reflected in the terminal `done.cancelled` event.

### Streaming

v2:

1. Open `GET /api/event` first.
2. Bind the dedicated agent and optionally switch the model.
3. Post the composed prompt.
4. Append documented `session.text.delta` fragments verbatim. `session.text.ended`
   carries a full snapshot, so only the unstreamed suffix is emitted.
5. Map tool events to neutral `running`/`completed`/`failed`.
6. Emit reported usage and terminal `session.idle`/error.

Every SSE envelope id is remembered across reconnects. A replayed frame with an
already-seen id is ignored; deduplication never compares text. Bounded reconnect
recovers without resubmitting a prompt. A clean EOF before a terminal event is an
`unreachable` recoverable failure.

v1:

1. Open `GET /event` first.
2. Post `{parts: [{type: "text", text: ...}], model?, agent?}` to
   `/session/{id}/message` once.
3. Text part updates are cumulative per part id, so only the suffix is emitted.
   Tool part states `pending`/`running`/`completed`/`error` become neutral
   `running`/`completed`/`failed` tools.
   Step-finish or message updates may carry reported tokens/cost.
4. `session.idle` is terminal; `session.error` emits a redacted error.
5. If the event stream disconnects, the same in-flight POST is awaited instead
   of resubmitted. The final message parts provide a snapshot fallback.

The adapter never exposes shell, filesystem, or general-purpose tools. Tool names
are only reported to the caller; authorization and execution belong to the
runtime.

## Hermes

Discovery starts at `GET /v1/capabilities`. A missing route falls back to
`GET /health` (JSON) plus `GET /v1/models`; any other failure is reported
truthfully. Capabilities are selected from advertised features, in this order:

1. `session_resources` and `session_chat_stream`: session transport with streaming,
   sessions, and tools; cancel is false because the documented session API has no
   stop route.
2. `run_submission` and `run_events_sse`: run transport; streaming is false because
   progress is event-based, sessions are false, and cancel follows `run_stop`.
3. `chat_completions`: stateless chat transport with streaming and optional tool
   progress events.
4. Otherwise `none`, with every capability false.

The legacy health/models fallback exposes only stateless chat capabilities.
Discovered models use the raw OpenAI-compatible model id and the provider from
`owned_by` (falling back to `hermes`); Hermes does not publish a free marker, so
`free` is always `null`.

Hermes authenticates with a bearer API credential. A profile is bound by that
credential on the server; the adapter never invents a `profile` request field.
`create_session()` calls `POST /api/sessions` only when the session feature is
advertised. Otherwise it returns an ITSM-local conversation id and never claims
an engine-side session.

- Session stream: `POST /api/sessions/{id}/chat/stream` with the composed input;
  `assistant.delta` is appended verbatim, commentary is ignored, tool events are
  mapped, `run.completed` supplies final text/usage, and failed/cancelled runs are
  terminal.
- Runs: `POST /v1/runs` then `GET /v1/runs/{id}/events`. `message.delta` and
  interim messages are intentionally ignored; final text and usage come from
  `run.completed`. Cancellation uses `POST /v1/runs/{id}/stop`.
- Chat: `POST /v1/chat/completions` with OpenAI messages and `stream: true`;
  `choices[].delta.content` fragments are appended and `[DONE]` is terminal.

Hermes cancellation is reported as `unsupported` for session and chat transports
because no documented stop endpoint exists. The adapter does not simulate one.

## Security and verification limits

- Credentials come only from `EngineConfig`, supplied by the server. The adapter
  sends them only in auth headers, never in URLs or event payloads.
- History is bounded to 12 items, 1,500 characters per item, and an 8,000
  character context block. Tool-call wire fields are not forwarded into prompts.
- Tool input/output and model text are bounded before being emitted.
- Tests in `tests/test_external_engines.py` use deterministic HTTP mocks for
  protocol behavior, reconnects, cancellation, redaction, and discovery changes.
