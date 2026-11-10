# AI usage quotas

The quota ledger is ITSM-owned business state. It does not call provider SDKs,
does not meter tokens, and does not share a process lock. Metering normalizes
evidence; this module admits, holds and settles budget against SQL transactions.

## Funding scopes

`company` and `personal` are independent ledgers with independent balances and
receipts. There is no personal-to-company fallback. A provider resolved from the
system fallback credential is attributed to `company` by the caller; the ledger
never guesses funding from a provider row.

Personal funding is **record-only**. A call funded by a person's own provider
key is always admitted, and its reservation, receipt and settlement are stored
with the attributed provider id, scope, name, model and engine. No daily token
limit — company policy, personal policy or a per-user override — can admit or
deny a personal-funded call. The company/global path keeps the atomic admission
rule below. Technical limits (request rate, concurrency, per-run step caps) are
unaffected: they are not token budgets.

## Limits and inheritance

Only company-funded work has an effective limit. It is resolved in this order:

1. A per-user company override row. Row presence is explicit: `null` means
   unlimited and `0` means deny all new work.
2. The installation policy `companyDailyLimit`.
3. When no explicit company policy exists: the existing
   `ITSM_AGENT_DAILY_TOKEN_BUDGET` setting. To preserve its installed
   semantics, a configured value `<= 0` maps to unlimited (`null`); a positive
   value is the numeric limit. The response reports
   `companyLimitSource="legacy_config"`.

Personal funding resolves to `limitTokens=null` and
`limitSource="record_only"` for every actor, independent of stored data.

`null` always means unlimited and `0` always denies new company reservations.
Policy limits can be reduced below already consumed or reserved usage; reports
and `/me` continue to show the consumed and reserved amounts, and only new work
is denied.

### Personal limit inputs

The personal daily limit was part of the first quota contract and is now
unsupported. The legacy `ai_usage_quota_policy.personal_*` columns and any
personal override rows stay in the database and stay inert; they are never read
for admission or summaries.

- `PUT /agent/usage/policy` with `personalDailyLimit`, and
  `PUT`/`DELETE /agent/usage/overrides/{user_id}?scope=personal`, are rejected
  with HTTP `422` and the stable code `personal_budget_unsupported`. Nothing is
  mutated, including an otherwise valid company field in the same request.
- `GET /agent/usage/policy` reports `personalDailyLimit: null` and
  `personalLimitSource: "not_applicable"`.
- `GET /agent/usage/overrides` lists only `company` rows; legacy personal rows
  are not exposed.

Only a human installation owner (the reserved `system.providers` authority,
superadmin role ceiling) may read or change policy, overrides, reports, pending
holds or administrative resolutions. An actor may read only their own summary.

## Day periods, time zones and DST

A period is an IANA local calendar day. Day keys are computed with
`zoneinfo`; there is no midnight task or cron. Reservations record the period
day and time zone they were admitted under, and settlement always returns to
that original period, including after midnight and across DST transitions.

A time-zone change is never applied immediately. It is stored as pending with
`pendingEffectiveDay = max(active-zone today + 1 day, candidate-zone today)`.
The switch applies only when the active-zone date has reached that day and the
candidate-zone date is not behind the active-zone date. This prevents a second
same-day allowance. `GET /me` and `GET /policy` expose `timezone`,
`pendingTimezone` and `pendingEffectiveDay`.

## Metered evidence and receipts

The ledger accepts the normalized evidence dictionary from metering. It never
treats a missing field as zero.

| Evidence key | Meaning |
| --- | --- |
| `totalTokens` | Authoritative total when present |
| `inputTokens`, `outputTokens` | Nullable components |
| `cacheReadTokens`, `cacheWriteTokens` | Nullable cache components |
| `reasoningTokens` | Nullable reasoning component |
| `inputIncludesCache` / `cacheIncludedInInput` | Whether input already includes cache |
| `outputIncludesReasoning` / `reasoningIncludedInOutput` | Whether output already includes reasoning |
| `precision` | `measured`, `estimated` or `unavailable` |
| `source` | `provider`, `engine`, `estimate` or `none` |
| `totalSource` | `provider` or `derived`, when metering supplies it |
| `estimationMethod` | Required for estimated evidence |

An explicit total wins. A derived total is allowed only when all five token
components and both inclusion flags are present. Cache is added once only when
the flag is explicitly `false`; the same rule applies to reasoning. A known
provider/engine total does not require components. Precision is independent of
provenance. `precision="unavailable"` or `source="none"` produces an unresolved
hold, not zero consumption.

A reservation is admitted by one conditional SQL `UPDATE` on the funding
balance. Denial raises `QuotaExceeded` and inserts no reservation, so no upstream
request may start. Settlement and release are idempotent: a repeated call reads
the existing reservation/receipt and does not move budget again. Unresolved
holds survive restarts and appear in pending administration and reports. A
settled amount may exceed the reserved hold; actual consumption is recorded
truthfully and availability clamps at zero.

`release` is internal only and requires `trusted_no_upstream=True` plus a
reason. It exists for an explicit known outcome such as "the first paid call
was established" or "dispatch failed before any provider request". There is no
timeout-based or zero-by-default release path. Administrative resolution requires
`system.providers` authority, trustworthy evidence for settlement (or an explicit
reason for release), and writes an identity audit event.
Measured evidence accepts only provider or engine provenance. Estimated evidence
requires `source="estimate"` and a non-empty method; unavailable evidence cannot
carry token counts. Contradictory reconciliation evidence is rejected without
releasing the existing hold.

