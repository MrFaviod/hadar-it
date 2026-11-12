# Reports, QR codes, labels and generated documents

Reporting turns the reporting, template, QR and label screens into real
authorized documents. One canonical `ReportService` serves HTTP, background
jobs, Pydantic AI and FastMCP; the Vue interface never computes report data.

## Quick path

1. Grant access: `assets.view` reads/generates private reports and labels,
   `assets.edit` saves custom templates, `config.general` edits report settings,
   and the new `reports.share` independently allows creating/revoking public
   links. `reports.share` is seeded only for the administrator role.
2. `GET /api/v1/reports/templates` lists the four built-ins (`inventory-list`,
   `inventory-sheet`, `history-list`, `warranty-list`) plus saved templates.
3. `POST /api/v1/reports/preview` returns the same normalized data and CSS used
   by the final document: `html`, `assets`, `rows`, `columns`, `summary`,
   `matched`, `truncated: false`, `template`, `branding`.
4. `POST /api/v1/reports/jobs` persists the bounded request plus an executor
   locator and returns a job (`202`). The worker calls
   `ReportService.execute(job_id)`; polling uses `GET /reports/jobs/{id}`.
5. Downloads use `GET /reports/documents/{id}/download`: current identity,
   `assets.view`, owner or administrator, retained, integrity-checked bytes.

## Report families

| Family | Data | Rows |
| --- | --- | --- |
| `inventory` | selected assets by ids and/or filters | one row per asset; summary counts, cost, status/category/site |
| `history` | append-only asset history for selected assets | changes/assignments plus intervention/incident technical history in effective-date order |
| `warranty` | per-asset warranty records | current/expiring/expired/missing coverage and a protected receipt reference |

`assetIds` and `filters` always intersect. Filters are empty when null, so an
empty filter object selects everything up to `report_max_assets`; oversized
selections are rejected (never silently truncated). History filters also accept
`from`, `to`, `actor` and `event`. Warranty filters accept
`all|active|expiring|expired|missing`.

History `from` and `to` are **inclusive UTC calendar dates**: each event is
matched on the UTC day of its effective instant (`effectiveAt` when present,
otherwise `createdAt`), so `from` equal to `to` selects that single UTC day and
the result never depends on the server or browser timezone. They are not the
business dates shown on intervention and incident records (`occurredOn` and
`openedOn`): a row can carry an earlier business date while its recorded history
entry belongs to the UTC day it was written. Previews report the first and last
selected UTC days in `summary.from` and `summary.to`.

History merges the asset ledger with the canonical intervention/incident
technical projection; each technical event appears once (the general inventory
page excludes those entity types before merging). Warranty rows expose
`receiptId` as an attachment reference only — never bytes, blob keys or a
public URL.

## Fields and grouping

`ReportRequest.fields` are family-specific, never arbitrary keys:

* inventory: `id,quickCode,name,category,site,location,status,responsible,serial,brand,model,ip,purchaseCost,technical`
* history: `assetId,quickCode,name,action,actor,effectiveAt,entityType,entityId,statusOld,statusNew,changes,notes,source`
* warranty: `assetId,quickCode,name,category,site,supplier,purchaseDate,expiresOn,coverage,receiptId,notes`

When `fields` is empty, inventory uses its template fields and history/warranty
use their meaningful default columns. Preview, PDF, CSV and XLSX all use the
same selected columns and projected rows.

`group` is one of `none|category|site|responsible|location|status` (default
`none`). Grouping sorts rows stably by the group label, keeps rows contiguous,
adds a non-column `group` row key, and reports `summary.groups` as
`[{key,label,count}]` for the chart. Exports never add `group` as a column.

## Templates, preview and output

Templates are versioned structured definitions. Only the admissible block types
(`heading`, `text`, `asset`, `table`, `photo`, `summary`, `qr`, `footer`) are
accepted; template fields use the family field allowlist above, and text is
plain and escaped. Built-ins live in
code and need no startup seed writes. Custom templates use `PUT/DELETE
/reports/templates/{id}` and require `assets.edit`; built-in ids are read-only.

List responses add `builtin: true|false` editing metadata outside the strict
stored definition. The editor references pristine defaults by `templateId` and
saves an edited default under a new custom id; it never overwrites a built-in.

Template images read the existing InventoryService image resource for the
selected assets, bounded by the asset count cap; a missing photo is simply
omitted and rendering continues with the generic layout. Logos are authorized,
bounded raster attachments normalized by the renderer, never fetched from a
URL.

