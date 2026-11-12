English: [operations.md](operations.md)

# Operaciones de infraestructura e identidad

Ejecuta los comandos desde la raíz que contiene `compose.yaml`, `backend/` y `frontend/`. Empieza con la [guía de instalación](../INSTALL.md); usa esta referencia para configuración, almacenamiento, actualizaciones y recuperación.

## Configuración sin archivos de secretos

Las variables se documentan y se ofrece `.env.example` sin secretos para uso local opcional de Compose con `--env-file .env`; los comandos de abajo mantienen `--env-file /dev/null` para usar solo el entorno. Los comandos deshabilitan explícitamente la carga implícita de `.env` de Compose. Suministra las variables desde el entorno que invoca o desde tu mecanismo aprobado de gestión externa de secretos; no pongas credenciales de producción en Git, en transcripciones de terminal ni en archivos de ejemplo. Codifica con URL las credenciales de las URLs de base de datos. El entorno de los contenedores es visible para los administradores de Docker: esto no es una bóveda de secretos.

Todos los comandos de Compose de este documento se ejecutan en una shell de instalación donde
el modo de release y su overlay ya están exportados. El modo es obligatorio: nombra el
proyecto Compose y sus volúmenes, y un valor ausente falla en la interpolación en lugar de
adivinar.

```bash
# Example for a production installation. Use deploy/compose.dev.yaml or
# deploy/compose.demo.yaml (with RELEASE_MODE=dev|demo) for the other modes.
export RELEASE_MODE=prod
export COMPOSE_FILE=compose.yaml:deploy/compose.prod.yaml
```

Las bases, orígenes, comportamiento de preparación, la entrada TLS y las partes no probadas
por modo están en [despliegue por modo](release-modes-deployment.md).

| Variable | Valor por defecto / significado |
|---|---|
| `ITSM_AUTH_ORIGIN` | Origen exacto del navegador; valor por defecto de Compose http://localhost:18080. Debe coincidir con el hostname del navegador. |
| `ITSM_AUTH_COOKIE_SECURE` | `true`; `false` solo de forma explícita para HTTP aislado/local. En cualquier otro caso usa HTTPS. |
| `ITSM_BOOTSTRAP_PASSWORD` | Contraseña inicial externa para el CLI explícito de administrador; no hay cuenta por defecto. |
| `ITSM_SELINUX_LEVEL` | Nivel MCS de SELinux específico de la instalación, obligatorio y compartido por API, worker, migraciones y bootstrap. Reserva categorías distintas por instalación; ver más abajo. No es una credencial. |
| `ITSM_AGENT_MODEL` | Vacío deshabilita la inferencia; `provider:model` elegido por el servidor, por ejemplo `openai:gpt-4.1-mini` o `anthropic:claude-sonnet-4-5`. |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | Credencial externa específica del proveedor; nunca entrada del navegador, configuración confirmada en Git ni argumento de herramienta. |
| `ITSM_AGENT_OPENAI_BASE_URL` | Endpoint compatible con OpenAI, opcional y propiedad del servidor; nunca se acepta desde el chat. |
| `ITSM_AGENT_MAX_STEPS` / `ITSM_AGENT_MAX_HISTORY_MESSAGES` / `ITSM_AGENT_MAX_OUTPUT_TOKENS` | `8` / `20` / `1024`; interacción de inferencia y herramientas acotada. |
| `ITSM_DATABASE_URL` | URL de SQLAlchemy para PostgreSQL; por defecto el `postgres` local con usuario y base `itsm` y `ITSM_POSTGRES_PASSWORD` suministrada externamente |
| `ITSM_POSTGRES_PASSWORD` | Sin contraseña incorporada; obligatoria para el perfil PostgreSQL local |
| `ITSM_TASK_STORAGE` | `sqlite`; alternativas `redis` / `postgres` |
| `ITSM_TASK_SQLITE_PATH` | Compose define `/data/tasks/huey.db`, separado de `/data/app/itsm.db` |
| `ITSM_ATTACHMENT_STORAGE_PATH` | Compose define `/data/attachments`, respaldado por el volumen independiente `attachment-data` |
| `ITSM_ATTACHMENT_MAX_BYTES` | `10485760` (10 MiB), ajustable de 1 byte a 50 MiB |
| `ITSM_TASK_REDIS_URL` | `redis://redis:6379/0`; perfil opcional o Redis externo |
| `ITSM_TASK_POSTGRES_DSN` | DSN de PostgreSQL para Huey, separado; nunca infieras la cola desde el motor SQL principal |
| `ITSM_TASK_RETRIES` / `ITSM_TASK_RETRY_DELAY_SECONDS` | `2` / `1`; política de reintentos de la demo, acotada |
| `ITSM_DEMO_PERIODIC_MINUTES` | `0` deshabilita la demo periódica; 1–60 habilita una agenda del worker |
| `ITSM_LOG_LEVEL` | `INFO`; logs estructurados de aplicación y worker |
| `ITSM_MEILISEARCH_URL` | Vacío selecciona la búsqueda SQL canónica. URL base HTTP(S) opcional del motor; sin credenciales, query ni fragmento embebidos. Si se pierde el motor, vuelve a SQL. |
| `ITSM_MEILISEARCH_API_KEY` | Secreto opcional para un motor externo; Compose usa por defecto `ITSM_MEILI_MASTER_KEY` suministrada externamente para su perfil de búsqueda. |
| `ITSM_MEILISEARCH_HTTP_TIMEOUT_SECONDS` | `5`; entre 1 y 60 segundos para las peticiones al motor. |
| `ITSM_SEARCH_INDEX_NAME` | `itsm_entities`; nombre de índice seguro para endpoints, de 1 a 64 caracteres. |
| `ITSM_SEARCH_SYNC_BATCH_SIZE` | `100`; entre 1 y 500 filas durables del outbox por lote de sincronización de Huey. |
| `ITSM_SERVICE_REDIS_URL` | Descriptor opcional, no es una dependencia de readiness. |
| `ITSM_PROMETHEUS_URL` | URL base del motor que usa el adaptador de monitorización. Por defecto en Compose `http://prometheus:9090` para el perfil local; en su lugar configura una URL HTTPS externa. Un motor vacío o inalcanzable se informa como no disponible, nunca como todos los dispositivos caídos. Se rechazan credenciales, query y fragmento; usa la variable del token. |
| `ITSM_PROMETHEUS_TOKEN` | Bearer opcional para una API externa de Prometheus. Secreto; nunca en URLs, logs ni Git. |
| `ITSM_ALERTMANAGER_URL` | Vacío deshabilita el modo nativo de Alertmanager. Configura `http://alertmanager:9093` con el perfil local, o la dirección externa. |
| `ITSM_ALERTMANAGER_TOKEN` | Bearer opcional para la API de Alertmanager (silencios) cuando tu instancia exige autenticación. |
| `ITSM_MONITORING_DISCOVERY_TOKEN` | Bearer compartido para el descubrimiento HTTP de servicios de Prometheus y las métricas de configuración. Obligatorio para el perfil local de Prometheus; suminístralo externamente. |
| `ITSM_MONITORING_INGEST_TOKEN` | Bearer que Alertmanager presenta al webhook del ITSM. Obligatorio cuando AM publica; distinto del token de descubrimiento. |
| `ITSM_MONITORING_HTTP_TIMEOUT_SECONDS` | `10`; entre 1 y 60 segundos para las llamadas al motor y a Alertmanager. |
| `ITSM_MONITORING_POLL_SECONDS` | `60`; entre 60 y 3600; cadencia de sondeo de Huey cuando el modo nativo de Alertmanager está desactivado. |
| `ITSM_MONITORING_PUBLIC_URL` | Base visible para el usuario que se usa en los enlaces, por defecto `http://localhost:18080`. |
| `ITSM_MONITORING_SECRETS` | Objeto JSON que asocia una referencia de Apprise con su URL/token completa, suministrado externamente. Las respuestas de la API solo exponen si una referencia está configurada. |
| `ITSM_SNMP_AUTHS` | Documento YAML `auths:` para el SNMP Exporter, suministrado externamente y proyectado como archivo de secreto de Compose para `monitoring-snmp`. Obligatorio para ese perfil; nunca se confirma en Git, se imprime ni se almacena en ITSM. |
| `ITSM_NOTIFICATION_RETENTION_DAYS` | `90`; entre 1 y 3650; retención de notificaciones entregadas/fallidas y de la bandeja de entrada. |
| `ITSM_API_PORT` / `ITSM_FRONTEND_PORT` | Loopback `18000` / `18080` |
| `ITSM_PROMETHEUS_PORT` | Loopback `19090` |
| `ITSM_PROMETHEUS_RETENTION` | `7d`; duración de retención válida de Prometheus; un motor externo la ignora |
| `ITSM_ALERTMANAGER_PORT` | Loopback `19093` para el Alertmanager local opcional |
| `ITSM_MEILI_MASTER_KEY` | Obligatoria solo para el perfil local opcional de búsqueda, suministrada externamente; se reenvía a API y worker como clave de API del motor salvo que se sobrescriba de forma explícita. |

