# Dashboard, workspace and universal search (frontend)

Original Vue Options API surfaces connected to canonical authorized services. No demo dataset, no browser-storage authority for durable preferences, and no replacement application shell.

## Runtime files

| File | Responsibility |
|---|---|
| `assets/js/phase10-api.js` | Session-scoped API adapter, monotonic epochs, serialized `PUT /workspace/state`, dashboard, search and integration calls; Vue mixin methods. |
| `assets/js/dashboard-model.js` | Canonical `GET /dashboard` DTO normalization and widget availability. |
| `assets/js/dashboard-views.js` | Panel composition, loading/error/unavailable states and real drilldowns. |
| `assets/js/dashboard-preferences.js` | Widget catalogue, order/visibility/defaults, session-only temporary widgets, shortcut validation. |
| `assets/js/workspace-engine.js` | Local workspace projection: per-owner favorites/usage, personal/shared views, view validation. |
| `assets/js/workspace-runtime.js` | Existing routes plus favorites, views and last-view restoration against canonical endpoints. |
| `assets/js/workspace-views.js` | Favorite/view popover, asynchronous save/delete with explicit errors. |
| `assets/js/search-engine.js` | Quick actions, local normalization/ranking and `fromServer()` canonical record adapter. |
| `assets/js/search-views.js` | Ctrl + K palette, server search, scopes, keyboard, loading/empty/error states. |

## Script registration

Load after `access.js` and before `dashboard-model.js` / views:

```html
<script src="assets/js/phase10-api.js"></script>
```

`phase10-api.js` depends on `window.AssetAccess.request`, `window.AssetWorkspace`, `window.AssetSearch` and `window.AssetDashboardPrefs` at call time; load `workspace-engine.js`, `dashboard-preferences.js` and `search-engine.js` before their consumers.

## Vue app hooks

Merge `AssetPhase10.methods` into the root Vue methods, then:

```js
// after the canonical session is authenticated, in created/mounted
phase10Start();

// route watcher, after access checks
handlePhase10Route(next);

// activeUserId watcher
phase10IdentityChanged();

// logout and beforeUnmount
phase10Clear();
phase10Stop();
```

The mixin owns `patchWorkspaceState`, so writers (`toggleWorkspaceFavorite`, view saves, usage, last views) share one serialized queue. Do not add a second queue or write workspace state directly. The workspace widget state is applied to `vm.dashboard` during hydration; the existing `applyThemeMode` is called with `light|dark|auto`.

Required root data already present in the application: `authenticated`, `activeUserId`, `currentUser`, `route`, `dashboard`, `config`, `assets`, `prefs`, `workspaceState`, `showToast`, `navigateWorkspace`, `applyThemeMode`, `can`.

## Contracts consumed

- `GET /dashboard?period&category&siteId` — canonical stats, availability (`configured`, `samples`), latency, groups (`up|degraded|down|other`), alerts, incidents, rows, activity, maintenance, warranties, inventory, generated timestamp. Missing sections stay visibly unavailable; nothing is fabricated.
- `GET|PUT /workspace/state` — `{widgets, favorites, usage, lastViews, themeMode, shortcuts, views}`. `PUT` merges top-level keys and returns the saved state. `lastViews` is always sent as the complete per-user route map, never a single route key, so saving inventory cannot drop map/graph/panel snapshots. Widgets `null`/absent means the existing eight defaults; `[]` intentionally hides all.
- `GET|POST /workspace/shortcuts`, `PATCH|DELETE /workspace/shortcuts/{id}` — personal/shared external links; server owns ownership/authorization.
- `GET|POST /workspace/views`, `PATCH|DELETE /workspace/views/{id}` — personal/shared saved views with route snapshot.
- `GET /search?q&kind&limit&offset` — `{items, total, limit, offset, engine, fallback}`. Items are adapted to palette records keyed `type:id`; quick actions remain local. `favorites` and `actions` scopes stay local; `views` queries `kind=view`.
- `GET|PUT /workspace/integrations` — AnyDesk/Tactical RMM defaults used by asset remote actions.

Search echoes only current-account responses: a newer query, identity change or `phase10Clear()` invalidates in-flight results. Failures are explicit; SQL fallback is displayed as `Búsqueda SQL de respaldo`.

## Integrations save contract

`config.js` must not persist integration settings locally. Call:

```js
const result = await this.saveArtifactIntegrations(next);
if (result.ok) this.settingsOpen = false; // existing UI close
else this.error = result.error;
```

`saveArtifactIntegrations(draft)` / `AssetPhase10Api.saveIntegrations(vm, draft)` accepts either the original settings shape `{anydesk:{enabled,url}, rmm:{enabled,url}}` or the canonical flat DTO `{anydeskEnabled, anydeskUrl, rmmEnabled, rmmUrl}`. It returns `{ok:true, integrations:{anydesk:{enabled,url}, rmm:{enabled,url}}}` or `{ok:false,error}`. Responses are applied only when the originating session epoch, account and authentication still match; `clear()` and `stop()` invalidate in-flight reads and writes.

## Durable workspace behavior

- Favorites and usage are stored per canonical user on the server.
- Temporary dashboard widgets live only in `dashboard.temporary`; they never enter the durable widget list.
- Personal views are visible only to their owner; shared views are visible to all and editable by their owner (subject to backend authorization).
- Last inventory view is persisted; favorites and saved views are returned by `/search` with `view:`/`asset:`/`person:` keys and navigate through the existing runtime.
- External shortcuts open in a new tab through existing link rendering; no iframe.

## Session lifecycle and explorer restoration

Workspace writes capture their initiating account and session epoch before entering
the queue. Guards run before transport and after each asynchronous boundary; late
view/shortcut responses cannot publish into a replacement account. `lastViews`
merges with the server copy rather than replacing sibling route snapshots.

A reload restores saved explorer filters and selection when shared state is still
empty. Pending navigation, active shared filters, or an explorer already mounted
in the current session take precedence, including intentionally cleared filters.

Typed queries in the palette's Todo scope also rank matching persisted favorites
and deduplicate canonical keys against server results. Vistas remains server-backed;
Favoritos remains the current account's persisted records.

## Existing modular configuration

Configuración → General retains personal Dashboard layout/shortcuts and now exposes the canonical search status, synchronization and rebuild controls. Administrative mutations reuse `AssetAccess.request` (session/CSRF) and `config.general`; the API still checks effective Casbin authority. Status requests are aborted/invalidated on unmount or account replacement; denied actions do not publish queued success. The engine URL/key remain externally supplied deployment settings, never browser-managed secrets.

General links to the existing Apariencia editor for installation identity instead of retaining a second local-only identity form. Mapas y planos and Relaciones retain their existing configuration sections. No duplicate branding authority or new product module is introduced.
