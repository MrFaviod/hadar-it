# Operación avanzada de la instalación

Guía breve para quien administra el servidor: instalación, respaldos, módulos externos y operaciones del Superadmin. Para el uso diario de inventario, incidentes y reportes, la [ayuda integrada](../frontend/docs/user-help.md) alcanza; este documento no la repite. Los detalles de infraestructura, variables y verificaciones ya ejecutadas viven en [operations.md](operations.md), que es la fuente de verdad operativa.

## Antes de empezar

### Tres repositorios independientes

El producto son tres repositorios Git distintos, no un monorepo ni submódulos. La raíz ignora `frontend/` y `backend/`: no ve sus commits, cambios ni respaldos.

| Ruta | Contenido | Verificación |
|---|---|---|
| `asset/` (raíz) | Documentación de coordinación, `compose.yaml`, versión de producto | `git status --short --branch` |
| `frontend/` | Interfaz, pruebas y ayuda en español | `git -C frontend status --short --branch` |
| `backend/` | API, persistencia, worker y CLI de identidad | `git -C backend status --short --branch` |

Revisa cada repositorio donde vas a trabajar antes de editar y antes de confirmar cambios. Las versiones de los componentes evolucionan por separado de `VERSION`.

### Identidad del producto: nombre provisional

El nombre definitivo sigue pendiente y no se reemplaza por decisión unilateral. El nombre visible se configura en **Configuración → Apariencia** (`#/configuracion/apariencia`), campo **Nombre visible de la aplicación** (`appName` de la apariencia activa): el shell y el título del documento lo toman de ahí. No renombres paquetes, identificadores, rutas de almacenamiento ni la base de datos para cambiar la presentación; el nombre heredado es provisional, no una decisión de branding. Ver [phase10-appearance.md](../backend/docs/phase10-appearance.md).

## Instalación

