# Redundancy groups in the interface

The contract of the screens that show and manage the server's **redundancy groups**. The views are Vue 3 with the global Options API and classic templates: no single-file components, no Composition API and no new dependencies.

For the server side, see [Redundancy groups](../backend/redundancy.md).

## What a group represents

A redundancy group declares that several **independent** inventory instances are replicas of the same workload. Each replica keeps its own UUID, quick code, history and `hosted_in` relationship: a group never merges rows or creates a synthetic "service" asset. `active_active` mode spreads the workload by configured percentages (for example 40 % and 60 %); `active_passive` mode declares a **Primary** and at least one **Backup**.

The share is descriptive inventory information. It is not measured utilization or host CPU or memory, and the interface performs no load balancing, replication, migration, failover or discovery.

## Component map

| Module | Responsibility | Contract |
|---|---|---|
| `assets/js/redundancy-api.js` | The single redundancy adapter: bounded pages, bounded asset search, create/edit/deactivate and session state. Its own monotonic epoch and an `AbortController` per resource. | `window.AssetRedundancy.{data,computed,methods}`; `GET|POST /redundancy-groups`, `GET|PATCH /redundancy-groups/{id}`, `POST /redundancy-groups/{id}/deactivate` |
| `OrganizationRelations` (`relations-views.js`) | The **Redundancy** section on the asset record: the asset's groups, role, share and host; create/edit/deactivate from the same panel. | props `asset`, `app`; uses `app.redundancy`, `app.redundancy.dialog`, permissions `assets.view` / `assets.edit` |
| `GraphExplorer` (`graph-views.js`, `graph-layout.js`) | Side panel of loaded groups, membership mark on the node, and an inspector block with role, share and host. No new edges. | `app.serverGraphMode`, `app.redundancy.groups`, `app.redundancyGroupForAsset` |
| `app.js` | Registers the mixin and wires route, sign-out and unmount to `handleRedundancyRoute` / `clearRedundancyState`. | `window.AssetRedundancy` |

## REST contracts used

- `GET /redundancy-groups?query&active&mode&limit&offset` → `{total, limit, offset, items}`.
- `GET /redundancy-groups/{id}` → the group with `members`.
- `POST /redundancy-groups` → `201` with the full group.
- `PATCH /redundancy-groups/{id}` → a subset of fields; `members` is always the
  **complete** list and `"description": null` clears the description.
- `POST /redundancy-groups/{id}/deactivate` → `active=false`, keeping rows.

Group DTO: `id`, `name`, `description`, `mode` (`active_active` |
`active_passive`), `active`, `createdAt`, `updatedAt`, `memberCount`,
`members[]`. Each member: `assetId`, `name`, `quickCode`, `archived`, `role`
(`primary` | `backup` | `null`), `share` (exact decimal string or `null`) and
`host` (`{id, name}` or `null`). The adapter invents no fields and does not
convert the share to floating point.

## Interface rules

- **Bounded membership.** The list endpoint does not filter by asset. The record
  reads one bounded page (`limit=200`, `offset=0`) and compares `members[].assetId`;
  it states how many groups were examined against the `total` when groups fall
  outside the page. The full inventory is not loaded and no endpoint is invented.
- **Bounded asset search.** The member picker queries
  `GET /assets/search?limit=50&offset=0&query=…` with its own debounce and
  cancellation; it never filters the first page on the client as if it were the
  whole inventory.
- **Full replacement.** Saving sends the entire member list in one request;
  there are no partial per-member writes.
- **Client validation.** A name is required and at most 50 distinct assets are
  allowed. Creating a group, and any active group, requires at least 2 replicas;
  an inactive group may keep 0 or 1, which is what the server accepts when
  clearing it. In `active_active` each member carries a finite share with at most
  two decimals and, when the list is complete (2 or more), the sum is exactly
  100; with a single replica no sum is required. In `active_passive` each member
  carries a role — at most one **Primary** and, with the complete list, exactly
  one plus at least one **Backup** — and no share. The server remains the
  authority: its `422`, `409`, `403` and `404` are shown as they are and never
  turned into success.
