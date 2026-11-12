# Report rendering engine

The report engine turns authorized, already-projected data into four
artifacts with one **structured** pipeline and no browser-provided authority:

1. preview HTML (server-composed, resource bytes embedded as data URIs only for
   the sandboxed browser),
2. PDF via WeasyPrint 70 in an isolated child process,
3. CSV/XLSX rows built from the same projections,
4. physical label sheets and individual asset reports with a permanent-UUID QR.

The modules in `itsm.reports` are deliberately free of FastAPI, SQLAlchemy and
settings imports. They are the shared boundary used by the service, the worker
and the agent/MCP tools.

| Module | Responsibility |
| --- | --- |
| `schemas.py` | Strict Pydantic v2 wire contracts, allowlists and builtin templates |
| `composition.py` | Deterministic HTML/CSS plus the exact registered image bytes |
| `rendering.py` | Bounded, isolated WeasyPrint rendering with deny-all fetching |
| `qr.py` | Permanent-URL construction and Segno SVG generation |

## Wire contracts

All models use `extra="forbid"`, string/collection bounds and the camelCase
wire shape; `model_dump()` is directly serializable to the API.

### `TemplateDefinition`

```json
{
  "id": "inventory-list",
  "name": "Inventario · listado",
  "description": "Listado consolidado de activos.",
  "family": "inventory",
  "mode": "list",
  "format": "A4",
  "fields": ["id", "quickCode", "name"],
  "logo": true,
  "images": false,
  "version": 1,
  "blocks": [
    {"id": "heading", "type": "heading", "label": "Activos", "text": "", "enabled": true}
  ]
}
```

* `family` is `inventory`, `history` or `warranty`; `mode` is `list` or `sheet`;
  `format` is `A4` or `Letter`; `version` is exactly `1`.
* `blocks` admits only `heading`, `text`, `asset`, `table`, `photo`, `summary`,
  `qr` and `footer`. Block ids are unique handles; text is plain and escaped.
* `fields` must belong to the selected family. Unknown, duplicated or
  cross-family keys are rejected:
  * inventory: `id, quickCode, name, category, site, location, status,
    responsible, serial, brand, model, ip, purchaseCost, technical`
  * history: `quickCode, name, action, actor, effectiveAt, entityType,
    entityId, statusOld, statusNew, changes, notes, source, assetId`
  * warranty: `quickCode, name, category, site, supplier, purchaseDate,
    expiresOn, coverage, receiptId, notes, assetId`

`builtin_templates()` returns four fresh wire dictionaries without seed writes:
`inventory-list`, `inventory-sheet`, `history-list`, `warranty-list`.

### `ReportRequest`

```json
{
  "family": "history",
  "group": "category",
  "templateId": null,
  "template": null,
  "assetIds": [],
  "filters": {"from": "2026-01-01", "to": "2026-12-31"},
  "fields": ["quickCode", "action", "actor"],
  "mode": "consolidated",
  "output": "pdf",
  "name": "Historial de enero",
  "labels": null
}
```

* `group` is `none` (default), `category`, `site`, `responsible`, `location` or
  `status`. The service groups rows stably and adds a non-column `group` label;
  composition prints the section headings and the `summary.groups` count chart.
* `templateId` and `template` are mutually exclusive, never both.
* `assetIds` are canonical UUIDs (deduplicated, at most 500). Explicit ids and
  filters intersect; an empty filter means “unfiltered”.
* `fields` use the same family allowlist as templates. The service projects the
  same columns for preview, PDF, CSV and XLSX.
* `labels` is only valid for `inventory` + `pdf`.

### `LabelOptions`

`formatId` is `a4-24` (70 × 37 mm, 3 × 8, A4), `a4-21` (63.5 × 38.1 mm,
3 × 7 with canonical printable margins), `roll-50x30`, `roll-80x50` or
`custom`. Presets always win over caller-supplied dimensions; custom geometry
must provide width, height and page size and must fit inside the page margins
after the grid and gaps. An impossible grid raises `ValueError`; labels are
never silently cropped by moving their physical position.

Allowed label fields are `logo, name, id, code, qr, site, location, serial`.
`logo`/`qr` flags add those fields. `widthMm`/`heightMm` are 10–500 mm, page
dimensions 20–1000 mm, margins 0–50 mm, gaps 0–30 mm, 1–12 columns and offset
0–500. At most 2,000 labels are accepted.

### `ReportSettingsInput`

