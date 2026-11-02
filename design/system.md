# Existing frontend design system

Captured from existing sources; not a proposed starter. Artboards use system-font fallbacks, never external font files. Production keeps its local fonts.

## Tokens

### Base
Source: `frontend/assets/css/app.css`

| Token | Value | Usage |
| --- | --- | --- |
| `--font-display` | `'Space Grotesk', 'Trebuchet MS', sans-serif` | Typography |
| `--font-body` | `'IBM Plex Sans', 'Helvetica Neue', sans-serif` | Typography |
| `--font-mono` | `'IBM Plex Mono', 'Courier New', monospace` | Typography |
| `--ink-950` | `#071923` | Color |
| `--ink-900` | `#0b2331` | Color |
| `--ink-800` | `#123346` | Color |
| `--ink-700` | `#1a4559` | Color |
| `--ink-600` | `#2e5b6c` | Color |
| `--teal-800` | `#0b5f59` | Color |
| `--teal-700` | `#0d766e` | Color |
| `--teal-600` | `#0f8c80` | Color |
| `--teal-200` | `#a7dfd7` | Color |
| `--teal-100` | `#d7f0eb` | Color |
| `--teal-050` | `#edf8f5` | Color |
| `--amber-800` | `#8a4b0f` | Color |
| `--amber-700` | `#a65c13` | Color |
| `--amber-200` | `#f2d3a4` | Color |
| `--amber-100` | `#fbead1` | Color |
| `--amber-050` | `#fff7eb` | Color |
| `--slate-900` | `#152b34` | Color |
| `--slate-800` | `#243f49` | Color |
| `--slate-700` | `#3b5660` | Color |
| `--slate-600` | `#557079` | Color |
| `--slate-500` | `#5c747c` | Color |
| `--slate-400` | `#8ba0a6` | Color |
| `--slate-300` | `#b9c8cb` | Color |
| `--slate-200` | `#d8e3e3` | Color |
| `--slate-150` | `#e4eceb` | Color |
| `--slate-100` | `#eef4f3` | Color |
| `--slate-050` | `#f4f8f7` | Color |
| `--white` | `#ffffff` | Color |
| `--danger-700` | `#a92f24` | Color |
| `--danger-600` | `#c23a2e` | Color |
| `--danger-100` | `#fbe7e4` | Color |
| `--danger-050` | `#fef4f2` | Color |
| `--bg` | `#f2f7f5` | Color |
| `--paper` | `#ffffff` | Color |
| `--border` | `#d7e2e1` | Color |
| `--border-strong` | `#c2d2d0` | Color |
| `--text` | `#152b34` | Color |
| `--muted` | `#58717a` | Color |
| `--radius-xs` | `5px` | Radius |
| `--radius-sm` | `8px` | Radius |
| `--radius-md` | `12px` | Radius |
| `--radius-lg` | `18px` | Radius |
| `--radius-pill` | `999px` | Radius |
| `--shadow-sm` | `0 1px 2px rgba(7, 25, 35, 0.06)` | Shadow |
| `--shadow-md` | `0 12px 30px -18px rgba(7, 25, 35, 0.35)` | Shadow |
| `--shadow-lg` | `0 28px 70px -24px rgba(7, 25, 35, 0.45)` | Shadow |
| `--ease-out` | `cubic-bezier(0.22, 0.68, 0.22, 1)` | Motion |
| `--ease-in` | `cubic-bezier(0.55, 0, 0.78, 0.4)` | Motion |
| `--dur-fast` | `160ms` | Motion |
| `--dur-base` | `220ms` | Motion |
| `--dur-slow` | `320ms` | Motion |
| `--sidebar-w` | `268px` | Layout / dimensions |
| `--topbar-h` | `68px` | Layout / dimensions |
| `--page-max` | `1440px` | Layout / dimensions |
| `--icon-size` | `20px` | Layout / dimensions |
| `--od-icon-size` | `20px` | Layout / dimensions |

### Dark
Source: `frontend/assets/css/theme.css`

