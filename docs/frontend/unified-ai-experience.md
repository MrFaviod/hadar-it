# Conversación e IA en ITSM

La conversación autenticada puede permanecer abierta mientras trabajas en los módulos permitidos. El panel compacto y la página **Conversación** comparten una sola instancia, el borrador y la transcripción; cambiar de ruta no vuelve a enviar mensajes ni cancela el flujo activo.

## Abrir, ampliar y recuperar

1. Usa **Abrir conversación** en la esquina inferior derecha. El panel empieza cerrado y no bloquea el módulo con un fondo modal.
2. Escribe y pulsa **Enviar**. **Cancelar** solicita la cancelación del trabajo en curso; los errores y el estado comunicado por el servidor se muestran en el panel.
3. Usa **Ampliar conversación** para abrir `#/conversacion`. **Volver al chat compacto** recupera el módulo anterior con el mismo estado.
4. **Cerrar conversación** o `Escape` ocultan el panel compacto y devuelven el foco al botón de apertura. Ocultar el panel no cancela una respuesta.
5. En **Tus conversaciones**, elige una conversación propia para consultar su transcripción del servidor. **Nueva conversación** empieza otra conversación sin reenviar la anterior. Si hay una respuesta activa, termina o cancela esa respuesta antes de cambiar de conversación.
6. Las respuestas largas se desplazan dentro del panel compacto sin superponerse a las herramientas ni al compositor; este permanece accesible en pantallas pequeñas.

Cerrar sesión, cambiar de usuario o desmontar la aplicación aborta las solicitudes locales y borra el estado privado de la conversación. Las respuestas tardías no pueden restaurarlo. El servidor mantiene la autoridad sobre la identidad, los permisos y la propiedad de cada conversación.

### Contexto de activos y demostraciones

- **Usar este activo como contexto** exige un registro canónico recibido del servidor. También puedes elegir un activo conocido en **Activo en contexto** o abrir su ruta de conversación explícita.
- La URL con un UUID, por sí sola, no convierte un registro de demostración en contexto válido. El registro se consulta mediante el adaptador de inventario existente.
- Las alertas de demostración no se presentan como una integración con el agente o con un backend de supervisión.

## Motores, modelos y preferencias

Elige un motor habilitado y uno de sus modelos explícitamente anunciados. Si ya existe una conversación, el cambio usa `PATCH /agent/sessions/{id}` sobre su mismo identificador y conserva la transcripción. No se crea otra conversación para esconder un rechazo del servidor. No se reproducen las llamadas a herramientas anteriores.

«Motor» muestra una sola opción por motor externo y «Perfil» elige un perfil autorizado de ese motor, solo cuando el servidor anuncia más de uno. Las opciones se derivan de las instancias autorizadas (nombre o perfil), nunca de rutas, endpoints ni credenciales del cliente. Cambiar de perfil aplica el mismo `PATCH` a la misma sesión ITSM: conserva los mensajes, el borrador y el identificador, y reinicia únicamente la sesión nativa del motor; no cambia el perfil global de Hermes. La preferencia del chat en Configuración → IA usa el mismo agrupamiento Motor/Perfil y solo se aplica a conversaciones nuevas. Cada proveedor Pydantic, global o personal, mantiene su propia opción de motor.

La preferencia guardada del usuario sirve como valor inicial de una conversación nueva. Recuperar una conversación conserva su motor y modelo propios sin sustituir esa preferencia; tampoco se cambia silenciosamente a otro modelo si el de la conversación deja de estar disponible. La selección no amplía los permisos del usuario ni los límites del perfil de integración.

El panel compacto prioriza la transcripción y el compositor. Las capacidades y la explicación del presupuesto se mantienen en la vista completa. Los motores sin modelos, los fallos de descubrimiento, las credenciales ausentes y los rechazos se muestran como tales; no se simula una respuesta correcta. Si el servidor no ofrece la API de sesiones, se conserva la ruta de chat anterior existente, sin inventar disponibilidad de un motor.

### Evidencia de consumo de la última llamada