### Runs and per-call holds

A run may reserve a minimum sentinel with `run_id`. A per-call child passes
`parent_reservation_id`; it inherits the parent actor, funding, period day, time
zone, provider snapshot, model, engine and run. Passing `None` for `actor_id`
or `funding` inherits that value; a supplied value must match the parent.
Children have their own bound and are admitted against the
parent's original period even if the run spans midnight. A released sentinel can
still be a parent; later unresolved children remain independently visible.

## Legacy daily usage

Rows in `agent_daily_usage` predate attribution. They remain untouched,
unattributed and visibly legacy: provider/model/cache fields are `null`,
`precision="unavailable"`, `source="legacy"`, and `state="legacy"` in reports.
They are never reassigned to a provider or to personal funding. The company
current-period budget includes every legacy UTC daily row whose
`[UTC 00:00, next UTC 00:00)` interval overlaps the active local period
`[local 00:00, next local 00:00)`, using the period's IANA time zone and its DST
transitions. The included total is reported as `legacyTokens`; this keeps the
pre-cutover current day from granting a fresh allowance.

This is deliberately conservative. A legacy UTC row can overlap adjacent local
periods when the local day is not aligned to UTC, so it may be charged in more
than one period. The worst case is a bounded overcharge; it never undercounts a
live legacy day. Each row remains visibly legacy with its exact UTC day, and
historical rows remain visible in reports.

The integrated runtime no longer writes `AgentIntegrationsService.record_usage`
daily rollups. Built-in, isolated and managed calls use durable reservations and
per-call receipts; direct external runs settle their received evidence without
inventing a provider-call boundary. Existing legacy rows remain in place for
reporting and conservative transition-day company carry. No attribution is
backfilled, and UTC overlap handles non-UTC periods and DST boundaries.

## HTTP API

All routes are registered before the MCP mount under the configured API prefix.
Mutation routes require the normal Origin/CSRF guards. Payloads are camelCase.
There is deliberately no public reserve or settle route.

| Method | Path | Authority |
| --- | --- | --- |
| GET | `/agent/usage/me` | Authenticated actor, own data only |
| GET | `/agent/usage/policy` | `system.providers` human owner |
| PUT | `/agent/usage/policy` | `system.providers` human owner |
| GET | `/agent/usage/overrides` | `system.providers` human owner |
| PUT | `/agent/usage/overrides/{user_id}` | `system.providers` human owner |
| DELETE | `/agent/usage/overrides/{user_id}?scope=company` | `system.providers` human owner |
| GET | `/agent/usage/report` | `system.providers` human owner |
| GET | `/agent/usage/pending` | `system.providers` human owner |
| POST | `/agent/usage/reservations/{id}/resolve` | `system.providers` human owner |

Policy `PUT` omits unchanged fields; explicit `null` means unlimited; `0` means
deny. `cancelTimezoneChange=true` clears a pending switch and cannot be combined
with `timezone`. Overrides `DELETE` means inherit. Report filters are
`userId`, `providerId`, `model`, `engine`, `funding`, `dayFrom`, `dayTo`,
`groupBy` (comma-separated `user,provider,model,engine,funding,day`) and
`includeLegacy`. Items always carry precision/source/state/legacy plus nullable
token components, settled/reserved counts and provider snapshot fields.

`/me` returns `periodDay`, `timezone`, pending time-zone fields and a `funding`
object with `company` and `personal` summaries: limit and source, unlimited,
consumed, reserved, legacy, available, pending count and precision totals. The
`personal` summary always reports `limitTokens: null`, `availableTokens: null`,
`limitSource: "record_only"` and `unlimited: true`, while still showing the
tokens it consumed.

## Internal service contract

`AiUsageService(settings, session_factory, *, now=None)` opens its own SQL
session and transaction per call. It has no provider SDK dependency.

- `reserve(actor_id: str | None, *, funding: str | None = None,
  reserved_tokens, provider_id=None, provider_scope=None, provider_name=None,
  model=None, engine=None, run_id=None, parent_reservation_id=None,
  idempotency_key=None) -> ReservationGrant`
  `actor_id` and `funding` may be `None` only for a parent-linked child; both are
  then inherited. Company admission conservatively includes every legacy UTC
  day overlapping the reservation's local period. Same actor plus idempotency
  key replays the existing grant.
- `settle(reservation_id, evidence) -> SettlementResult`
- `release(reservation_id, *, reason,
  trusted_no_upstream=False) -> SettlementResult`
- `pending(*, run_id=None, user_id=None, limit=100) -> list[dict]`
- `me(actor_id) -> dict` (server-resolved actor only)
- `policy(principal)`, `update_policy(principal, ...)`,
  `list_overrides(principal)`, `set_override(principal, user_id, ...)`,
  `delete_override(principal, user_id, ...)`, `report(principal, ...)`,
  `pending_admin(principal, ...)`, `resolve(principal, reservation_id, ...)`

Those administrative methods are human-only: they require the reserved
`system.providers` authority, a human principal and the superadmin role ceiling.
A machine principal is rejected even if delegated.

`ReservationGrant` and `SettlementResult` expose snake_case attributes and
`.as_dict()` for the camelCase wire contract.
