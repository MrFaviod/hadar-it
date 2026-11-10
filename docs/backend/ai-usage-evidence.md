# AI usage evidence

External engines expose usage evidence, not budget authority. `itsm.agents`
normalizes what a runtime actually reported; the ITSM quota service decides
admission and settlement. A connector never imports the quota service and never
writes SQL.

## Event contract

A final `usage` event is a dict-compatible JSON object:

```json
{
  "type": "usage",
  "inputTokens": 120,
  "outputTokens": 30,
  "cacheReadTokens": 40,
  "cacheWriteTokens": 0,
  "reasoningTokens": 12,
  "totalTokens": 190,
  "precision": "measured",
  "source": "engine",
  "estimationMethod": null,
  "inputIncludesCache": false,
  "outputIncludesReasoning": true,
  "totalSource": "derived",
  "cost": 0.0012
}
```

Token fields are nullable. `null` means the engine did not provide that
component; it never means zero. `cost` is omitted when unknown. Once a turn is
submitted, the adapter emits exactly one final usage event, including when
evidence is missing, followed by `done`; a user-visible error may precede it.
Failures before any prompt is submitted (session setup, discovery, model
selection, a Hermes `prompt.submit` rejection) raise without a usage event
because no turn was attempted. Missing evidence produces
`precision: "unavailable"`, `source: "none"` (or `"engine"` when a cumulative
snapshot or unidentifiable snapshots existed but no trustworthy aggregate could
be derived), and all token fields `null`.

`precision` is independent of `source`:

- `measured` with `source: "engine"` or `"provider"` means exact counters
  reported by that engine or provider. It does **not** mean ITSM independently
  measured or provider-billed the work.
- `estimated` requires `source: "estimate"` and a non-blank
  `estimationMethod`. There is no default estimation method. Connectors do not
  estimate an unknown baseline.
- `unavailable` carries no token values and no cost.

Nonnegative genuine integers only: booleans, fractions, negative numbers, and
strings are invalid counts. An invalid component becomes unknown instead of a
fabricated zero.

Inclusion flags describe the arithmetic, not a preference:

- `inputIncludesCache`: `true` only when `inputTokens` already contains cache
  read/write counts. Cache fields are then children, not additional tokens.
- `outputIncludesReasoning`: `true` when `reasoningTokens` is already inside
  `outputTokens`, `false` when reasoning is a separate component, and `null`
  when the relationship is unknown.
- `totalTokens`/`totalSource`: a provider total is passed as
  `totalSource: "provider"`. A total computed from disjoint components is
  `"derived"`, and only when every required component is known. Otherwise the
  total is `null`.

## Hermes

Hermes `session.usage` and `session.stats` are **session-cumulative** snapshots;
`message.complete.usage` carries the same cumulative TUI view. They must never be
charged directly or summed across turns.

Native top-level counters are `input_tokens`, `output_tokens`,
`cache_read_tokens`, `cache_write_tokens`, `reasoning_tokens`, and
`total_tokens`. Hermes normalizes them as follows:

- `input_tokens` excludes cache read/write; cache counters are additional.
- `output_tokens` includes `reasoning_tokens`; reasoning is a subset and must
  not be added again.
- `total_tokens` includes input, cache, and output. A turn delta of the native
  total is reported as `totalSource: "provider"`.

The adapter records a before snapshot and a final snapshot, then subtracts each
counter independently. A new native session starts at a known zero baseline. A
resumed session asks `session.stats` for its pre-turn baseline; if that RPC is
unsupported, the turn is `unavailable`, not estimated from zero. If any final
counter is lower than its baseline, the adapter assumes a counter reset and
reports the whole turn as `unavailable` rather than a negative or partial delta.
A missing component stays `null`.

After a completed turn, the final cumulative snapshot becomes the next baseline.
The emitted delta is therefore usage **since the last observed snapshot**, not
an exact per-turn attribution. Background title, memory, or skill work that runs
outside the turn launders into the next delta; it cannot be attributed exactly to
a turn with the native session protocol. A turn without a usable final snapshot
drops the baseline, and the next turn re-reads `session.stats` instead of
inventing one.

## OpenCode

OpenCode assistant `tokens` are disjoint components:

- `input` excludes cache read/write.
- `output` is visible output and excludes reasoning.
- `reasoning`, `cache.read`, and `cache.write` are separate.

Therefore `inputIncludesCache` and `outputIncludesReasoning` are both `false`,
and the adapter derives a total only when all five components are known. Native
OpenCode does not report a total token count in these messages.

v2 recovery aggregates every distinct completed assistant message for the run
and requires the prompt response's user message id to appear in the message
list as the run anchor. A missing prompt id or a list without that anchor
yields no measured evidence: the adapter emits `unavailable` and never sums all
assistant messages in the session. Per-message cumulative snapshots are
replaced by message id, never summed with their own updates. Session-cumulative
usage events are not treated as turn usage. Reconnects and replayed envelopes
cannot emit the message twice.

OpenCode 2.1.2 `session.execution.failed` is terminal for the matching session,
just like `session.error`; it emits the normalized upstream error and finishes
without waiting for the long-lived event connection to close. A failure for
another session is ignored. Failure is not evidence of zero usage: absent a
recoverable per-prompt usage record, accounting stays unavailable.

v1 `message.updated.info.tokens` is a cumulative per-message snapshot; only
assistant-role snapshots with a stable id are accepted, and the latest snapshot
for each id replaces earlier ones. Before submitting the prompt, the adapter
reads the session's message ids. Snapshots whose id is in that baseline are
excluded, so a replayed prior-turn assistant message is never charged to this
turn. Multiple new assistant messages in one run are summed once. Step-finish
token parts are used only when no message-level snapshot exists, so the same
assistant work is not counted twice. If the baseline read fails, is malformed,
or contains an id-less message, the aggregate is `unavailable`; there is no
"sum everything" fallback. Id-less message or step snapshots likewise make the
aggregate `unavailable` rather than sharing a synthetic key. A missing terminal
snapshot yields `unavailable`, not zero.

## Direct and managed control

`source: "engine"` describes provenance, not enforcement. A direct native
instance is **non-strict**: ITSM can account the evidence it receives, but the
engine may perform background or alternate-path inference that ITSM cannot
bound, pause, or deny. A superadmin may explicitly authorize a company-funded
direct instance, and the UI/status must call it non-strict. Personal direct
instances are accounted separately and never fall back to company funds.

A managed gateway can be strict only when all three hold: run-scoped gateway
authority is enforced, the upstream provider credential is server-held and not
available to the engine process, and no alternate egress exists. Per-call
gateway evidence is the only evidence suitable for strict admission and
settlement. Without the controlled credential and egress proof, the same
gateway is still only an explicitly labeled observation. Missing safe
pre-count/output bounds must never be presented as strict.