`#conversation-usage` muestra solo el último evento de uso recibido, no el total
de la ejecución. La precisión (`measured`, `estimated`, `unavailable`) se presenta
separada del origen (`provider`, `engine`, `estimate`, `none`); proveedor y motor
son orígenes válidos, no precisiones desconocidas. Entrada, salida, caché leída,
caché escrita, razonamiento y total conservan sus valores nulos como **no
disponible**, sin convertirlos en cero ni sumar componentes incluidos de nuevo.
Los indicadores del servidor aclaran si la caché ya está incluida en la entrada
y el razonamiento en la salida; el total indica su origen y una estimación
muestra su método. Los saldos y reportes diarios, no el último evento del flujo,
representan el consumo acumulado.

## Proveedores en Configuración → IA

Los proveedores compatibles con OpenAI se muestran en el panel de IA existente y se utilizan mediante el motor **Pydantic AI**; no constituyen otro motor. Su configuración no sustituye el asistente existente de perfiles e instalaciones.

| Autoridad efectiva | Controles disponibles |
| --- | --- |
| Usuario sin permiso de administración | Estado público autorizado por el servidor; sin botones para añadir, editar o eliminar. |
| Permiso `system.providers` y capacidad `canManageGlobal` | **Añadir proveedor global** y modificación de proveedores globales. |
| Permiso explícito `agents.providers.personal` y capacidad `canManagePersonal` | **Añadir proveedor personal** y modificación de proveedores propios. No se concede por defecto al rol User. |

El formulario pide nombre, endpoint, identificadores de modelos —uno por línea—, estado habilitado y una credencial opcional de solo escritura. No hay descubrimiento ficticio de modelos. El servidor valida la URL y la autoridad: los endpoints personales deben ser HTTPS públicos, sin destinos privados ni redirecciones; la configuración global conserva la política del operador.

La credencial nunca vuelve en la respuesta ni se precarga al editar. Dejarla vacía al editar conserva la existente. Solo se muestra **Credencial configurada** o **Sin credencial**. Si `credentialStorageAvailable` es falso, el campo queda deshabilitado y se explica que falta `ITSM_AI_CREDENTIAL_KEY` en el servidor. Los mensajes concretos de error del servidor permanecen visibles. Cambiar de usuario borra los metadatos, permisos de interfaz y cualquier credencial aún escrita en el formulario.

Eliminar exige una confirmación explícita. El panel se actualiza desde el servidor después de guardar o eliminar; no presenta un éxito local cuando la operación ha fallado.

## Perfiles e instalaciones

Se conserva el asistente existente: elección de instancia y perfil, detección del destino, configuración MCP, selección de skills e instalación/verificación. Un perfil configurado o una solicitud remota exportada no equivale a un perfil verificado. La interfaz muestra el resultado y los límites de verificación del servidor y del recibo, sin fabricar un resultado verificado.

OpenCode selecciona un espacio de trabajo y el campo **Perfil** muestra, deshabilitado, el perfil registrado en esa instancia: el asistente envía exactamente ese perfil, o ninguno si la instancia no declara perfil, y nunca lo sustituye por otro. Hermes conserva la selección editable de perfiles con nombre. La versión esperada debe corresponder al motor que se está verificando.

La comprobación aislada del 27 de octubre de 2026 ejecutó el asistente desde Configuración para OpenCode 2.1.2 y dos perfiles dedicados de Hermes 0.22.5. Los tres resultados persistieron **MCP: verificado · Perfil: verificado**, la skill `itsm-inventory`, 63 herramientas autorizadas y una consulta no mutante `search_assets`. Además, con el proveedor real configurado, una misma conversación pasó de Hermes a OpenCode y al segundo perfil de Hermes, completó una consulta autorizada en cada paso y conservó sus seis turnos. Un usuario común completó el recorrido con Pydantic AI 2.59.0; no recibió opciones de motores externos. Son comprobaciones de desarrollo aisladas, no una certificación de producción.

## Comprobaciones y selectores

El comando focalizado de componentes es:

```sh
node --test tests/conversation.test.cjs tests/agent-integrations.test.cjs tests/contextual-chat.test.cjs
```

