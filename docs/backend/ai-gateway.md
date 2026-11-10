# Managed AI gateway

`itsm.ai_gateway` is the data plane for native engines that must spend a run's
AI budget through ITSM instead of calling a provider directly. It issues
short-lived, run-scoped leases, enforces a per-call admission bound against the
AI usage ledger, and accounts provider-reported usage exactly once.

The gateway is not an arbitrary provider proxy and it is not a token mint for
browsers. Lease issuance exists only as a Python service method; there is no HTTP
endpoint that creates tokens. The native runner receives a lease because trusted
server code already authorized its run.

## Routes

The router is built for the canonical API prefix, so with the default settings it
is mounted at `/api/v1/agent/gateway` and exposes:

| Method | Path | Behavior |
| --- | --- | --- |
| `POST` | `/v1/chat/completions` | Bounded OpenAI-compatible chat call, JSON or SSE |
| `GET` | `/v1/models` | The single lease-pinned model; no upstream call |
| `GET`, `POST` | `/v1/responses` | Explicit `404 unsupported_route` |

Every data-plane request requires `Authorization: Bearer <lease token>`. Cookie
sessions and browser CSRF credentials are not accepted and are not forwarded.
Client `Authorization`, provider headers, cookies and identity headers are
discarded; only the lease-sealed provider credential and the pinned model are
sent upstream.

## Lease issuance

```python
gateway = AiGatewayService(settings, session_factory, usage_service)
lease = gateway.issue_lease(
    actor_id=actor_id,
    funding="company",              # or "personal"
    parent_reservation_id=run_reservation_id,
    selection=provider_model_selection,
    provider_id=provider.id,
    provider_scope="global",        # or "personal"
    provider_name=provider.name,
    model=selection.model,
    engine="hermes",                # or the actual native engine
    run_id=run_id,
    context_tokens=context_bound,
    output_tokens=output_bound,
    ttl_seconds=3600,
)
```

The call is trusted server code. `issue_lease` validates that the parent
reservation is pending for the same actor and run, and that its funding,
provider, scope, name, model and engine match the lease. A personal provider may
only use the personal funding balance. The parent reservation is required: the
gateway does not create a run-level budget itself.

The provider identity in a managed run comes from the session's provider
selection, resolved by `AgentIntegrationService` under the run owner's
authorization. A personal selection produces `provider_scope="personal"`,
`funding="personal"` and the personal balance; the instance's configured global
provider stays the default when the session has no selection. The gateway never
infers a provider, never falls back from personal to company funding and never
reads a provider from the request body or a native client.

Only issuance requires a pending parent. The parent runtime may release its
run-level sentinel before the first gateway child; child reservations still
inherit the parent's actor, funding, period day and provider attribution from
the released parent. The lease, not the sentinel, is the per-call authority.

Issuance returns `IssuedLease` with `lease_id`, the opaque `bearer_token`,
`run_id`, `model`, expiry and bounds. The raw token is returned once and is never
stored. Only its SHA-256 hash is persisted. The provider `base_url`, `model`,
`api_key` and `allow_private` flag are stored as a Fernet-sealed snapshot using
`settings.ai_credential_key`; no plaintext credential is persisted, logged or
returned. The provider URL is validated with
`itsm.agent_integrations.providers.validate_provider_endpoint`: personal
providers must be HTTPS and public, global providers may use the operator's
private endpoints.

The parent runtime should issue one lease immediately before starting a
disposable native engine process, bind that process's provider base URL to
`<api_prefix>/agent/gateway/v1`, its API key to the lease token and its model to
the lease model, then call `gateway.revoke(lease_id)` when the run ends.
Revocation blocks new calls and never refunds budget already held by calls. This
is identical for global and personal providers: the seal decides where egress
goes, and the native child holds only the opaque run-scoped key.

## Request contract

`POST /v1/chat/completions` accepts a bounded JSON object. Supported fields are
`model`, `messages`, `max_tokens`, `max_completion_tokens`, `temperature`,
`top_p`, `top_k`, `stop`, `stream`, `stream_options`, `n`, `seed`,
`presence_penalty`, `frequency_penalty`, `logit_bias`, `user`, `response_format`,
`tools`, `tool_choice` and `parallel_tool_calls`. Leases also carry
`input_modalities` (which non-text kinds the turn may carry) and
`attachment_bytes` (the encoded budget); both are sealed at issuance and cannot
be widened by the caller.

- The body must be at most 2 MiB. Invalid JSON, unknown fields, unsupported
  fields and unsupported stream options are rejected before any reservation or
  upstream connection.
- `model` is optional only when it equals the lease model. Any other value is
  `invalid_model`; a user header, body model or provider URL cannot override the
  lease.
- `n` must be exactly the integer 1.
- Output is capped by the lease `output_tokens` bound. `max_tokens` and
  `max_completion_tokens` are validated, must agree when both are present, and
  an unbounded or excessive value is rejected. When neither is supplied the
  gateway injects `max_tokens` with the lease output bound.
