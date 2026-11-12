# Reports, labels and QR codes (frontend)

The original Vue report, label, QR and settings views remain in the existing React host. The server owns selection, projections, templates, document jobs, files and public shares. The browser keeps no document history, queue or labels in `localStorage`; the only anonymous call is a public report read whose capability is the share token.

## Request contract

`POST /api/v1/reports/preview` and `POST /api/v1/reports/jobs` receive the same body. `fields` and the nested template fields are family-specific; the request projection wins over the template projection.

```json
{
  "family": "history",
  "templateId": null,
  "template": {
    "id": "custom-history-by-site",
    "name": "Historial por sede",
    "description": "",
    "family": "history",
    "mode": "list",
    "format": "A4",
    "fields": ["quickCode", "action", "actor", "effectiveAt", "entityType", "changes", "notes"],
    "logo": true,
    "images": false,
    "version": 1,
    "blocks": [
      { "id": "heading-1", "type": "heading", "label": "Encabezado", "text": "Historial", "enabled": true },
      { "id": "table-2", "type": "table", "label": "Tabla de datos", "text": "", "enabled": true },
      { "id": "footer-3", "type": "footer", "label": "Pie de página", "text": "", "enabled": true }
    ]
  },
  "assetIds": ["5a1e0c10-0001-4f10-9a10-000000000001"],
  "filters": {
    "search": "",
    "category": "",
    "siteId": "",
    "locationId": "",
    "responsiblePersonId": "",
    "status": "",
    "archived": false,
    "from": "2026-01-01",
    "to": "2026-12-31",
    "actor": "Ana Canónica",
    "event": "",
    "warrantyFilter": ""
  },
  "fields": ["quickCode", "action", "actor", "effectiveAt", "entityType", "changes", "notes"],
  "mode": "consolidated",
  "group": "site",
  "output": "pdf",
  "name": "Historial por sede",
  "labels": null
}
```

`assetIds` is empty when the user chooses **Todos los resultados**; the server re-resolves the filters. `mode` is `consolidated` or `individual`. `group` is top-level `none|category|site|responsible|location|status`. `output` is `pdf|csv|xlsx`. `archived` is `true`, `false` or `null`, never the view label `"active"`/`"archived"`.

## Field mapping

| Family | Allowed field keys | Default columns |
| --- | --- | --- |
| Inventory | `id`, `quickCode`, `name`, `category`, `site`, `location`, `status`, `responsible`, `serial`, `brand`, `model`, `ip`, `purchaseCost`, `technical` | `id`, `quickCode`, `name`, `category`, `site`, `location`, `status`, `responsible` |
| History | `assetId`, `quickCode`, `name`, `action`, `actor`, `effectiveAt`, `entityType`, `entityId`, `statusOld`, `statusNew`, `changes`, `notes`, `source` | `quickCode`, `action`, `actor`, `effectiveAt`, `entityType`, `changes`, `notes` |
| Warranty | `assetId`, `quickCode`, `name`, `category`, `site`, `supplier`, `purchaseDate`, `expiresOn`, `coverage`, `receiptId`, `notes` | `quickCode`, `name`, `category`, `site`, `supplier`, `purchaseDate`, `expiresOn`, `coverage`, `receiptId`, `notes` |

Label content is a separate vocabulary: `logo`, `name`, `id`, `code`, `qr`, `site`, `location`, `serial`. Labels send the canonical inventory request fields as `[]` and the label selection under `labels.fields`; `code` is not an asset field and `quickCode` is not a label field.

The history view maps **Actor** to `filters.actor`; date bounds map to `from`/`to`. Warranty coverage maps to `warrantyFilter=active|expiring|expired|missing` (the view labels “Vigente”, “Por vencer”, “Vencida”, “Sin datos”). Grouping never changes the selected rows: W2 sorts stably, adds contiguous group labels and `summary.groups [{key,label,count}]`, and preview/PDF/CSV/XLSX use that same table.

