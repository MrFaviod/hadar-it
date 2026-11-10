# Agent and MCP operational tools

Pydantic AI and FastMCP expose canonical inventory, maintenance, intervention,
incident, monitoring and document services. This guide describes their implementation contracts and operational limits.

## Technical operations on both surfaces

`itsm.agents.runtime` and `itsm.mcp.server` register the same technical operations.
Both call the canonical `MaintenanceService` and `InterventionService`; neither
surface reimplements a business rule, month calculation, authorization check,
audit entry or transaction.

| Tool | Canonical call | Permission | Result |
| --- | --- | --- | --- |
| `search_maintenance` | `MaintenanceService.list_plans` | `assets.view` | Bounded plan page |
| `complete_maintenance` | `MaintenanceService.complete_plan` | `assets.edit` | Completed plan with recalculated `dueOn` |
| `record_intervention` | `InterventionService.create` | `assets.edit` | Intervention with costs and attachments |
| `create_incident` | `InterventionService.create_incident` | `assets.edit` | Incident summary |
| `link_incident_assets` | `InterventionService.update_incident_assets` | `assets.edit` | Incident detail with the replaced affected set |
| `get_technical_history` | `InterventionService.asset_technical_history` | `assets.view` | Bounded persisted history page |
| `prepare_incident_resolution` | `InterventionService.prepare_resolution` | `assets.edit` | `{incidentId, token, revision, preparedAt}` |
| `confirm_incident_resolution` | `InterventionService.confirm_resolution` | `assets.edit` | Resolved incident detail |
| `search_incidents` | `InterventionService.list_incidents` | `assets.view` | Bounded incident page |

The two surfaces differ only in transport conventions: the chat tools use the
same snake_case arguments as the rest of the Pydantic AI toolset, and FastMCP
maps those arguments to the canonical service keyword arguments. Nested part
objects are typed (`name`, `quantity`, `unitCost`) and reject unknown fields.
Part quantities are integers; `unitCost` and `labor_cost` use decimal strings
(for example `"12.50"`), not floating-point JSON numbers. The tool schema matches
the canonical service's exact-money validation.

## Identity and authorization

- Chat requests keep the existing human session: cookie plus Origin/CSRF. The
  transport resolves the `Principal`; the message, history and tool arguments
  can never supply one.
- Every MCP operation re-reads the raw `Authorization: Bearer` header from the
  transport and authenticates it against persisted machine credentials. Cookie
  sessions are never accepted, and a revoked or expired credential fails the
  next operation even on an already-open client.
- Services apply live Casbin permissions for the authenticated principal.
  Reads require `assets.view`; operational writes require `assets.edit`. There
  is no hidden administrator path, and a tool never claims a permission it did
  not exercise.
- The service source is fixed by the adapter: `agent` for chat, `mcp` for the
  mounted server. Audit records and technical history carry that source.

## Structured, bounded operations

Each write is one call, not a sequence of partial updates:

- `record_intervention` accepts the asset, type, description, technician,
  occurrence date, status, notes, parts, labor cost, attachment ids and the
  optional incident or preventive plan linkage. Attachment ids must reference
  existing attachments that belong to the intervention asset; the service
  validates them, the tool only bounds the list.
- `create_incident` accepts the primary asset, description, priority, every
  affected asset, responsible person and opening date in one call.
  `link_incident_assets` atomically replaces the unique affected set.

Result pages are clamped to at most 50 rows with the true `total`, `limit` and
`offset`; ids lists are limited to the same bound. The chat surfaces the same
page under its `results` list. Callers page with `limit` and `offset` instead of
requesting unbounded data.

## Maintenance completion

`complete_maintenance` delegates the entire completion to
`MaintenanceService.complete_plan`. The service anchors the next due date to the
actual completion date using calendar-month arithmetic with month-end clamping,
writes the single terminal business audit entry and returns the updated plan.
The tool does not calculate dates itself, and a corrective intervention never
resets a preventive cycle.

## Incident resolution prepare and confirm

