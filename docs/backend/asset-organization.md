# Asset organization: sites, locations, people, positions and map data

Inventory uses canonical directory records for people and locations.
An asset can now keep a canonical reference to a site, a location and a
responsible person, an optional plan position, and a business event for every
assignment, return and transfer. The legacy free-text `site`, `location` and
`responsible` columns still exist and still work for callers that send no id.

This document states the contract that REST, the Pydantic AI tools and the
FastMCP tools share. It does not describe the directory itself; see
`directory.md` for people, locations and their own events.

## The single rule for ids and legacy text

`ids are the authority; the legacy text mirrors the canonical label.`

`InventoryService` applies exactly that rule, in `itsm/inventory/organization.py`:

| Sent by the caller | Result |
|---|---|
| `siteId` / `locationId` / `responsiblePersonId` only | the reference is validated and the legacy text is derived from the canonical label |
| legacy `site` / `location` / `responsible` only | the free text is stored as before and the corresponding stale reference is cleared |
| both, and the text equals the canonical label | accepted; the reference is stored and the text kept in sync |
| both, and they disagree | rejected with `422` (`site and siteId must agree`, and the same for `location`/`responsible`) |
| an id sent as explicit `null` | the reference and its mirrored text are cleared together (`locationId: null` keeps the site) |
| a legacy text sent as explicit `null` | the same clear: a text-only value, `null` included, drops the stale reference |
| an id `null` plus legacy text | a text-only switch: the text is kept and no reference is implied |
| `locationId` without `siteId` | the site is derived from the location's ancestor chain |
| a cleared, switched or replaced site | the stored location and its position are dropped, unless the same request names a valid replacement `locationId` |
| `siteId` with a stored location outside that site | the stale `locationId` and location text are cleared |

Labels are derived on read and never stored twice: `site` is the current
directory location name, `location` its name, and `responsible` the person label
(`"{name} ({jobTitle})"` when a job title exists). Renaming a person, room or site
therefore changes what `get`, `search`, `batch`, `clone` and the relationship graph
projections report for an id-backed asset, through one bounded batched lookup and
without touching the asset, its `updatedAt` or its history. The stored text stays
the historical snapshot that history `old`/`new` values keep reporting, and a
legacy-only asset keeps exactly the text it was given. A read never refuses an
archived asset because a referenced person or location became inactive.

There is no automatic matching between the legacy text and a directory record,
no backfill and no heuristic lookup. An asset that only has legacy text keeps
`siteId`, `locationId` and `responsiblePersonId` as `null` until a caller sends
explicit ids.

## Asset payload additions

`AssetView.as_payload()` and the REST payload gain six additive keys after
`responsible`: `siteId`, `locationId`, `responsiblePersonId`,
`responsibleLabel`, `positionX`, `positionY`. Every previous key is unchanged.
`siteId`, `locationId` and `responsiblePersonId` are also accepted as input on
create, update, clone, batch update and the agent/MCP tools.

Reference error mapping is deliberate:

- a reference id that is not a well-formed UUID is `422 ValidationFailed`
  (`siteId must be a UUID`), while a malformed asset id in the route path or an
  unknown asset is `404 NotFound`;
- a well-formed reference UUID that no directory record owns is `404 NotFound`
  (`404` over REST);
- an existing but unusable target (inactive person, inactive location, wrong
  level, location outside the chosen site) is `422 ValidationFailed`;
- an inactive person discovered while reading the label is also `422`.

## Positions and plan references

Positions are optional and bounded:

- `positionX`/`positionY` are canonical decimal strings inside the relative
  `0..1` band, with at most six decimals; `"0.50"` normalizes to `"0.5"`;
- both must be sent together and require a `locationId`;
- a position survives a transfer to another location in the same operation;
- clearing the effective location clears the position.

Plan references live on the directory location (`planRef`, `planPage`), not on
the asset: no plan file is uploaded, stored, fetched by URL or parsed, so a
position is a relative `x`/`y` pair and nothing more. Not every device needs a
position; unpositioned assets simply never appear in map positions.

## Business methods

All of them live in `itsm/inventory/service.py`, run under the shared
`serialized` SQL mutex, authorize before writing, and end with exactly one
terminal `IdentityService.record_operation(...)` that commits the asset change,
its history rows and the counters together. They never call a public directory
mutator, and they never call `InventoryService.update` internally.

