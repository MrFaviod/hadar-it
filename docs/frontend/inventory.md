# inventario real en el frontend existente

Alcance: sustituir las simulaciones correspondientes por operaciones reales sobre
`/api/v1/assets` y `/api/v1/inventory/config`, conservando las vistas, el diseño
navy/teal, los formularios, la búsqueda, los filtros y las rutas hash existentes.
No se migran SFC ni Composition API y no se añade ningún framework ni dependencia.

## Mapa de componentes (responsabilidad y contrato)

Las vistas siguen siendo Options API de Vue 3 dentro del host React 19. El estado
compartido vive en la raíz (`app.js`); los paneles reciben `app` por prop y llaman
a sus métodos (props-down / events-up mediante el objeto `app` ya existente).

| Componente / módulo | Responsabilidad | Props / eventos |
| --- | --- | --- |
| `assets/js/inventory-api.js` (`window.AssetInventory`) | Adaptador único del inventario servidor: lista, detalle, editor, ciclo de vida, medios, historial y catálogo. Dueño de la época monótona y de los `AbortController`. | `data`/`computed`/`methods` mezclados en la raíz (`app.js`). Sin props. |
| `assets/js/asset-editor.js` (`AssetEditor`, `AssetCommonField`) | Diálogo de alta y edición. En modo servidor muestra coste, campos técnicos tipados, fotografía, campo de visión y estado del catálogo; en modo demostración mantiene el formulario prototipo. | Props: `app`. Eventos: `@close` del `ModalShell`; guardado vía `app.saveAsset()`. |
| `assets/js/asset-config-views.js` (`AssetFieldsPanel`, `AssetFormsPanel`, `AssetStatusesPanel`, `AssetIdentityPanel`) | Configuración real de la biblioteca de campos, formularios por categoría, estados y reglas de identificación. Sustituye el borrado destructivo por desactivación. | Props: `app`. Acciones vía `app.*` (mismos nombres que la simulación donde fue posible). |
| `assets/js/config.js` (`window.AssetConfigMethods`) | Métodos heredados de configuración demostrativa; el adaptador `inventory-api.js` sustituye las operaciones del catálogo real e impide el fallback local cuando el servidor no está disponible. | Métodos sobre la raíz. |
| `assets/js/asset-admin.js` | Se conserva para los activos de demostración y para la configuración local que no tiene API (sedes, personas, integraciones). El inventario y su catálogo ya no se leen de `localStorage`. | Métodos sobre la raíz. |
| `assets/js/app.js` | Composición final: mezcla el adaptador al final, arranca/limpia la sesión y expone `deviceImagePresets` para las ilustraciones de categoría. | Raíz Vue. |
| `index.html` | Plantilla canónica: vista de inventario, ficha de activo, configuración de activos y diálogos. | Plantilla Vue 3. |
| `assets/css/inventory.css` | Añadidos visuales mínimos de la fase 4 (medios, historial, ciclo de vida) sobre los tokens existentes. | — |

## Contrato del adaptador

- `GET /api/v1/inventory/config` → `{fields, categories, statuses, rules, commonFields, operations}`.
  `operations.environment` y `operations.purge` son la política del servidor; el
  navegador no decide el entorno ni inventa permisos. Si el DTO no llega, la
  eliminación definitiva queda deshabilitada con un aviso explícito.
- `GET /api/v1/assets/search` y `GET /api/v1/assets/{id}` → lista paginada y ficha.
- `POST /assets`, `PATCH /assets/{id}` → solo campos del contrato; el ID permanente
  es inmutable y el código rápido vacío lo asigna el servidor.
- `POST /assets/{id}/clone|archive|restore|retire|purge`, `GET /assets/{id}/history`.
- `PUT|DELETE /assets/{id}/images/{photo|fov}` con cuerpo binario ≤ 1 MiB y sin SVG.
- `PUT /inventory/config/{fields|categories|statuses|rules}/{clave}` → metadatos no
  destructivos; los tipos y las opciones existentes no se pueden reescribir.

## Corrección tras revisión

- El catálogo de permisos del cliente incluye `assets.purge` con la etiqueta
  «Eliminar definitivamente»: la concesión real de `/auth/me` ya no se pierde al
  filtrar permisos y los grupos de rol la muestran. Sigue siendo una concesión
  explícita del servidor, sin ampliación implícita.
- La configuración se autoriza con los permisos reales del backend: campos,
  categorías y formularios con `config.categories`; estados, reglas y
  transiciones con `config.general`. `assets.edit` ya no habilita escrituras del
  catálogo, y cada sección muestra solo los controles que el rol puede guardar.
- `#/configuracion/categorias` carga el catálogo del servidor y crea o edita
  categorías (etiqueta, prefijo, tipo, disponibilidad) con `PUT` sobre
  `/inventory/config/categories/{id}`, conservando formulario y campos técnicos.
  Sin catálogo cargado no se ofrece ninguna escritura ni se usa el estado local.
- Si el catálogo responde con error (por ejemplo 500), la configuración muestra
  el mensaje del servidor, desactiva los controles de escritura y ofrece
  «Reintentar»; no se persiste nada en `localStorage` ni se anuncia un éxito
  ficticio.

## Límites conocidos

- La eliminación definitiva depende de la política del servidor: en producción
  exige `assets.purge`, archivo previo, ID escrito y motivo; el navegador solo la
  refleja. No se expone ninguna herramienta de purga a agentes.
- El smoke de navegador usa SQLite en bucle local; no cubre PostgreSQL/MariaDB,
  concurrencia real de códigos ni proveedores de modelos.
