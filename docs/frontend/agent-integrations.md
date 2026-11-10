# Motores de agente e integraciones (frontend)

El chat usa una interfaz común para los motores Pydantic AI, Hermes y OpenCode. El navegador solo transporta mensajes, contexto acotado, selección de motor/modelo y el identificador de un activo permanente. Las URL de proveedor, los tokens y la autorización de sesión permanecen en el servidor.

## Rutas

- `#/conversacion`: chat. Carga motores con `GET /api/v1/agent/engines`; si el endpoint aditivo no existe (`404`), mantiene el chat compatible `POST /api/v1/agent/chat`. Cada fallo de descubrimiento se muestra con la instancia y el mensaje público del servidor; una instancia sin modelos no reemplaza la selección guardada.
- `#/configuracion/ia`: preferencia del chat y, para administradores, instancias, catálogo, instalaciones y el asistente de integración. La ruta se resuelve con `window.AssetAgentViews.routeOverride` sin bifurcar el enrutador principal.
- `#/configuracion/ia` requiere `assets.view`: la preferencia de chat y modelo sigue disponible para cualquier usuario autenticado. La administración de instancias, catálogo, instalaciones y el asistente requiere `system.providers`, y cambiar un módulo requiere además `system.modules`. La UI no concede permisos ni los infiere: muestra el error del servidor.

## Transporte

Todas las llamadas usan `window.AssetAccess.request`/`stream` con la sesión same-origin y el token CSRF. No se usa `EventSource` porque el envío es un `POST` con cuerpo y señal de cancelación.

- `PUT /api/v1/agent/preferences` `{instanceId, model}`.
- `POST /api/v1/agent/sessions` `{instanceId, model, context?, assetId?}`.
- `POST /api/v1/agent/sessions/{id}/messages` `{message, assetId?}`: respuesta `text/event-stream`.
- `PATCH /api/v1/agent/sessions/{id}` `{model}` o `{instanceId, model}`: el servidor reautoriza la instancia destino, rechaza el cambio mientras la sesión está en ejecución y conserva el identificador y la transcripción de la conversación.
- `GET /api/v1/agent/sessions/{id}`: instantánea para reconexión.
- `POST /api/v1/agent/sessions/{id}/cancel`: sin cuerpo.

Los eventos SSE usan `data: {json}` terminado en una línea vacía. `delta.text` es **un fragmento nuevo que se concatena**; el adaptador del servidor compara las respuestas acumuladas del proveedor antes de emitir, de modo que una repetición acumulada no duplica texto. Los tipos soportados son `session`, `delta`, `tool`, `usage`, `error` y `done`. En `done` se conservan `actions`, `results` y `approvalPending` además de `cancelled`, por lo que las tarjetas existentes se siguen mostrando.

El cliente:

- Acumula fragmentos sin interpretar HTML; el texto se interpola, nunca se renderiza como marcado.
- Muestra herramientas, consumo de la última llamada (`precision: measured|estimated|unavailable`) y errores del motor sin inventar una respuesta.
- Envía como contexto solo el historial reciente (máximo 20 turnos) y un `assetId` UUID elegido entre activos ya devueltos por el servidor para esta sesión.
- Al cambiar de motor o de perfil aplica `PATCH` a la **misma** sesión ITSM: conserva mensajes, borrador e identificador y solo reinicia la sesión nativa del motor; nunca inicia otra conversación ni reenvía historial. Al cambiar de modelo sin cambiar de instancia aplica el mismo `PATCH`.
- «Motor» muestra un único valor por motor externo y «Perfil» sus perfiles autorizados; el selector de perfil solo aparece cuando el servidor anuncia más de uno. Las opciones y etiquetas salen de las instancias descubiertas (nombre o perfil), nunca de endpoints, directorios ni credenciales. Cada proveedor Pydantic, global o personal, conserva su propia opción de motor. Si el `PATCH` falla, la selección vuelve al valor que confirma el servidor.
- Muestra «Cancelar» durante todo el procesamiento, incluso mientras se crea la sesión; después de creada llama al endpoint de cancelación. Si el motor no permite interrumpir, muestra el motivo del servidor.
- Tras un corte no reenvía el mensaje automáticamente. Ofrece «Reconectar y consultar el estado», que reemplaza la transcripción con la instantánea del servidor; no duplica texto, acciones ni consumo.