- `messages` are limited to 256 entries with string content or content parts.
  Text parts are always allowed. An `image_url` part is admitted only when the
  lease declared the `image` modality, and its `url` must be an inline
  `data:image/(png|jpeg|webp|gif);base64,...` URL with an optional `detail` of
  `auto`, `low` or `high`. A `file` part is admitted only when the lease declared
  the `file` modality; its `file_data` is either an inline
  `data:application/pdf;base64,...`/`data:text/*;base64,...` URL or bare base64
  paired with a `.pdf`/`.txt`/`.csv` filename. Remote `http(s)` image URLs, other
  media types, audio, unknown parts and malformed base64 are refused with
  `unsupported_content`. Encoded attachment bytes are bounded by the lease
  `attachment_bytes` budget (at most 4 MiB), and the request body limit is
  raised by exactly that budget for the call.
- Function tools are allowed with bounded names/descriptions and a JSON schema
  `parameters` object. Other tool types are rejected. `tool_choice` accepts
  `none`, `auto`, `required` or one named function.
- `stream_options` accepts only `include_usage`; streaming always forces
  `include_usage: true`.

The reserved amount is `context_tokens + output_cap`; the lease's
`context_tokens` is an operator-declared upper bound, not a measurement of the
actual prompt. Missing bounds fail lease issuance, so no paid call can start
without an admission bound.

## Accounting and failures

Before forwarding a paid call the gateway reserves a child reservation through
`AiUsageService.reserve`, with the run reservation as `parent_reservation_id`.
The child inherits the parent's actor, funding, original period day, timezone,
provider, model, engine and run, so a call that finishes after midnight still
counts on the day the run started. `idempotency_key` is derived from the
gateway's SQL call id.

Settlement uses only provider-reported totals. `prompt_tokens_details.cached_tokens`
and `completion_tokens_details.reasoning_tokens` are recorded as cache-read and
reasoning components with flags declaring that they are already included in
input/output, so cached and reasoning tokens are not added again. If the provider
reports prompt and completion counts but no total, the total is derived and
marked `totalSource: derived`; if neither a total nor both components exist, the
call is settled as `unresolved` and the full hold remains.

The gateway never calls `release` automatically. Timeout, client disconnect,
missing usage, truncated streams, upstream 3xx/4xx/5xx, unreadable responses and
transport failures all leave the hold unresolved for the parent's reconciliation
flow. A 4xx does not prove the provider did not bill. Upstream error status and a
structured provider error body are returned when safe; otherwise the gateway
returns its own `upstream_error` envelope.

Non-stream responses are read with an 8 MiB limit, stream bodies with the same
total limit and 1 MiB per SSE event, and provider error bodies with a 64 KiB
limit. A non-stream response that exceeds a limit returns `502` with an
unresolved hold. A stream that exceeds the total limit is cut off and also
left unresolved; the gateway never treats a truncated stream as settled usage.

## Streaming

For `stream: true` the gateway sends `stream_options.include_usage: true`, reads
the upstream SSE stream incrementally, and relays every byte of event data
(deltas, tool calls, role chunks and `[DONE]`) unchanged. It scans `data:` lines
only to capture the last `usage` object. No full stream is buffered.

If the downstream client disconnects or the response generator is closed, the
gateway closes its owned upstream response and client, settles with whatever
complete usage was seen, and preserves the hold when usage is missing. The
upstream provider may already have billed for work it continues past the
disconnect; that is exactly why the hold is not released.

If the gateway process dies before a call is finalized, the ledger hold stays
pending and the SQL call row may stay `in_flight`. There is deliberately no
timeout-based release: the parent's reconciliation flow must resolve those
reservations after checking the run.

## Provider transport and limits

Calls use the existing `provider_http_client`, which verifies TLS, ignores
environment proxies, disables redirects and retries, and applies public-only
connection filtering when `allow_private` is false. The gateway builds a fixed
`/chat/completions` URL from the sealed base URL, sends only the allowlisted body
and server-derived headers, and never follows a provider redirect. No paid call
is retried automatically.

Idempotency is SQL-backed and bound to the run: a second request with the same
`Idempotency-Key` for the same run is rejected with `409 duplicate_request`
before a second reservation or upstream dispatch. Replay is not simulated; the
caller must reconcile the original call through the ledger.

## Honest capability

`gateway.capability()` reports:

```json
{
  "mode": "managed",
  "enforcement": "admission_only",
  "strict": false,
  "reason": "... declared context bound ... network isolation ..."
}
```

The gateway enforces admission, budget reservation, model/provider pinning,
output caps and per-call accounting. It cannot by itself prove the native
process uses no other provider, and it does not independently measure the
prompt against `context_tokens`; that bound is declared by the operator/native
configuration and is the amount reserved. Strict whole-engine enforcement
requires the parent runtime's disposable-process network isolation and egress
evidence. `/responses`, embeddings, audio, images and file uploads are not
supported and return explicit errors rather than being proxied.