- `prepare_incident_resolution` returns a short-lived opaque token bound to the
  incident revision. It does not change the incident status, and incident reads
  never return the token.
- `confirm_incident_resolution` requires the incident id and token. The service
  revalidates the current principal, permission, incident state and revision.
  A stale, replayed or revoked token is a conflict that leaves status, history
  and costs unchanged.
- Any currently authorized principal may confirm, including an authorized
  machine; there is no fabricated human-only barrier. Conversely, no tool
  resolves or closes an incident implicitly, and connectivity recovery does not
  auto-resolve anything.

## Model and provider isolation

The agent uses a server-configured provider/model; tool arguments cannot select
a model, endpoint, principal or service source. Tests replace the model with a
Pydantic AI `FunctionModel`, keep `ALLOW_MODEL_REQUESTS=False`, and call real
tools, real services and a real mounted MCP server over streamable HTTP. No
check forwards tools through a mock transport or consumes a provider request.

## Monitoring operations (Phase 8)

Both transports call `MonitoringService` with the authenticated principal and
the fixed `agent` or `mcp` source. They use the same bounded projection; they do
not accept arbitrary PromQL, exporter URLs, credentials, or caller authority.

| Tool | Canonical call | Permission | Result |
| --- | --- | --- | --- |
| `get_asset_availability` | `get_device` | `assets.view` | Availability, uptime, explicit missing states, period and provenance |
| `get_asset_metrics` | `get_device` | `assets.view` | Historical series summarized to at most 60 points each, with period and provenance |
| `investigate_outage` | `get_device`, `list_alerts` | `assets.view` | Measured availability plus at most ten persisted alert summaries |
| `list_active_alerts` | `list_alerts` | `assets.view` | At most 50 firing alerts, true total and pagination |
| `acknowledge_alert` | `acknowledge` | `assets.edit` | Acknowledgement without resolving the condition |
| `link_alert_incident` | `link_incident` | `assets.edit` | Existing incident linkage, or atomic canonical incident creation and linkage |
| `prepare_monitoring_maintenance` | `prepare_maintenance` | `assets.edit` | Suggested window only; no persistence or implicit silence |

The historical periods are `24h`, `7d` and `30d`. `unmonitored`, `no_data` and
`unavailable` are distinct from `down`; a Prometheus connection failure cannot
prove device failure. Tool output includes the actual queried range and
Prometheus provenance. Alert labels and annotations are not exposed in the
model projection. A recovery neither resolves an incident nor grants authority
to do so; existing incident preparation/confirmation remains the closure path.

Notification delivery is asynchronous: alert service mutations atomically
create durable outbox work through the notification service. These tools do not
send credentials or execute delivery themselves.

## Reports and labels

Both transports use the canonical report service and the same strict `ReportRequest`
schema as HTTP. The authenticated transport supplies the principal; requests carry
only family, template selection or structured blocks, canonical asset UUIDs, filters,
field choices, output mode and optional physical label options. They cannot submit
HTML/CSS, asset records, actor authority, shell commands or resource URLs.

| Tool | Outcome |
| --- | --- |
| `list_report_templates` | Available builtin and persisted custom structured templates. |
| `prepare_report` | Current authorized selection with `matched`, bounded first 20 assets/rows, columns, summary and `hasMore`; no HTML. |
| `generate_report` | Durable queued generation job, not an assertion that a PDF already exists. |
| `report_job_status` | Current owned job status, progress, errors and produced document references. |
| `report_documents` | Owned job identifier/status and protected document references, not raw file bytes or filesystem paths. |
| `generate_labels` | Queued generation using required structured label options and canonical asset selection. |

Private generation/read requires current `assets.view` plus job/document ownership
rules. Huey re-resolves the stored executor locator before rendering; downloaded
documents recheck current identity, permission, ownership and retention. Neither
surface grants public access: independent `reports.share` authorization remains a
separate explicit HTTP action. The model must poll job status and distinguish a
queued result, completed document and recorded failure. It must never turn an error
or empty result into a fabricated generated file.