```json
{
  "baseUrl": "https://itsm.example.com/itsm",
  "branding": {
    "name": "Acme",
    "primary": "#0d766e",
    "accent": "#147c73",
    "header": "Uso interno",
    "footer": "Generado por el ITSM",
    "logoAttachmentId": null
  },
  "labelDefaults": {"formatId": "a4-24", "fields": ["logo", "name", "id", "code", "qr"]}
}
```

`baseUrl` is empty or an absolute `http(s)` origin/path with a host, no
credentials, query string, fragment, control characters, backslashes or
leading/trailing whitespace; a path is normalized with one trailing slash.
Branding text is plain; colors use `#rrggbb`; `logoAttachmentId` is a UUID
validated by the service as an authorized, existing raster attachment. No HTML,
CSS, external URL or filesystem path is accepted.

## Composition

```python
from itsm.reports.composition import compose_document, preview_html

composition = compose_document(template_dict, context, labels=None)
# composition.html: HTML with only src="resource://<registered-key>"
# composition.resources: {"logo.png": b"...", "photo-1.png": b"..."}
browser_html = preview_html(composition)  # data URIs for registered bytes only
```

`context` is server-owned:

* `title`, `family`, `generatedAt`, `branding` (`name`, `primary`, `accent`,
  `header`, `footer`);
* `assets`: compact camelCase projections (image *bytes* are not in the asset
  payloads);
* `rows` and `columns`: exactly the same projected rows/ordered
  `{key,label}` columns used by CSV/XLSX. Rows may carry a non-column `group`
  label; group headings and counts are rendered without dropping rows;
* `summary`: `total`, optional scalar facts (`cost`, `withTechnical`, `from`,
  `to`), any `by*` mapping of labels to integer counts, and
  `groups: [{key,label,count}]`. `summary` blocks render real proportional
  count bars, never placeholder charts;
* `qrUrls`: `{assetId: permanent report URL}`; labels and QR blocks only accept
  these URLs;
* `images`: `{assetId: raw bytes}` for photo blocks. Bytes are decoded as a
  raster (PNG/JPEG/GIF/WebP by content), re-encoded to bounded PNG, EXIF
  orientation fixed, and may be absent for any asset;
* `logo`: authorized raw raster bytes or `None`.

Unknown context keys are rejected. Text is escaped, control characters are
stripped, table cells are bounded, and no context value is interpreted as HTML,
CSS, JavaScript or a URL. Missing images simply omit that figure; an invalid
image is ignored rather than aborting the document.

Report HTML includes running headers, page numbers (`página X de Y`), document
title and generation time. Label HTML uses absolute physical millimetres and a
correct SVG quiet zone around every QR.

## Rendering

```python
from itsm.reports.rendering import render_pdf, RenderFailed, RenderTimeout

pdf = render_pdf(
    composition,
    timeout_seconds=120,
    memory_mb=512,
    max_bytes=50 * 1024 * 1024,
)
```

* Rendering always happens in a freshly spawned, non-daemon child process. The
  parent never loads document fonts/layout into its own address space, so
  Huey thread and process executors behave the same.
* The child receives only the HTML string and validated resource bytes. It sets
  `RLIMIT_AS` (`memory_mb`, 64–4096) and `RLIMIT_CORE=0`, writes to a temporary
  file, and reports a bounded status through a pipe.
* `URLFetcher` is subclassed and called with the exact
  `URLFetcherResponse(url, body, headers, status)` interface. The fetcher serves
  only `resource://logo.png` and `resource://photo-N.png` keys registered in the
  composition. HTTP(S), file, data, unknown keys, traversal and query strings
  are rejected before WeasyPrint can open them.
* HTML is capped at 8 MiB, each resource at 8 MiB, all resources at 64 MiB and
  128 entries. Output is capped by `max_bytes` (1–512 MiB). Timeouts terminate
  (then kill) the child and raise `RenderTimeout`; other failures raise
  `RenderFailed`. Neither exception leaks a path, URL or document content.

QR destinations use the permanent asset UUID, never the mutable quick code:

```python
from itsm.reports.qr import asset_report_url, qr_svg

url = asset_report_url("https://itsm.example.com/itsm", asset_uuid)
# https://itsm.example.com/itsm/#/reporte/<uuid>
svg = qr_svg(url)  # Segno, error correction M, border=4 modules, scale=4
```

The public share token is a separate, single-use-revealed secret. A stored
share hash cannot be reversed into a URL; QR/share metadata must never
reconstruct or invent a token. Public links are `/#/reporte/<uuid>/publico?share=<token>`.

The translated pagination footer is encoded as a CSS string inside the HTML
style element: control characters, quotes, backslashes and angle brackets are
literal escapes. Only `{current}` and `{total}` become page counters; translations
cannot close the style element or introduce a CSS newline.
