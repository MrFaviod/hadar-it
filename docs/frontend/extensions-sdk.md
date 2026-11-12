# Extensions: interface and review (SDK v2)

The interface contract the host applies to extensions. The server is the authority for installation, permissions and execution; the browser only draws the declared views and, where needed, isolates the module's code. An extension never imports private components or modifies core Vue files.

For the package format, operations and lifecycle on the server, see the [backend extension SDK](../backend/extensions-sdk.md) and the [extension host](../backend/extensions-host.md).

## Principles

- **No module code in the page.** The host never creates `<script>` tags for an extension. `frontend.pages`, `frontend.assetPanels` and `frontend.widgets` declare views that the host draws with its own components and tokens.
- **Isolation for custom code.** An `isolated` view runs in an `<iframe sandbox="allow-scripts">` with an opaque origin. The approved document receives no cookies, session, `localStorage`, host DOM or network access (`connect-src 'none'`). That CSP does not stop the frame from navigating to another document, and the `sandbox` attribute has no flag to block it: that is why the host only hands over the asset identifier, not its data, and treats any navigation of the frame as terminal.
- **Server authority.** Every operation is invoked over HTTP with the host's session cookie, Origin and CSRF. `can()` in the browser only hides controls; Casbin decides on the server.
- **SDK 1 does not run.** A module with `manifest.sdkVersion: 1` or `status: "requires_upgrade"` appears as **Requires an update** and exposes no pages, panels, widgets or actions. Its data is kept.

## Declarative views

`frontend.pages`, `assetPanels` and `widgets` share the same shape:

```json
{
  "id": "licencias",
  "label": "Licencias",
  "icon": "package",
  "permission": "ext_license.read",
  "view": { "table": { "operation": "list_licenses", "columns": [{ "field": "key", "label": "Clave" }] } }
}
```

`view` must declare exactly one of these variants.

### `view.table`

```json
{
  "table": {
    "operation": "list_licenses",
    "columns": [
      { "field": "key", "label": "Clave" },
      { "field": "expires", "label": "Vence", "format": "date" },
      { "field": "perpetual", "label": "Perpetua", "format": "boolean" }
    ],
    "filterAsset": "asset_id",
    "form": { "operation": "create_license", "assetField": "asset_id", "fields": [] }
  }
}
```

- `operation` is an operation declared by this extension.
- `columns` accepts 1 to 12 fields; `format` is `text` (default), `date`, `date-time`, `number` or `boolean`, spelled as in JSON Schema. `date` and `date-time` use the host's `es-ES` locale, as does `number` with `Intl.NumberFormat('es-ES')` for finite numbers. A value that is not a number is drawn as text.
- Rows are records from the module's store, `{ "id", "version", "data" }`, inside `{ "items", "total" }`; `field` names a key of `data` (plus `id` and `version`). A response with flat objects is also drawn as is.
- `filterAsset` is the **name** under which the host places the permanent id (UUID) of the open asset. Its meaning depends on the operation type:
  - declarative `list` operation: it must be a declared property of the collection, and the host sends it inside `filters` with no other keys: `{ "limit": 10, "offset": 0, "filters": { "<filterAsset>": "<uuid>" } }`.
  - `handler` operation: it must be a parameter declared by the operation, and the host sends it as a top-level argument: `{ "limit": 10, "offset": 0, "<filterAsset>": "<uuid>" }`.
- The table requests `{ limit, offset }` (10 rows per page) and pages with **Previous** / **Next**; it only states the total the server returned.
- The optional `form` adds a creation form under the table. After saving, the table reloads its first page.

### `view.form`

```json
{
  "form": {
    "operation": "create_license",
    "assetField": "assetId",
    "fields": [
      { "field": "key", "label": "Clave", "input": "text", "required": true },
      { "field": "tier", "label": "Tipo", "input": "select", "options": ["Estándar", "Volumen"] },
      { "field": "perpetual", "label": "Perpetua", "input": "checkbox" }
    ]
  }
}
```

- `input`: `text`, `textarea`, `number`, `date`, `select` or `checkbox`. `select` requires `options` (strings or `{ value, label }`).
- `required` is validated before sending; empty optional fields are omitted.
- `assetField` is filled with the id of the open asset. In a `handler` operation it travels as a top-level argument, alongside the other fields. In a declarative `put` operation it travels inside `data`, alongside the record fields: `{ "data": { "<assetField>": "<uuid>", ... } }`. The server generates the `record_id` when the form is not editing an existing record.
- The server responds with the created record; its errors are shown as they arrive. The host never invents success or rows.

### `view.isolated`

```json
{ "isolated": { "component": "LicensePanel", "height": 420 } }
```

