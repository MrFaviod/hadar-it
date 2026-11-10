# Redundancy groups

A redundancy group records that several **independently identified** inventory
assets are replicas of the same workload. It is administrative inventory data:
it does not create, clone, move, start or monitor anything.

- Assets stay the only instance identity. Every member keeps its own permanent
  UUID, quick code, history and hosting relation; a group never merges two rows
  and never invents a synthetic "service" record.
- The single-host rule of `hosted_in` is unchanged. The optional `host` field of
  a member is read from that existing relation, so a group may legitimately have
  members on different hosts (for example VM1 on host1 at 40% and VM2 on host2
  at 60%).
- Out of scope: autodiscovery, real replication, load balancing, failover,
  hypervisor migration, service catalogs, service accounts and any measured
  utilization. A traffic share is a **configured percentage** that describes how
  traffic is meant to be split between replicas; it is not measured load, not a
  host CPU/memory allocation and not a capacity reservation.

## Data model

`0010_redundancy` (previous head `0009_asset_directory`) adds two tables and
touches nothing else:

`redundancy_groups`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID string | permanent, generated once |
| `name` | text ≤160 | required, trimmed |
| `description` | text ≤1000, nullable | optional workload/service note |
| `mode` | `active_active` \| `active_passive` | mode of the group |
| `active` | boolean | activation state; inactive groups are still stored and readable |
| `created_at`, `updated_at` | timestamp | UTC |

`redundancy_group_members`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID string | row id of the membership |
| `group_id` | UUID string | `FOREIGN KEY ... ON DELETE RESTRICT` |
| `asset_id` | UUID string | `FOREIGN KEY ... ON DELETE RESTRICT` |
| `role` | `primary` \| `backup` \| NULL | only for `active_passive` |
| `share` | canonical decimal text ≤8, nullable | only for `active_active` |
| `created_at`, `updated_at` | timestamp | UTC |

`UNIQUE (group_id, asset_id)` and an index on `asset_id`. There is no group
deletion operation, no seeded group, no backfill and no destructive step; a
downgrade only drops the two new tables.

Shares are stored as a canonical decimal string (`40`, `33.33`), never as float,
because the exact total matters. The service rejects booleans, `NaN`, `±Infinity`,
more than two decimals and values outside `0..100`; `40.0` and `60.00` are
normalized to `40` and `60`. SQLite has no native decimal type, so text with
service-side `Decimal` validation is the portable representation.

## Rules

| Rule | `active_active` | `active_passive` |
|---|---|---|
| Roles | none (`role` is `NULL`) | exactly one `primary`, at least one `backup` |
| Shares | required; `0 <= share <= 100`, ≤2 decimals | `NULL` (never a fake `0`/`100`) |
| Complete group total | exactly `100` | not applicable |
| Complete group size | ≥2 distinct members | ≥2 distinct members |
| Active group size | ≥2 | ≥2 |
| Archived members in an active group | rejected (`409`) | rejected (`409`) |

Additional invariants:

- Create requires at least two members, whatever the activation state.
- An active group cannot include an archived asset, and an archived member cannot
  be added to or kept in an active group when the member list is replaced.
- An inactive group keeps its rows and history, may shrink to an incomplete
  member list (`0..50`) so a retired or archived replica can be removed, and may
  be activated again only once the full rules hold.
- Archiving is refused while the asset is a member of **any** active group (see
  below), so the invariant cannot be reached through the inventory lifecycle.
- Changing `mode` requires the complete member list in the same request.
- A member list is the complete desired state. There is no add/remove delta API
  and no separate member endpoint, so a partial application cannot happen.
- A member belongs to at most one group per row; the same asset cannot appear
  twice in one list (duplicate → `422`).

## DTOs (stable frontend contract)

Group:

```json
{
  "id": "uuid",
  "name": "Portal web",
  "description": "Balanceo AB 40/60 entre dos réplicas",
  "mode": "active_active",
  "active": true,
  "createdAt": "2026-06-01T12:00:00+00:00",
  "updatedAt": "2026-06-01T12:00:00+00:00",
  "memberCount": 2,
  "members": [
    {
      "assetId": "uuid",
      "name": "Portal replica 1",
      "quickCode": "RG-V1",
      "archived": false,
      "role": null,
      "share": "40",
      "host": {"id": "uuid", "name": "Host Perimetral 1"}
    },
    {
      "assetId": "uuid",
      "name": "Portal replica 2",
      "quickCode": "RG-V2",
      "archived": false,
      "role": null,
      "share": "60",
      "host": {"id": "uuid", "name": "Host Perimetral 2"}
    }
  ]
}
```

- `members` is always present and ordered: `primary`, then `backup`, then by
  ascending name/`assetId`; `memberCount` is `len(members)`.
- `host` is `null` when the member has no `hosted_in` relation. It names the
  existing host asset; it never claims a placement the inventory does not have.
- `share` is a string (exact decimal) or `null`. `role` is `"primary"`,
  `"backup"` or `null`.
- `archived` mirrors the asset row and is informational; an archived member can
  only exist in an inactive group.
