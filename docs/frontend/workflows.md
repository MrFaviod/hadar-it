# Imports, exports and bulk workflows (frontend)

How the import wizard, reusable profiles, bulk actions, exports, attachments and warranties in the interface use the server workflow API described in [Workflows](../backend/workflows.md).

## Import and reusable profiles

The original five-step `AssetTransferViews.TransferImport` is decorated by `assets/js/transfer-server.js`. Real CSV/XLSX bytes go to server inspection, then configured server analysis. Mapping, sheet selection/defaults, explicit conflict decisions, confirmation and receipt summaries keep the incumbent interaction. No `AssetTransferEngine.applyRow`, fixture files or browser storage are inventory authority. Empty cells preserve existing values unless explicitly configured otherwise; permanent IDs never change.

Human approval binds the exact preview. Resolving a conflict invalidates approval. Execution checks current permissions and target versions. Imports over the UI threshold use the existing Huey adapter and opaque operation/job locators, with persisted progress rather than simulated delays. SQL-backed profiles distinguish import and export kinds; built-ins are not deleted by the dialog.

## Bulk and export

The inventory action **Editar esta página** opens the original four-step BulkEditor with the loaded page selected. Individual checkboxes adjust the selection. Unloaded and retired assets remain visible as omissions rather than being silently submitted. Explicit selected fields are previewed, approved and executed through canonical services; unselected fields remain unchanged and each affected asset has history. This entry does not claim to operate on every unloaded search result.

The original export view sends server selection/filter/field options and downloads the original returned Blob. The permanent UUID column is always retained. CSV separators use named wire tokens; header, BOM and empty-column controls are server-validated. XLSX export is explicitly disabled: no CSV is disguised as a spreadsheet. Browser-only text filters that cannot be represented in the server contract are reported rather than silently ignored. Server-side all-selection remains bounded.

## Attachments and warranties

`AssetPhase6` owns authenticated upload/list/download/delete requests. Bytes are not embedded in browser persistence. The existing warranty editor, panel, center and settings use server DTOs and retain their original template classes and identifiers. Duration omits a competing expiry date; the server calculates calendar expiry and coverage. A single receipt is an attachment UUID. Uploading a receipt stores actual bytes before linking; removing the reference never deletes the file.

The warranty center loads bounded server pages and joins already-loaded inventory only for display names, falling back to the UUID. Coverage is filtered server-side. Other search/site/category/provider filters and counts describe loaded rows, not an invented global total. Only `expiringDays` is persisted from settings with `config.general`; other view filters are explicitly session-only.

## Session and cancellation invariants

Reuse `AssetAccess.request` for cookie, Origin and CSRF handling, including raw uploads, Blob downloads and 204 responses. Late reads/writes must match the current session token, resource object identity and request epoch. Check again after file reads and before sending a mutation. A stale finally block cannot clear another session's busy state. Logout, identity replacement and unmount abort owned requests and stop polling. No backend-connected domain falls back to localStorage or prototype mutators.
