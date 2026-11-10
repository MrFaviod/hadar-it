# Frontend development

[Back to the README](../../README.md) · [Install the full application](https://github.com/MrFaviod/hadar-it/blob/master/INSTALL.md) · [Visual feature tour](https://github.com/MrFaviod/hadar-it/blob/master/docs/features.md)

Use the central Docker walkthrough to run Hadar. This page is for changing the browser application, not a second installation path.

## Local development

Use **Node.js 22+**. From the `frontend/` repository:

```bash
npm ci
npm run dev -- --port 5173
```

Open <http://127.0.0.1:5173>. Start a separately initialized backend first. Vite proxies `/api` to `http://127.0.0.1:8000` by default. To use the Docker walkthrough's API instead:

```bash
ITSM_DEV_API_URL=http://127.0.0.1:18000 npm run dev -- --port 5173
```

Set the backend's `ITSM_AUTH_ORIGIN` to the **exact browser origin**, including scheme and port. `localhost` and `127.0.0.1` are different origins. Use `ITSM_AUTH_COOKIE_SECURE=false` only for explicit loopback HTTP development. A proxy URL does not override server authorization or CSRF checks. `vite preview` is not the development API proxy or a production deployment.

No `.env` file is required. Keep credentials on the server; never put provider keys, database credentials or session tokens in a `VITE_*` variable or browser bundle.

## How the interface fits together

React 19 and TypeScript own the application shell. Vue 3 renders locally vendored domain views inside that shell. The main application is not an iframe and does not need an OpenDesign service at runtime. Executable extension pages are a separate case: their isolation is intentional.

The backend is authoritative for persisted inventory, identity, workflows and configuration. UI permissions control visibility; server services enforce access. Keep unavailable, unconfigured and empty states distinct. A failed monitoring request must not become a claim that a device is down.

For UI conventions, start with [DESIGN.md](design.md). Earlier phase and visual-review documents record implementation history; use the current source and contract pages when behavior differs.

## Checks

```bash
npm run check
```

This runs the Node test suite, TypeScript checking and the production Vite build. Narrower commands:

```bash
npm test
npm run build
```

Browser and lifecycle checks need a running, isolated application and their own prerequisites. Inspect the relevant scripts and test setup before running them; a successful build is not a browser interaction verdict. Do not aim tests at someone else's inventory or claim live engine coverage from local doubles.

For the focused monitoring browser scenarios, use a disposable demo stack and the
Playwright/Chromium prerequisites documented at the top of the browser script:

```bash
python3 tests/ui-monitoring-visual.browser.py
node --test tests/ui-monitoring-visual.test.cjs
```

The browser script logs in and creates test state. Never point it at an existing
business installation.

## Contracts by topic

| Topic | Read next |
|---|---|
| Inventory and workflows | [Inventory](inventory.md), [workflows](workflows.md) |
| Dashboard and monitoring | [Workspace](workspace.md), [infrastructure and monitoring](infrastructure-monitoring.md) |
| Search | [Global search](../frontend/development.md) |
| Reports and workspace | [Reports](reports.md), [workspace](workspace.md) |
| Language and help | [Internationalization](i18n.md), [integrated help](user-help.md) |
| Agents | [Agent integrations](agent-integrations.md), [multimodal UI](ai-multimodal.md) |
| Extensions | [Extension SDK](extensions-sdk.md) |
| Deployment and boundaries | [Root technical guide](https://github.com/MrFaviod/hadar-it/blob/master/docs/technical-guide.md) |

## Screenshot contributions

Use an isolated `demo` installation with fictional records. Keep its **Modo demostración** banner visible; do not conceal warnings or add invented monitoring/AI results. Avoid account menus, credentials and real inventory. Keep capture logs outside the product repositories.