- **Optional description.** Emptying the field sends `description: null`; the
  field is not omitted and the previous value is not kept.
- **Mode.** Changing mode sends the complete member list, because the server
  requires the full state in the same request. Roles and shares are not changed
  on the client's own initiative.
- **Deactivate / reactivate.** Deactivating uses `POST …/deactivate`;
  reactivating uses `PATCH {active:true}`. A `409` (for example, an archived
  member or an already inactive group) is shown in the dialog, which keeps the
  form and the canonical data already loaded. No active group is left empty and
  the change is never simulated.
- **No local fallback.** A load error, a `403` or a missing permission shows a
  factual message; it is never filled with demo data, `localStorage` or an
  invented success. Reads require `assets.view`; writes, `assets.edit`.

## State, session and interaction

`redundancy-api.js` keeps its own monotonic epoch (never reset), a session mark
that advances on sign-out or unmount, and an interaction epoch that advances
when the dialog opens or closes and when the route is left.

- **Session identity.** The write token includes the effective identity
  (`activeUserId` and the sorted permission set) together with the epoch. An
  `/auth/me` that replaces the session with another identity or with read-only
  permissions leaves `authenticated` as `true` but invalidates the in-flight
  write: no notice, no refresh, no `true`, no late rows. A periodic check of the
  same user with the same permissions (even if the CSRF token or the array order
  changes) does not cancel a legitimate write.
- **Interaction ownership.** Saving is bound to the specific dialog and its
  epoch: closing the dialog, reopening it or changing route prevents a late
  response from closing another draft, writing its error or setting `busy`.
  Deactivate and reactivate use a view token, so opening or closing the dialog
  does not cancel them; a route change or unmount does.
- **Exits.** Unmounting the record closes its dialog, cancels the queued search
  and advances the panel epoch, so a panel operation still in flight —
  deactivate or reactivate — is no longer presented as its own: its late response
  returns no success, does not refresh membership and writes no error. A route
  change does the same and discards what was left in flight. A request already
  sent may have been applied on the server: the client does not claim to have
  cancelled it, it only stops presenting it as its own.
- A `401` or sign-out empties the state and aborts reads, and a late response
  revives nothing. Pending search text is cancelled with its timer. The server
  domain is never written to `localStorage`.

## On the asset record

- Creating a group from an asset's record **seeds that asset** as the draft's
  first replica (`openRedundancyCreate(this.asset)`). The panel belongs to the
  record and a group created there must include it; the seeded asset does not
  reappear in search results and can be removed with its own control before
  saving.
- Loaded members show **Primary**/**Backup** or **Load share N %** and each
  replica's real host; the record's own asset is marked **This asset**. A group
  without a recorded host says **No registered host** instead of assuming one.
- The record states **Examined X of Y groups** and, if the bounded page does not
  cover the total, warns that groups may exist outside it. When the page is
  truncated and no examined group includes the asset, the text says none of the
  examined groups includes it and the rest were not read; a definitive absence
  ("belongs to no group") is only stated with the complete page.
- Deactivate and reactivate act on the whole group and refresh the record and
  the graph; a server rejection leaves the group as it was and the message on
  screen.

## Graph

Membership is shown as group information — a side panel, a mark on the node and
an inspector block with **Primary**/**Backup**, **Load share** and the member's
real host. No nodes or edges are added to the graph: hosting remains the
directed `hosted_in` relationship, and the redundancy mark does not replace that
meaning. If the loaded page does not cover all groups, the panel says so instead
of presenting the partial set as complete.

## Known limits

- The integrated test uses SQLite and a single Chromium browser; it does not
  certify other engines, browsers or production.
- The graph panel shows only groups with some member in the loaded page; if the
  graph is truncated, it says so instead of completing the set.
- The browser test does not repeat the archived-member check on an active group
  (already covered by the backend): it only verifies the reactivation `409` and
  that the group does not change.
- Session, interaction and unmount races are tested with deferred transport in
  Node, mounting and unmounting the real component; the browser does not provoke
  those races, so there is no browser test for this case.
