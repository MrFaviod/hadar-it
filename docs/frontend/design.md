# Diseño de la consola

## Identidad

Nombre oficial temporal: **Hadar IT**. Bajada: **Bring your own department.** Solo en acceso y metadatos; no añadir eslóganes al trabajo cotidiano. La apariencia personalizada de cada instalación sigue siendo suya. Los identificadores técnicos, formatos y claves de almacenamiento no cambian por este nombre.

## Dirección

Aplicación operativa, no página de presentación. El contenido manda: lectura rápida del estado, comparación y acceso al detalle. Se abandona la acumulación de bandas, tarjetas decorativas y explicaciones por defecto. El rediseño está autorizado; este documento describe decisiones revisables, no congela una interfaz insatisfactoria.

## Arquitectura visual

- Navegación oscura estable, contenido claro u oscuro según preferencia. Cabecera compacta con búsqueda, vistas guardadas, avisos y cuenta. Las herramientas globales no ocupan una fila vacía encima de cada página.
- Título, estado de actualización y acciones forman un encabezado. Filtros en un grupo; resultados en otro. Una acción principal por grupo.
- Superficies planas y bordes discretos. Sin degradados de fondo, vidrio, halos, sombras repetidas ni cuadrículas de tarjetas idénticas por decoración.
- IBM Plex Sans para interfaz y encabezados; IBM Plex Mono para medidas. Space Grotesk sigue disponible para identidad. Números tabulares; etiquetas en escritura normal, no una pared de mayúsculas diminutas.
- Chrome compacto, paneles amplios. El ancho liberado se entrega a datos, no a márgenes. Los paneles comparables comparten filas; listas y registros tienen altura por contenido.

## Color y superficies

La paleta teal/navy sirve de continuidad, no como restricción a mejorar la composición. `--bg`, `--paper`, `--text`, `--muted`, `--border` y los tokens de marca son la fuente de color, incluidos presets personalizados. Una jerarquía de superficies, un acento interactivo. Rojo y ámbar significan fallo y advertencia, no decoración. Oscuro y claro son versiones completas, no filtros sobre una captura.

## Proximidad

El padre separa secciones; los hijos no repiten ese margen. Campo/ayuda más cercanos que campos entre sí; filtros/conteo más cercanos que secciones distintas. Los roles `--layout-field`, `--layout-group`, `--layout-section` y `--layout-inset` mantienen esa relación. No se considera mejora cambiar px por rem sin mejorar agrupación o lectura.

## Dashboard

Inspiración: las consolas de Grafana, no su marca ni una imitación de datos.

1. Estado y alcance legibles antes del análisis. Disponibilidad del período no equivale a cobertura de supervisión ni a equipos en línea ahora.
2. Medidor para disponibilidad porcentual; barras para comparar medias de ventanas. «24 h», «7 d» y «30 d» no son fechas consecutivas: nunca se conectan como una tendencia.
3. Donut para composición de estados con leyenda, nombres y cantidades. Barras apiladas para categorías/sedes. Barras para latencia por equipo cuando hay lecturas. Registro para sucesos; listas para trabajo pendiente.
4. Líneas solo con observaciones fechadas distintas de una misma serie. No inventar muestras, utilización CPU/RAM, tiempos de caída ni mapas de calor con datos inexistentes. Un valor actual puede ser un número; no necesita curva ficticia.
5. Período y filtros gobiernan las consultas canónicas. Estado actual se etiqueta como tal. Carga, error, vacío y ausencia de mediciones son distintos de cero.
6. Alertas reconocidas siguen activas hasta resolución. Conservar equipo/contexto incluso fuera del subconjunto visible. Enlaces a detalle; no títulos técnicos reescritos arbitrariamente.
7. Paneles de altura variable usan masonry compatible: cada panel avanza sin esperar al más alto de la fila, con orden DOM y teclado estable, recálculo al cambiar contenido/ancho y una columna en móvil. No usar columnas CSS que alteren el recorrido visual ni soporte experimental como único camino.
8. Orden y visibilidad personales se conservan. No instalar Grafana/Metabase ni introducir dependencias por parecido visual; evaluar integración separada si la solución nativa no cumple.

## Texto

Etiquetas y acciones cortas. Sin eslóganes, frases cliché, adjetivos de autopromoción ni explicaciones obvias repetidas. Describir una limitación solo donde cambia una decisión; conservar mensajes de error, alcance, confirmación y ayuda necesaria. Español de tú y catálogos ES/EN; datos del usuario no se traducen ni adornan.

No añadir un subtítulo a cada paso, pestaña o entrada de navegación. El título y la acción deben bastar. Si una ayuda evita un error, indicar solo la restricción o consecuencia concreta; no explicar la arquitectura interna. No ocultar indiscriminadamente ayudas por CSS ni eliminar avisos de alcance, secretos, aprobación o acciones destructivas.

## Configuración y otras vistas

Los grupos etiqueta/control/ayuda se alinean al inicio y sus filas tienen altura por contenido: la ayuda de un campo no estira el selector vecino. Los controles equivalentes comparten altura; los textos largos crecen debajo, no dentro del control.

La navegación de secciones deja espacio al formulario; si no caben ambas, selector accesible. Hechos de estado en pares etiqueta/valor; no como un formulario interminable. Pestañas móviles completamente descubribles. Tablas para comparación, fichas para detalle; UUID y datos necesarios siguen accesibles. No alterar geometría física de reportes, QR o etiquetas.

## Accesibilidad y aceptación

Objetivos táctiles de al menos44px, foco perceptible, teclado, texto además de color, movimiento reducido y reflujo sin desbordamiento del documento. Gráficos con cantidades y etiquetas accesibles. Revisar contraste y lectura en ambos temas, sin declarar auditoría completa por pasar tests.

La aceptación exige capturas del artefacto realmente servido, desktop y móvil, estados y funciones ejercitados, pruebas y build reales. Ningún conteo de tokens, sustitución de unidades, test textual o plan terminado demuestra por sí mismo que la UI es buena.

Referencias: [prácticas de Grafana](https://grafana.com/docs/grafana/latest/dashboards/build-dashboards/best-practices/), [selección de visualizaciones](https://grafana.com/docs/grafana/latest/panels-visualizations/visualizations/).
