# In-app help

Open **Help** in the navigation or visit `#/ayuda`. Search ignores case and accents and does not query private data or external providers. The page covers inventory, operations, incidents and maintenance, the dashboard and monitoring, warranties, reports, settings, agents and extensions. Action links appear according to the account's permissions; final authorization stays on the server.

## Product identity

**Hadar IT** is the current product name, with the tagline "Bring your own department." The name shown in the interface is configured separately in **Settings → Appearance** (`#/configuracion/apariencia`), in the **Visible application name** field (`appName` in the active appearance). **General** shows the current name and links to the editor. The shell and the document title use that value; do not rename packages or storage identifiers to customize the presentation. "Asset Manager" is the legacy label, not the product name.

## Demo mode

When the server marks the session as a demo, the application shell shows the **Demo mode** strip under the top bar, on desktop and mobile. The flag comes from the server's session response, not from a browser preference: it disappears on sign-out, when the session expires and when a new session starts. It distinguishes the demo installation from a real one; on its own it does not describe the effect of any particular operation.

Next to the strip, the **Restart in m:ss** countdown uses the time and next restart reported by `GET /api/v1/demo/status`; the browser polls it every 15 seconds and advances the seconds in between. If that request fails, it shows **Next restart unavailable** instead of inventing a time. When the server resets the demo, sessions stop being valid and the application returns to the sign-in screen; you can also sign out from the account menu.

## Scope

Help explains the available functions; it does not promise an autonomous system or production certification. Installation, backups and advanced administration need the deployment's operations documentation. Keep these guides alongside behavior changes: an explanation does not replace a permission check or the confirmation of an irreversible operation.

## Installed extensions

Extensions add pages, panels on the asset detail, dashboard widgets and actions on an asset. A **declarative** extension contributes data only: the host draws its tables and forms and runs no code on the page. An extension with **isolated code** shows its interface inside a separate frame that cannot access your session, the rest of the page or browser storage; it receives only the asset identifier and requests the data it shows through its declared operations, which the server authorizes with your permissions. If the frame navigates to another document, the application stops answering it.

If a module shows **Requires an update**, it uses an older SDK version: its data stays stored, but its pages are not shown until it is updated. Review, installation, uninstallation and rollback are Superadmin tasks in **Settings → Extensions**; uninstalling keeps the module's own database.
