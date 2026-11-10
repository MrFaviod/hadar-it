# Directory: inventory people, departments and hierarchical locations

Directory is the responsibility side of inventory. `Asset.responsible` is free
text; Directory gives that responsibility a stable record with an owner,
without turning it into an access account.

## Scope and non-goals

- A person is an **inventory record**: no credential, session, role, group or
  `Identity` row is created, and no login path exists here. Installation,
  identity administration and machine identities stay in `docs/backend/identity.md`.
- Directory never matches legacy free text automatically. `Asset.responsible`
  and `Identity.person_id` are not resolved, back-filled or compared against
  person names, and no person, department, site, asset or user is seeded.
- No deletion. `active`/`status` transitions are non-destructive and audited;
  a person's id and a location's id are permanent UUIDs.
- Asset assignment and optional-asset relations belong to the inventory
  organization service. It reuses Directory identities and canonical labels.
- No plan file storage, retrieval, path resolution or upload. A location may
  carry a bounded textual plan reference only (`planRef`, `planPage`); nothing
  in this module reads the filesystem or the network.
- Custom fields, bulk import, CSV export, notifications, organization charts,
  map rendering and coordinate-based search are out of scope.

## Schema (migration `0007_directory`)

`0007_directory` revises `0006_inventory_codes` and is a sibling of the
relation work's `0007_relationships`; both are parents of a later merge
revision. It creates four tables and inserts no rows. No runtime import of the
schema and no startup/migration side effect exists in the module.

| Table | Key columns | Constraints |
| --- | --- | --- |
| `directory_departments` | `id` UUID string, `name`, `name_key`, `active`, `created_at`, `updated_at` | unique `name_key` (case-insensitive names) |
| `directory_locations` | `id`, `level`, `parent_id` (self FK), `name`, `name_key`, `description`, `latitude`, `longitude`, `plan_ref`, `plan_page`, `active`, timestamps | unique (`parent_id`, `name_key`); indexes on `level` and `parent_id` |
| `directory_people` | `id`, `name`, `job_title`, `department_id` FK, `site_id` FK, `contact_email`, `contact_phone`, `status`, timestamps | indexes on `status`, `department_id`, `site_id` |
| `directory_events` | `id`, `entity`, `entity_id`, `action`, `actor_id`, `actor_username`, `source`, `recorded_at`, `effective_at`, `before_snapshot`, `after_snapshot`, `reason`, `notes` | index (`entity`, `entity_id`, `recorded_at`) |

Coordinates are stored as canonical decimal **strings** (portable across
SQLite, PostgreSQL and MariaDB) and exposed as floats. The column names
`before_snapshot`/`after_snapshot` avoid the reserved word `BEFORE` in MySQL
and MariaDB.

Sibling-name uniqueness is enforced by the service for `parent_id IS NULL`
(roots), because a SQL unique constraint does not compare `NULL` parents on
every supported engine.

## Public DTOs

Every payload is camelCase and returned verbatim by REST; there is one
projection, not a per-transport copy.

- Department: `id, name, active, createdAt, updatedAt`
- Person: `id, name, label, jobTitle, departmentId, siteId, contactEmail,
  contactPhone, status, createdAt, updatedAt`
- Location: `id, level, parentId, name, description, latitude, longitude,
  planRef, planPage, active, createdAt, updatedAt`
- Location tree: `{roots, nodeCount, depth, truncated}` where each node is a
  location payload plus `children`
- Event: `id, entity, entityId, action, actorId, actorUsername, source,
  recordedAt, effectiveAt, before, after, reason, notes`
- Pages: `{items, total, limit, offset}`; history pages also carry `entity`
  and `entityId`

`label` is the canonical display string: `name` when `jobTitle` is absent,
otherwise `"{name} ({jobTitle})"`.

## Service API

`itsm.directory.service.DirectoryService(session, settings, *, identity=None)`
is the only directory business layer. Adapters call it; they never add
validation, SQL or permission checks. Every operation takes a resolved
`Principal` and authorizes through `IdentityService`.

| Method | Permission | Notes |
| --- | --- | --- |
| `create_department(principal, values, *, source, effective_at, notes)` | `config.departments` | `values`: `name` |
| `update_department(principal, department_id, changes, *, source, effective_at, reason, notes)` | `config.departments` | `changes`: `name`, `active` |
| `get_department` / `list_departments` | `people.view` | filtered by `query`, `active` |
| `create_person(principal, values, *, source, effective_at, notes)` | `people.create` | `values`: `name`, `job_title`, `department_id`, `site_id`, `contact_email`, `contact_phone`, `status` |
| `update_person(principal, person_id, changes, *, source, effective_at, reason, notes)` | `people.edit` | same fields as create |
| `get_person` / `list_people` / `person_label` | `people.view` | filters: `query`, `status`, `department_id`, `site_id` |
| `create_location(principal, values, *, source, effective_at, notes)` | `config.sites` | `values`: `level`, `parent_id`, `name`, `description`, `latitude`, `longitude`, `plan_ref`, `plan_page` |
| `update_location(principal, location_id, changes, *, source, effective_at, reason, notes)` | `config.sites` | same fields plus `active`; `level` is immutable |
| `get_location` / `list_locations` / `location_tree` | `assets.view` | filters: `query`, `level`, `parent_id`, `active`; tree: `root_id`, `depth`, `max_nodes` |
| `history(principal, *, entity, entity_id, limit, offset)` | `people.view` (people, departments), `assets.view` (locations) | append-only events, newest first |