### Reserva el dominio SELinux del volumen compartido

Antes de **cualquier** comando de Compose, haz que el operador del host reserve un nivel
MCS sin usar para esta instalación y lo exporte como `ITSM_SELINUX_LEVEL`. Por ejemplo, un
nivel tiene la forma `s0:c491,c492`; esas categorías se usaron solo en la verificación
aislada, **no se asignaron como valor por defecto universal de despliegue**. Instalaciones
separadas deben usar niveles reservados distintos. Mantén el mismo valor en cada sesión
administrativa y mecanismo externo de configuración, incluidos los posteriores comandos
`run --rm migrate`, bootstrap y actualización. Compose falla con un mensaje accionable si
falta, en lugar de adivinar una asignación de categorías compartida.

Los contenedores de aplicación (`initialize`, `backend`, `worker`, `frontend` y `proxy`) corren
con el sistema de archivos raíz de solo lectura; `/tmp` es el único espacio temporal tmpfs.
El estado persistente queda en los volúmenes nombrados del modo. Cada contenedor tiene
`pids_limit: 256`. Por defecto no hay límite de memoria; define `ITSM_APP_MEM_LIMIT` (por
ejemplo `1g`) para añadirlo. Dimensiónalo con el pico medido, incluidos los procesos hijos de
render de PDF: un límite demasiado pequeño detiene el proceso.

API, worker y comandos de una sola ejecución comparten los volúmenes nombrados de
aplicación, cola y archivos opacos. Las etiquetas privadas independientes de Docker hacían
que las instalaciones nuevas parecieran sanas mientras el worker no podía leer la cola. Por
eso el ancla del backend da a estos contenedores cooperantes el mismo nivel MCS, conservando
la aplicación de tipos de SELinux, la reducción de capacidades y `no-new-privileges`. No
deshabilites SELinux, no agregues `:z`/`:Z` solo para bind en volúmenes nombrados ni
reetiquetes directorios del host para ocultar esto. Un operador que cambie la asignación de
una instalación existente debe coordinar a todos los consumidores; no ejecutes contenedores
de una sola ejecución con etiquetas distintas contra volúmenes vivos.

Después de la instalación y de una migración tardía, ejecuta una tarea autenticada real y
verifica su resultado completado. El readiness por sí solo no prueba que el worker pueda
acceder al almacenamiento compartido de la cola.

### Primero la base de datos integrada

El valor por defecto sigue siendo la búsqueda SQL persistente sin servicio adicional. Una
instalación puede optar por Meilisearch para mejorar la relevancia; SQL sigue rehidratando y
autorizando cada resultado, y las caídas conservan la búsqueda SQL. La configuración
existente de PostgreSQL es opcional.

### PostgreSQL local (opcional)

Suministra primero `ITSM_POSTGRES_PASSWORD` de forma externa y después ejecuta:

```bash
export ITSM_POSTGRES_PASSWORD=<external password>
export ITSM_DATABASE_URL="postgresql+psycopg://itsm:${ITSM_POSTGRES_PASSWORD}@postgres:5432/itsm"
export ITSM_AUTH_ORIGIN=https://itsm.example.com   # exact browser origin; prod cookies are Secure
docker compose --env-file /dev/null --profile local-postgres up -d --wait postgres
docker compose --env-file /dev/null build backend frontend
docker compose --env-file /dev/null up -d
# After `initialize` (`python -m itsm.deployment prepare`) succeeds, create the first owner:
docker compose --env-file /dev/null run --rm -e ITSM_BOOTSTRAP_PASSWORD backend \
  python -m itsm.identity.cli bootstrap-superadmin --username YOUR_USERNAME --name 'Your installation owner'
```

`initialize` aplica las migraciones una vez antes del readiness de la API; los entrypoints de
la API y del worker nunca migran de forma concurrente, y el servicio `migrate` del perfil
`tools` sigue siendo un recurso manual, no un paso de instalación. Frontend:
`http://127.0.0.1:18080`; OpenAPI de la API: `http://127.0.0.1:18000/docs`. Los servicios
básicos no requieren Redis, Meilisearch ni Prometheus. Para una prueba local por HTTP plano usa
el modo `dev`, cuyo overlay desactiva las cookies `Secure`; `prod` conserva cookies `Secure` y
espera un origen HTTPS.

### SQL principal externo / SQLite persistente

Provee `ITSM_DATABASE_URL` para la base externa elegida; omite `local-postgres`. Ejemplo de
selección local de SQLite sin secretos dentro del proyecto de producción:

```bash
export ITSM_DATABASE_URL=sqlite:////data/app/itsm.db
docker compose --env-file /dev/null build backend frontend
docker compose --env-file /dev/null up -d
# After `initialize` (`python -m itsm.deployment prepare`) succeeds, create the first owner:
docker compose --env-file /dev/null run --rm -e ITSM_BOOTSTRAP_PASSWORD backend \
  python -m itsm.identity.cli bootstrap-superadmin --username YOUR_USERNAME --name 'Your installation owner'
```

