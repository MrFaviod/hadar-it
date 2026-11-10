# Relationships and structured history

Phase 5 adds typed directed relationships between permanent assets and enriches
asset history with trusted origin/entity metadata. This document describes the
backend contract only. REST wiring is mounted by the parent integration task;
directory/location filters and Vue use are explicitly out of this slice.

## Authority and surfaces

`itsm.relationships.service.RelationshipService` is the only relationship
business layer. REST routes, Pydantic AI tools and FastMCP tools must call it;
adapters never duplicate validation, SQL or permission checks.

| Operation | Permission | Notes |
|---|---|---|
| `list`, `graph`, `list_types` | `assets.view` | Reads include archived assets and edges. |
| `create`, `update`, `remove`, `move_host` | `assets.edit` | Checked on every affected endpoint. |
| `create_type`, `update_type` | `config.general` | Type keys are stable and never renamed. |

Authorization is `IdentityService.authorize`; a denial is audited and commits.
Every mutation ends with one `IdentityService.record_operation` call, which is the
terminal audit commit for the edges, both endpoint histories and the audit row.

`source` is a trusted constructor keyword (`rest`, `agent`, `mcp`, `internal`,
default `internal`). A request payload can never choose the history origin; the
adapter sets it once when building the service. `InventoryService` accepts the
same keyword so lifecycle events share the transport context.

## Relation model

Each row is one directed edge `source_id -> target_id` under a stable `type_key`.
Asset ids are the permanent asset UUIDs. `(source_id, target_id, type_key)` is
unique, so the same pair may carry different relation types but never an exact
duplicate. Multiple valid relations are allowed.

Default type snapshot (migration `0007_relationships`, not application startup):

| Key | Forward | Inverse | Containment |
|---|---|---|---|
| `connected_to` | Conectado a | Conectado desde | no |
| `installed_in` | Instalado en | Contiene | yes |
| `hosted_in` | Alojado en | Aloja | yes |
| `protected_by` | Protegido por | Protege a | no |
| `depends_on` | Depende de | Requerido por | no |
| `associated_with` | Asociado con | Asociado con | no |

Types can be deactivated (`active=False`) without deleting edges; existing edges
stay visible with `typeActive=false`, while new or updated edges require an
active type. Type keys are immutable.

General directed graphs may contain cycles. Only **containment** semantics
(`installed_in`, `hosted_in`, including mixed containment edges) reject
self-relations and ancestor cycles, because those would make the hierarchy
incoherent. No global DAG is imposed.

## Hosting invariant

`hosted_in` represents a VM/container host relationship. One child has at most one
host, and a child cannot be its own host. Moving a VM between hosts is the
explicit `move_host(child_id, new_host_id, reason=..., notes=..., effective_at=...)`
operation: the old `hosted_in` edge is replaced by the new one atomically, the
asset UUID and technical data are untouched, and all three affected assets get a
`host_moved` history event with the old/new host or hosted child. Other relation
types keep normal multiplicity.

`installed_in` is containment but not exclusive; an asset may be installed in
several places when the modeled topology requires it.

## Archived endpoints and purge

Archived assets remain queryable and existing edges stay visible. New or moved
relations with an archived endpoint are rejected. Removing/cleaning an edge that
touches an archived asset is allowed.

Permanent purge is rejected with `Conflict` before any write when either endpoint
still has edges. The graph therefore cannot be left dangling, and a purge never
deletes another asset's relations.

## Bounded queries

`list(asset_id=... | asset_ids=[...], type_key=..., direction="both")` returns a
global, paginated page (`limit` 1-200, default 50; `offset >= 0`). Bulk endpoint
selection is capped at 50 ids. `direction` is `out`, `in` or `both`; each returned
edge carries `direction` (`outgoing`/`incoming`, relative to the selected asset)
and the matching `label` (forward or inverse display label).

`graph(root_id=... | asset_ids=[...], depth=..., direction=..., type_key=...)`
performs level-wise batched `IN` queries; it never loads all inventory and then
truncates.

- `depth` 1-5, default 2.
- At most 200 nodes and 400 edges per traversal.
- Truncation is explicit: `nodesTruncated`, `edgesTruncated`, `depthTruncated`,
  plus a combined `truncated` flag. `depthTruncated` means the selected depth was
  reached with unexplored containment/edge endpoints remaining.
- Without a root, the same method returns a page of edges plus their endpoint
  nodes, with global `total`/`limit`/`offset`; it is not a traversal.

The service exposes `GraphNode` summaries, not the full asset projection. This is
deliberate: graph callers need identity/classification, not media or every field.

## Structured asset history

`asset_history` gains additive columns: `source` (trusted origin, default
`internal`), `entity_type` (default `asset`), `entity_id` (defaults to the asset
id; migration backfills old rows), `effective_at` (nullable, always timezone-aware
when supplied) and `notes` (nullable, max 500 chars). `created_at` remains the
insertion time and is distinct from `effective_at`.

Relationship events record the same `changes.relationship` object (`old`/`new`
descriptor with `id`, `type`, `sourceId`, `targetId`) on **both** endpoints, plus
`reason`, `notes`, `effectiveAt`, `entityType="relationship"` and `entityId` set
to the edge id. Existing asset lifecycle events (`created`, `updated`, `archived`,
`restored`, `retired`, `purged`, batch/clone) use the constructor `source` and
default entity `asset`; their payload shape is unchanged.

`HistoryView.as_payload()` keeps the legacy fields. `structured_payload()` adds
`source`, `entityType`, `entityId`, `effectiveAt` and `notes` for adapters that
read the enriched record. History is append-only and survives purge; the
structured representation preserves the old keys.

## Thin REST adapter

`itsm.relationships.api.create_relationship_router()` is a thin adapter over the
service. It uses the shared identity dependencies (`authenticated_actor` for
reads, `mutation_guard` for mutations) and builds one service per request with
`source="rest"`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/relationship-types` | Active types; `includeInactive=true` for all. |
| POST | `/relationship-types` | Create a custom type (`config.general`). |
| PATCH | `/relationship-types/{key}` | Labels, containment or `active` toggle. |
| GET | `/relationships` | Paginated edges filtered by `assetId`, repeated `assetIds` (max 50), `typeKey`, `direction`. |
| POST | `/relationships` | Create an edge. |
| PATCH | `/relationships/{id}` | Change type/reason/notes/effectiveAt. |
| DELETE | `/relationships/{id}` | Remove an edge (optional JSON reason/notes/effectiveAt). |
| POST | `/relationships/host-move` | Replace the `hosted_in` host atomically. |
| GET | `/infrastructure/graph` | Bounded `rootId`/`assetIds` traversal or global page. |

Register HTTP routers before the MCP mount: a prefix mount can shadow routes
registered after it.

## Integration boundaries

The application composes HTTP routing, structured history, Directory and the
frontend graph. Agent/MCP adapters must construct the service with the matching
`source="agent"` or `source="mcp"`, preserving the same permission checks.
