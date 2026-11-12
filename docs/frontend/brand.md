# Brand

**Hadar IT** is the current product name, with the tagline **Bring your own department.** The tagline appears on the sign-in screen and in page metadata; it is not repeated as help text on every screen. Names configured by an installation are preserved, and "Asset Manager" is a legacy interface label, not the product name.

The interface is an internal IT tool: cool near-white surfaces, petrol-blue ink, a single teal accent and technical typography (Space Grotesk and IBM Plex).

## Mark

Hadar is a star. The mark is an **H** whose crossbar is a four-point star: two vertical bars in the accent teal and a lighter star whose horizontal points reach into the bars.

| File | Use | Notes |
|---|---|---|
| `frontend/assets/svg/logo.svg` | Sidebar, sign-in header, appearance preview | 48 × 48 box, transparent background, drawn for the dark chrome. |
| `frontend/assets/svg/favicon.svg` | Browser tab icon | 64 × 64 rounded tile. The star has a wider waist so the crossbar survives at 16 px. |
| `assets/banner.svg` | Repository header | 1440 × 440: mark, wordmark, tagline and alpha notice, with the star and its orbits on the right. `assets/banner.png` is a raster copy. |

The backend keeps byte-identical copies of the logo and favicon as the built-in artwork of the original appearance preset (`backend/itsm/appearance/builtin.py`), so exported appearance packages do not depend on frontend paths. Change both places together.

Rules for the mark:

- Keep the colors: bars `#0d766e`, star `#7bd3ca`. The favicon uses bars `#14958a` and star `#b5ece5` on a `#0c2333` tile so it stays legible at tab size.
- Place the logo on the dark chrome. On light surfaces its star loses contrast; use the favicon tile there.
- Do not stretch, outline or recolor it, and do not add effects. Leave clear space of at least one bar width around it.
- The banner wordmark is Space Grotesk 600 converted to outlines, so it renders the same where the font is not installed.
- Every SVG has a `<title>` referenced by `aria-labelledby`. Where the logo `<img>` sits next to the visible product name, it keeps `alt=""` so screen readers do not announce the name twice.

## Tokens

Values come from `frontend/assets/css/app.css` (light theme) and `frontend/assets/css/theme.css` (dark theme). The hex value is the one in the code; the OKLCH value is its conversion.

| Token | Light | Dark | Variable in the code |
|---|---|---|---|
| `--bg` | `oklch(0.972 0.006 170.4)` · `#f2f7f5` | `oklch(0.201 0.025 235.0)` · `#0a1820` | `--bg` |
| `--surface` | `oklch(1 0 0)` · `#ffffff` | `oklch(0.247 0.032 228.0)` · `#0f242d` | `--paper` |
| `--fg` | `oklch(0.275 0.033 226.4)` · `#152b34` | `oklch(0.946 0.013 202.9)` · `#e4f0f1` | `--text` |
| `--muted` | `oklch(0.532 0.033 221.9)` · `#58717a` | `oklch(0.794 0.026 205.8)` · `#a9c1c4` | `--muted` |
| `--border` | `oklch(0.904 0.012 190.4)` · `#d7e2e1` | `oklch(0.365 0.035 219.3)` · `#29434b` | `--border` |
| `--accent` | `oklch(0.511 0.087 186.4)` · `#0d766e` | `oklch(0.530 0.088 185.7)` · `#147c73` | `--teal-700` / `.btn--primary` |

## Typefaces

- **Display:** `'Space Grotesk', 'Trebuchet MS', sans-serif` — 500, 600, 700
- **Body:** `'IBM Plex Sans', 'Helvetica Neue', sans-serif` — 400, 500, 600
- **Mono:** `'IBM Plex Mono', 'Courier New', monospace` — 400, 500

All are served locally from `frontend/assets/fonts/`.

## Rules

1. One accent (teal) for the primary action, links and the active state. Amber and red only signal warning and failure.
2. The chrome (sidebar, compact sign-in header) sits on near-black ink `#071923`; content sits on light surfaces with a 1 px border and minimal shadow.
3. Text describes the screen and the action: no slogans, introductions or marketing adjectives.
4. Motion is short, uses only `opacity` and `transform`, and disappears under reduced motion.
5. Illustrations are thin-line equipment SVGs on a centered halo, without loose decorative strokes.

See [Design](design.md) for layout and composition rules.
