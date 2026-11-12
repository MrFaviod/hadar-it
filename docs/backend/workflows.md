# Workflows

The server API for import analysis, approved previews, queued execution, exports and individual warranties, and its limits. It is not a production certification.

## Import analysis

`POST /api/v1/imports/analyze?filename=assets.csv&options=<JSON>` accepts the raw file body after cookie Origin/CSRF validation or machine bearer authentication. It persists an operation preview, not asset changes. Supported input is CSV or XLSX, up to 10 MiB, 5,000 data rows, 100 columns and 20 worksheets. XLSX expanded ZIP contents are bounded; formulas are not evaluated. CSV encodings include UTF-8, UTF-8 BOM, Windows-1252 and Latin-1.

Options include `mapping`, `headerRow`, `delimiter`, `encoding`, `decimalSeparator`, `category`, `siteFromSheet`, `overwriteEmpty`, `matchFields` and a saved `profileId`. `selectedSheets`, `sheetMappings`, `sheetSites` and `sheetCategories` configure individual worksheets. Mapping targets use canonical asset fields, supported camelCase aliases, or `technical.<key>`. Empty cells preserve stored values unless `overwriteEmpty` is explicitly true. Native Excel dates are decoded as ISO dates. Declared `dateFields` (technical fields) use strict `dateFormat`: `%d/%m/%Y`, `%m/%d/%Y` or `%Y-%m-%d`; invalid dates become row errors.

`inspectOnly: true` returns bounded raw sheet metadata (`id`, `name`, `columns`, `rows`, `total`, `hasMore`) before matching or creating an operation. It creates no assets, history, code allocations or operation records. Formula text remains opaque text, never evaluated.

The permanent asset UUID is the only automatic update match. Unknown supplied UUIDs are errors, not new asset UUIDs. Quick codes, serials and IPs generate possible matches requiring a decision. Ambiguous rows cannot be approved. Existing UUIDs never change. Built-in profiles cover basic CSV, decimal-comma CSV and worksheets named after sites; custom profiles persist through `/import-profiles`.

## Fixed previews and approval

`POST /bulk/preview` fixes an explicit `assetIds` selection or supported nonempty filters, action, changed values and the current version of each target. Actions are `update`, `archive`, `transfer`, `assign` and `return`. Only selected fields are changed. Export uses `/assets/export` separately.

`GET /operations/{id}` returns bounded rows, progress, summary, state and a queue job identifier when present. UUIDs are locators, not shared access: another human receives `404` even with inventory permissions. The owner controls its preview. A machine owner's persisted human delegator may read, resolve and approve that proposal. `/resolve` invalidates prior approval; `/approve` requires a currently authorized human and rejects unresolved conflicts. Machines cannot approve.

For human→machine execution, the machine must be explicitly delegated to that human in the existing identity record, and that human must own and have approved the fixed preview. Only then may the machine read, enqueue or execute it; it cannot resolve/change the human's rows. Undelegated machines and other humans are not collaborators by default. Existing operations keep their owner and approval; former UUID-only sharing must use this persisted delegation or prepare a new owner-local preview. Inventory itself remains installation-global.

`/execute` uses the same canonical inventory services as direct HTTP mutations and agent tools. The approved human and current executor must still have the relevant permissions. Target versions are checked again before mutation. Each row has a durable result receipt; successful rows are not replayed. A stale or invalid row can fail while other rows succeed. Each changed asset retains its own history. Approval is not an authorization bypass.

## Huey execution

`POST /operations/{id}/enqueue` requires the same fixed approval and returns HTTP 202 with an operation and job locator. The existing Huey adapter dispatches only a fixed business function with the SQL operation ID; there is no additional queue system. API and worker must share main SQL configuration and task storage. The executor session or exact machine credential must remain unrevoked and unexpired, and current authority and the persisted owner/delegation frontier are rechecked on execution. Changing the delegator invalidates the former handoff; a stale approver is not an access grant.

The operation SQL records provide business progress. Huey task results alone are not proof that a row was applied. Dispatch uses a conditional SQL state claim; a missing queue dispatch can reuse the stored job locator. Failure marking does not regress an operation already completed. Trusted source and executor authority are captured server-side, never from request fields.

Queue storage failures return a sanitized HTTP 503 and leave the persisted operation retryable.

## Export

`POST /assets/export` accepts an explicit selection or supported filters and allowlisted fields. It returns real CSV bytes, always including permanent IDs first. Optional `options` support named `separator` (`comma`, `semicolon`, `tab`, `pipe`), strict boolean `headerRow`, `bom` and `includeEmpty`. Defaults preserve comma/header/BOM/all columns; `includeEmpty: false` drops wholly empty columns except the permanent ID. `filters: {"all": true}` selects the entire bounded inventory, including archived records; other filters and explicit IDs remain supported. Text beginning with `=`, `+`, `-`, `@`, whitespace (including U+0085 and U+FEFF), C0 (U+0000–001F), DEL (U+007F) or C1 (U+0080–009F) receives a literal apostrophe prefix. Actual numeric values, including negative decimals, retain their numeric spelling; numeric-looking text remains text. CSV quoting preserves delimiters, quotes and CR/LF. The frontend panel and transfer downloads share the same typed writer; report CSV reuses the backend export cell rule, including headers. Safe text/numeric CSV can roundtrip through import preview. The apostrophe is intentional exported data for dangerous text: generic CSV import does not strip it or promise byte-identical roundtrip for neutralized text. No spreadsheet application execution was certified. It does not return CSV under an XLSX filename. Genuine XLSX export is not currently implemented.

## Individual warranties

`GET`, `PUT` and `DELETE /assets/{id}/warranty` manage a single independent warranty per asset. Fields are supplier, purchase date, duration in calendar months or explicit expiration, status, receipt attachment ID and notes. Month addition clamps to the last valid day of the resulting month. Receipt IDs must belong to the same asset and remain undeleted. A referenced attachment cannot be deleted before clearing the warranty reference.

`GET /warranties?coverage=current|expiring|expired|unknown` supports bounded pages. `/warranty-preferences` stores the upcoming-expiration window, default 30 days, range 1–365. Reading uses `assets.view`; changing preferences uses `config.general`; editing an individual warranty uses `assets.edit`. No shared warranty or collective contract is introduced.

## Shared agent tools

Pydantic AI and FastMCP expose the same five operations: `prepare_inventory_import` (bounded CSV text, no filesystem path), `preview_bulk_operation`, `get_inventory_operation`, `resolve_import_conflict` and `apply_inventory_operation`. All five tools return at most 20 rows with the true `total` and `hasMore`; retrieve later pages through `get_inventory_operation`. REST retains its bounded full-page contract for the browser wizard. There is no machine approval tool, arbitrary callable, shell, SQL, browser or provider URL input. REST upload supports binary XLSX; the text tool must not be described as a binary upload client.

## Persistence and verification boundaries

Apply explicit migrations before starting API/worker. The new additive revisions are `0011_attachments` and `0012_workflows`; they do not backfill or rewrite existing inventory. Attachment bytes have independent persistent storage; see [attachments](attachments.md). Existing raster photo/FOV endpoints are unchanged.

The default main database remains PostgreSQL; local verification uses fresh SQLite. Existing external-engine tests require explicit disposable database settings and may skip. No deployment, external-engine certification, OCR, advanced PDF generation, autonomous interpretation or mandatory external storage service is implied. Final acceptance, browser/design preservation and independent security review remain tracked, not completed here.