Estas pruebas ejecutan los componentes Vue reales y simulan únicamente la frontera HTTP. Cubren continuidad al navegar, aislamiento por identidad, reanudación y cambio de sesión/motor/modelo, autoridad de proveedores y el tratamiento de credenciales y errores. No prueban por sí solas la disposición visual, un motor externo real, la seguridad del almacenamiento del backend ni una instalación en un perfil real.

Para la comprobación de navegador en ambos temas y pantallas pequeñas:

- Apertura/cierre y foco: `#conversation-opener`, `#conversation-surface`; después de `Escape`, espera al siguiente render antes de comprobar el foco.
- Cambio de formato: `#conversation-expand`, `#conversation-collapse`; conserva borrador, transcripción y respuesta activa al navegar.
- Selección: `#conversation-session`, `#conversation-engine`, `#conversation-profile`, `#conversation-model`, `#conversation-asset`, `#conversation-input`.
- Contexto canónico: `#conversation-use-asset` en la ficha de un activo recibido del servidor.
- Autoridad de proveedores: `#provider-new-global`, `#provider-new-personal`; los botones ausentes no deben reaparecer al cambiar de cuenta.
- Formulario: `#provider-form`, `#provider-name`, `#provider-url`, `#provider-models`, `#provider-key`; el campo de credencial debe estar vacío al editar y no aparecer en el estado leído.

La verificación de navegador, la suite completa y los motores/perfiles reales son comprobaciones separadas. No se infiere su éxito de estas pruebas de componentes.

## Cuota diaria de IA

La conversación y el panel de preferencias muestran el saldo diario propio que
devuelve `GET /api/v1/agent/usage/me`: empresa y cuenta personal por separado,
con consumido, reservado, disponible, retenciones pendientes, legado sin
atribuir y precisión. **Ilimitado** y **0 tokens · sin admisión** son estados
distintos; un dato ausente se muestra como **No disponible**, nunca como cero.
El contexto activo solo resalta la financiación que el servidor declara para el
ámbito del proveedor de la instancia: una clave personal no se presenta como
empresa y, si no hay ámbito, el saldo no se atribuye. El botón **Actualizar
cuota**, el fin, la cancelación o el error de un flujo, el enfoque de la ventana
y el regreso a la pestaña vuelven a consultar; no hay sondeo continuo y el
navegador no reinicia el día por su cuenta. Al cerrar sesión o recibir `401` se
borran los saldos y una respuesta tardía de la cuenta anterior se descarta.

En **Configuración → IA**, la política diaria, las excepciones y el reporte
requieren `system.providers` en una cuenta humana. Se pueden fijar un límite de
empresa y otro personal, elegir ilimitado o cero, cambiar la zona horaria y
cancelar un cambio pendiente antes de que se aplique. Las excepciones se aplican
a una cuenta real y a una financiación; **heredar** elimina la excepción y es
distinto de fijar ilimitado o cero explícitos. El selector de cuentas usa la
lista existente con `users.view`; sin ese permiso la interfaz pide el UUID y
advierte que el nombre de usuario no sirve como identificador. El reporte
respeta los filtros, la agrupación y los totales del servidor, muestra los nulos
como no disponibles, no suma caché en el cliente, no pagina localmente y separa
las retenciones pendientes del consumo liquidado y el legado sin atribuir.

El estado estricto de un motor solo se muestra si su DTO declara
`mode: managed` y `enforcement: strict`; si falta el DTO se indica no disponible
y no estricto, sin deducirlo del nombre del motor ni del modo proxy. Las
retenciones no se liberan desde esta interfaz. El editor de instancias y el
asistente permiten elegir, solo con `system.providers`, el modo gestionado con
proveedor global habilitado, modelo predeterminado exacto y límite positivo de
contexto de entrada declarado por el operador; o el modo directo con una
excepción de empresa explícita. Esa excepción no convierte el modo directo en
estricto. El límite de salida sigue configurado en el servidor; la interfaz no
lo deduce del modelo ni declara aislamiento de red.
