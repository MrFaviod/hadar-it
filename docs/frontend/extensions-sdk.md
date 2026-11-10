# Extensiones: interfaz y revisión (SDK 2)

Este documento describe el contrato de interfaz que el host aplica a las extensiones. El servidor es la autoridad de instalación, permisos y ejecución; el navegador solo dibuja las vistas declaradas y, cuando corresponde, aísla el código del módulo. Una extensión nunca importa componentes privados ni modifica archivos Vue del núcleo.

## Principios

- **Sin código del módulo en la página.** El host no crea etiquetas `<script>` para una extensión. `frontend.pages`, `frontend.assetPanels` y `frontend.widgets` declaran vistas que el host dibuja con sus propios componentes y tokens.
- **Aislamiento para código propio.** Una vista `isolated` se ejecuta en un `<iframe sandbox="allow-scripts">` con origen opaco. El documento aprobado no recibe cookies, sesión, `localStorage`, DOM del host ni acceso de red (`connect-src 'none'`). Esa CSP no impide que el marco se navegue a otro documento y el atributo `sandbox` no tiene una bandera para bloquearlo: por eso el host solo entrega el identificador del activo, no sus datos, y trata cualquier navegación del marco como terminal.
- **Autoridad del servidor.** Cada operación se invoca por HTTP con la cookie de sesión, Origin y CSRF del host. `can()` en el navegador solo oculta controles; Casbin decide en el servidor.
- **SDK 1 no se ejecuta.** Un módulo con `manifest.sdkVersion: 1` o `status: "requires_upgrade"` aparece como **Requiere actualización** y no expone páginas, paneles, widgets ni acciones. Sus datos se conservan.

## Vistas declarativas

`frontend.pages`, `assetPanels` y `widgets` comparten la misma forma:

```json
{
  "id": "licencias",
  "label": "Licencias",
  "icon": "package",
  "permission": "ext_license.read",
  "view": { "table": { "operation": "list_licenses", "columns": [{ "field": "key", "label": "Clave" }] } }
}
```

`view` debe declarar exactamente una de estas variantes:

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

- `operation` es una operación declarada por esta extensión.
- `columns` admite de 1 a 12 campos; `format` es `text` (por defecto), `date`, `date-time`, `number` o `boolean`, con la ortografía de JSON Schema. `date` y `date-time` usan el locale `es-ES` del host, igual que `number` con `Intl.NumberFormat('es-ES')` para números finitos. Un valor que no es número se dibuja como texto.
- Las filas son los registros del almacén del módulo, `{ "id", "version", "data" }`, dentro de `{ "items", "total" }`; `field` nombra una clave de `data` (además están `id` y `version`). Una respuesta con objetos planos también se dibuja tal cual.
- `filterAsset` es el **nombre** donde el host coloca el id permanente del activo abierto (UUID), y su significado depende del tipo de la operación:
  - operación declarativa `list`: debe ser una propiedad declarada de la colección y el host la envía dentro de `filters`, sin otras claves: `{ "limit": 10, "offset": 0, "filters": { "<filterAsset>": "<uuid>" } }`.
  - operación `handler`: debe ser un parámetro declarado por la operación y el host la envía como argumento de nivel superior: `{ "limit": 10, "offset": 0, "<filterAsset>": "<uuid>" }`.
- La tabla pide `{ limit, offset }` (10 filas por página) y pagina con **Anterior** / **Siguiente**; solo afirma el total que devolvió el servidor.
- `form` opcional añade el formulario de alta bajo la tabla. Al guardar, la tabla vuelve a cargar su primera página.

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

- `input`: `text`, `textarea`, `number`, `date`, `select` o `checkbox`. `select` exige `options` (cadenas o `{ value, label }`).
- `required` se valida antes de enviar; los campos vacíos opcionales se omiten.
- `assetField` se rellena con el id del activo abierto. En una operación `handler` viaja como argumento de nivel superior, junto al resto de los campos. En una operación declarativa `put` viaja dentro de `data`, junto a los campos del registro: `{ "data": { "<assetField>": "<uuid>", ... } }`. El servidor genera el `record_id` cuando el formulario no edita un registro existente.
- El servidor responde con el registro creado; sus errores se muestran tal como llegan. El host no inventa éxito ni filas.

