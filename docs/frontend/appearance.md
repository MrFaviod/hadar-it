# Installation appearance and per-user mode

The original `AppearanceSettings` UI now uses the installation-wide appearance API as
its authority. The Vue components, routes, design tokens and Spanish copy are
unchanged; `appearance-api.js` is the only new adapter.

## Behavior

- Public pre-login: `startAppearance()` reads only `GET /appearance/active` and
  applies the active branding, favicon, CSS tokens and browser chrome color to the
  login shell. The gallery is not requested before authentication.
- Authenticated: the gallery, active preset and previous preset come from the
  server. Saving, duplicating and importing never activate a preset. Only
  `POST /appearance/apply/{id}`, `restore` and `revert` return a new active
  identity, and only that response updates the shell.
- Per-user light/dark/automatic mode is stored in workspace state as
  `themeMode: "light" | "dark" | "auto"` (`system` in the preset schema maps to
  `auto`). Workspace patches preserve `widgets`, `favorites`, `usage` and
  `lastViews`; the adapter prefers the serialized `patchWorkspaceState()` helper
  and never writes those fields itself.
- `AssetTheme.setScope(userId)` isolates the browser preference key per account
  and restores the guest key on logout. A guest or previous account preference
  never becomes an authenticated account's mode; server hydration replaces it.
- Epochs per channel plus a session epoch drop late public/gallery/theme/package
  responses after logout or an account switch. Stale results do not mutate the
  shell or show toasts.
- ZIP preview is a pure server read. Corrupt, incompatible, oversized, traversal
  or unsafe packages cannot replace the active identity; staging returns a preset
  that still requires explicit Apply. Export and download use the server ZIP for
  any gallery preset. The local ZIP engine remains as the unauthenticated test
  fallback only.
- Graphic resources must be bounded embedded `data:image/...;base64` values,
  `/api/v1/appearance/{resources,assets}/...` URLs, or relative `assets/...`
  paths. External schemes, protocol-relative URLs, traversal and control
  characters are rejected before rendering or submission.

## API contract consumed

All paths are passed to `window.AssetAccess.request`, which supplies the
`/api/v1` prefix, session cookie, CSRF header and Spanish error mapping.

| Method | Path | Result |
|---|---|---|
| GET | `/appearance/active` | `{active, activeId, previousId, builtinIds}` — public |
| GET | `/appearance/presets` | `{presets, activeId, previousId, builtinIds}` |
| POST | `/appearance/presets` | `{preset}` |
| PUT | `/appearance/presets/{id}` | `{preset}` |
| DELETE | `/appearance/presets/{id}` | `204` |
| POST | `/appearance/apply/{id}` | `{active, presets, activeId, previousId, builtinIds}` |
| POST | `/appearance/restore` | same applied state |
| POST | `/appearance/revert` | same applied state |
| GET | `/appearance/presets/{id}/export` | ZIP blob |
| POST | `/appearance/import/preview` | `{preset, resources, comparison, warnings}` |
| POST | `/appearance/import` | `{preset, staged: true}` |

`POST /appearance/import` accepts `{preset, policy: "both" | "replace"}`. It never
activates the staged preset. A stale or non-manager session is rejected client
side (`config.general`) and by the backend Casbin guard.

## Integration

`index.html` loads the adapter immediately before the runtime:

```html
<script src="assets/js/appearance-api.js"></script>
<script src="assets/js/appearance-runtime.js"></script>
```

In `app.js` `created()`, after `AssetAccess.start(this)`, call
`this.startAppearance()`. In `beforeUnmount()`, before `AssetAccess.stop(this)`,
call `this.stopAppearance()`. No new reactive data is required and the existing
`activeUserId` watcher already calls `changeAppearanceUser()`.

`theme.js` needs one narrow hook: a dynamic `storageKey` (`KEY` for guests,
`KEY + '.user.' + encodeURIComponent(id)` for accounts), used by read, write and
the storage-event filter, plus `AssetTheme.setScope(id)` which selects the key,
re-reads the preference and applies it. Runtime calls `setScope(userId)` after
authentication and `setScope(null)` on logout.

## Cross-client changes

The shell refreshes appearance when it starts and when the authenticated account
changes. It does not poll a version endpoint: no live cross-client propagation is
required by the acceptance criteria. Opening or reloading the app re-reads the
authoritative active document.