Los datos principales de SQLite persisten en `app-data`; la cola de tareas y sus resultados
en `task-data`; los archivos opacos en `attachment-data`. Los overlays `dev` y `demo`
reemplazan esos tres montajes por un único directorio propio del modo: `/data/dev`, y `/data`
que contiene el directorio de datos demo `/data/demo`; ver [volúmenes por modo](release-modes-deployment.md#2-one-project-and-one-volume-set-per-mode). Son volúmenes nombrados gestionados
por Docker, compartidos por API, migración y worker, sin sufijos `:z`/`:Z` solo para bind.
Todos los consumidores deben conservar el `ITSM_SELINUX_LEVEL` reservado para la instalación
como se describe arriba. Conserva las etiquetas SELinux en los bind mounts reales del
proyecto; nunca reetiquetes `/proc`, `/sys` ni `/` del host. La cola SQLite debe seguir siendo
local a un único host Docker, compartida entre API y worker, no NFS ni un clúster multi-host.
El worker por defecto tiene un hilo/proceso; escala solo después de probar la cola, el
almacenamiento y la idempotencia de negocio. La configuración del dialecto SQL principal no
es prueba de compatibilidad con el motor vivo; consulta la matriz de validación del backend.

### Propiedad de la instalación y operaciones de sistema controladas

La cuenta inicial es un **Superadmin**, el propietario operativo de la instalación.
**Admin** conserva la administración del negocio pero no tiene autoridad `system.*`; **User**
es de solo lectura por defecto y puede recibir concesiones de negocio específicas. Todos los
transportes usan la misma autorización persistida, incluidos MCP y los agentes delegados. Un
Admin no puede promoverse a sí mismo, conceder permisos reservados ni alterar un objetivo de
mayor privilegio. Los administradores existentes no se promueven de forma silenciosa mediante
migración. Después de actualizar una instalación existente sin propietario activo, el operador
selecciona explícitamente una cuenta humana activa existente:

```bash
docker compose --env-file /dev/null run --rm backend \
  python -m itsm.identity.cli adopt-superadmin --username EXISTING_OWNER_USERNAME
```

Este comando es exclusivo de la instalación y no es una API web; rechaza una instalación que
ya tiene un propietario activo. Conserva al último propietario activo. Consulta
`docs/backend/identity.md` para la administración de cuentas y de máquinas delegadas.

El ejecutor opcional corre **fuera de los contenedores de la aplicación**, bajo una cuenta de
mínimo privilegio elegida por el operador. Acepta únicamente acciones fijas autenticadas:
`deployment.status`, `update.prepare` y `backup.create`. ITSM autoriza y audita cada operación;
la configuración inmutable de acciones del ejecutor elige el ejecutable real. Ni los prompts
del chat ni los argumentos de herramientas HTTP/MCP suministran un comando, ruta, endpoint,
credencial ni URL de release. No se concede a ITSM ni a sus agentes ningún socket de Docker,
montaje del sistema de archivos del host, contenedor privilegiado ni shell arbitrario del host.

Suministra externamente `ITSM_SYSTEM_EXECUTOR_URL`, `ITSM_SYSTEM_EXECUTOR_TOKEN` y,
opcionalmente, `ITSM_SYSTEM_EXECUTOR_TIMEOUT_SECONDS`. El entorno compartido de Compose los
reenvía a los procesos de backend, worker y migración. Para un ejecutor del lado del host, el
gateway existente `host.docker.internal` requiere un listener o proxy autenticado orientado a
Docker, no un listener solo del loopback del host. Usa TLS para transporte que no sea loopback
y restringe el acceso de red. Sin un ejecutor configurado y alcanzable, las operaciones se
informan como **no disponibles**, nunca como respaldo o actualización exitosos.

El ejecutor ejecutable y el contrato exacto de acciones y resultados están documentados en
`docs/backend/system-operations.md`. Los scripts de producción, las herramientas y credenciales
de respaldo de base de datos admitidas, la consistencia coordinada entre SQL y adjuntos, la
retención y el destino, la preparación de una release fijada y confiable y el ensayo de
recuperación son integraciones propias de cada instalación. Preparar una actualización no es
aplicar la actualización ni reiniciar servicios. La pantalla de configuración de la aplicación
edita solo preferencias finitas propias de la aplicación, no variables de entorno en bruto,
secretos ni el despliegue real del host.

### Servicios opcionales

```bash
docker compose --env-file /dev/null --profile redis up -d redis
# Only when ITSM_MEILI_MASTER_KEY is supplied externally:
docker compose --env-file /dev/null --profile search up -d meilisearch
```

Seleccionar solo el perfil de Redis **no** cambia la cola; configura `ITSM_TASK_STORAGE=redis`
y su URL, y luego recrea API y worker de forma intencional. Del mismo modo, la cola en
PostgreSQL usa `ITSM_TASK_STORAGE=postgres` más su propio DSN. Las tablas y el ciclo de vida
del almacenamiento de la cola pertenecen a Huey, separados de las migraciones principales de
Alembic.

Para la búsqueda opcional, configura `ITSM_MEILISEARCH_URL=http://meilisearch:7700` y suministra
la clave externamente antes de recrear API y worker de forma intencional. El consumidor real de
Huey procesa las filas transaccionales del outbox de búsqueda y reintentos acotados. Un
administrador puede inspeccionar `/api/v1/search/status` y solicitar `POST /search/rebuild`
o `/search/sync` usando los guardas existentes de Origin y CSRF. La reconstrucción prepara un
índice temporal y cambia solo tras indexar con éxito; una reconstrucción fallida conserva el
índice anterior. No se necesita ningún motor para la búsqueda SQL, los favoritos ni las vistas
guardadas.

### Topología de monitorización

Cada perfil opcional inicia un servicio; habilita solo aquello que la instalación monitoriza.
Ningún perfil es una dependencia de readiness, y un perfil retirado nunca inventa datos.

| Servicio | Perfil | Puerto | Almacenamiento / notas |
|---|---|---|---|
| Prometheus | `monitoring` | loopback `19090` | `prometheus-data`, retención `ITSM_PROMETHEUS_RETENTION` |
| Blackbox Exporter | `monitoring-blackbox` | interno `9115` | sondas ICMP/HTTP(S)/TCP/DNS; `NET_RAW` para ICMP |
| SNMP Exporter | `monitoring-snmp` | interno `9116` | switches, gateways, routers; auths suministrados externamente |
| Node Exporter | `monitoring-node` | host `9100` | red/PID del host, `/proc`, `/sys`, `/` en solo lectura |
| Alertmanager | `monitoring-alertmanager` | loopback `19093` | `alertmanager-data`; silencios nativos |

```bash
# Tokens come from your external secret manager; do not export them in shared shells.
# ITSM_MONITORING_DISCOVERY_TOKEN: Prometheus -> ITSM discovery/config endpoints
# ITSM_MONITORING_INGEST_TOKEN:    Alertmanager -> ITSM webhook
docker compose --env-file /dev/null \
  --profile monitoring --profile monitoring-blackbox \
  --profile monitoring-snmp --profile monitoring-node \
  --profile monitoring-alertmanager up -d
```

Inicia un subconjunto cuando una instalación solo necesita sondas HTTP, solo switches o solo
métricas del host. `docker compose config` funciona sin los tokens; `up` de un perfil que monta
un secreto de token requiere su variable de entorno. La API y el worker deben llevar los mismos
valores de token para que los endpoints de descubrimiento y métricas y el webhook acepten a
quienes llaman. `monitoring-snmp` requiere además `ITSM_SNMP_AUTHS` (ver más abajo); sin ella, los
exporters fallan al arrancar en lugar de sondear con una credencial vacía.

Las imágenes están fijadas por etiqueta y digest de registro:

| Imagen | Digest |
|---|---|
| `prom/prometheus:v3.14.0` | `sha256:5ce7540c3c00ef4ab0c9d2c995c6a5b9c421f44b4a115d97a2c7af3b1c21cbb0` |
| `prom/blackbox-exporter:v0.29.1` | `sha256:ea1c7aa3ef3f307cd03e85f34abb604478ccb90b567fc690da0cd9776da76b13` |
| `prom/snmp-exporter:v0.30.1` | `sha256:e5fd5e8b43ace6c088fe9bf0b37b7fff0e04380bee352be7ec41b853a4dd5859` |
| `prom/node-exporter:v1.12.1` | `sha256:1b4e4438faca4dd7e001dd445d161a4a2091b0fededa84093b3a8dfeae1f1be0` |
| `prom/alertmanager:v0.34.1` | `sha256:e9733bafb1bdef9b00e25a21f8f99dc26a22224bf16641ad754d1649f4c3357a` |

#### Descubrimiento, reglas y retención

Prometheus descubre los objetivos desde ITSM mediante el descubrimiento HTTP nativo de
servicios, con un endpoint por tipo de comprobación (`icmp`, `http`, `tcp`, `dns`, `snmp`,
`node`, `windows`), refrescando cada 60 segundos. Agregar, cambiar o deshabilitar un activo
cambia la siguiente respuesta de descubrimiento; no hay archivos por dispositivo, listas de
objetivos ni pasos de recarga. Un activo deshabilitado, sin objetivo o no monitorizado está
ausente, lo cual no es lo mismo que fuera de línea.

`deploy/prometheus.yml` también recolecta el endpoint de configuración de ITSM como series:
indicador de habilitado por activo, umbrales y preset de duración mínima.
`deploy/prometheus-rules.yml` es un paquete versionado fijo, instalado una vez en el motor.
Usa duraciones `for` nativas literales para los presets admitidos (0/60/300/900 segundos) y
permanece silencioso para cualquier objetivo que no esté en ese preset; no se prometen
archivos de reglas generados, recargas de Huey ni duraciones arbitrarias. El comportamiento
intermitente usa `changes()` sobre resultados reales de sonda y series descubiertas de
scrape (`up`), no una máquina de estados sintética. La comparación de umbrales usa unidades
normalizadas: latencia en segundos, CPU/memoria/disco en porcentaje, temperatura en Celsius.
La cadencia de scrape es de 60 segundos por job por defecto. La etiqueta `interval_seconds`
por activo se respeta de forma nativa para los presets admitidos (30/60/300/900 segundos)
mediante el objetivo especial de relabel `__scrape_interval__`; un valor ausente o no
admitido conserva los 60 segundos del job, y el timeout explícito de scrape de 10 segundos
queda por debajo del preset más pequeño. La API de objetivos expone el `scrapeInterval` y
`scrapeTimeout` efectivos por objetivo activo (`discoveredLabels.__scrape_interval__` sigue
mostrando el valor por defecto del job), mientras que la serie de configuración
`itsm_monitoring_check_interval_seconds` refleja el mismo ajuste.

Prometheus guarda su propia TSDB en `prometheus-data`; la retención es configurable e
independiente de la retención de inventario y de notificaciones. Un Prometheus externo
mantiene su propio almacenamiento y retención.

#### Modo nativo de Alertmanager

Con `monitoring-alertmanager` habilitado, configura `ITSM_ALERTMANAGER_URL` (y
`ITSM_ALERTMANAGER_TOKEN` solo si tu Alertmanager exige autenticación). Alertmanager es
entonces la única autoridad para agrupación, inhibición y silencios; ITSM crea y expira
silencios a través de su API en lugar de mantener un segundo sistema de supresión. Prometheus
publica webhooks v4 estándar al backend del ITSM, autenticados con
`ITSM_MONITORING_INGEST_TOKEN`; el adaptador acepta un cuerpo acotado, identifica los eventos
por identificador estable de activo y rechaza activos desconocidos. El acuse nunca resuelve
una alerta, y la recuperación nunca cierra un incidente vinculado.

Sin Alertmanager, ITSM sondea las alertas nativas de Prometheus mediante la agenda Huey
existente y aplica la supresión localmente solo para notificaciones. El inventario, la
configuración de monitorización y el estado de los dispositivos siguen siendo utilizables sin
ningún motor y sin Alertmanager. Los datos ausentes del motor se informan como no disponibles
o sin datos, nunca como dispositivos caídos.

No dupliques reglas de agrupación, inhibición y silencio en dos sistemas. El archivo local
`deploy/alertmanager.yml` es deliberadamente mínimo: agrupa por `asset_id`, suprime una
advertencia mientras exista una crítica para el mismo activo y enruta al webhook autenticado
del ITSM. El clustering de Alertmanager está deshabilitado (una sola réplica); los silencios
persisten en `alertmanager-data`.

#### Prometheus externo (instalación única)

Un Prometheus externo usa el mismo contrato de descubrimiento y reglas; ITSM nunca requiere
remote write ni plugins específicos del motor.

1. Instala `deploy/prometheus.yml` como base o fusiona sus jobs en la configuración existente:
   el scrape de configuración `itsm-monitoring`, un job de HTTP SD por tipo de comprobación,
   el autoscrape de los exporters y el job de SNMP en `/snmp`. Reemplaza `backend:8000` por la
   dirección del backend del ITSM alcanzable desde el host de Prometheus, y
   `blackbox-exporter:9115` / `snmp-exporter:9116` por direcciones enrutables desde ese host.
2. Monta el token de descubrimiento donde apunta `credentials_file` y configura el mismo valor
   en `ITSM_MONITORING_DISCOVERY_TOKEN` para la API. No incrustes el token en el YAML.
3. Instala `deploy/prometheus-rules.yml` en `rule_files` una vez y recarga la configuración.
   Los cambios posteriores de activos, umbrales y presets se leen de las series del ITSM; este
   archivo no cambia por dispositivo.
4. Apunta `ITSM_PROMETHEUS_URL` a la API del motor, con `ITSM_PROMETHEUS_TOKEN` cuando la
   API esté autenticada. Mantén la API del motor privada; no expongas los endpoints de TSDB
   públicamente y usa TLS en tu proxy inverso.
5. Si un exporter para un tipo de comprobación corre en otro lugar, configura el
   `exporter_address` de esa instalación en ITSM para que el descubrimiento sobrescriba la
   dirección de scrape mientras el objetivo del activo sigue siendo el destino sondeado.

#### Exporters en los hosts monitorizados

- Servidores Linux: ejecuta `node_exporter` de forma nativa bajo el gestor de servicios del
  host, expón `:9100` solo al motor de Prometheus y registra el activo con `checkType: node`
  y objetivo `host:9100`. El perfil `monitoring-node` es para el propio host de Docker.
- Servidores Windows: instala `windows_exporter` como servicio nativo de Windows desde su MSI,
  expón `:9182` solo al motor y registra `checkType: windows` con objetivo `host:9182`. Nunca
  instales un servicio node exporter de Linux en Windows.
- DNS: registra el activo con `checkType: dns` y la dirección del resolutor (`host:53`) como
  objetivo. El nombre y tipo de consulta están fijados en el módulo compartido `dns_udp` de
  `deploy/blackbox.yml` (`example.com` tipo A por defecto); reemplázalo una vez para zonas
  internas. No es configurable por dispositivo y nunca crea un archivo por activo.
- SNMP: un único SNMP exporter compartido atiende a muchos dispositivos. Las credenciales
  existen solo en su documento `auths`, nunca en ITSM, en respuestas de la API, en logs ni en
  Git; ITSM guarda solo el nombre de la referencia de autenticación por activo. Suministra el
  documento a través del entorno externo como `ITSM_SNMP_AUTHS`; Compose lo proyecta como
  archivo de secreto y lo pasa al exporter como segundo `--config.file`. El `deploy/snmp.yml`
  confirmado en el repositorio contiene solo módulos y no incluye auths ni comunidad por
  defecto, así que el perfil no puede arrancar sin el valor del entorno y nunca sondea con una
  credencial vacía o pública. Ejemplo de forma del documento, con valores suministrados
  externamente y nunca confirmados en Git:

  ```yaml
  auths:
    switch-core:
      version: 2
      community: <community>
  ```

  Usa SNMPv2c o v3 USM según la capacidad de cada dispositivo. Nunca una comunidad pública
  compartida por defecto. El job fijo de SNMP selecciona `/snmp`, el módulo proveniente de ITSM
  (`if_mib` por defecto) y la referencia de autenticación solo cuando está configurada; la
  disponibilidad es `up`, y una caída del exporter queda excluida de la evaluación de
  dispositivos caídos.

No se requiere ni se admite un archivo manual de Prometheus por dispositivo. Los hosts que no
pueden ejecutar un exporter se configuran con comprobaciones ICMP/TCP/HTTP o se dejan sin
monitorizar.

#### Entrega de notificaciones

La entrega usa el adaptador interno de Apprise y el worker Huey existente. Los canales se
configuran en ITSM; cada canal externo guarda una referencia de secreto, nunca la URL ni el
token. `ITSM_MONITORING_SECRETS` asocia esas referencias con las URLs completas de Apprise
suministradas externamente:

```text
{"<channel-reference>":"<full-apprise-url-or-token>"}
```

El canal interno no necesita credencial externa. SMTP y Telegram son canales externos; otros
tipos de Apprise son opcionales. Las respuestas solo exponen si una referencia está
configurada, y los logs y errores redactan URLs, contraseñas y tokens. Prueba los canales de
forma deliberada; no envíes notificaciones externas reales sin autorización.

La entrega es durable: un outbox en SQL indexado por ciclo de alerta, regla, destinatario,
canal y tramo de escalado alimenta la cola por id estable de SQL, así los reintentos y los
workers en competencia no duplican una notificación. Solo los fallos confirmados se reintentan;
una entrega ambigua queda marcada como incierta en lugar de informarse como exitosa o
duplicarse. Los registros entregados y fallidos, las entradas de la bandeja y el estado de
lectura siguen `ITSM_NOTIFICATION_RETENTION_DAYS`. No se guardan muestras de métricas en SQL, y
no hay un segundo planificador: la entrega y el sondeo reutilizan la agenda existente del worker.

#### Diagnóstico de monitorización

- Prometheus en `http://127.0.0.1:19090` muestra los errores de descubrimiento en su página
  Targets; un 401/403 significa que el token de descubrimiento difiere entre el motor y la API,
  no una caída de la monitorización. Una respuesta vacía de HTTP SD es correcta cuando ningún
  activo de ese tipo de comprobación está habilitado.
- `probe_success` impulsa ICMP/HTTP/TCP/DNS; `up` impulsa node/windows/SNMP. Una serie faltante
  es `no_data`, nunca `down`; los errores del motor y las muestras ausentes no se convierten en
  eventos de dispositivo caído. Las reglas de dispositivo SNMP caído dependen del autoscrape del
  exporter, así que una caída del exporter no se informa como todos los switches caídos.
- Las alertas se disparan solo para el preset de duración propio del objetivo (0/60/300/900
  segundos); la etiqueta `preset` muestra qué regla coincidió. Un activo deshabilitado o sin
  umbral no tiene serie de configuración, así que las reglas de umbral permanecen silenciosas.
- El modo nativo de Alertmanager se selecciona únicamente con `ITSM_ALERTMANAGER_URL`. Los
  silencios existen entonces solo en Alertmanager (`/api/v2/silences`, UI en loopback `19093`), y
  ITSM no mantiene una supresión local duplicada. Sin la URL, las alertas se sondean mediante la
  agenda Huey existente y la supresión se aplica solo a las notificaciones.
- El fallo de conexión con el motor se manifiesta como estado de monitorización `unavailable`; el
  inventario, las fichas de activos y la configuración siguen siendo utilizables. No registres
  caídas a partir de tus propias consultas fallidas. Los períodos son UTC y acotados
  (24h/7d/30d, como máximo 300 puntos por serie); la procedencia es el motor más el período
  consultado.

Meilisearch opcional está implementado detrás del adaptador interno de búsqueda; SQL sigue
siendo la fuente de verdad y el respaldo ante caídas. Casbin evalúa las políticas desde el
almacenamiento SQL propio. Apprise, WeasyPrint, Pydantic AI y FastMCP usan sus adaptadores
estrechos existentes y los servicios autorizados canónicos. No se introduce ninguna
implementación de negocio separada.

### Reportes, códigos QR y etiquetas

Los reportes usan el worker Huey existente y el volumen compartido `attachment-data`. Aplica la
migración explícita antes de iniciar la API y el worker; nunca migres en cada arranque de proceso.
Los metadatos de documentos generados viven en SQL; los bytes de PDF/CSV/Excel usan claves de blob
opacas, no columnas del activo ni un directorio estático público. La API y el worker deben usar
configuración de reportes idéntica y el mismo volumen de blobs.

| Variable | Por defecto | Propósito |
| --- | --- | --- |
| `ITSM_REPORT_BASE_URL` | `http://localhost:18080` | Origen y ruta de despliegue del frontend codificados en los enlaces QR de reportes con UUID permanente; sin credenciales, query ni fragmento. |
| `ITSM_REPORT_RETENTION_DAYS` | `7` | Retención de documentos generados, de 1 a 3650 días. |
| `ITSM_REPORT_MAX_ASSETS` | `1000` | Selección máxima de activos coincidentes por trabajo, de 1 a 10000. |
| `ITSM_REPORT_MAX_DOCUMENT_BYTES` | `52428800` | Bytes máximos de salida por documento, como máximo 200 MiB. |
| `ITSM_REPORT_RENDER_TIMEOUT_SECONDS` | `120` | Timeout aislado de renderizado PDF, de 1 a 600 segundos. |
| `ITSM_REPORT_RENDER_MEMORY_MB` | `512` | Límite de espacio de direcciones del proceso hijo de PDF, de 64 a 4096 MiB. |

La imagen instala las bibliotecas Pango/HarfBuzz y las fuentes DejaVu necesarias. El renderizado
no necesita ningún servidor adicional y acepta solo plantillas estructuradas de lista blanca y
recursos propiedad de la aplicación; nunca expongas un directorio del sistema de archivos ni un
obtenedor arbitrario de recursos para hacer aparecer una imagen. Configura la identidad visual a
través de los ajustes autorizados de reportes en lugar de cambiar el HTML generado. Si falta la
identidad visual se usan plantillas genéricas. Mantén estable la URL base de reportes: los códigos
QR impresos antes conservan la URL codificada. Cambiar el sitio, la categoría o el código rápido
de un activo no cambia su ruta de reporte por UUID.

Los reportes privados requieren autoridad vigente `assets.view` y propiedad del documento generado
(o autoridad de administrador). El uso compartido público es aparte: solo la autoridad explícita
`reports.share` puede emitir o revocar enlaces con campos limitados y vencimiento. Un UUID de
activo o un código QR no es una concesión de permiso. La salida pública excluye detalles
técnicos, direcciones IP, personas, costos y adjuntos. No publiques una URL de descarga privada.

### Conversación y herramientas MCP seleccionadas

Suministra `ITSM_AGENT_MODEL` y la credencial del proveedor elegido a través del entorno externo,
y luego recrea el backend de forma intencional. Sin un modelo configurado, `/api/v1/agent/chat`
devuelve un 503 veraz, no un éxito conversacional falso. Listado, detalle, CRUD y búsqueda siguen
siendo utilizables. Las operaciones simples son directas; el worker Huey no es obligatorio para
cada llamada de herramienta. El agente no recibe shell, SQL en bruto, obtención arbitraria de URL
ni herramientas del sistema operativo.


#### OpenCode y Hermes en bare-metal

Ejecuta OpenCode y Hermes en el host, fuera de Compose. La configuración compartida del servicio
backend asigna `host.docker.internal` al `host-gateway` de Docker; registra una URL de motor como
`http://host.docker.internal:<engine-port>` en Configuración → IA. Usa el puerto realmente
configurado del motor, nunca un valor por defecto adivinado. OpenCode usa su API nativa HTTP/SSE y
credenciales Basic del servidor. Hermes 0.22.5 usa JSON-RPC/WebSocket nativo en `/api/ws`; su
proveedor integrado de inicio de sesión por contraseña emite la sesión y el ticket del dashboard.
No es un servidor `/v1` de OpenAI, y las cabeceras HTTP Basic no son su protocolo de inicio de
sesión. Suministra las credenciales del motor a través del mecanismo existente de referencia
externa de secretos, nunca en URLs ni en archivos de skills.

En Linux, un proceso del host vinculado solo a `127.0.0.1` no es alcanzable a través del gateway
del bridge. Vincula cada motor a la dirección del host orientada a Docker, o usa un proxy
autenticado del lado del host en esa dirección. Si el motor debe vincularse a todas las
interfaces, restringe su puerto a la red de contenedores prevista con el firewall del host; no lo
expongas públicamente. Este repositorio no cambia listeners del host, reglas de firewall ni la
configuración del daemon de Docker de forma automática. Los motores bare-metal remotos usan su
nombre DNS enrutable real en lugar del alias local del host.

Para la conexión MCP inversa, el motor del host debe alcanzar la URL MCP publicada del backend, no
un nombre de servicio exclusivo de Compose. La publicación por defecto en el host es
`http://127.0.0.1:18000/api/v1/mcp`; ten en cuenta cualquier puerto de API configurado y usa su
bearer de máquina de mínimo privilegio separado. Las credenciales de la API del motor y las
credenciales MCP no son intercambiables. Un host remoto necesita una URL MCP enrutable y protegida
de forma explícita.

Instala skills e inspecciona perfiles usando el instalador auxiliar en el host bare-metal elegido.
No montes directorios home del host, perfiles de motor ni el socket de Docker dentro del
contenedor ITSM. La alcanzabilidad de red no establece la seguridad de un perfil confiable; los
bloqueos de aceptación de `docs/backend/agent-integrations.md` siguen aplicándose. Para deshacer el
cambio de alias, quita `extra_hosts` de `x-backend` y recrea solo los servicios afectados durante
una ventana de mantenimiento autorizada.

Para un perfil Hermes dedicado de desarrollo local, usa el ejecutable fijado del workspace con el
launcher propiedad del host:

El conector apunta a Hermes 0.22.5 en el commit upstream
`bf0203a794a07aac3ff764972ab9087baa4e4f4e`. Su entorno dedicado necesita el extra `mcp`
del lockfile: una instalación básica puede iniciar `serve` sin exponer herramientas del ITSM.
Instala desde el código fijado y revisa los cambios de dependencias antes de aplicarlos.
No actualices una instalación global ni reemplaces el perfil de un operador de forma implícita.

```bash
# Supply ITSM_HERMES_MODEL, HERMES_DASHBOARD_BASIC_AUTH_PASSWORD and an independent
# ITSM_HERMES_INSPECTOR_TOKEN (at least 32 characters) in the process environment.
# Supply ITSM_HERMES_PROVIDER_URL/KEY and optional ITSM_HERMES_HEADERS_JSON, or
# explicitly opt into --omp-config with the operator-authorized provider config.
backend/.venv/bin/python scripts/itsm-ai-dev.py \
  --binary /absolute/path/to/pinned/hermes \
  --home /absolute/path/to/dedicated/profiles/itsm
```

El launcher se vincula al loopback, usa `admin` por defecto pero nunca suministra una contraseña,
conserva la configuración existente y escribe referencias de entorno de proveedor y cabeceras, no
valores de credenciales. Su endpoint `/profile-proof`, autenticado de forma independiente,
atestigua solo su propio proceso hijo vivo, el digest exacto de la configuración, el home y el
endpoint. La instalación puede reiniciar solo ese proceso hijo para cargar la nueva configuración
restringida. Configura juntos `ITSM_HERMES_INSPECTOR_URL` y `ITSM_HERMES_INSPECTOR_TOKEN` de la
API; el token del inspector debe ser distinto de las credenciales del dashboard, del proveedor y
de MCP. La contraseña de desarrollo debe cambiarse antes de producción, con un listener y una
configuración de autenticación protegidos. Este script no instala Hermes ni modifica perfiles home
existentes.

Para cambiar en caliente entre perfiles de Hermes, registra cada home dedicado y cada puerto de
loopback distinto al arrancar el launcher usando
`--additional-profile /absolute/path/to/profiles/itsm-review=19122` de forma repetible. Registra
cada uno como una instancia ITSM separada y verifica ambos. Las solicitudes de prueba pueden
seleccionar solo un par exacto de home y endpoint de esa lista fija de arranque; no pueden crear
perfiles ni elegir un binario, puerto o comando.

Admin y Superadmin pueden seleccionar instancias verificadas de Hermes/OpenCode. Los usuarios
ordinarios pueden seleccionar solo Pydantic AI, ejecutado en contenedores reales etiquetados por
usuario a través del broker fijo del host autenticado de forma separada. No hay respaldo en el
mismo proceso ni socket de Docker en la API. Consulta `docs/backend/ai-runtime-isolation.md` para
el despliegue del broker y la configuración del sandbox. Cambiar un perfil de chat selecciona otra
instancia configurada y autorizada, reinicia su sesión nativa y conserva la transcripción y el
borrador del ITSM; nunca cambia en el lugar el perfil activo de un motor compartido.

Referencia de Docker: [Compose networking and host gateway](https://docs.docker.com/compose/how-tos/networking/).

### Preparación de recordatorios de mantenimiento

Mantenimiento agrega planes preventivos persistidos, intervenciones e incidentes técnicos. Aplica las
migraciones explícitamente antes de iniciar API y worker. Las pantallas originales de
mantenimiento en Vue usan estas APIs. La monitorización vincula sus eventos con incidentes,
pero el acuse, la recuperación y el cierre siguen siendo distintos: el acuse nunca resuelve, la
recuperación nunca cierra un incidente automáticamente, y el cierre sigue siendo una decisión
humana explícita con una sugerencia de cierre asistido.

El consumidor Huey existente registra `maintenance_due_scan` cada cinco minutos. Mantén un solo
planificador periódico por cola. Cada barrido lee los planes activos y no archivados que vencen en
los próximos 30 días, incluidos los vencidos, y prepara un recordatorio SQL por plan, fecha de
vencimiento y etapa (`upcoming` o `overdue`). La unicidad durable hace idempotentes los reintentos
y los barridos en competencia. Los ajustes de reintentos de la cola siguen siendo
`ITSM_TASK_RETRIES` e `ITSM_TASK_RETRY_DELAY_SECONDS`; no se necesita ningún servicio ni secreto
adicional.

Observa el evento estructurado del worker `maintenance.reminders_prepared` y sus contadores
`created` y `scanned`. La preparación nunca completa un plan, resuelve un incidente ni envía
correo o Telegram. La entrega es propiedad del servicio de notificaciones descrito
arriba; el barrido de mantenimiento solo prepara filas durables de recordatorio. Consulta
`docs/backend/maintenance.md`, `docs/backend/interventions.md` y `docs/backend/agent-tools.md`
para los contratos de operación y permisos.

## Actualización y reversión

1. Registra las tres revisiones de Git, las versiones de los componentes y los digests de imagen. Respalda la base principal y la cola antes de cambios de esquema o de bibliotecas.
2. Revisa las notas de release y de seguridad, actualiza las dependencias fijadas y el digest de la imagen base relacionada, reconstruye y ejecuta las pruebas de adaptadores, API, worker y migración en estado aislado.
3. Prueba las migraciones contra los motores SQL disponibles; no anuncies motores no probados como verificados. Aplica una ventana de mantenimiento cuando los cambios de esquema no sean retrocompatibles.
4. Ejecuta la compuerta de preparación (`initialize`, que ejecuta `python -m itsm.deployment prepare`: la actualización protegida en `prod`, migraciones en los demás modos) o el recurso manual `migrate` del perfil `tools`, y luego recrea API y worker juntos con la imagen probada. Comprueba readiness y la tarea y el resultado de demo.
5. Conserva la imagen y el lock anteriores. Revertir la imagen no deshace una migración irreversible; recupera el respaldo si la migración no puede revertirse de forma segura. Nunca ejecutes `downgrade` ni restaures sobre datos vivos sin una decisión explícita de recuperación.

Las imágenes usan etiquetas de versión exactas y digests de registro, no `latest`. Las dependencias
están fijadas por el lock del backend y el package lock del frontend. No se requiere actualizador
automático, orquestador, pipeline de release ni microservicios de negocio.

## Respaldos y recuperación

- PostgreSQL: ejecuta `pg_dump -Fc` con tus credenciales aprobadas hacia un destino protegido. Verifica `pg_restore --list` y luego ensaya la restauración en una base nueva y ejecuta migraciones y readiness. Los respaldos de bases de datos externas pertenecen al operador externo; los volúmenes locales de Docker no son respaldos.
- MariaDB: usa `mariadb-dump --single-transaction` para tablas transaccionales con credenciales externas aprobadas y luego importa en una base nueva con `mariadb`. Coordina los cambios de esquema y las subidas de archivos con la instantánea SQL. Ejecuta migraciones, readiness y comprobaciones autenticadas después de restaurar.
- SQL Server: usa el procedimiento nativo de respaldo y restauración completa del operador de la base, incluidas las claves y certificados de cifrado donde estén configurados. Este entorno no ejecutó la instalación ni la restauración de SQL Server; no infieras compatibilidad desde la URL de SQLAlchemy ni desde los resultados de otro motor.
- Base principal SQLite: usa la API de respaldo en línea de SQLite o `.backup`, no una copia informal de una base WAL viva. Para un respaldo de archivo en frío, detén primero la API y el worker propios e incluye un estado consistente de base y WAL.
- Huey SQLite: pausa el encolado de la API y el worker de este workspace, respalda todo el volumen de la cola de forma consistente; restaurarlo puede repetir trabajos. Los trabajos de importación usan recibos durables por fila en el SQL principal para evitar repetir filas exitosas. No restaures el estado de la cola de forma independiente de los datos de negocio relacionados sin considerar efectos duplicados.
- Adjuntos: respalda `attachment-data` junto con una instantánea consistente del SQL principal. SQL guarda metadatos y claves opacas de blobs, no los bytes de los archivos. Restaurar solo SQL o solo el volumen queda incompleto. Coordina subidas y bajas durante el respaldo y ensaya descargas autenticadas después de restaurar en estado aislado. No borres blobs desconocidos como operación de limpieza improvisada; las escrituras interrumpidas pueden dejar objetos sin referencia que requieren una reconciliación autorizada de forma explícita.
- Redis opcional: persiste AOF y respalda de forma consistente usando los procedimientos de Redis. Prometheus: respalda en frío su volumen propio `prometheus-data` (detén el servicio o toma una instantánea del sistema de archivos) o usa su procedimiento admitido de TSDB; la retención no es un respaldo. El estado de Alertmanager (silencios y log de notificaciones) vive en `alertmanager-data`; respáldalo por separado. El outbox de notificaciones, la bandeja y el historial de entrega viven en el SQL principal y siguen el procedimiento de respaldo SQL. Restaurar métricas o el estado de Alertmanager es independiente de la disponibilidad del inventario.
- Respalda por separado los repositorios raíz, frontend y backend, los ajustes externos y los volúmenes nombrados. Nunca confirmes en Git archivos de respaldo ni secretos.
- Los presets de apariencia, los metadatos de logotipo, la apariencia publicada y los ajustes de integración están en el SQL principal; los bytes de logotipos y documentos están en el almacén opaco de adjuntos. Restaura ambos de forma consistente. Reaplica los orígenes y URLs base externos, la política de cookies, las credenciales de proveedores, las credenciales de cliente, las referencias y tokens de notificación y las credenciales de motores a través del mecanismo aprobado de secretos. Los archivos y el SQL no recuperan automáticamente secretos gestionados externamente. No los rotes ni los divulgues durante un ensayo.
- Meilisearch es estado derivado: después de restaurar SQL, archivos y la autorización vigente, solicita la reconstrucción de búsqueda protegida y observa su resultado terminal. El intercambio de índices temporales preserva el índice anterior en caso de fallo; el respaldo de SQL sigue siendo utilizable. Su volumen es opcional para la recuperación, no el respaldo canónico del inventario.
- Ensaya la recuperación en un proyecto Compose y volúmenes nuevos y aislados antes de reemplazar producción. Estas instrucciones no ejecutan respaldos ni restauraciones contra servicios existentes del servidor.

## Comprobaciones e inspección

```bash
# Renders this installation's project: RELEASE_MODE and COMPOSE_FILE are already exported.
docker compose --env-file /dev/null config --quiet
docker compose --env-file /dev/null --profile monitoring config --quiet
# Prometheus config/rules; point the token mount at the same external file the engine uses.
docker run --rm --security-opt label=disable \
  -v "$PWD/deploy/prometheus.yml:/etc/prometheus/prometheus.yml:ro" \
  -v "$PWD/deploy/prometheus-rules.yml:/etc/prometheus/rules/itsm-rules.yml:ro" \
  -v /path/to/discovery-token:/run/secrets/monitoring_discovery_token:ro \
  --entrypoint promtool \
  prom/prometheus:v3.14.0@sha256:5ce7540c3c00ef4ab0c9d2c995c6a5b9c421f44b4a115d97a2c7af3b1c21cbb0 \
  check config /etc/prometheus/prometheus.yml
docker run --rm --security-opt label=disable \
  -v "$PWD/deploy/prometheus-rules.yml:/rules.yml:ro" \
  --entrypoint promtool \
  prom/prometheus:v3.14.0@sha256:5ce7540c3c00ef4ab0c9d2c995c6a5b9c421f44b4a115d97a2c7af3b1c21cbb0 \
  check rules /rules.yml
docker run --rm --security-opt label=disable \
  -v "$PWD/deploy/blackbox.yml:/etc/blackbox_exporter/blackbox.yml:ro" \
  prom/blackbox-exporter:v0.29.1@sha256:ea1c7aa3ef3f307cd03e85f34abb604478ccb90b567fc690da0cd9776da76b13 \
  --config.check --config.file=/etc/blackbox_exporter/blackbox.yml
docker run --rm --security-opt label=disable \
  -v "$PWD/deploy/snmp.yml:/etc/snmp_exporter/snmp.yml:ro" \
  -v /path/to/projected-auths.yml:/run/secrets/snmp_auths.yml:ro \
  prom/snmp-exporter:v0.30.1@sha256:e5fd5e8b43ace6c088fe9bf0b37b7fff0e04380bee352be7ec41b853a4dd5859 \
  --config.file=/etc/snmp_exporter/snmp.yml \
  --config.file=/run/secrets/snmp_auths.yml --dry-run
# The auths file above is the content of ITSM_SNMP_AUTHS, materialized only for this
# disposable check; alternatively run the same --dry-run inside the running profile so
# the secret is already projected at /run/secrets/snmp_auths.yml.
docker run --rm --security-opt label=disable \
  -v "$PWD/deploy/alertmanager.yml:/etc/alertmanager/alertmanager.yml:ro" \
  -v /path/to/ingest-token:/run/secrets/monitoring_ingest_token:ro \
  --entrypoint amtool \
  prom/alertmanager:v0.34.1@sha256:e9733bafb1bdef9b00e25a21f8f99dc26a22224bf16641ad754d1649f4c3357a \
  check-config /etc/alertmanager/alertmanager.yml
# Discovery and configuration metrics use the bearer the engine mounts; never print it.
curl -fsS -H "Authorization: Bearer $ITSM_MONITORING_DISCOVERY_TOKEN" \
  "http://127.0.0.1:18000/api/v1/monitoring/discovery?check_type=http"
curl -fsS -H "Authorization: Bearer $ITSM_MONITORING_DISCOVERY_TOKEN" \
  http://127.0.0.1:18000/api/v1/monitoring/prometheus-metrics
# Effective target schedule; discoveredLabels keep the per-job defaults.
curl -fsS http://127.0.0.1:19090/api/v1/targets | python3 -c \
  'import json,sys; [print(t["labels"].get("asset_id"), t["scrapeInterval"], t["scrapeTimeout"]) for t in json.load(sys.stdin)["data"]["activeTargets"]]'
curl -fsS http://127.0.0.1:19090/-/ready
curl -fsS http://127.0.0.1:19093/-/ready
curl --fail http://127.0.0.1:18000/api/v1/health/live
curl --fail http://127.0.0.1:18000/api/v1/health/ready
docker compose --env-file /dev/null ps
docker compose --env-file /dev/null logs --tail=100 backend worker
npm --prefix frontend run check
# Opt-in cold-start regression: isolated PostgreSQL projects, both startup orders.
# Creates volumes, stops its containers, does not delete volumes or touch other services.
python3 tests/worker_cold_start.py
# With an isolated, migrated stack and worker running:
# Requires an isolated installed account via ITSM_TEST_USERNAME / ITSM_TEST_PASSWORD.
ITSM_TEST_API_URL=http://127.0.0.1:18000 python3 tests/infrastructure.py
# Isolated SQLite inventory smoke: creates uniquely named test assets, never deletes.
# Optional ITSM_TEST_EXPECT_AGENT_UNAVAILABLE=1 checks the no-model 503 path.
ITSM_TEST_API_URL=http://127.0.0.1:18080 python3 tests/inventory.py
```

Los comandos de pruebas del backend están en la [guía de desarrollo](backend/development.md);
El envío de tareas de demo es solo para desarrollo, no un servicio público
de ejecución de tareas sin autenticación. Vincula a loopback y exige un límite de autorización
adecuado antes de exponer datos o acciones de negocio reales. Sin migración automática de esquema
en las comprobaciones de salud y sin valores sensibles de URL o secretos en logs ni errores.

Para detener solo este stack, usa su proyecto Compose explícito y `down` **sin `--volumes`**. Borrar
volúmenes persistentes, cambiar servicios existentes y desplegar en producción requieren
autorización aparte.

## Almacenamiento de credenciales de proveedores de IA

La conversación unificada usa la API existente de sesiones de agente y la propiedad por persona. La
administración global de proveedores y motores sigue restringida al Superadmin de la instalación.
Agregar un proveedor personal compatible con OpenAI requiere una concesión explícita
`agents.providers.personal`; el User por defecto no la recibe.

Suministra `ITSM_AI_CREDENTIAL_KEY` externamente al proceso de la API (y a los mismos contenedores
de aplicación a través del entorno existente de Compose). Debe ser una clave Fernet válida para las
credenciales cifradas de proveedores. La aplicación no genera ni almacena la clave de instalación.
Mantenla separada de los respaldos SQL, consérvala para la recuperación y usa la misma clave después
de un reinicio. Perderla hace ilegibles las credenciales cifradas previamente; cambiarla no es un
procedimiento de rotación de credenciales. Nunca la pongas en un archivo confirmado en Git, en el
almacenamiento del navegador, en logs ni en una fila de base de datos. Sin la clave, las escrituras
de credenciales de proveedor se informan como no disponibles en lugar de guardar texto plano.

Las listas de modelos de los proveedores se configuran de forma explícita; no son prueba de
disponibilidad del modelo ni de inferencia exitosa. Un motor externo instalado sigue no disponible
para conversar hasta que el perfil activo seleccionado, las herramientas restringidas, la identidad
MCP del ITSM y las skills pasen la verificación. Un endpoint configurado, un ejecutable en PATH o
una respuesta sintética de prueba por sí solos no son esa prueba. OpenCode y Hermes siguen siendo
servicios externos del host, no nuevos servicios de aplicación de Compose.

## SDK de extensiones nativas

El SDK v2 admite paquetes declarativos y extensiones ejecutables. Python ejecutable usa un proceso restringido y las interfaces usan renderizado aislado. Una persona responsable debe revisar el digest exacto, los permisos, el plan de migración y la validación antes de aprobar la instalación. Los agentes pueden enviar candidatos, no aprobarlos.

Los puntos de entrada para desarrolladores son `docs/backend/extensions-sdk.md` (inicio rápido
humano, generador y validador offline), `docs/backend/extensions-host.md` (contrato del host y del
ciclo de vida) y `docs/frontend/extensions-sdk.md` (slots y componentes nativos de Vue). Chat y MCP
exponen `extension_sdk_index` y referencias acotadas `extension_sdk_reference`; el acceso
arbitrario a shell, sistema de archivos y SQL no forma parte de estas herramientas.

### Broker de validación fijo

Los contenedores de aplicación no tienen, deliberadamente, socket de Docker ni CLI de Docker.
Ejecuta el broker fijo de validación fuera de ellos, bajo una cuenta elegida por el operador que
pueda iniciar la imagen de validación dedicada. Suministra un token aleatorio separado de al menos
32 caracteres ASCII imprimibles a través de `ITSM_EXTENSION_VALIDATOR_BROKER_TOKEN`; nunca lo pases
como argumento de CLI ni lo incluyas en un paquete de extensión. Ejecuta desde `backend/`:

```bash
.venv/bin/python -m itsm.extensions serve-validator \
  --listen 127.0.0.1 --port 8766 --image itsm-extension-validator:1
```

La imagen debe estar ya construida; consulta la guía del SDK del backend para sus requisitos
previos de construcción offline fijados.
Este servicio acepta solo paquetes acotados y autenticados en un endpoint fijo. Es dueño de la
imagen, del comando y de las restricciones de recursos; ni el código candidato ni el chat los
eligen. Solo los bytes del paquete y el runtime del SDK entran al contenedor de validación sin red,
sin montajes de la aplicación ni credenciales.

Configura la aplicación con los valores emparejados `ITSM_EXTENSION_VALIDATOR_URL` (solo la URL
base del servidor) y `ITSM_EXTENSION_VALIDATOR_TOKEN` (el mismo secreto dedicado del broker).
`ITSM_EXTENSION_VALIDATION_TIMEOUT_SECONDS` vale 60 por defecto.
Para un broker del host alcanzado desde Compose, el gateway existente `host.docker.internal`
necesita un listener restringido orientado a Docker o un proxy TLS autenticado; el loopback del
host por sí solo no es alcanzable desde el contenedor de la aplicación. Usa TLS fuera del loopback
y restringe el acceso de red. Compose no realiza ningún despliegue automático del broker ni
exposición de red. Una validación ausente o inalcanzable se informa como no disponible, nunca se
aprueba.

El almacenamiento de workspaces en Compose usa por defecto `/data/app/extension-workspaces` en el
volumen de aplicación existente. Las versiones instaladas, los registros de extensión, las
revisiones de esquema y el estado de la agenda viven en la base de datos SQL canónica. Ejecuta el
comando explícito de migración antes del readiness. Deshabilitar una extensión bloquea sus
operaciones, retira las contribuciones nativas y detiene el despacho programado sin borrar datos.
Las migraciones de actualización y la reversión condicionada por compatibilidad son acciones
explícitas del ciclo de vida humano; ni el arranque de la API ni el del worker migran datos de
extensiones.
