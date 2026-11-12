# Interface design

Layout, composition and copy rules for the Hadar IT console. Colors, typefaces and the mark are in [Brand](brand.md).

## Identity

**Hadar IT** is the current product name, with the tagline **Bring your own department.** The tagline appears only on sign-in and in metadata; do not add slogans to everyday work. Each installation's custom appearance stays its own. Technical identifiers, formats and storage keys do not change with this name.

## Direction

An operational application, not a presentation page. Content leads: a quick read of status, comparison and access to detail. Stacked bands, decorative cards and default explanations are dropped. These are revisable decisions, not a frozen interface.

## Visual architecture

- Stable dark navigation; light or dark content according to preference. A compact header with search, saved views, notices and account. Global tools do not occupy an empty row above each page.
- Title, refresh status and actions form one header. Filters in one group; results in another. One primary action per group.
- Flat surfaces and discreet borders. No background gradients, glass, halos, repeated shadows or grids of identical cards as decoration.
- IBM Plex Sans for interface and headings; IBM Plex Mono for measurements. Space Grotesk remains available for identity. Tabular figures; labels in normal case, not a wall of tiny capitals.
- Compact chrome, wide panels. Freed width goes to data, not margins. Comparable panels share rows; lists and records take the height of their content.

## Color and surfaces

The teal/navy palette provides continuity, not a constraint on better composition. `--bg`, `--paper`, `--text`, `--muted`, `--border` and the brand tokens are the color source, including custom presets. One surface hierarchy, one interactive accent. Red and amber mean failure and warning, not decoration. Dark and light are complete versions, not filters over a screenshot.

## Proximity

The parent separates sections; children do not repeat that margin. A field and its help sit closer than fields to each other; filters and their count sit closer than separate sections. The `--layout-field`, `--layout-group`, `--layout-section` and `--layout-inset` roles keep that relationship. Swapping px for rem without better grouping or reading is not an improvement.

## Dashboard

Inspiration: Grafana's consoles, not its brand or imitated data.

1. Status and scope readable before analysis. Availability over a period is not monitoring coverage, nor devices online now.
2. A gauge for percentage availability; bars to compare window averages. "24 h", "7 d" and "30 d" are not consecutive dates: never connect them as a trend.
3. A donut for status composition, with legend, names and counts. Stacked bars for categories/sites. Bars for per-device latency when there are readings. A log for events; lists for pending work.
4. Lines only with distinct dated observations of one series. Do not invent samples, CPU/RAM utilization, downtime or heat maps from data that does not exist. A current value can be a number; it does not need a fictitious curve.
5. Period and filters drive the canonical queries. Current status is labeled as such. Loading, error, empty and absence of measurements are distinct from zero.
6. Acknowledged alerts stay active until resolved. Keep device and context even outside the visible subset. Link to detail; do not arbitrarily rewrite technical titles.
7. Variable-height panels use compatible masonry: each panel advances without waiting for the tallest in the row, with stable DOM and keyboard order, recalculation when content or width changes, and one column on mobile. Do not use CSS columns that alter the visual path, or experimental support as the only path.
8. Personal order and visibility are preserved. Do not install Grafana/Metabase or add dependencies for visual resemblance; evaluate a separate integration if the native solution falls short.

## Copy

Short labels and actions. No slogans, clichés, self-promoting adjectives or repeated obvious explanations. Describe a limitation only where it changes a decision; keep error, scope, confirmation and necessary help messages. Spanish uses informal "tú"; ES/EN catalogs. User data is neither translated nor embellished.

Do not add a subtitle to each step, tab or navigation entry. The title and the action should be enough. If help prevents an error, state only the concrete restriction or consequence; do not explain internal architecture. Do not hide help indiscriminately with CSS, and do not remove notices about scope, secrets, approval or destructive actions.

## Settings and other views

Label/control/help groups align to the start and their rows take the height of their content: one field's help does not stretch the neighboring selector. Equivalent controls share a height; long text grows below the control, not inside it.

Section navigation leaves room for the form; when both do not fit, use an accessible selector. Status facts as label/value pairs, not as an endless form. Mobile tabs fully discoverable. Tables for comparison, cards for detail; UUIDs and necessary data stay accessible. Do not alter the physical geometry of reports, QR codes or labels.

## Accessibility and acceptance

Touch targets of at least 44 px, visible focus, keyboard support, text in addition to color, reduced motion, and reflow without document overflow. Charts with accessible quantities and labels. Check contrast and reading in both themes, without claiming a full audit because tests pass.

Acceptance requires screenshots of the artifact actually served, on desktop and mobile, with states and functions exercised, and real tests and builds. No token count, unit substitution, text test or finished plan proves on its own that the UI is good.

References: [Grafana dashboard best practices](https://grafana.com/docs/grafana/latest/dashboards/build-dashboards/best-practices/), [choosing visualizations](https://grafana.com/docs/grafana/latest/panels-visualizations/visualizations/).