| Token | Value | Usage |
| --- | --- | --- |
| `--ink-950` | `#f1fbfa` | Color |
| `--ink-900` | `#e7f2f2` | Color |
| `--ink-800` | `#d0e3e4` | Color |
| `--ink-700` | `#b4ced0` | Color |
| `--ink-600` | `#9db9bc` | Color |
| `--teal-800` | `#91e9dc` | Color |
| `--teal-700` | `#62d4c7` | Color |
| `--teal-600` | `#42c2b4` | Color |
| `--teal-200` | `#a7dfd7` | Color |
| `--teal-100` | `#164743` | Color |
| `--teal-050` | `#102f31` | Color |
| `--amber-800` | `#ffd48c` | Color |
| `--amber-700` | `#f6bf67` | Color |
| `--amber-200` | `#7c5a2b` | Color |
| `--amber-100` | `#3d2c16` | Color |
| `--amber-050` | `#2b2115` | Color |
| `--slate-900` | `#edf6f6` | Color |
| `--slate-800` | `#d7e6e7` | Color |
| `--slate-700` | `#bfd2d4` | Color |
| `--slate-600` | `#a6bec1` | Color |
| `--slate-500` | `#8ca7aa` | Color |
| `--slate-400` | `#708d91` | Color |
| `--slate-300` | `#536e73` | Color |
| `--slate-200` | `#3c565b` | Color |
| `--slate-150` | `#2e464c` | Color |
| `--slate-100` | `#243c42` | Color |
| `--slate-050` | `#1c3238` | Color |
| `--white` | `#f4fbfa` | Color |
| `--danger-700` | `#ffaba0` | Color |
| `--danger-600` | `#f47b70` | Color |
| `--danger-100` | `#4b2624` | Color |
| `--danger-050` | `#351d1b` | Color |
| `--bg` | `#0a1820` | Color |
| `--paper` | `#0f242d` | Color |
| `--border` | `#29434b` | Color |
| `--border-strong` | `#3a5962` | Color |
| `--text` | `#e4f0f1` | Color |
| `--muted` | `#a9c1c4` | Color |
| `--shadow-sm` | `0 1px 2px rgba(0, 0, 0, 0.35)` | Shadow |
| `--shadow-md` | `0 12px 30px -18px rgba(0, 0, 0, 0.72)` | Shadow |
| `--shadow-lg` | `0 28px 70px -24px rgba(0, 0, 0, 0.78)` | Shadow |
| `--chrome-bg` | `#071923` | Color |
| `--chrome-panel` | `#0d2a35` | Color |
| `--toast-bg` | `#06171f` | Color |

### Motion
Source: `frontend/assets/css/motion.css`

| Token | Value | Usage |
| --- | --- | --- |
| `--motion-ease` | `cubic-bezier(0.16, 1, 0.3, 1)` | Motion |
| `--motion-enter` | `360ms` | Motion |
| `--motion-step` | `45ms` | Motion |

## Typography
Source: `frontend/assets/css/app.css`, `frontend/DESIGN.md`. Display: Space Grotesk / Trebuchet MS / sans-serif. Body: IBM Plex Sans / Helvetica Neue / sans-serif, 16px / 1.55. Mono: IBM Plex Mono / Courier New / monospace. Artboards use only the documented system fallbacks.

## Components
Sources: `frontend/assets/css/app.css`, `frontend/assets/css/theme.css`, `frontend/DESIGN.md`, `frontend/brand-spec.md`.
- Navy chrome; teal primary actions. Semantic amber/red only for warning/error, with text labels.
- Buttons at least 44px (existing compact variant 38px); fields 50px; focus 3px teal600, offset 3px.
- Light/dark tokens remain paired. One primary action per group.
- Shared radius and shadow tokens only. Tables scroll locally rather than overflow the viewport.
- System-only self-contained design boards; production retains local fonts and existing Vue/React ownership.
- Reduced motion disables transforms/transitions; no decorative load delays.
- Existing shell: sidebar268px, topbar68px, content maximum1440px. Responsive breakpoint differences require runtime proof before correction.
