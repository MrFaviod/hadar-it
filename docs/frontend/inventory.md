# Inventory in the frontend

How the inventory views talk to the server: assets through `/api/v1/assets` and the inventory catalog through `/api/v1/inventory/config`. The views, navy/teal design, forms, search, filters and hash routes are the existing ones; there are no single-file components, no Composition API and no extra framework or dependency.

## Component map

The views are Vue 3 Options API components inside the React 19 host. Shared state lives at the root (`app.js`); panels receive `app` as a prop and call its methods (props down, events up through the existing `app` object).

| Component / module | Responsibility | Props / events |
| --- | --- | --- |
| `assets/js/inventory-api.js` (`window.AssetInventory`) | The single adapter for server inventory: list, detail, editor, lifecycle, media, history and catalog. Owns the monotonic epoch and the `AbortController`s. | `data`/`computed`/`methods` mixed into the root (`app.js`). No props. |
| `assets/js/asset-editor.js` (`AssetEditor`, `AssetCommonField`) | Create and edit dialog. In server mode it shows cost, typed technical fields, photo, field of view and catalog status; in demo mode it keeps the prototype form. | Props: `app`. Events: `@close` from `ModalShell`; saving through `app.saveAsset()`. |
| `assets/js/asset-config-views.js` (`AssetFieldsPanel`, `AssetFormsPanel`, `AssetStatusesPanel`, `AssetIdentityPanel`) | Real configuration of the field library, per-category forms, statuses and identification rules. Deactivation replaces destructive deletion. | Props: `app`. Actions through `app.*`. |
| `assets/js/config.js` (`window.AssetConfigMethods`) | Legacy demo configuration methods; `inventory-api.js` replaces the real catalog operations and prevents a local fallback when the server is unavailable. | Methods on the root. |
| `assets/js/asset-admin.js` | Kept for demo assets and for local configuration without an API (sites, people, integrations). Inventory and its catalog are no longer read from `localStorage`. | Methods on the root. |
| `assets/js/app.js` | Final composition: mixes in the adapter last, starts and clears the session, and exposes `deviceImagePresets` for category illustrations. | Vue root. |
| `index.html` | Canonical template: inventory view, asset record, asset configuration and dialogs. | Vue 3 template. |
| `assets/css/inventory.css` | Minimal visual additions (media, history, lifecycle) on the existing tokens. | — |

## Adapter contract

- `GET /api/v1/inventory/config` → `{fields, categories, statuses, rules, commonFields, operations}`.
  `operations.environment` and `operations.purge` are the server's policy; the
  browser does not decide the environment or invent permissions. If the DTO is
  missing, permanent deletion is disabled with an explicit notice.
- `GET /api/v1/assets/search` and `GET /api/v1/assets/{id}` → paginated list and record.
- `POST /assets`, `PATCH /assets/{id}` → contract fields only; the permanent ID
  is immutable and an empty quick code is assigned by the server.
- `POST /assets/{id}/clone|archive|restore|retire|purge`, `GET /assets/{id}/history`.
- `PUT|DELETE /assets/{id}/images/{photo|fov}` with a binary body ≤ 1 MiB and no SVG.
- `PUT /inventory/config/{fields|categories|statuses|rules}/{clave}` → non-destructive
  metadata; existing types and options cannot be rewritten.

## Permissions and catalog

- The client permission catalog includes `assets.purge`, labeled **Permanently
  delete**: the real grant from `/auth/me` is not lost when permissions are
  filtered, and role groups show it. It remains an explicit server grant, with
  no implicit widening.
- Configuration is authorized with the backend's real permissions: fields,
  categories and forms with `config.categories`; statuses, rules and
  transitions with `config.general`. `assets.edit` does not enable catalog
  writes, and each section shows only the controls the role can save.
- `#/configuracion/categorias` loads the server catalog and creates or edits
  categories (label, prefix, type, availability) with `PUT` on
  `/inventory/config/categories/{id}`, keeping the form and technical fields.
  Without a loaded catalog no write is offered and local state is not used.
- If the catalog responds with an error (for example 500), configuration shows
  the server message, disables write controls and offers **Retry**; nothing is
  persisted to `localStorage` and no fictitious success is announced.

## Known limits

- Permanent deletion depends on the server policy: in production it requires
  `assets.purge`, prior archiving, the typed ID and a reason; the browser only
  reflects it. No purge tool is exposed to agents.
- The browser smoke test uses SQLite on loopback; it does not cover
  PostgreSQL/MariaDB, real concurrency of codes or model providers.