```python
InventoryService(session, settings, *, identity=None, source="internal")

assign_responsible(principal, asset_id, person_id, *, reason=None, notes=None,
                   effective_at=None) -> AssetView          # assets.assign
return_responsible(principal, asset_id, *, reason=None, notes=None,
                   effective_at=None) -> AssetView          # assets.assign
transfer(principal, asset_id, *, site_id=None, location_id=_UNSET,
         reason=None, notes=None, effective_at=None) -> AssetView   # assets.edit
map(principal, *, site_id=None, limit=50, offset=0) -> AssetMap    # assets.view
search(principal, *, query=None, category=None, site=None, status=None,
       quick_code=None, asset_id=None, site_id=None, location_id=None,
       responsible_person_id=None, archived=None, limit=50, offset=0)
       -> InventoryPage                                        # assets.view
```

- `assign_responsible` requires an active person (`person_label`), clears
  nothing else, records history `assigned` with `changes["responsible_person_id"]`
  `{old, new}` and audits `inventory.responsible_assigned`.
- `return_responsible` clears both the reference and the legacy text, records
  `returned`, and refuses with `409` when there is nothing to return.
- `transfer` changes `site_id`/`location_id` (and their legacy text). The
  permanent UUID and the technical data stay untouched; the formatted quick code
  may be reallocated by the same allocator that a classification or place change
  already uses, and the history `transferred` event carries the old and new code
  next to the old and new references. The audit action is
  `inventory.asset_transferred`. A transfer to the same site and location is a
  `409` conflict, not a silent no-op.
- `retire` clears the canonical person reference together with the legacy text.
- An archived asset keeps its organization frozen: `assign_responsible` and
  `transfer` refuse with `409` until it is restored, while `return_responsible`
  is still allowed because it only removes a binding. `restore` revalidates the
  effective stored references with the same active validators before it clears
  the archive flag: an inactive person, an inactive location or a location that
  no longer belongs to the stored site rejects the request with the usual `422`,
  the archive flag stays, and no row, history entry or audit event is written.
  Legacy-only and otherwise valid assets restore normally.
- `search` accepts the new filters: `siteId` matches the site itself and every
  descendant location; `locationId` matches that location and its subtree (up to
  200 descendants, beyond that the filter is rejected instead of loading the
  tree); `responsiblePersonId` matches the canonical assignment.

Multiple assets may belong to one person. The person side is a thin REST query
over the same `search` call:
`GET {api_prefix}/people/{person_id}/assets`. People are never access accounts:
nothing here creates an `Identity`, and no account is auto-linked to a person.

## REST surface

All routes use the shared `authenticated_actor` and `mutation_guard`
dependencies and are registered before the MCP mount at the same prefix.

| Method and path | Body / query | Service call |
|---|---|---|
| `POST /assets/{id}/assign` | `personId`, `reason?`, `notes?`, `effectiveAt?` | `assign_responsible` |
| `POST /people/{person}/assets/{asset}/assign` | same body, `personId` optional | `assign_responsible` |
| `POST /assets/{id}/return` | `reason?`, `notes?`, `effectiveAt?` | `return_responsible` |
| `POST /assets/{id}/transfer` | `siteId?`, `locationId?`, `reason?`, `notes?`, `effectiveAt?` | `transfer` |
| `GET /assets/{id}/relations` | `typeKey?`, `direction=both`, `limit=50` | `RelationshipService.list(asset_ids=[id])` |
| `POST /assets/relations` | `assetIds` (1..50), `typeKey?`, `direction`, `limit` | `RelationshipService.list(asset_ids=...)` |
| `GET /people/{person}/assets` | `limit`, `offset` | `search(responsible_person_id=...)` |
| `GET /map` | `siteId?`, `limit=50`, `offset=0` | `map` |

`GET /assets/search` and `GET /assets` accept `siteId`, `locationId` and
`responsiblePersonId` in addition to the previous filters.

Body fields are strict (`extra="forbid"`), so `source`, `actorId`, `entityId`
and `effectiveAt`-as-actor forgery is a `422`. History `source` is decided by
the transport constructor (`rest`, `agent`, `mcp`, `internal`), never by the
caller.

The relationship DTOs report an edge and both endpoint ids, plus its
`direction` and label; they deliberately do not embed node projections. The
graph query may keep an edge whose opposite endpoint was omitted by the node
budget, so consumers must treat `nodesTruncated`/`edgesTruncated` as a statement
about their own input and fetch the missing endpoint explicitly instead of
inventing a position or a summary for it.