La preferencia guardada se corrige si la instancia o el modelo ya no existen. La lista de modelos siempre proviene de la instancia conectada; no hay catálogo de modelos gratuitos en el cliente. Si el DTO del motor no declara un presupuesto estricto, la UI no lo presenta como tal.

El evento `usage` conserva por separado `precision` y `source`
(`provider|engine|estimate|none`). **Última llamada** muestra entrada, salida,
caché leída/escrita, razonamiento y total recibidos, sin sumarlos en el navegador
ni presentarlos como el total de la ejecución. Los componentes ausentes o `null`
se muestran como no disponibles; un cero explícito se mantiene como cero. Los
indicadores `inputIncludesCache` y `outputIncludesReasoning` aclaran si esos
componentes ya forman parte de entrada y salida, evitando contarlos dos veces.
`totalSource` distingue el total del proveedor del derivado por el servidor;
`estimationMethod` muestra el método comunicado cuando hay una estimación.
La cuota diaria y los reportes siguen siendo la autoridad sobre el consumo
acumulado, no este último evento del flujo.

## Configuración → IA

- `GET /api/v1/agent/integrations` devuelve instancias, instalaciones con `target:{engine,path,profile,version,remote}`, estado de verificación, enlaces y valores predeterminados. La UI consume esa forma canónica; `verified` solo se toma del servidor.
- `GET /api/v1/agent/integrations/catalog` devuelve skills y módulos. La clasificación oficial sale de `module.official === true` y del `module` declarado por cada skill: el módulo canónico es `itsm`. La sección «Paquete oficial» agrupa esas skills; «Módulos» muestra solo los módulos externos y el módulo oficial no expone una acción de deshabilitación. Solo los módulos habilitados ofrecen sus skills.
- `POST/PUT /api/v1/agent/integrations/instances` envía `{name,engine,baseUrl,secretRef,username?,profile?,directory?,defaultModel?,integrationIdentityId?,enabled}`. Solo viaja el **nombre** de la referencia al secreto, nunca su valor. Si el servidor rechaza la configuración, la UI muestra el mensaje seguro y los campos informados por el servidor (por ejemplo, una referencia de secreto no configurada), sin incluir valores de secretos.
- `PUT /api/v1/agent/integrations/modules/{id}` `{enabled}`. Requiere `system.modules`; el módulo oficial no se deshabilita (`409`).
- `POST /api/v1/agent/integrations/targets` `{engine,path,profile?,version?}`: ruta absoluta explícita; el servidor no escanea el home. La respuesta canónica es `{target:{engine,path,profile,version,remote},detection:{engine,format,version,profile,targetPath,configFile,configExists,skillsDirectory,limitations}}`. El asistente solo acepta ese sobre completo: exige motor coincidente, rutas absolutas, versión/formato, archivo y directorio de skills, booleano `configExists` y limitaciones de texto. `configExists:false` es un destino válido cuya configuración se creará. Un `200` sin esos campos se muestra como error y nunca se convierte en un destino instalable inventando `detected:true`.
- `POST /api/v1/agent/integrations/install` con `{instanceId,target:{engine,path,profile?,version?,remote?},mcp:{url,secretRef,identityId},skills,operation:"install"}`. Para un destino remoto se envía además `mode:"remote"`; ese campo, y no `target.remote`, determina el flujo en el servidor. El `profile` de un OpenCode nunca se teclea en el asistente: se reutiliza el registrado en la instancia (`null` si no declara ninguno) y el de Hermes sigue siendo editable. La respuesta es el DTO canónico de instalación (`id,instanceId,target,skills,mcp,status,verified,mcpVerified,profileSafetyVerified,checks,conflicts,binding,requestDigest,operation,managedFiles,createdAt,updatedAt`, más `request` cuando aplica y `error:{code,message}`/`limitations` cuando el servidor sanea un fallo); la UI la conserva tal cual, muestra ese mensaje y esas limitaciones en lugar de una frase genérica cuando existen, mantiene la frase genérica cuando no hay `error`, lee la versión de `target.version` y nunca infiere `verified`. Una instalación remota devuelve `status:"exported"`, `verified:false`, `request` y `requestDigest`.
- La inspección local pertenece a un destino concreto: el asistente guarda una instantánea de `engine`, `path`, `profile` (normalizado como en la petición), `version` y `remote`. Instalar en local exige que esa instantánea siga coincidiendo con el destino actual y que proceda de `POST /targets`, no de un `detection` asignado a mano. Cambiar cualquiera de esos campos invalida la inspección y obliga a repetirla; `canNext` del paso 2 aplica la misma regla. Cada inspección lleva un contador de generación: una respuesta que llega tarde se descarta sin fijar `detection`, `version` ni un error de sobre válido, y no puede habilitar una instalación posterior. Un destino remoto sigue exportando la solicitud sin inspección local; volver a local exige una inspección nueva.
- Las operaciones de ciclo de vida (`verify`, `update`, `repair`, `disable`, `uninstall`) envían solo `{instanceId,target,operation}`: el servidor resuelve el enlace guardado y el secreto; la UI no reenvía tokens ni skills.
- `GET /api/v1/agent/integrations/installations/{id}/request` recupera la solicitud remota.
- `POST /api/v1/agent/integrations/receipts` `{instanceId,requestDigest,receipt}` importa el recibo emitido en el host remoto. El servidor rechaza un resumen que no coincida y solo devuelve `verified: true` tras validar el recibo y comprobar de forma independiente MCP y seguridad del perfil.

