# Inventory identification, catalog validation and tool projections

Inventory identification integrates the catalog and asset core into the
canonical `InventoryService`. REST, the Pydantic AI tools and the FastMCP server
keep calling that single business layer; the allocator, catalog validation and
projection helpers below are internal seams of it, not alternative front doors.

## Quick-code contract

- `id` is a server-generated UUID. It is permanent, immutable and never reused;
  purge keeps a tombstone instead of returning the id to circulation.
- `quickCode` is editable and unique case-insensitively (`quick_code_key` is the
  lowercased value used by the unique index and by lookups).
- Location and category are part of the *visible* code only. Moving an asset or
  changing its category may recompute the code and always keeps the same `id`;
  every change is recorded in the asset history.
- Manual values follow the existing bounds: 1-32 characters, starting with a
  letter or digit, then letters, digits, dot, dash, slash or underscore.

### Configured format

The catalog rule record `rules/identification` defines the format:

| Rule key | Installed default | Meaning |
|---|---|---|
| `separator` | `-` | Joins the site, type and numeric parts |
| `quickPad` | `2` | Minimum digits of the auto number |
| `siteCodeLength` | `3` | Truncation bound for a derived site abbreviation |
| `includeSite` | `true` | Whether the site part appears at all |
| `order` | `site-type` | `site-type` or `type-site` |
| `siteCodes` | `{}` | Explicit site label to code map |

Resolution for an auto-generated code:

1. The site part comes from `site`, then `location`, then the literal `NA`. An
   exact `siteCodes` entry wins; otherwise the value is NFKD-normalized, reduced
   to ASCII letters/digits, uppercased, truncated to `siteCodeLength`, with `NA`
   as the fallback when nothing remains.
2. The type part is the category form `prefix` (1-6 alphanumerics).
3. Parts are joined in the configured order with `separator`, a trailing
   separator is added, and the number is zero-padded to `quickPad`; for example
   `DC-SER-01`.
4. The allocator starts at 1 and returns the first free candidate at or above
   the current counter for that prefix (`max(start, counter)`).

Length and range are bounded: a prefix plus padding over 32 characters, a start
above 2,000,000,000 is a `422`; a scan of 10,000 occupied candidates is a `409`, never
a truncated or duplicated code.

### Explicit values and collisions

- An explicit value with trailing digits keeps its own prefix, casing and digit
  width, and its suffix is incremented until free inside that prefix. Creating
  `SW-SN-001` and then requesting `sw-sn-001` stores `sw-sn-002`; the first
  asset keeps `SW-SN-001` and its id.
- An explicit value without trailing digits (for example `MANUAL`) is stored
  verbatim. If another asset already holds it case-insensitively, the request
  fails with `409 quickCode already exists`; suffixless values are never
  rewritten.
- A suffixless code repeated inside one batch is rejected before any row is
  written; numeric repeats receive distinct advanced suffixes.
- When the category is not in the catalog (legacy free-text asset), no code is
  invented: the existing value is kept on category/site edits, and a create
  without a code falls back to the original random `A-<8 hex>` value.

## Atomicity, locking and counters

All asset write entries (`create`, `update`, `batch`, `clone`, `archive`,
`restore`, `retire`, `purge`, `set_image`, `remove_image`) run through the
`serialized` decorator in `itsm/inventory/codes.py`:

1. It executes `UPDATE inventory_code_sequences SET next_value = next_value
   WHERE key = '__lock__'`, a no-op self-assignment that locks that single row
   on PostgreSQL/MariaDB and reserves the writer slot on SQLite. A row count
   other than one means the schema is not migrated: the write fails with
   `409 inventory schema is not ready; run migrations`.
2. Allocation reads and updates the prefix counter in memory
   (`_pending_sequences`) and reserves the chosen code for the transaction.
3. Counter rows, asset rows, history rows and identity audit rows are flushed
   inside the same transaction. Any error - validation, permission, conflict or
   an `IntegrityError` on the unique index - rolls back the whole unit, so a
   rejected request changes neither assets nor counters.

There is no process-wide mutex, no optimistic `max + 1` retry and no separate
connection or independent counter commit. `inventory_code_sequences` keys are
the lowercased prefix without the number (for example `dc-ser-`), and
`next_value` is the next candidate. Counters never rewind: purge leaves the
counter and the tombstone, so a later auto code continues past the purged one.

Concurrency is covered by a four-thread creation test on SQLite. PostgreSQL and
MariaDB use the same single-row lock in design, but no live multi-engine
concurrency run is part of this task.