1. **Nivel SELinux por instalación.** Reserva categorías MCS propias y expórtalas como `ITSM_SELINUX_LEVEL` antes de cualquier comando de Compose; cada instalación usa un nivel distinto. Ver [operations.md](operations.md#reserve-the-shared-volume-selinux-domain).
2. **Secretos fuera de archivos.** No hay `.env` ni `.env.example`: exporta las variables desde el entorno o tu gestor de secretos aprobado y ejecuta Compose con `--env-file /dev/null`. Nunca pongas credenciales en Git, en capturas de terminal ni en documentación.
3. **Migración explícita antes de la API y del worker.** La migración nunca corre al arrancar cada proceso. Desde la raíz:

   ```bash
   docker compose --env-file /dev/null run --rm migrate
   ```

   El servicio `migrate` ejecuta `alembic upgrade head` ([compose.yaml](../compose.yaml)). No uses `downgrade` ni restaures sobre datos vivos sin una decisión de recuperación explícita.
4. **Primer propietario explícito.** Ejecuta el siguiente comando desde `backend/`, con las variables de esa instalación ya configuradas. `bootstrap-superadmin` crea la cuenta inicial y se rechaza si ya existe cualquier identidad humana; no hay cuenta fija ni contraseña por defecto. La contraseña llega por `getpass` o `ITSM_BOOTSTRAP_PASSWORD`, nunca como argumento.

   ```bash
   .venv/bin/python -m itsm.identity.cli bootstrap-superadmin --username TU_USUARIO --name 'Tu nombre'
   ```

   En una instalación existente sin propietario activo, la reclamación es `adopt-superadmin --username CUENTA_EXISTENTE`. Ver [identity.md](../backend/docs/identity.md#installation).
5. **Origen y cookies.** `ITSM_AUTH_ORIGIN` debe coincidir exactamente con el origen del navegador; las cookies son `HttpOnly`, `SameSite=Strict` y `Secure` salvo el `false` explícito para HTTP local aislado. Toda mutación autenticada por cookie exige Origin y token CSRF; los clientes con bearer no llevan CSRF, pero conservan los mismos permisos.

Roles: **Superadmin** ejerce además los códigos `system.*`; **Admin** administra el negocio sin `system.*`; **User** es de solo lectura por defecto. La administración nunca concede por encima de los permisos efectivos de quien la ejecuta, y se protegen el último Superadmin activo y los cambios de rol propio.

## Modo demostración

La demo es una instalación ficticia y separada, nunca un seed de producción. El inicializador exige un directorio **nuevo** cuyo padre ya exista: rechaza cualquier directorio existente, incluido uno vacío, y no ofrece sobrescribir ni reiniciar. Solo puede usar su propia base `demo.db`, ignora `ITSM_DATABASE_URL` y se niega con `ITSM_ENVIRONMENT=production`.

Desde `backend/`, con `ITSM_BOOTSTRAP_PASSWORD` suministrada explícitamente en el entorno y el directorio padre ya creado:

```bash
.venv/bin/python -m itsm.demo init --directory ../<local-artifacts> --username demo.owner
```

Deja un marcador durable antes de confirmar los datos: la notificación externa queda suprimida aunque reinicies, y ninguna API de configuración lo borra. No lo limpies a mano ni reutilices la base demo como producción, y no borres volúmenes para "empezar de nuevo": elige otro directorio. No modifica servicios ajenos. La telemetría sintética es un paso aparte y opcional; en esta etapa ya se verificó con Prometheus aislado y no hace falta repetir esa corrida larga. Ver [demo.md](../backend/docs/demo.md).

## Respaldos y recuperación

Un respaldo completo combina piezas que no se recuperan entre sí:

| Pieza | Qué incluir |
|---|---|
| SQL principal | Volcado consistente con la herramienta del motor: `pg_dump -Fc` + `pg_restore --list`; `mariadb-dump --single-transaction`; SQLite con `.backup` o API online, nunca copiar una base WAL en caliente; SQL Server con el procedimiento nativo del operador, incluidas claves de cifrado |
| Bytes externos | Volumen `attachment-data` (adjuntos, logotipos, documentos) junto al mismo corte de SQL; solo SQL o solo volumen queda incompleto |
| Cola | Volumen Huey completo y consistente; restaurarlo puede repetir trabajos |
| Extensiones | Base SQL (versiones, revisiones, agenda) y `/data/app/extension-workspaces` |
| Configuración | Apariencia publicada, ajustes e integraciones en SQL, más las URLs/orígenes externos reaplicados a mano |
| Secretos | Conserva por separado las claves externas y las credenciales suministradas por el operador. Algunas credenciales de proveedores se guardan cifradas en SQL: requieren también la clave externa `ITSM_AI_CREDENTIAL_KEY` para recuperarse. Reaplica referencias desde el mecanismo aprobado; no rotes claves durante el ensayo |

Advertencias por motor: no infieras compatibilidad desde la URL de SQLAlchemy. SQL Server no se instaló ni se restauró en este entorno; no lo presentes como verificado.

Para ensayar una recuperación: elige una ventana de mantenimiento, coordina escrituras y subidas durante el corte, restaura en un **destino nuevo y aislado** (otro proyecto Compose y volúmenes nuevos), aplica migraciones explícitas y verifica readiness, inicio de sesión y descargas autenticadas. Nunca sobrescribas la instalación viva ni borres volúmenes para liberar espacio. La fase 11 ensayó PostgreSQL y MariaDB nativos en bases desechables ([phase-11-validation.md](phase-11-validation.md)); esta guía no ejecutó ninguna restauración. Ver [operations.md](operations.md#backups-and-recovery).

## Módulos externos

Un módulo aprobado es **código nativo de confianza**, no un sandbox contra código hostil: su Python corre en el proceso de la aplicación y su Vue en el mismo origen. La validación de desarrollo ocurre en un contenedor offline fijo; después, una persona con rol Superadmin revisa versión y digest exactos, avisos, permisos nuevos, plan de migración y compatibilidad de rollback, y aprueba explícitamente. Editar el código exige un digest nuevo, validación y aprobación nuevas. Deshabilitar un módulo bloquea sus operaciones, retira sus contribuciones y detiene la agenda **sin borrar datos**. La autorización de backend sigue vigente para toda operación del módulo.

La composición de interfaz por SDK permite agregar, ocultar o reemplazar navegación, páginas, widgets, paneles y acciones de negocio mediante contribuciones declaradas. Está integrada en esta rama de desarrollo y requiere una extensión validada, aprobada y habilitada; no implica un despliegue ni una publicación. Login, permisos, recuperación de extensiones y operaciones de sistema siguen siendo superficies del core. Ver [extensions-sdk.md](../backend/docs/extensions-sdk.md) y [frontend/docs/extensions-sdk.md](../frontend/docs/extensions-sdk.md).

## Operaciones de Superadmin

Solo una persona persistida con rol `superadmin` ejerce `system.*`. Un Admin no puede otorgarse permisos reservados ni promover a nadie por encima de sí mismo, y una identidad máquina los obtiene únicamente con delegación explícita de un Superadmin humano activo: ningún agente recibe permisos por sí mismo ni por indicación en un chat.

Las operaciones de sistema se limitan a acciones fijas (`deployment.status`, `update.prepare`, `backup.create`) que ejecuta un operador externo bajo su propia cuenta de mínimo privilegio. ITSM autoriza y audita cada una; ni los prompts ni los argumentos de herramientas eligen comandos, rutas o credenciales. Sin ejecutor configurado y alcanzable, la operación se informa como **no disponible**, nunca como exitosa. Toda aprobación es humana y explícita. Ver [system-operations.md](../backend/docs/system-operations.md).

## Límites de esta etapa

Instalación, respaldos y módulos externos siguen siendo integraciones propias de cada operador: esta guía no incluye scripts de respaldo, automatizaciones ni certificación de producción. Si una comprobación no se ejecutó, el documento correspondiente debe decir "no verificado" en lugar de inferirlo.