El asistente de cinco pasos solo se abre automáticamente en el primer registro (sin instalaciones ni instancias externas). Permite instancia nueva o existente, perfil/entorno, comprobación real del destino, servidor MCP con identidad de máquina y selección explícita de skills. Una instalación remota genera una solicitud JSON y **no** afirma que el destino esté instalado: solo un recibo verificado por el servidor puede mostrar `verified: true`. El comando auxiliar es:

```bash
python -m itsm.agent_integrations --request <ruta del archivo>
```

Nunca se muestra «instalado» a partir de la solicitud, de la escritura de archivos o de un recibo sin verificación de conexión MCP.

## Seguridad y límites

- El navegador no recibe tokens de motores, secretos MCP ni configuración de proveedores; no los guarda en almacenamiento local.
- No hay URL de endpoint arbitraria en las peticiones del chat: el `instanceId` se resuelve en el servidor.
- Los permisos efectivos son los de la identidad de integración; cambiar motor, modelo o skill no amplía privilegios.
- La cuota diaria de tokens se presenta con la clasificación del servidor. El consumo de motores externos se muestra por separado porque puede no ser interrumpible antes de procesar.
- Los errores del servidor se presentan con su mensaje público; no se exponen excepciones crudas del proveedor.

## Pruebas enfocadas

Desde `frontend/`:

```bash
node --test tests/conversation.test.cjs tests/agent-integrations.test.cjs
```

Cubren, entre otros: descubrimiento dinámico y corrección de un modelo desaparecido, streaming por fragmentos exactos, consumo clasificado, tarjetas de acciones/resultados, cambio de motor/modelo, cancelación, reconexión sin duplicar, presupuesto y su advertencia, ruta `#/configuracion/ia`, permisos, asistente, sobre canónico `{target,detection}` del destino y rechazo de un `200` incompleto, instalación exacta, DTO canónico en instalación y ciclo de vida, solicitud/recibo remoto y rechazo del servidor sin afirmar instalación. Los archivos modificados son `assets/js/{conversation,agent-integrations,access,app}.js`, `assets/css/{conversation,agent-integrations}.css`, `index.html`, `tests/{conversation,agent-integrations}.test.cjs` y este documento.

## Cuota diaria de IA

El cliente consume exclusivamente los endpoints de cuota del servidor mediante
`AssetAccess.request` (cookie, `Origin` y CSRF ya existentes); no guarda cuotas,
saldos ni claves en almacenamiento local y no reinicia el día en el navegador.

| Endpoint | Uso |
| --- | --- |
| `GET /api/v1/agent/usage/me` | Saldo propio por financiación `company`/`personal`, día y zona horaria informados por el servidor. |
| `GET /api/v1/agent/usage/policy` | Política diaria, zona pendiente y excepciones. Autoridad: `system.providers` en una cuenta humana. |
| `PUT /api/v1/agent/usage/policy` | Límites de empresa y personales, zona horaria y `{cancelTimezoneChange:true}`. |
| `PUT /api/v1/agent/usage/overrides/{userId}` | Excepción por cuenta real y financiación; `{dailyLimit:null}` es ilimitado explícito y `0` niega el envío. |
| `DELETE /api/v1/agent/usage/overrides/{userId}?scope=company\|personal` | Hereda la política; es distinto de una excepción ilimitada o cero. |
| `GET /api/v1/agent/usage/report` | Reporte con filtros, agrupación, totales y procedencia informados por el servidor. |
| `GET /api/v1/agent/usage/pending?limit=100` | Retenciones pendientes o sin resolver; no son consumo liquidado. |

