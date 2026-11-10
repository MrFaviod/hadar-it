# Grupos de redundancia en la interfaz

Contrato de la superficie que muestra y administra los **grupos de redundancia**
del servidor. La fase sigue siendo Vue 3 con Options API global y plantillas
clásicas: no hay SFC, Composition API, dependencias nuevas ni renombrado del
producto.

## Qué representa

Un grupo de redundancia declara que varias instancias **independientes** del
inventario son réplicas de la misma carga. Cada réplica conserva su UUID, su
código rápido, su historial y su relación `hosted_in` propia: el grupo nunca
fusiona filas ni crea un activo «servicio» sintético. Un modo `active_active`
reparte la carga con porcentajes configurados (por ejemplo 40 % y 60 %); un modo
`active_passive` declara un `Principal` y al menos un `Respaldo`.

El reparto es información descriptiva de inventario. No es utilización medida, no
es CPU ni memoria del host, y la interfaz no ejecuta balanceo, replicación,
migración, failover ni descubrimiento.

## Mapa de componentes y responsabilidades

| Módulo | Responsabilidad | Contrato |
|---|---|---|
| `assets/js/redundancy-api.js` | Único adaptador de redundancia: páginas acotadas, búsqueda acotada de activos, alta/edición/desactivación y estado de sesión. Época monotónica propia y `AbortController` por recurso. | `window.AssetRedundancy.{data,computed,methods}`; `GET|POST /redundancy-groups`, `GET|PATCH /redundancy-groups/{id}`, `POST /redundancy-groups/{id}/deactivate` |
| `OrganizationRelations` (`relations-views.js`) | Sección «Redundancia» dentro de la ficha del activo: grupos del activo, rol, reparto y host; alta/edición/desactivación desde el mismo panel. | props `asset`, `app`; usa `app.redundancy`, `app.redundancy.dialog`, permisos `assets.view` / `assets.edit` |
| `GraphExplorer` (`graph-views.js`, `graph-layout.js`) | Panel lateral de grupos cargados, marca de pertenencia en el nodo y bloque del inspector con rol, reparto y host. Sin aristas nuevas. | `app.serverGraphMode`, `app.redundancy.groups`, `app.redundancyGroupForAsset` |
| `app.js` | Registra el mixin y enlaza ruta, cierre de sesión y desmontaje con `handleRedundancyRoute` / `clearRedundancyState`. | `window.AssetRedundancy` |

## Contratos REST usados (sin rutas inventadas)

- `GET /redundancy-groups?query&active&mode&limit&offset` → `{total, limit, offset, items}`.
- `GET /redundancy-groups/{id}` → grupo con `members`.
- `POST /redundancy-groups` → `201` con el grupo completo.
- `PATCH /redundancy-groups/{id}` → subconjunto de campos; `members` siempre es la
  lista **completa** y `"description": null` borra la descripción.
- `POST /redundancy-groups/{id}/deactivate` → `active=false` conservando filas.

DTO del grupo: `id`, `name`, `description`, `mode` (`active_active` |
`active_passive`), `active`, `createdAt`, `updatedAt`, `memberCount`,
`members[]`. Cada miembro: `assetId`, `name`, `quickCode`, `archived`, `role`
(`primary` | `backup` | `null`), `share` (cadena decimal exacta o `null`) y
`host` (`{id, name}` o `null`). El adaptador no inventa campos ni traduce el
reparto a números de coma flotante.

## Reglas de interfaz

- **Pertenencia acotada.** El endpoint de lista no filtra por activo. La ficha
  consulta una página acotada (`limit=200`, `offset=0`) y compara `members[].assetId`;
  declara `examinados` frente a `total` cuando hay grupos fuera de la página. No
  se carga el inventario completo ni se inventa un endpoint.
- **Búsqueda acotada de activos.** El selector de miembros consulta
  `GET /assets/search?limit=50&offset=0&query=…` con retardo y cancelación propios;
  nunca filtra en cliente la primera página como si fuese el inventario.
- **Reemplazo completo.** Guardar envía la lista entera de miembros en una sola
  petición; no hay escrituras parciales por miembro.
- **Validación de cliente.** Nombre obligatorio y como máximo 50 activos
  distintos. Un alta y un grupo activo exigen al menos 2 réplicas; un grupo
  inactivo puede quedar con 0 o 1, que es lo que el servidor acepta al limpiarlo.
  En `active_active` cada miembro lleva un reparto finito con dos decimales como
  máximo y, cuando la lista está completa (2 o más), la suma es exactamente 100;
  con una sola réplica no se exige suma. En `active_passive` cada miembro lleva
  rol — como mucho un `Principal` y, con la lista completa, exactamente uno más al
  menos un `Respaldo` — y ningún reparto. El servidor sigue siendo la autoridad:
  sus `422`, `409`, `403` y `404` se muestran tal cual y no se convierten en éxito.
- **Descripción opcional.** Vaciar el campo envía `description: null`; no se omite
  el campo ni se conserva el valor anterior.
- **Modo.** Cambiar de modo envía la lista completa de miembros, porque el
  servidor exige el estado completo en la misma petición. No se cambian roles ni
  repartos por cuenta propia.