- Timestamps are ISO-8601 with the UTC offset.
- Pages: `{"total": int, "limit": int, "offset": int, "items": [group...]}`.

Every response contains exactly these keys; there is no `source`, `actorId`,
`entityId` or permission field, and the request bodies use `extra="forbid"`, so
forging them is a `422`.

## REST

Mounted under `/api/v1` (same prefix, registered before the MCP mount). Cookie
sessions use the same `Origin` + `X-CSRF-Token` mutation guard as every other
write; machine identities use the same bearer credential and the same service
rules.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/redundancy-groups?query=&active=&mode=&limit=&offset=` | bounded page |
| `POST` | `/redundancy-groups` | create group + complete member list (`201`) |
| `GET` | `/redundancy-groups/{group_id}` | one group with members |
| `PATCH` | `/redundancy-groups/{group_id}` | update fields and/or replace members |
| `POST` | `/redundancy-groups/{group_id}/deactivate` | set `active=false`, keep history |

`POST` body:

```json
{
  "name": "Portal web",
  "description": "opcional",
  "mode": "active_active",
  "active": true,
  "members": [
    {"assetId": "uuid", "share": "40"},
    {"assetId": "uuid", "share": "60"}
  ],
  "reason": "alta del grupo",
  "notes": "opcional",
  "effectiveAt": "2026-06-01T12:00:00+00:00"
}
```

`PATCH` accepts any subset of `name`, `description`, `mode`, `active`,
`members`, `reason`, `notes`, `effectiveAt`. A field that is present is applied,
so `"description": null` clears it. `members`, when present, is the complete new
list. The deactivation body is optional (`reason`, `notes`, `effectiveAt`).

Errors use the shared envelope `{"error": {"code", "message"}}`:

| Situation | Status / code |
|---|---|
| malformed UUID/body, invalid share, wrong role, sum ≠ 100, mode change without members, bound exceeded, activation with <2 members | `422` `validation_error` |
| unknown group, unknown/malformed member asset UUID | `404` `not_found` |
| archived member in an active group, archiving a member of an active group, deactivating an already inactive group, IntegrityError conflict | `409` `conflict` |
| missing permission | `403` `forbidden` |
| missing/invalid session or bearer | `401` `unauthorized` |
| missing CSRF/origin on a cookie mutation | `403` `forbidden` |

## Permissions

No permission catalog change was needed.

- Reads (`list`, `get`, REST `GET`, agent/MCP read tools) require
  `assets.view` with resource `inventory:redundancy`.
- Mutations (`create`, `update`, `deactivate`) require `assets.edit` on the group
  resource (`redundancy-group:{id}`) **and** `assets.edit` on every affected
  asset: all current members plus all proposed members. References and
  permissions are validated for the full union before the first write.
- `reader` can read groups and is denied every mutation (`403`, denial audited
  by the identity layer). `operator` and `admin` can mutate.

## Service

`itsm/redundancy/service.py` is the only business layer; REST, Pydantic AI and
FastMCP call it. Signatures (keyword-only after `principal`):

```python
RedundancyService(session, settings, *, identity=None, inventory=None, source="internal")

list(principal, *, query=None, active=None, mode=None, limit=50, offset=0) -> RedundancyGroupPage
get(principal, group_id) -> RedundancyGroupView
create(principal, *, name, mode, members, description=None, active=True,
       reason=None, notes=None, effective_at=None) -> RedundancyGroupView
update(principal, group_id, *, name=UNSET, description=UNSET, mode=UNSET, active=UNSET,
       members=UNSET, reason=None, notes=None, effective_at=None) -> RedundancyGroupView
