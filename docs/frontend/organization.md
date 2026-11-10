# Directorio, relaciones, grafo y mapa con autoridad del servidor

Fase 5 conecta las superficies de organización de la interfaz con la API
canónica. La UI sigue siendo Vue 3 con Options API y plantillas `index.html`;
no se migra a SFC ni se introduce estado de dominio en React.

## Mapa de componentes y contratos

| Módulo | Responsabilidad | Contrato |
|---|---|---|
| `assets/js/organization-api.js` | Único adaptador de organización: personas, departamentos, ubicaciones, árbol, tipos de relación, relaciones, grafo, mapa e historial. Mantiene época monotónica, `AbortController` y errores por recurso. | `window.AssetOrganization.{data,computed,methods,map*,canonical*}` |
| `OrganizationRelations` (`relations-views.js`) | Panel de relaciones de un activo: lista dirigida con etiqueta directa/inversa, alta/edición/baja y cambio de host. | props `asset`, `app`; usa `organization.relations`, `organization.types`, `organization.dialogs.*` |
| `OrganizationRelationTypes` (`relations-views.js`) | Configuración del vocabulario de tipos (clave inmutable, etiquetas, contención, activo). | permiso `config.general`; rutas `/relationship-types` |
| `GraphExplorer` | Reutiliza el motor y el diseño existentes sobre una fuente proxy acotada por el servidor. | `serverGraphMode`, `organizationGraphSource`, `organization.graph` |
| `MapExplorer` + `FloorLogic` | Reutiliza el canvas de planos existente; convierte píxeles del lienzo a coordenadas relativas 0..1 y persiste posiciones. | `serverMapMode`, `organizationMapSource`, `saveOrganizationPosition` |
| `AssetEditor` | Sustituye selectores de persona/sede/ubicación por los UUID canónicos que ya usa el adaptador de inventario. | `assetSiteLocations`, `assetActivePeople`, `app.sites` |
| Página de personas | Lista, ficha, historial, asignar/devolver/trasladar con motivo, notas y fecha efectiva. | `/people`, `/people/{id}`, `/people/{id}/assets`, `/people/{id}/history`, `/assets/{id}/assign|return|transfer` |

## Contratos REST usados (sin rutas inventadas)

- Directorio: `GET|POST /departments`, `GET|PATCH /departments/{id}`,
  `GET|POST /people`, `GET|PATCH /people/{id}`, `GET|POST /locations`,
  `GET /locations/tree?rootId&depth&maxNodes`, `GET|PATCH /locations/{id}`,
  historiales `GET /{entidad}s/{id}/history`.
- Ciclo de vida: `GET /people/{person}/assets`,
  `POST /assets/{id}/assign`, `POST /assets/{id}/return`,
  `POST /assets/{id}/transfer`, `PATCH /assets/{id}` (posición canónica).
- Relaciones: `GET|POST /relationship-types`, `PATCH /relationship-types/{key}`,
  `GET|POST /relationships`, `PATCH|DELETE /relationships/{id}`,
  `POST /relationships/host-move`, `GET /infrastructure/graph`.
- Mapa: `GET /map?siteId&limit&offset`. El payload es
  `{sites, positions, limit, offset, truncated}`; cada posición trae los ids
  canónicos del activo y `x`/`y` como decimales 0..1, no `positionX`/
  `positionY` ni una lista `items`.

Cada lectura valida una época monotónica; cada escritura vuelve a comprobar el
permiso efectivo del servidor antes de enviar. Un 401 limpia todo el estado de
organización y aborta las peticiones en vuelo. El dominio del servidor nunca
escribe en `localStorage`.

## Permisos

`people.view`, `people.create`, `people.edit`, `config.departments`,
`config.sites`, `assets.view`, `assets.edit`, `assets.assign`,
`config.general`. Una capacidad ausente produce un mensaje factual y, cuando
corresponde, una vista de solo lectura; nunca se rellena con datos de
demostración. `config.departments` sin `assets.edit` administra el directorio
sin habilitar la edición de activos.

Los grupos de redundancia que aparecen en la ficha y en el grafo tienen su propio
contrato en `docs/frontend/redundancy.md`: se leen con `assets.view`, se escriben con
`assets.edit` y no conceden capacidades nuevas de organización.

## Coordenadas y planos

El servidor expone `positionX`/`positionY` como cadenas decimales en 0..1. El
canvas conserva su espacio de píxeles y convierte con los límites reales del
plano (`organizationPlanBounds`). Una posición sólo se envía cuando el activo
tiene ubicación; `planRef`/`planPage` son metadatos, nunca un archivo o una URL
de plano. El dibujo de planos existente sigue siendo ilustrativo.

## Cambio de host en la interfaz

`OrganizationRelations` conserva la acción «Cambiar host» únicamente en el hijo
de una relación `hosted_in` y abre un diálogo `modal-shell` con controles Vue
reales: el activo que cambia de host (su nombre canónico o, si el panel no lo
conoce, su UUID), la búsqueda de destino `#server-host-search`, la lista de hosts
de la página acotada del servidor, el motivo `#server-host-reason`, las notas
`#server-host-notes` y la fecha efectiva `#server-host-effective`. Confirmar
llama al `confirmOrganizationHostMove` existente; cerrar, `Escape` y el botón de
cancelar usan `closeOrganizationHostMove`. `modal-shell` mantiene el foco, lo
devuelve al disparador y bloquea el desplazamiento del documento.

- El hijo se toma siempre del origen de la arista (`from`), se vea la relación
  como saliente o entrante; la dirección sólo cambia las etiquetas.
- El destino es la página acotada `GET /assets/search?limit=50&offset=0` del
  servidor. La interfaz no filtra ni valida por su cuenta: el servidor decide si
  un host es válido y su rechazo queda en el diálogo. Un mismo host, el propio
  activo o el host actual no se rechazan en el cliente.
- El motivo mínimo de cuatro caracteres del servidor se comprueba antes de
  enviar, para no producir un 422 previsible. Las notas y la fecha efectiva son
  opcionales; la fecha se convierte con `organizationEffectiveIso` y conserva la
  zona horaria del navegador.
- La petición es `POST /relationships/host-move` con `{childId, newHostId,
  reason, notes?, effectiveAt?}`. No incluye argumentos de autoridad ni llama a
  hipervisores, Docker o migraciones: sólo registra inventario y relaciones.
- Tras el éxito se recargan las relaciones desde el servidor, el grafo si estaba
  cargado y, cuando el activo afectado está abierto en su ficha, el detalle y el
  historial estructurado. Cada refresco revalida la marca de sesión, así que un
  cierre de sesión en curso no revive filas, diálogos ni avisos.
- Un rechazo del servidor mantiene el diálogo abierto, deja el mensaje en el
  cuerpo y no modifica la relación existente en pantalla.

## Límites conocidos

- En sesión autenticada los dominios de organización sólo leen la API. Carga,
  error y falta de permiso no autorizan respaldo demo ni persistencia local del
  dominio. Las preferencias visuales del mapa siguen siendo estado local.
- Las posiciones requieren ubicación y coordenadas relativas emparejadas. Los
  planos siguen siendo representaciones ilustrativas con `planRef`/`planPage`;
  no hay almacenamiento de archivos, geocodificación ni descubrimiento.
- Un grafo truncado puede omitir extremos de relaciones; la UI no inventa nodos.
  Una ubicación sin su cadena ancestral cargada no se inventa en la búsqueda.
- La prueba integrada usa SQLite. No certifica motores externos, proveedores de
  modelos, integración con hipervisores ni producción.