- **Desactivar / reactivar.** Desactivar usa `POST …/deactivate`; reactivar usa
  `PATCH {active:true}`. Un `409` (por ejemplo, un miembro archivado o un grupo ya
  inactivo) se muestra en el diálogo, que conserva el formulario y los datos
  canónicos ya cargados. No se deja un grupo activo vacío ni se simula el cambio.
- **Sin respaldo local.** Un error de carga, un `403` o una falta de permiso
  muestran un mensaje factual; nunca se rellenan con datos de demostración,
  `localStorage` ni un éxito inventado. Las lecturas requieren `assets.view`; las
  escrituras, `assets.edit`.

## Estado, sesión e interacción

`redundancy-api.js` mantiene su propia época monotónica (nunca se reinicia), una
marca de sesión que avanza al cerrar sesión o desmontar y una época de
interacción que avanza al abrir o cerrar el diálogo y al abandonar la ruta.

- **Identidad de sesión.** El token de escritura incluye la identidad efectiva
  (`activeUserId` y el conjunto de permisos ordenado) junto con la época. Un
  `/auth/me` que reemplaza la sesión por otra identidad o por permisos de sólo
  lectura deja `authenticated` en `true`, pero invalida la escritura en vuelo: no
  hay aviso, ni refresco, ni `true`, ni filas tardías. Un chequeo periódico del
  mismo usuario con los mismos permisos (aunque cambie el CSRF o el orden del
  arreglo) no cancela una escritura legítima.
- **Propiedad de la interacción.** Guardar está atado al diálogo concreto y a su
  época: cerrar el diálogo, abrirlo de nuevo o cambiar de ruta impide que una
  respuesta tardía cierre otro borrador, escriba su error o marque `busy`.
  Desactivar y reactivar usan un token de vista, de modo que abrir o cerrar el
  diálogo no los cancela; un cambio de ruta o el desmontaje sí.
- **Salidas.** Desmontar la ficha cierra su diálogo, cancela la búsqueda en cola y
  avanza la época de panel, de modo que una operación del panel que seguía en
  vuelo —desactivar o reactivar— tampoco se presenta como propia: su respuesta
  tardía no devuelve éxito, no refresca la pertenencia y no escribe un error. Un
  cambio de ruta hace lo mismo y descarta lo que quedó en vuelo. La petición ya
  enviada puede haberse aplicado en el servidor: el cliente no afirma haberla
  cancelado, sólo deja de presentarla como propia.
- Un `401` o el cierre de sesión vacían el estado y abortan las lecturas, y una
  respuesta tardía no revive nada. El texto de búsqueda pendiente se cancela con
  su temporizador. El dominio del servidor nunca se escribe en `localStorage`.

## Interacción final en la ficha del activo

- El alta abierta desde la ficha de un activo **siembra ese activo** como primera
  réplica del borrador (`openRedundancyCreate(this.asset)`). El panel pertenece a
  la ficha y un grupo creado allí debe incluirla; el activo sembrado no reaparece
  en los resultados de búsqueda, y se puede retirar con su propio control antes de
  guardar.
- Los miembros ya cargados muestran `Principal`/`Respaldo` o `Reparto de carga N %`
  y el host real de cada réplica; el activo de la ficha se distingue con
  «Este activo». Un grupo sin host registrado dice «Sin host registrado» en vez de
  suponer uno.
- La ficha declara `Se examinaron X de Y grupos` y, si la página acotada no cubre
  el total, advierte que puede haber grupos fuera de ella. Cuando la página está
  recortada y ningún grupo examinado incluye el activo, el texto dice que ninguno
  de los examinados lo incluye y que el resto no se consultó; la ausencia
  definitiva («no pertenece a ningún grupo») sólo se afirma con la página completa.
- Desactivar y reactivar actúan sobre el grupo completo y refrescan la ficha y el
  grafo; un rechazo del servidor deja el grupo como estaba y el mensaje en pantalla.

## Grafo

La pertenencia se muestra como información del grupo —panel lateral, marca en el
nodo y bloque del inspector con `Principal`/`Respaldo`, `Reparto de carga` y el
host real del miembro—. No se añaden nodos ni aristas al grafo: el alojamiento
sigue siendo la relación dirigida `hosted_in`, y la marca de redundancia no
sustituye esa semántica. Si la página cargada no cubre todos los grupos, el panel
lo dice en lugar de presentar el conjunto parcial como completo.

## Límites conocidos

- La prueba integrada usa SQLite y un único navegador Chromium; no certifica otros
  motores, navegadores ni producción.
- El panel del grafo muestra sólo los grupos con algún miembro en la página
  cargada; si el grafo está truncado, lo dice en lugar de completar el conjunto.
- La prueba de navegador no repite la comprobación de archivado con grupo activo
  (ya cubierta por el backend): sólo verifica el `409` de reactivación y que el
  grupo no cambia.
- Las carreras de sesión, de interacción y de desmontaje se prueban con
  transporte diferido en Node, montando el componente real y desmontándolo; el
  navegador no provoca esas carreras. No hay, por tanto, prueba de navegador de
  este caso concreto.