`source` is a trusted constructor argument, never caller- or input-derived:
`rest`, `agent`, `mcp` or `internal` (default). REST always passes `rest`; a
later transport passes its own value. Unknown values are rejected.

`effective_at` is an optional timezone-aware business timestamp; naive values
are rejected. It defaults to the recording time.

### Transaction and audit discipline

Mutations run under the existing serialized SQL write mutex
(`itsm.inventory.codes.serialized`), so no second mutex, nested commit or side
connection is introduced. Order is fixed:

1. authorize the concrete permission (`resource="directory:…"` or
   `department:{id}` / `person:{id}` / `location:{id}`);
2. validate every input, reference and invariant before touching a row;
3. mutate and flush;
4. write exactly one `directory_events` row in the same transaction;
5. make one terminal `IdentityService.record_operation(...)` call, which
   commits business row, event and audit together;
6. on any exception the mutex wrapper rolls the whole transaction back.

A denied request leaves the directory untouched and only the identity layer's
denied audit row behind, which the identity service commits itself before
raising `PermissionDenied`.

## Validation rules and limits

- Person `name` 1–160 chars; `job_title` ≤120; `contact_email` ≤254 and must
  contain `@` without whitespace; `contact_phone` ≤40 with only `+ - . ( )`
  separators and digits; `status` is `active` or `inactive`, default `active`.
- Department `name` 1–120, unique case-insensitively (`name_key` on a
  casefolded, whitespace-collapsed value).
- Location `level` is one of `site`, `building`, `floor`, `room_zone`. A
  `site` has no parent; `building` requires a `site`, `floor` a `building` and
  `room_zone` a `floor`. The parent must exist, match that level and be active.
  A record may not be moved under itself or into its own subtree (defensive
  guard against pre-existing corrupt rows).
- Location `name` 1–120 and unique among siblings; `description` ≤1000.
- Coordinates are optional, site-only, always paired (both or neither),
  finite, within ±90/±180 and limited to 9 decimals. Setting one alone, or on a
  non-site location, is rejected; sending both as `null` clears them.
- `planRef` ≤64 and `planPage` ≤32; both reject `/`, `\`, `..` and `://`
  because they are references, not paths or URLs.
- Deactivation is refused while an active person references the department or
  site, or while an active child location exists: `409 conflict`.
- Reactivation is validated like creation. Activating an inactive location
  revalidates its effective parent (the patched `parent_id`, or the stored one
  when the patch omits it); activating an inactive person revalidates the
  effective `site_id` and `department_id` (patched, cleared or stored).
  A reactivation patch that replaces or clears an inactive reference is
  evaluated with the resulting references, not the previous ones. The check
  runs before any row, event or audit write, so a rejected reactivation leaves
  the record inactive with unchanged history. Deactivation and metadata edits
  keep their existing behavior.
- Patches must change at least one field; unknown fields are rejected.
- Listing/search: `limit` 1–200 (default 50), `offset` ≥0, `query` ≤120 chars
  matched with escaped `LIKE`. Tree: `depth` 1–4 (default 2), `max_nodes` 1–500
  (default 200), returning `truncated: true` when the node budget stops the
  walk. History: `limit` 1–200, `offset` ≥0.

## REST surface

Under the versioned prefix (default `/api/v1`), with the existing
`authenticated_actor` dependency and `mutation_guard` for every mutation
(Origin + CSRF for cookie sessions; bearer machine credentials are exempt from
CSRF but keep their own permissions):

- `GET|POST /departments`, `GET|PATCH /departments/{id}`,
  `GET /departments/{id}/history`
- `GET|POST /people`, `GET|PATCH /people/{id}`, `GET /people/{id}/history`
- `GET|POST /locations`, `GET /locations/tree`, `GET|PATCH /locations/{id}`,
  `GET /locations/{id}/history`

Mutations accept `effectiveAt`, `reason` and `notes` in addition to the entity
fields. Status thresholds come from the existing error envelope: `422`
validation, `403` permission/CSRF, `404` unknown record, `409` conflict.

## Asset/person relation

The relation change must reuse, not re-derive, these pieces:

- `PersonView.id` — permanent UUID stored on the asset side.
- `PersonView.label` — canonical label; it is also in the person payload.
- `DirectoryService.person_label(principal, person_id, *, require_active=True)`
  — authorizes `people.view`, raises `NotFound` for unknown ids and `Conflict`
  for an inactive person, and returns the label.
- `DirectoryService.get_person(principal, person_id)` — full validated view
  when the relation needs status, department or site as well.
- `DirectoryService.get_location(principal, location_id)` and
  `person.site_id` — site selection for the asset's location field.

Asset assignment requires `assets.assign`. Directory does not
add those columns, and never resolves `Asset.responsible` text into a person
automatically; a migration may only link records where the operator chose a
person explicitly.

## Adapters and permissions

REST (`itsm/directory/api.py`) is the only transport in this change. Its
`source` is always `rest`. An agent or MCP surface added later must pass
`agent`/`mcp` and reuse the same service methods; no new permission, role
shortcut or administrator bypass was introduced. Directory uses the existing
catalog codes `people.view`, `people.create`, `people.edit`,
`config.departments`, `config.sites` and `assets.view`, so the built-in
`reader` (read), `operator` (people write) and `admin` (all) roles already
behave as expected.
