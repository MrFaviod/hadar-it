# Agent and MCP operational tools

The conversational agent (`itsm/agents/runtime.py`) and the mounted FastMCP server
(`itsm/mcp/server.py`) expose the same compact operational tools on top of the
canonical services. Both transports reuse `itsm/operations/tools.py`, so validation
and payload bounds cannot drift between them.

## Tools

| Tool | Purpose | Service |
| --- | --- | --- |
| `get_operational_summary` | Availability, uptime, alert/incident and inventory summary for one period and optional category/site scope. | `DashboardService.summary` |
| `search_everything` | Authorized entity search (assets, people, locations, sites, incidents, maintenance, categories, sections, saved views) with grouped types and a bounded page. | `SearchService.search` |
| `query_relationships` | Focused relationship traversal (`asset_id`, `depth`, `direction`, `type_key`) or paginated global graph (`limit`/`offset`). | `RelationshipService.graph` |
| `list_saved_views` | The caller's durable views, favorites and shortcuts with the theme mode. Read-only; mutations stay on the existing authorized REST/UI surface. | `WorkspaceService.get_state` |

Existing tools such as `get_asset_metrics`, `list_active_alerts`, `report_documents`
and the relationship mutations are unchanged; the new tools do not duplicate their
queries.

## Authorization

- The agent receives its principal from the authenticated chat request; no tool
  argument can supply an actor, source, role or permission.
- MCP revalidates the persisted bearer credential immediately before every tool
  operation (`run_operations` → `IdentityService.authenticate_token`), so revoking a
  machine identity invalidates an already open MCP session.
- Each service keeps its own authorization: `assets.view` for summaries, search,
  relationships and workspace state; `people.view` only where the search adapter
  queries people; owner-or-shared visibility for saved views.
- A token without the MCP `assets.view` scope is rejected at the transport before any
  tool runs.

## Bounds and provenance

- Every page is clamped to 1–50 rows (`MAX_RESULTS`), offsets are non-negative, and
  search kinds/period/type keys are validated before the service call.
- Relationship results cap nodes and edges at 50 each and report
  `truncated`/`nodesTruncated`/`edgesTruncated`/`depthTruncated`; a focused traversal
  never falls back to scanning every module. Affected devices are the incoming
  `depends_on` edges of a focus (`direction="in"`, `type_key="depends_on"`), while
  `depends_on` with `direction="out"` lists what the focus itself depends on.
- Search returns the engine actually used (`sql` or `meilisearch`), whether the SQL
  fallback applied, and the canonical target for each match.
- The operational summary preserves `generatedAt` and the requested `period`; missing
  metric data is reported as such, not as an outage.
- Node payloads contain identifiers, names, states and summaries only — no full
  module dumps, credentials or server paths.

## Integration prerequisite

`itsm/operations/tools.py` imports `itsm.dashboard.service`, `itsm.search.service` and
`itsm.workspace.service` directly. The installation is valid only once those packages,
their tables (migration 0019) and the startup wiring are present; there is no fallback
path and no demo data. The focused test module therefore collects only in the integrated
installation, then exercises all tools without skips.