Templates are versioned structured definitions. The editor exposes the eight admitted blocks (`heading`, `text`, `asset`, `table`, `photo`, `summary`, `qr`, `footer`), page format and family fields only. Pristine server templates use `templateId`; edited builtins become a new `custom-…` definition. Saving sends `PUT /api/v1/reports/templates/{id}`; the server revalidates the structured definition and authorizes template administration.

## Routes and authority

| Use | Route | Authority |
| --- | --- | --- |
| Template list/save/delete | `GET/PUT/DELETE /api/v1/reports/templates[/{id}]` | `assets.view` / `assets.edit` |
| Settings and branding | `GET/PUT /api/v1/reports/settings` | `assets.view` / `config.general` |
| Selection | `GET /api/v1/assets/search?query=&limit=&offset=…` | `assets.view` |
| Preview | `POST /api/v1/reports/preview` | `assets.view` + mutation guard |
| Jobs and files | `POST/GET /api/v1/reports/jobs`, `GET /api/v1/reports/jobs/{id}`, `GET /api/v1/reports/documents/{id}/download` | `assets.view` |
| Private report | `GET /api/v1/reports/assets/{id}` | `assets.view` |
| QR | `GET /api/v1/reports/assets/{id}/qr` | `assets.view` |
| Share create/revoke | `POST /api/v1/reports/assets/{id}/shares`, `DELETE /api/v1/reports/shares/{id}` | `reports.share` |
| Public report | `GET /api/v1/reports/public/{token}` | share token only |

`AssetAccess.request` supplies cookies, Origin and CSRF handling for every authenticated call. Reads carry a resource epoch and abort their previous controller; late preview/job/download/QR responses cannot overwrite a newer session or selection. Logout and identity changes clear the phase-9 state and stop job polling.

`GET /api/v1/reports/assets/{id}/qr` returns private immutable-identity URLs and share metadata, not a recovered secret token. The stored model keeps only a hash, so a later QR read returns share metadata (`id`, `fields`, `expiresAt`) without `url`; the panel hides **Copiar/Abrir** instead of inventing a URL. A newly created share returns its URL once.

## Original UI actions

- **Reportes → Preparar**: family, editable template, family fields, search/site/location/responsible/status/archived filters, history dates and actor/event, warranty coverage, **Agrupar por**, consolidated/individual composition, output PDF/CSV/XLSX, selection search/page/toggle/current page/all results/clear, preview iframe, and **Generar**.
- **Reportes → Trabajos**: persisted queued/running/completed/failed state, progress, errors and real document downloads. Selecting a job loads only that owner's job; a deleted actor fails closed server-side.
- **Configuración → Reportes**: base URL, branding and label defaults. **Configuración → QR/Etiquetas** expose only the admitted share expiry and physical label options.
- **Etiquetas**: format/page geometry, fields, asset selection and jobs share the same server preview/document pipeline as reports.
- **Activo → QR/compartir**: loads the server SVG, creates a bounded public-field link and revokes a share. Copy/Open appear only for a URL the server returned; no local token is fabricated.
- **Asset report**: `#/reporte/{id}` loads the authenticated private projection. `#/reporte/{id}/publico?share={token}` boots without a session only for the public report; every other unauthenticated route goes to login.

No report, label, job, share or public data is read from `localStorage` or a prototype mutator.

## Labels and documents

The original label center keeps its format, geometry, offset and field controls. Values are bounded by the server contract (margins 0–50 mm, gaps 0–30 mm, 1–12 columns, offset 0–500) and every preset is normalized before sending. The server preview and PDF use the same label options; the iframe is sandboxed without scripts. Page estimates in the UI use the active preset's columns and rows and never replace the server preview.

Reports generate real queued documents. The jobs view polls the owned job, shows persisted progress and errors, and downloads the returned Blob through the server URL. CSV/XLSX reuse the same canonical table; there is no client-side document fabrication.