## Catalog validation on asset writes

- Statuses are read from the persisted catalog: an inactive or unknown status is
  rejected, and an unchanged status skips transition rules.
- Transitions use the category override when present, otherwise the global
  `rules/transitions` record. The visible status is independent of site,
  location and responsible.
- `technical` for a category resolved in the catalog is validated against the
  category form and the field library: only active fields associated with that
  category are accepted, values are typed by the field definition, required
  fields are enforced and defaults are applied. A legacy free-text category has
  no form, so its stored `technical` map keeps the bounded generic shape check
  instead of catalog field rules. Values already stored for a field that was
  disabled or disassociated are kept unchanged instead of being erased, so
  catalog evolution does not destroy asset data.
- `cost` keeps its bounded two-decimal string representation. Images, archive,
  retire and history behavior are the contracts in [Asset core: common fields, lifecycle, history and media](asset-core.md); this
  task only routes them through the same serialized write path.
- Mutation of configuration stays in `InventoryCatalog.put`; asset writes never
  mutate catalog metadata.

## History

Every successful create/update/clone/archive/restore/retire/purge appends to
`asset_history`, and a quick-code change records `quickCodeOld`/`quickCodeNew`
including allocator increments. Reads through `GET /assets/{id}/history` are
unchanged. A rejected write appends no history row.

## Shared agent and MCP projections

`itsm/inventory/projection.py` is the only place that shapes tool output:

- Default compact fields: `id`, `quickCode`, `name`, `category`, `site`,
  `location`, `responsible`, `status`, `ip`, `archived`.
- Optional `fields` argument: 1-24 unique names from the 23 public payload keys
  (`archivedAt`, `archivedBy`, `createdAt`, `updatedAt`, `cost`, `technical`,
  `images`, ...). Unknown, duplicated, empty or oversized lists are rejected;
  nothing is silently dropped.
- Projection selects from `AssetView.as_payload()`; no internal column, SQL or
  permission data can be requested.

The selected tool registry is the same eleven tools for Pydantic AI and MCP:

`search_assets`, `get_asset`, `create_asset`, `update_asset`,
`batch_update_assets`, `clone_asset`, `archive_asset`, `restore_asset`,
`retire_asset`, `get_asset_history`, `get_inventory_config`.

There is no purge tool and no shell, SQL, filesystem or HTTP tool.
`get_inventory_config` requires `assets.view` and returns the catalog exactly as
the configuration endpoint does. Tool authorization, conflicts and validation
still come from the service and `IdentityService`; adapters only translate the
result or error into a compact response.

REST keeps the full asset payload (including `cost`, `technical`, `archived`,
`archivedAt`, `archivedBy`, `images`) and does not accept a `fields` parameter;
projection is an agent/MCP concern.

## Errors and authorization

| Situation | Result |
|---|---|
| Missing permission | `403`, audited as denied; no write and no counter change |
| Unknown asset id | `404` |
| Suffixless duplicate, schema not migrated, exhausted sequence | `409` |
| Invalid/extra field, immutable `id`, invalid reference | `422` |

Denied and failed requests are rejected before or inside the serialized unit, so
they leave assets, history and counters unchanged. Agent actions report
`completed`, `failed` or `denied`; MCP returns safe tool errors.

## Verification and proof limits

Covered by the backend tests:

- `tests/test_inventory_identification.py`: configured example, numeric
  collision advance with suffixless conflict, four-thread concurrency, rejected
  batch leaving counters untouched, purge not rewinding, catalog technical
  validation/transitions and disabled-field preservation.
- `tests/test_inventory_agent_core.py`: typed create with projected fields
  through the agent and MCP, clone/archive/restore, unknown field rejection.
- `tests/test_catalog_migration.py`: upgrade from `0003_inventory` to the merged
  head keeps legacy rows, installs 14 default categories and the counter row.
- `tests/test_inventory_service.py`, `test_inventory_api.py`,
  `test_asset_core.py`, `test_agent_chat.py`, `test_mcp_server.py`,
  `test_inventory_parity.py`: collision behavior, atomic batch, clone, tool
  registry, compact projection and cross-interface parity.

Not covered here: live PostgreSQL/MariaDB concurrency or migration runs, the
browser/frontend integration, real provider inference (tests use Pydantic
AI `FunctionModel` with `ALLOW_MODEL_REQUESTS=False`), approval workflows and a
destructive purge UI. SQLite is the only engine exercised in this task.