deactivate(principal, group_id, *, reason=None, notes=None, effective_at=None) -> RedundancyGroupView
```

`members` entries accepted by the service are
`{"asset_id": str, "role": str | None, "share": str | int | Decimal | None}`.
HTTP and MCP use `assetId`/`asset_id` respectively and map to this form; the
service rejects any extra member key.

Bounds: `limit` `1..200` (default 50), `offset >= 0`, `query` ≤120, `members`
`≤50`, `name` ≤160, `description` ≤1000, `reason` ≥4 and ≤500,
`notes` ≤500, `effective_at` must carry a timezone. A 50-asset read binds at most
50 ids plus their hosts, well within SQLite's variable limit; the member
projection issues a constant number of queries (group page, members, host edges,
asset facts), never one query per member and never a whole-inventory scan.

## Transaction, history and audit

Each mutation runs under the shared `serialized` inventory mutex
(`inventory_code_sequences` row) on one session/transaction:

1. resolve references and authorize every current/proposed member;
2. validate the complete desired state;
3. apply group fields and the membership diff (retained rows update `role`/
   `share`, removed rows are deleted, added rows are inserted);
4. append structured history to every affected asset;
5. exactly one terminal `IdentityService.record_operation` commit.

A failure in any step rolls the whole unit back, releases the mutex and leaves
groups, members, assets, history and counters unchanged. There is no nested
public mutator and no intermediate commit; group creation and member replacement
cannot be observed half-applied.

History rows (`asset_history`, through `InventoryService._record_history`) carry
the acting principal, the trusted `source` of the front door (`rest`, `agent`,
`mcp`; `internal` for in-process) and:

| Field | Value |
|---|---|
| `action` | `redundancy_group_created`, `redundancy_group_updated`, `redundancy_group_deactivated` |
| `entityType` / `entityId` | `redundancy_group` / group UUID |
| `changes.redundancyGroup.old` | previous member state or `null` |
| `changes.redundancyGroup.new` | new member state or `null` |
| member state | `{groupId, name, mode, active, role, share}` |

Only assets whose member state actually changed receive a row (a pure group-name
change writes the new group name for every member; a no-op request writes
nothing). `reason`, `notes` and `effectiveAt` are attached to the event. Exactly
one identity audit event is written per mutation: `redundancy.group_created`,
`redundancy.group_updated` or `redundancy.group_deactivated`, with resource
`redundancy-group:{id}`.

`source` is constructor-supplied by the trusted adapter (`rest`/`agent`/`mcp`)
and validated against the allowed set; no request body, tool argument or chat
text can set it.

## Archive transition

Archiving an asset that belongs to **an active group of any mode** is refused:

```
POST /api/v1/assets/{id}/archive
409 {"error": {"code": "conflict", "message": "an active redundancy group cannot include archived assets"}}
```

- The check runs inside `InventoryService.archive`, before any archive mutation,
  flush, history row or audit event, and inside the same `serialized` mutex as
  the group mutations. A refused archive leaves the group, every member asset,
  media, structured history, tombstone and success-audit state unchanged; the
  caller's permission check still happens first, so a denied caller reads `403`
  and nothing is written.
- Any active membership blocks it. If the asset belongs to several groups, all of
  them must be accounted for; deactivating one group is not enough while another
  one is still active.
- The refusal does not deactivate the group, rewrite memberships, shares, roles
  or hosting relations, or change the asset UUID or quick code. There is no
  implicit repair.
- Permitted cleanup order: deactivate the group (or replace the membership to a
  valid list that excludes the replica), then archive. An inactive group may keep
  an archived member and reports it truthfully as `archived: true`; activating or
  replacing members with an archived asset is still rejected (`409`).
- Assets in no group and assets only in inactive groups archive exactly as
  before, and restore semantics are unchanged (`POST /assets/{id}/restore`).
- Ordering is symmetric: activate a group first and the later archive is refused;
  archive a member while the group is inactive and the later activation is
  refused. Either order leaves the invariant intact and releases the mutex, so
  subsequent legitimate operations still run.

## Purge guard

`InventoryService.purge` now also refuses (`409`) while the asset is a member of
any group, in addition to the existing relationship guard. The guard is enforced
in the service, so a permanent purge cannot dangle a membership row: the asset
must first be removed from its group (deactivating the group if needed), and only
then purged. Groups and members are never deleted implicitly.

The migration declares `ON DELETE RESTRICT` foreign keys, but this foundation
does not enable SQLite foreign-key enforcement (`PRAGMA foreign_keys=0` on the
current engine), so the database-level constraint is not what protects SQLite
installations: the service-level guard above is the enforced protection. On
engines that do enforce foreign keys the declared constraint applies as well.
This is inventory behaviour only and makes no claim about other storage layers.

## Agent and MCP tools

Both transports keep the previous 21 tools and add exactly three, for 24:

| Tool | Arguments | Result |
|---|---|---|
| `list_redundancy_groups` | `query`, `active`, `mode`, `limit`, `offset` | `{"ok": true, "groups": page}` (MCP: `{"groups": page}`) |
| `get_redundancy_group` | `group_id` | `{"ok": true, "group": group}` |
| `save_redundancy_group` | `group_id` (absent = create), `name`, `description`, `mode`, `active`, `members`, `reason`, `notes`, `effective_at` | `{"ok": true, "group": group}` |

- `members` uses `{"asset_id": ..., "role": ..., "share": ...}` and is the
  complete list. Creating requires `name`, `mode` and `members`.
- The tool subset cannot clear a description (`null` means "unchanged"); use
  `REST PATCH` with `"description": null` for that. REST is the complete surface.
- Tools accept no actor, source, permission or provider/SQL/HTTP parameter. The
  agent principal comes from the authenticated chat request, MCP re-reads the raw
  bearer token from the transport and reauthenticates per operation, history
  source is `agent`/`mcp`, and a denied call returns a compact failure and writes
  nothing.

## Migration and verification

```bash
cd backend
.venv/bin/python -m alembic upgrade head        # 0009 -> 0010_redundancy
.venv/bin/python -m alembic heads               # single head: 0010_redundancy
.venv/bin/python -m alembic downgrade 0009_asset_directory
.venv/bin/python -m pytest tests/test_redundancy_service.py tests/test_redundancy_api.py \
    tests/test_redundancy_agents.py tests/test_redundancy_migrations.py
```

The migration was exercised against isolated SQLite only: fresh upgrade, upgrade
from a `0009` database holding assets and a `hosted_in` edge (rows retained, no
seeded group) and a repeated upgrade (no-op, single head).
