# Entity change events

The reliable change feed an extension consumes when a core entity it references
changes, is archived or is deleted. The core owns the mechanism end to end: the
extension never reads core tables, never adds a table to the core database and
never holds a hidden cross-database dependency.

Two guarantees shape the design:

* **Written with the change.** The outbox row is inserted in the same
  transaction, and the same flush, as the `asset_history` or
  `technical_incident_events` row it describes. A rolled-back mutation leaves
  neither history nor event.
* **At-least-once, idempotent.** The event carries a permanent UUID, so a
  consumer may process it twice and deduplicate; the cursor only moves forward.

## Tables (core migrations only)

`entity_change_events`

| column | notes |
| --- | --- |
| `sequence` | integer primary key, database-assigned ordering key |
| `id` | UUID, derived deterministically from the history row id |
| `entity_type` | `asset` or `incident` |
| `entity_id` | permanent core UUID |
| `event_type` | `asset.created`, `asset.updated`, `asset.archived`, `asset.restored`, `asset.deleted`, `incident.created`, `incident.updated` |
| `occurred_at` | history timestamp |
| `actor_id` | acting identity, nullable (system work has none) |
| `changed_fields` | JSON list of field **names** plus `status`/`archived` flags, never values |

`entity_event_consumers`

| column | notes |
| --- | --- |
| `consumer_id` | string, at most 96 characters (the extension module id) |
| `last_sequence` | monotonic cursor; `0` means nothing acked |
| `attempts` | consecutive failures for the pending event |
| `last_error` | closed failure code (`handler_error`, `timeout`, ...) |
| `state` | `active` or `stalled`, visible to the operator |
| `retry_after` | backoff timestamp |
| `updated_at` | last cursor change |

## Mapping from existing history

| history row | event |
| --- | --- |
| `AssetHistory.action = created`, `cloned` | `asset.created` |
| `archived` | `asset.archived` |
| `restored` | `asset.restored` |
| `purged` | `asset.deleted` |
| any other asset action (`updated`, `retired`, `assigned`, ...) | `asset.updated` |
| `IncidentEvent.action = created` | `incident.created` |
| any other incident action | `incident.updated` |

`asset_history` rows that mirror an incident onto an asset (`entity_type` other
than `asset`) are skipped: the incident's own history already produced the
incident event and the asset did not change. An unmapped action never produces
silence; it degrades to the entity's `updated` event.

The hook is a SQLAlchemy `before_flush` listener installed once by
`itsm/database.py`, the single engine/session seam, so the API, the worker, the
CLIs and the tests all inherit it. It is idempotent per session (the same history
row emits once) and is cleared on commit and rollback.

## Sequence gaps and late commits

`sequence` is the table's integer primary key, so allocation is atomic on
PostgreSQL, MariaDB/MySQL and SQLite without an application counter or a lock.
Two consequences are accepted and handled:

1. **Gaps are permanent.** A rolled-back transaction consumes its allocation. On
   SQLite the table is declared `AUTOINCREMENT` so a pruned slot is never handed
   out again; a reused number would look already delivered to a cursor.
2. **A lower sequence can commit after a higher one.** A reader cannot know from
   the visible rows how far back an uncommitted allocation may be.

Consumers therefore **do not** treat `max(sequence)` as a commit barrier. `poll`
applies a holdback window: an event is delivered when it is at most
`max(sequence) - lag` (`lag`, default 2) **or** older than `grace_seconds`
(default 2.0). The first condition absorbs a concurrent writer that allocated a
little earlier and has not committed yet; the second releases a low-volume feed
that would otherwise wait forever for newer traffic. Delivery stops at the first
held event, so the order the consumer sees is always ascending, and a late
committed lower sequence is delivered before its successor instead of being
skipped.

The window is a probability bound, not a proof: a writer that holds a
transaction open longer than the grace period can still be overtaken. That is
why reconciliation exists — `assets.resolve` on permanent ids repairs a
reference whose event was missed, and the event id makes replay safe. Gaps left
by rolled-back transactions never block a consumer; the cursor advances past
them with `ack`.

`tests/test_entity_events.py` covers the late-commit case on a SQLite file
(two sessions, sequences inserted out of order) and the grace release, because
SQLite serialises writers and cannot produce a genuinely concurrent late commit.

## Feed API (`itsm/events/feed.py`)

`EntityEventFeed(session_factory, *, lag, grace_seconds, backoff_seconds,
max_backoff_seconds, clock)`.

| method | behaviour |
| --- | --- |
| `poll(consumer, limit)` | registers the cursor on first use; returns committed events with `sequence > last_sequence`, ascending; never moves the cursor |
| `ack(consumer, through_sequence)` | conditional update `WHERE last_sequence < :target`; monotonic, idempotent, safe under concurrency; clears the retry budget |
| `fail(consumer, code, max_attempts)` | increments `attempts`, stores the closed code, sets exponential `retry_after`, and moves to `stalled` when the budget is spent |
| `reset(consumer)` | explicit operator retry: clears attempts/error, back to `active`, keeps the cursor |
| `status(consumer)` | current cursor, attempts, error, state and backoff |
| `prune(older_than, keep_after_min_cursor=None)` | deletes events older than the cutoff that every registered consumer already acked; a stalled consumer still protects its position because it awaits an operator decision |

Payloads are bounded: `limit` is 1–200, `consumer` is at most 96 characters,
`attempts` is at most 10 and the failure code must be one of the closed set in
`itsm/events/models.py`. Nothing stored or returned may contain a traceback, a
payload body or a storage detail.

## Reference resolution (`itsm/events/references.py`)

```python
resolve_entities(principal, "asset", ids, session=session, settings=settings)
# {"<uuid>": "active" | "archived" | "missing"}
```

* at most 200 identifiers per call, de-duplicated, each 1–36 characters;
* `asset` reads through `InventoryService.reference_states`, `incident` through
  `InterventionService.incident_reference_states`;
* both authorize `assets.view` with the ordinary resource, so the resolver adds
  no new authority and cannot read more than the caller could read through REST;
* incidents have no archive flag in the core lifecycle, so they resolve to
  `active` or `missing` only.

## Boundaries

* These are host tables created by core migration `0036_entity_change_events` (after `0035_extension_isolation`);
  the extension runtime keeps only its own cursor tables and never migrates the
  core schema.
* The feed stores identifiers, event kinds and field names — no field values, no
  secrets, no configuration.
* Retention is an operator action (`prune`); events are never deleted by the
  application on a timer, and a failed event is never silently discarded.

## Extension consumers

Installed SDK v2 modules consume the feed through the host, never by opening the
core database. Each enabled module uses consumer id `extension:<id>`; the worker
dispatches events in order and acknowledges only after the sandboxed
subscription or declarative reference policy succeeds. Membership and reference
resolution reuse the same public contracts: `assets.resolve`/`incidents`
capabilities for sandboxed modules and `resolve_entities` for host-applied
policies. Failures use the closed codes above, back off and stall visibly, and a
Superadmin can reset the consumer without losing its cursor. See
[the host guide](extensions-host.md#events-and-reconciliation) and
[the SDK events reference](https://github.com/MrFaviod/hadar-it-backend/blob/master/itsm/extensions/sdk/references/events.md).
