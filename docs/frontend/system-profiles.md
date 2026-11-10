# Perfiles de sistema (frontend)

La administración del negocio y la propiedad de la instalación son distintas. El navegador solo presenta lo que el servidor autoriza: los permisos efectivos, los roles y su etiqueta llegan de la API de identidad; no hay autoridad en `localStorage`/`sessionStorage` ni promoción de roles en el cliente.

## Perfiles

- **Superadmin**: propietario de la instalación. Recibe los seis permisos reservados `system.*` y conserva los permisos de negocio. Solo un humano con `superadmin` puede ejercerlos; una identidad de máquina necesita un superadmin humano activo como delegador.
- **Admin**: administra el negocio (incluido `config.integrations`), pero no recibe permisos `system.*` ni puede otorgarse roles reservados. El techo existente `canAssignRole` sigue aplicando: un rol solo es asignable si quien edita ya posee todos sus permisos.
- **User**: lectura por defecto (`assets.view`, `people.view`) con concesiones de negocio acotadas.

El primer Superadmin se crea por CLI (`bootstrap-superadmin`); la web nunca eleva roles. Los roles base se reconocen por `builtIn`/`system` del servidor, no por su identificador.

## Sección Sistema

`#/configuracion/sistema` es una sección más de la navegación de Configuración, visible solo con `system.view`. Admin y User reciben la ruta denegada; las peticiones directas a la API responden `403`.

Los controles se habilitan con su propio permiso:

| Control | Permiso |
| --- | --- |
| Estado, configuración y proveedores (lectura) | `system.view` |
| Guardar clasificación de despliegue y ventana de mantenimiento | `system.configure` |
| Elegir proveedor y modelo predeterminados | `system.providers` |
| Consultar y habilitar/deshabilitar módulos | `system.modules` |
| Crear respaldo | `system.backup` |
| Preparar actualización | `system.update` |
| Comprobar despliegue | `system.view` |

Administración de IA (`#/configuracion/ia`): la preferencia de chat y modelo sigue disponible con `assets.view`; instancias, catálogo, instalaciones y el asistente requieren `system.providers`, y mutar un módulo desde el catálogo requiere además `system.modules`.

## Contrato de API

Base `/api/v1/system`, mismo transporte que el resto de la aplicación (sesión same-origin, CSRF en escrituras, cancelación por señal):

- `GET /status` → `{ready, checkedAt, app:{name,version,mode,database}, readiness:{database,migrations,current,head}, executor:{configured,available,actions,detail}}`.
- `GET /configuration` → `{deployment:{classification,maintenanceWindow,database}, executor:{configured}}`.
- `PATCH /configuration` con `{deployment:{classification?,maintenanceWindow?}}`; no se envían otras claves. «Clasificación de despliegue configurada» es una preferencia y no cambia el entorno real del proceso.
- `GET /providers` → `{selected, selection, providers:[{id,label,credentialConfigured,credentialEnv}]}`. `PUT /providers` envía solo `{provider,model}`; nunca viajan credenciales.
- `GET /modules` → `{modules:[...]}`; `PATCH /modules/{id}` con `{enabled}`. El módulo oficial no se puede deshabilitar (`409`).
- `POST /operations` con `{action:"deployment.status"|"update.prepare"|"backup.create"}` → `{action,state,result,reference,exitCode,startedAt,durationMs,message}`. El servidor elige el ejecutor; la UI no envía rutas, comandos ni endpoints.

## Ejecutor externo

Un ejecutor no configurado o inalcanzable se muestra como **no configurado** o **no disponible**, con el detalle público del servidor. Las acciones que dependen de él quedan deshabilitadas y nunca se presenta un resultado inventado. Una respuesta `state:"unavailable"` se muestra como tal; solo `state:"completed"` con `reference` del servidor se presenta como respaldo completado.

## Pruebas enfocadas

Desde `frontend/`:

```bash
node --test tests/system-profiles.test.mjs
```

Cubren catálogo/permisos, ruta y denegación, lectura mínima, guardado anidado de configuración, proveedor sin secretos, módulos incluido el oficial, operaciones completadas/no disponibles, limpieza al cerrar sesión, metadatos de rol del servidor y el techo de asignación.
