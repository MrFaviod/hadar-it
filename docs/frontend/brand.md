# Hadar IT — brand spec

**Hadar IT** es el nombre oficial temporal. **Bring your own department.** aparece en el acceso, no repetido como ayuda en cada pantalla. Los nombres personalizados de una instalación se conservan; la etiqueta histórica "Asset Manager" no es el nombre del producto.

Herramienta interna de TI: superficies frías casi blancas, tinta azul petróleo, un único acento verde azulado y tipografía técnica (Space Grotesk + IBM Plex).

Valores extraídos de `assets/css/app.css` (tema claro) y `assets/css/theme.css` (tema oscuro). El hex es el valor real del código; el OKLch es su conversión.

## Tokens

| Token | Claro | Oscuro | Variable en el código |
|---|---|---|---|
| `--bg` | `oklch(0.972 0.006 170.4)` · `#f2f7f5` | `oklch(0.201 0.025 235.0)` · `#0a1820` | `--bg` |
| `--surface` | `oklch(1 0 0)` · `#ffffff` | `oklch(0.247 0.032 228.0)` · `#0f242d` | `--paper` |
| `--fg` | `oklch(0.275 0.033 226.4)` · `#152b34` | `oklch(0.946 0.013 202.9)` · `#e4f0f1` | `--text` |
| `--muted` | `oklch(0.532 0.033 221.9)` · `#58717a` | `oklch(0.794 0.026 205.8)` · `#a9c1c4` | `--muted` |
| `--border` | `oklch(0.904 0.012 190.4)` · `#d7e2e1` | `oklch(0.365 0.035 219.3)` · `#29434b` | `--border` |
| `--accent` | `oklch(0.511 0.087 186.4)` · `#0d766e` | `oklch(0.530 0.088 185.7)` · `#147c73` | `--teal-700` / `.btn--primary` |

## Fuentes

- **Display:** `'Space Grotesk', 'Trebuchet MS', sans-serif` — 500, 600, 700
- **Body:** `'IBM Plex Sans', 'Helvetica Neue', sans-serif` — 400, 500, 600
- **Mono:** `'IBM Plex Mono', 'Courier New', monospace` — 400, 500

Todas se sirven en local desde `assets/fonts/`.

## Reglas observadas

1. Un solo acento (verde azulado) para la acción principal, el enlace y el estado activo; el ámbar y el rojo solo indican advertencia y fallo.
2. El chrome (barra lateral, cabecera compacta del login) va sobre tinta casi negra `#071923`; el contenido, sobre superficies claras con borde de 1 px y sombra mínima.
3. Los textos describen la pantalla y la acción; sin eslóganes, frases de presentación ni adjetivos de marketing.
4. El movimiento es corto, solo con `opacity` y `transform`, y desaparece con movimiento reducido.
5. Las ilustraciones son SVG de equipos en línea fina sobre un halo centrado, sin trazos decorativos sueltos.