### `view.isolated`

```json
{ "isolated": { "component": "LicensePanel", "height": 420 } }
```

Solo una extensión `runtime: "sandboxed"` puede declararla, y requiere `frontend.entry` con `frontend.js`. El host descarga ese archivo desde la URL firmada por digest (`/api/v1/extensions/<id>/frontend.js?digest=<sha256>`), exige que la ruta y el digest coincidan con el id y el digest de esa misma extensión, y lo inserta en el documento del marco junto al build global de Vue vendorizado. El módulo se registra dentro del marco:

```js
window.ITSMExtension.register({ components: { LicensePanel: { template: '<p>{{ assetId }}</p>', props: ['assetId', 'sdk'] } } });
```

El componente recibe `assetId` (el UUID del activo abierto, no su contenido), `permissions` y `sdk` con `request(operation, args)`, `can(permission)`, `navigate(page | '#/ruta')` y `assetId`. Los datos del activo y del módulo se piden con operandos declarados y con permiso: el host no incluye el registro del activo en `itsm:init`. El marco puede usar los componentes mínimos del kit (`ItsmTable`, `ItsmField`, `ItsmStatus`, `ItsmButton`), que toman la paleta del tema actual mediante un mensaje del host.

El host acepta un único `itsm:ready` por marco. Si el marco carga otro documento, el host cierra el puente y deja de responder mensajes, temas y resultados pendientes. Esa frontera no puede impedir que un módulo exfiltre los datos que su propia operación autorizada le devuelve; un módulo con permiso de lectura del activo siempre puede hacerlo.

## Acciones sobre activos

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

La acción aparece en el detalle del activo cuando la cuenta tiene el permiso. Si declara `confirm`, el host pide confirmación en su diálogo nativo antes de invocar la operación con `{ assetId }`. El resultado se informa en la propia barra de acciones.

## Contribuciones adicionales

`frontend.contributions` solo permite dos modos dentro del catálogo cerrado del host:

- `add`: añade una vista declarativa a un destino existente (`page.*`, `widget.*`, `asset.panel.*`, `config.*`).
- `hide`: oculta un destino del núcleo. Los destinos de administración (`config.seguridad`, `config.extensiones`, `nav.system`, etc.) nunca son componibles.

Los destinos de navegación solo admiten `hide`. No existe `replace` ni registro de componentes del host: un módulo no puede sustituir la interfaz del núcleo.

## Límites del contrato

- Máximo 50 contribuciones por colección y 12 columnas / 30 campos por vista.
- Ids de página, panel, widget y acción: minúsculas con guiones; operaciones: minúsculas con guiones bajos.
- El host no acepta `component` en una vista declarativa ni rutas `file://`.
- Una extensión desactivada conserva su catálogo de permisos marcado como inactivo, pero no renderiza vistas.

## Revisión y administración

La pantalla **Configuración → Extensiones** (`#/configuracion/extensiones`) es la única superficie de administración y requiere `system.modules`:

- **Ejecución**: *Declarativa* (sin código en la página) o *Código aislado* (frontend en marco aislado).
- **Capacidades** declaradas, con su descripción en español, y **Almacenamiento**: *Base SQLite propia* cuando el manifiesto lo declara.
- **Estado** por módulo instalado: tamaño del almacenamiento, versión de esquema, eventos detenidos y disponibilidad del entorno restringido, tal como los informa `GET /extensions/{id}/status`.
- **Desinstalar** (`POST /extensions/{id}/uninstall` con `expectedVersion`): retira el paquete y su interfaz, y **conserva** la base SQLite y el historial de la extensión.
- **Rollback**: si el esquema es compatible, se aplica directamente; si no, el host ofrece restaurar la copia previa con `restoreData: true` y una confirmación escrita con el identificador exacto. Sin esa confirmación no se envía nada.

La aprobación sigue siendo humana y usa CAS (`expectedVersion` = revisión entera informada por el servidor). El frontend nunca deriva autoridad de sus propias comprobaciones.