Outputs are `pdf`, `csv` and `xlsx`. CSV/XLSX reuse the established spreadsheet
escaping helper used by the workflow export, including formula neutralization,
and always prepend the immutable identity column (`id`, or `assetId` for
history/warranty rows) when requested fields omit it. Every XLSX value is
written as an explicit string so untrusted text can never become a formula.
Cost totals accumulate canonical `Decimal` values and serialize as an exact
decimal string; currency is never accumulated as float.
`mode: individual` creates one document per selected asset; `consolidated`
creates one document. Individual jobs resolve fields, rows and image bytes per
asset and release them between documents. Labels require the inventory family
and PDF output, and use the physical geometry presets `a4-24`, `a4-21`,
`roll-50x30`, `roll-80x50` or a bounded custom size.

PDFs are composed by the shared composition module and rendered in an isolated
WeasyPrint process with network fetching denied. `report_render_timeout_seconds`,
`report_render_memory_mb` and `report_max_document_bytes` bound execution and
output size.

## QR and public links

`GET /reports/assets/{uuid}/qr` returns `{assetId, url, svg, share}`. The URL is built
from `report_base_url` and the permanent asset UUID:
`https://itam.example.com/#/reporte/<uuid>`. Renaming the quick code, moving the
asset or changing its category never changes the URL. An active share is
reported as `{id, fields, expiresAt, revokedAt}` without a URL/token: only the
hash is stored, so the tokenized URL is returned exactly once by
`POST /shares` and cannot be reconstructed or leaked by a GET.

Private report data keeps the normal `assets.view` authorization. A limited
public link is a separate capability:

* `POST /reports/assets/{uuid}/shares` with `{fields, expiresInDays}` requires
  `reports.share`; only the public subset `id`, `quickCode`, `name`, `category`,
  `site`, `location`, `status` is accepted.
* The random token appears only in the returned URL
  `/#/reporte/<uuid>/publico?share=<token>`; SQL stores only its SHA-256 digest.
* `GET /reports/public/{token}` is the sole anonymous route. It checks the
  active, unexpired share, the current asset and the issuer's current
  independent `reports.share` permission, then returns only the chosen fields.
* `DELETE /reports/shares/{id}` revokes immediately. Revoked or expired links, inactive
  issuers and unknown tokens all return the same 404.

## Branding, labels and storage

Branding comes from `GET/PUT /reports/settings`: organization name, primary and
accent colors, header/footer, and an optional logo that must reference an
existing authorized raster attachment. No URLs, data URLs or filesystem paths
are accepted. Without configuration a generic theme still renders.

Generated bytes live in the existing opaque blob storage; SQL keeps metadata,
blob keys, sizes and digests only. `report_retention_days` controls cleanup:
`ReportService.cleanup()` tombstones metadata first, then deletes bytes. A
failed blob delete leaves a hidden tombstoned row that a later cleanup retries;
no downloadable document points at deleted bytes.

## Operational notes

* Set `ITSM_REPORT_BASE_URL` to the public origin used by QR labels.
* Run the existing Huey consumer; the parent task adapter exposes
  `submit_report(job_id, task_id)`.
* Existing `GET /assets/{uuid}` remains the canonical asset read (with
  `assets.view`) used by the private report page; the report-specific read is
  `GET /reports/assets/{uuid}` so inventory routes are not shadowed.
* Re-running a completed job returns the same documents; retryable storage or
  renderer failures requeue the job and re-resolve executor authority on every
  attempt. Current-authority or validation failures are terminal (`failed`) and
  are not retried by Huey; the SQL job status is the authority even when the
  queue task envelope reports completion.
* A job claim is one conditional SQL `UPDATE` evaluated by the database, not by
  the ORM session: a duplicate delivery of a fresh `running` claim returns the
  current job untouched, a stale claim (twice the render timeout plus 60s, at
  least 120s) is taken over, and concurrent workers store at most one document.
* Machine jobs store only the SHA-256 digest of the transport bearer that queued
  them (HTTP bearer, MCP tool call or agent transport). Execution revalidates
  that exact, non-revoked credential for the same identity; a missing or revoked
  digest fails the job before rendering and stores no document. Human jobs
  revalidate their stored session instead.

## Checklist before release

- [ ] Migrations applied to a disposable database; admin shows `reports.share`.
- [ ] Preview and PDF show the same rows for the same request.
- [ ] Public link returns only selected fields and dies on revoke/expiry.
- [ ] Label PDF page size matches the chosen physical format.
- [ ] Cleanup removes bytes after retention and retries failed deletes.