## Structured history

`AssetHistory` carries `source`, `entity_type`, `entity_id`, `effective_at` and
`notes`. `HistoryView.as_payload()` still emits every legacy key;
`structured_payload()` adds the five fields; `HistoryPage` keeps its legacy
`as_payload()` for compatibility.

The REST history route, the agent tool and the MCP tool now serialize
`structured_payload()` per item, keeping `assetId`, `total`, `limit`, `offset`
and every old history key. Actions recorded here: `assigned`,
`returned`, `transferred`, `relationship_created`, `relationship_updated`,
`relationship_removed`, `host_moved`, plus the pre-existing `created`,
`updated`, `archived`, `restored`, `retired`, `purged`, `cloned`. Each row keeps
the actor, the entity (`asset` or `relationship`), the recorded time, the
optional effective time, the reason and the notes, and is written in the same
transaction as the asset change.

## Directory deactivation guards

`DirectoryService.update_person` and `update_location` refuse deactivation
(`409`) while an unarchived asset still uses that person, location or site.
They reuse the `serialized` mutex and never call back into `InventoryService`;
the guard is a narrow read of `assets.responsible_person_id` and
`assets.site_id`/`assets.location_id`. Archived assets are deliberately ignored
by that guard, which is exactly why `restore` revalidates the same references.

## Agent and MCP tools

Both transports register the same 24 typed tools over the same services:

`search_assets`, `get_asset`, `create_asset`, `update_asset`,
`batch_update_assets`, `clone_asset`, `archive_asset`, `restore_asset`,
`retire_asset`, `get_asset_history`, `get_inventory_config`,
`search_locations`, `search_people`, `assign_asset`, `return_asset`,
`transfer_asset`, `get_asset_relations`, `create_relationship`,
`remove_relationship`, `move_host`, `get_asset_map`,
`list_redundancy_groups`, `get_redundancy_group`, `save_redundancy_group`.

- `create_asset`/`update_asset`/`batch_update_assets` accept the reference and
  position fields, so a tool can bind an asset to a person or location without a
  free-form text lookup.
- `search_locations` reads `DirectoryService.list_locations` (`tree=True` reads
  `location_tree`, bounded by `depth` 1-4 and `max_nodes` 1-500) and
  `search_people` reads `list_people`; both return bounded pages.
- Every tool revalidates the principal: the agent receives it from the
  authenticated chat request, MCP re-reads the raw bearer token from the trusted
  transport and reauthenticates per operation. `source` is `agent`/`mcp` from the
  constructor, so history cannot be forged.
- Denied calls are audited by the identity layer, leave the asset, its history
  and the counters unchanged, and return a compact failure; there is no retry
  with elevated permissions.
- Outputs stay compact (`project`, `COMPACT_FIELDS`, 24-field cap) and never
  expose credentials, internal paths or raw SQL. No tool accepts SQL, a shell
  command, a filesystem path, an HTTP URL, a model name or a provider URL.
- No paid inference is required for these checks: tests use `FunctionModel` with
  `ALLOW_MODEL_REQUESTS=False`, and a missing model configuration still returns
  `503`.

## Migration

```bash
cd backend
.venv/bin/python -m alembic upgrade head     # 0009 asset references -> 0010 redundancy tables
.venv/bin/python -m alembic heads            # single head: 0010_redundancy
.venv/bin/python -m alembic downgrade 0009_asset_directory
```

`0009_asset_directory` is additive and portable: five nullable columns on
`assets` (`site_id`, `location_id`, `responsible_person_id`, `position_x`,
`position_y`) plus three indexes. The text columns are untouched, no row is
backfilled, no directory record is created and no engine-specific SQL is used.
The reference columns intentionally carry no database foreign key: adding a
constraint to an existing table is not portable, so referential integrity is
owned by `InventoryService` with `DirectoryService`.

`0010_redundancy` adds the tables described in [Redundancy groups](redundancy.md); it does not
change `assets`, its hosting relation or any directory rule.

## Limitations

- No custom fields, no bulk import, no notifications, no automatic discovery.
- No plan file storage, upload, redirect or URL fetch; `planRef`/`planPage` are
  bounded text on the location and positions are relative percentages.
- No coordinate search, no map rendering, no third-party inventory or
  hypervisor/Docker integration. A host move edits stored relations only.
- No deletion of people or locations, and no automatic link between an access
  account and a person.
- Location filters reject a subtree larger than 200 descendants rather than
  materialize it.
