# Ayuda integrada

Abre **Ayuda** en la navegación o visita `#/ayuda`. La búsqueda ignora mayúsculas y tildes; no consulta datos privados ni proveedores externos. La página documenta inventario, operaciones, incidentes y mantenimiento, Panel y supervisión, garantías, reportes, configuración, agentes y extensiones. Los enlaces de acción aparecen según los permisos de la cuenta; la autorización definitiva sigue en el servidor.

## Identidad del producto

**Hadar IT** es el nombre oficial temporal, con la bajada "Bring your own department." El nombre que muestra la interfaz se configura aparte, en **Configuración → Apariencia** (`#/configuracion/apariencia`), en el campo **Nombre visible de la aplicación** (`appName` en la apariencia activa). General muestra el nombre actual y enlaza al editor. El shell y el título del documento usan ese valor; no cambies nombres de paquetes ni identificadores de almacenamiento para personalizar la presentación. "Asset Manager" es la etiqueta heredada, no el nombre del producto.

## Modo demostración

Cuando el servidor marca la sesión como demostración, el shell de la aplicación muestra la franja **Modo demostración** bajo la barra superior, en escritorio y en móvil. La marca viene de la respuesta de sesión del servidor, no de una preferencia del navegador: desaparece al cerrar sesión, al vencer la sesión y al iniciar una sesión nueva. Sirve para distinguir la instalación de demostración de una instalación real; no describe por sí sola el efecto de una operación concreta.

Junto a la franja, la cuenta regresiva **Reinicio en m:ss** usa la hora y el próximo reinicio que informa `GET /api/v1/demo/status`; el navegador la consulta cada 15 segundos y avanza los segundos entre consultas. Si esa consulta falla, muestra **Próximo reinicio no disponible** en lugar de inventar una hora. Cuando el servidor reinicia la demo, las sesiones dejan de ser válidas y la aplicación vuelve a la pantalla de acceso; también puedes cerrar sesión desde el menú de cuenta.

## Alcance

La ayuda explica las funciones disponibles, no promete un sistema autónomo ni certificación de producción. La instalación, respaldos y administración avanzada requieren la documentación operativa del despliegue. Mantén estas guías junto a los cambios de comportamiento: una explicación no sustituye un control de permisos ni una confirmación de una operación irreversible.

## Extensiones instaladas

Las extensiones añaden páginas, paneles en el detalle del activo, widgets del panel y acciones sobre un activo. Una extensión **declarativa** solo aporta datos: el host dibuja sus tablas y formularios y no ejecuta código en la página. Una extensión con **código aislado** muestra su interfaz dentro de un marco separado que no accede a tu sesión, al resto de la página ni al almacenamiento del navegador; recibe solo el identificador del activo y pide los datos que muestra mediante sus operaciones declaradas, que el servidor autoriza con tus permisos. Si el marco se navega a otro documento, la aplicación deja de responderle.

Si un módulo aparece como **Requiere actualización**, usa una versión anterior del SDK: sus datos siguen guardados, pero sus páginas no se muestran hasta actualizarlo. La revisión, instalación, desinstalación y rollback son tareas de Superadmin en **Configuración → Extensiones**; desinstalar conserva la base de datos propia del módulo.