Only a `runtime: "sandboxed"` extension can declare it, and it requires `frontend.entry` with `frontend.js`. The host downloads that file from the digest-signed URL (`/api/v1/extensions/<id>/frontend.js?digest=<sha256>`), requires the path and digest to match the id and digest of that same extension, and inserts it into the frame's document next to the vendored global Vue build. The module registers itself inside the frame:

```js
window.ITSMExtension.register({
  components: {
    LicensePanel: {
      props: ['assetId', 'sdk'],
      render() { return Vue.h('p', this.assetId || ''); }
    }
  }
});
```

**Render-function contract.** Isolated components must ship a `render` function written by hand or precompiled by the author. Raw templates and runtime compilation (`Vue.compile`, `eval`, `new Function`) are not supported. The host adds no compiler, pipeline or configuration. The bundle runs only inside the frame; it is never evaluated in the privileged host.

Before mounting, every registered component is checked, including unselected siblings and local components, as well as `mixins` and `extends` options. A defined `template`, even alongside `render`, or a registered or local component without a render function produces a translated error visible in the frame, and nothing is mounted. Functional components are supported; mixins and extends that only contribute options do not need their own render. The extension as a whole and its declarative views are not withdrawn. `itsm:ready` only signals that the bridge is available, not that rendering succeeded.

Migrating: an earlier example with `template: '<p>{{ assetId }}</p>'` was documented, but the enforcing CSP prevented compiling it. Replace it with the render example above, or ship a precompiled artifact compatible with Vue 3.5.13 that includes its render functions and never invokes the compiler at runtime. Migrate local components, siblings, mixins and extends that contribute templates too, and remove the `template` property from the final artifact. Authors keep their own build process: the host neither compiles nor installs packages. The frame's CSP meta tag stays enforcing, separate from the host's diagnostic Report-Only header.

The component receives `assetId` (the UUID of the open asset, not its content), `permissions`, and `sdk` with `request(operation, args)`, `can(permission)`, `navigate(page | '#/ruta')` and `assetId`. Asset and module data are requested through declared operations and with permission: the host does not include the asset record in `itsm:init`. The frame can use the kit's minimal components (`ItsmTable`, `ItsmField`, `ItsmStatus`, `ItsmButton`), which take the current theme palette from a host message.

The host accepts a single `itsm:ready` per frame. If the frame loads another document, the host closes the bridge and stops answering messages, themes and pending results. That boundary cannot stop a module from exfiltrating data its own authorized operation returns to it; a module with read permission on the asset can always do so.

## Asset actions

```json
{
  "id": "revoke",
  "label": "Revocar licencia",
  "icon": "bolt",
  "target": "asset.action",
  "permission": "ext_license.execute",
  "operation": "revoke_license",
  "confirm": "Se revocará la licencia del activo. Los datos se conservan."
}
```

The action appears on the asset detail when the account has the permission. If it declares `confirm`, the host asks for confirmation in its native dialog before invoking the operation with `{ assetId }`. The result is reported in the action bar itself.

## Additional contributions

`frontend.contributions` allows only two modes within the host's closed catalog:

- `add`: adds a declarative view to an existing target (`page.*`, `widget.*`, `asset.panel.*`, `config.*`).
- `hide`: hides a core target. Administration targets (`config.seguridad`, `config.extensiones`, `nav.system`, etc.) can never be composed.

Navigation targets only accept `hide`. There is no `replace` and no host component registration: a module cannot substitute the core interface.

## Contract limits

- At most 50 contributions per collection, and 12 columns / 30 fields per view.
- Page, panel, widget and action ids: lowercase with hyphens; operations: lowercase with underscores.
- The host accepts no `component` in a declarative view and no `file://` paths.
- A disabled extension keeps its permission catalog marked as inactive, but renders no views.

## Review and administration

**Settings → Extensions** (`#/configuracion/extensiones`) is the only administration surface and requires `system.modules`:

- **Runtime**: *Declarative* (no code in the page) or *Isolated code* (frontend in an isolated frame).
- Declared **Capabilities**, with their description, and **Storage**: *Own SQLite database* when the manifest declares it.
- **Status** per installed module: storage size, schema version, stopped events and availability of the restricted environment, as reported by `GET /extensions/{id}/status`.
- **Uninstall** (`POST /extensions/{id}/uninstall` with `expectedVersion`): removes the package and its interface, and **keeps** the extension's SQLite database and history.
- **Rollback**: if the schema is compatible, it applies directly; otherwise the host offers to restore the previous copy with `restoreData: true` and a typed confirmation of the exact identifier. Without that confirmation nothing is sent.

Approval stays human and uses compare-and-set (`expectedVersion` = the integer revision reported by the server). The frontend never derives authority from its own checks.