La política y el reporte solo se ofrecen con `system.providers` y una identidad
humana; el rol de administración o `users.edit` no conceden esa autoridad. Para
elegir la cuenta de una excepción se usa la lista de usuarios ya disponible si
la sesión tiene `users.view`; sin ese permiso se pide un UUID acotado y se avisa
de que un nombre de usuario no identifica la cuenta. Nunca se envía un nombre
como si fuera un identificador.

`null` significa ilimitado y `0` significa denegación explícita; un valor
ausente significa no informado, no cero. La interfaz obliga a elegir entre
ilimitado y un entero no negativo, y conserva ambos valores como estados
distintos. Los campos de consumo, reservado, pendiente, disponible, legado y
precisión reflejan exactamente lo devuelto: los nulos se muestran como **No
disponible**. El total de caché no se suma en el cliente, el reporte no se
pagina ni se recalcula localmente, y las filas legadas sin atribución se marcan
como tales en lugar de asignarlas a una empresa o persona.

Un cambio de zona horaria queda pendiente hasta el siguiente límite diario
seguro y se puede cancelar; el cliente no simula el cambio de día. La vista
personal muestra ambos saldos cuando el servidor los devuelve, pero solo resalta
la financiación declarada por el ámbito del proveedor de la instancia activa.
No se asume empresa para una clave personal. Si el servidor no informa el
ámbito, no se atribuye el saldo. El saldo se refresca al terminar, cancelar o
fallar un flujo, al enfocar la ventana, al volver a la pestaña y mediante el
botón **Actualizar cuota**; no hay sondeo continuo. Un cierre de sesión, un
`401` o el desmontaje descartan los datos, y una respuesta tardía de una cuenta
anterior no puede restaurarlos.

El estado de cuota del motor se lee solo de `engineDTO.quota`:
`{mode: managed\|direct\|builtin, enforcement: strict\|admission_only\|observed\|unavailable, reason, directException}`.
Solo `managed` + `strict` se presenta como estricto antes de enviar. Un DTO
ausente se muestra como no disponible y no estricto; nunca se deduce del nombre
del motor, del modo proxy ni de un límite agregado del SDK.

El editor existente de instancias y el paso de instancia nueva del asistente
ofrecen **Cuota y enrutamiento** solo con `system.providers` en una cuenta humana.
El modo `managed` exige un proveedor global habilitado de la lista administrativa
existente, el identificador exacto del modelo predeterminado y un **Límite de
contexto de entrada** entero positivo declarado por el operador dentro de lo
admitido por el modelo y proveedor. No se deduce ningún tope de metadatos del
modelo. El límite de salida permanece en la configuración de instalación del
servidor (`ITSM_AGENT_MAX_OUTPUT_TOKENS`), sin un nuevo control en el navegador.
El modo `direct` ofrece una casilla de excepción explícita para trabajos de
empresa; no seleccionarla no autoriza una ejecución pagada de empresa. La cuota
directa se presenta como observada, no estricta. La selección del modo no prueba
aislamiento de red y nunca sustituye el estado `quota.enforcement` del servidor.
Los cuatro campos (`quotaMode`, `directCompanyException`, `managedProviderId`,
`managedContextTokens`) se envían por el transporte existente de instancias;
al elegir directo se borran proveedor y límite gestionados con `null`, y al
elegir gestionado se desactiva la excepción directa. Sin esa autoridad no se
ofrecen ni se añaden esos campos al cuerpo de la solicitud.

Limitaciones actuales: no hay UI de liberación o reconciliación de retenciones,
el reporte no pagina en el cliente y no se muestra un estado de certificación de
aislamiento de red. Las pruebas de componentes cubren permisos, cero frente a
ilimitado e inexistente, herencia, usuario real, nulos, legado, caché no sumada,
retenciones pendientes, estado del motor, refresco y respuestas tardías; no
sustituyen la verificación en navegador ni la suite completa.
