# global search

Canonical, permission-aware search over the SQL source of truth, with an
optional Meilisearch index for relevance. The index is never authoritative:
every engine hit is rehydrated from SQL and re-authorized before it reaches a
caller, and engine loss degrades to SQL instead of failing the request.

## Package

| File | Contents |
| --- | --- |
| `itsm/search/documents.py` | Canonical projections, SQL search, scoring, sections, views, rebuild iterator |
| `itsm/search/service.py` | `SearchService` request facade and C2 response contract |
| `itsm/search/engine.py` | Meilisearch adapter over production `httpx2` |
| `itsm/search/indexer.py` | Session outbox hook, sync/rebuild executors and queue wrappers |
| `itsm/search/models.py` | `SearchSyncOutbox`, `SearchIndexState` |
| `itsm/search/api.py` | `create_search_router(...)` |

## HTTP contract (C2)

`GET {api_prefix}/search?q=&kind=&limit=&offset=`

```json
{
  "items": [
    {"key": "asset:<uuid>", "type": "asset", "id": "<uuid>",
     "label": "Switch Aruba", "subtitle": "SW-SN-001 · 192.168.50.11",
     "icon": "server", "target": {"kind": "asset", "id": "<uuid>"}}
  ],
  "total": 1, "limit": 20, "offset": 0,
  "engine": "sql", "fallback": false
}
```

Types: `asset`, `person`, `location`, `site`, `incident`, `maintenance`,
`category`, `section`, `view`. Keys are stable `<type>:<id>`. `engine` is
`sql` or `meilisearch`; `fallback` is true when an engine was configured but
unavailable and SQL served the request.

`GET /search/status` requires `config.general` (Casbin), checked before
reading index metadata or probing the optional engine. It reports `configured`,
`available`, `engine`, `index`, `status`, `lastSyncAt`, `lastRebuildAt`,
`lastError`, `documentCount`, `pending`.

`POST /search/sync` and `POST /search/rebuild` require the browser mutation
guard (Origin + CSRF) and `config.general` (Casbin). They return `202` and
queue through the supplied task callables, or run the trusted executor inline
when none are configured.

## Permissions

Search does not add a permission. Each kind maps to an existing code and is
checked through `IdentityService.authorize` on every request:

| Kind | Permission |
| --- | --- |
| asset, incident, maintenance | `assets.view` |
| person | `people.view` |
| location, site | `assets.view` |
| category | `assets.view` |
| section | per-section existing code, default `assets.view` |
| view | `config.general`, or authenticated owner for personal views |

Denied kinds are skipped, engine hits are rechecked after rehydration, and
deactivated identities lose access immediately because permissions are read
from live SQL.

An explicit kind scope is never broadened when no indexed kinds are authorized.
Raw engine hit totals are not exposed: counts use canonical SQL and reauthorized
matches, so stale or denied hits cannot disclose restricted record counts.
The engine transport uses SHA-256 `_engine_id` primary keys; public record keys
remain `<type>:<permanent id>`. Index creation and filter settings are awaited
before incremental writes, including the first synchronization without a rebuild.

## Durable synchronization

`install_search_sync(settings)` installs one SQLAlchemy `Session.before_flush`
listener. For tracked asset, person, location, incident, maintenance-plan,
category and workspace-view objects, it inserts an outbox row in the
same transaction as the domain change. The listener never commits, so the
outbox and the domain write commit or roll back together. Call it once during
application startup, after the search tables exist, and pass the live settings.
Engine configuration is scoped to each SQL database: SQL-only installations do
not accumulate rows or disable synchronization for another application instance.

Coalescing uses `(entity_type, entity_id)`; each sync batch processes due rows
ordered by `available_at`, deletes superseded rows, and retries failures with
bounded exponential backoff (`30s * 2^(attempts-1)`, cap 1h). Deletes and
archives rehydrate to `None` and remove the document. Sync is safe to call
repeatedly and from a worker.

`execute_rebuild(session, settings)` builds a temporary index, configures
filterable attributes, then swaps it atomically with the live index; a failure
keeps the previous index and records `failed` plus the error in
`search_index_state`. The outbox is drained only after a successful swap.

## Trusted workers

```python
from itsm.config import get_settings
from itsm.search.indexer import process_search_sync, process_search_rebuild

settings = get_settings()
process_search_sync(settings)  # opens its own SQL session and engine
process_search_rebuild(settings)
```

Both are internal trusted operations: they only read committed SQL rows and
create no new authority. API actions stay permissioned and enqueue these via
the task queue.

## Application wiring

1. `itsm/main.py`: import and include
   `create_search_router(sync_task=..., rebuild_task=...)` with the other
   routers, before the MCP mount; call `install_search_sync(settings)` at
   startup; set `app.state.settings` and `app.state.session_factory` if not
   already present.
2. Migration `0019_*`: create `search_sync_outbox` and `search_index_state`
   exactly as declared in `itsm/search/models.py`.
3. Settings: `meilisearch_url` (existing), `meilisearch_api_key`,
   `meilisearch_http_timeout_seconds=5`, `search_index_name="itsm_entities"`,
   `search_sync_batch_size=100`. Compose may fall back
   `ITSM_MEILISEARCH_API_KEY` to the existing master key.
4. Task queue: register zero-argument wrappers around
   `process_search_sync` / `process_search_rebuild` and pass them to the router.

## Limitations

- SQL search is accent-folding for scoring but `LIKE` can only match stored
  spellings for filtering; Meilisearch adds accent-insensitive matching. This
  preserves SQL as the least surprising fallback.
- The outbox hook observes ORM session changes, not raw Core/bulk SQL or raw
  `DELETE` statements. Canonical services use ORM units of work; a full
  rebuild reconciles anything outside that path.
- Personal workspace views are only searched for their owner; shared views
  are visible to authenticated users. Both are re-authorized at read time.
