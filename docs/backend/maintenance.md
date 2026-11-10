# Preventive maintenance

Preventive maintenance is a first-class asset plan. A plan is not a corrective
intervention and does not replace the asset's own lifecycle history. Corrective
work may be recorded elsewhere, but it never resets a preventive cycle.

## Effective plans and identity

A plan id is a UUIDv5 derived from `plan/<asset-uuid>/<maintenance-type>`. The
same id identifies:

- the virtual plan computed from the category template, before any explicit
  change or transition;
- the persisted row created by the first override or lifecycle transition.

Materializing a plan never changes its id. Scheduler reminders and intervention
links can therefore keep the same plan id for the whole life of the cycle.

Reads are pure. `GET` never creates a row, history event or audit entry. A row
is written only when an explicit plan is created, edited, completed, postponed
or cancelled.

`persisted` in the DTO tells the caller whether the plan is currently inherited
(`false`) or backed by a row (`true`). `createdAt`/`updatedAt` are `null` while
the plan is virtual.

## Category templates

Every category in the authoritative inventory catalog has a preconfigured
`preventivo` template, even categories added after deployment. The default is
useful without manually creating one plan per asset. Categories with no explicit
default use a twelve-month fallback and logical inspection tasks.

Defaults live in code, keyed by the catalog ids seeded by migration `0004`
(`computadoras`, `notebooks`, `servidores`, `virtualizacion`, `docker`, `lxc`,
`contenedores`, `switches`, `routers`, `impresoras`, `ups`, `camaras`,
`monitores`, `otros`). A template's id is a stable UUIDv5 of
`template/<category>/<type>`.

Templates are editable. The first edit materializes a stored row with the same
id and `source: "stored"`; deleting that row restores the `source: "default"`
view. Deployed startup code never runs migrations or writes templates.

Every edit validates its supplied fields and optional directory person before
materializing or changing a template or plan. If the `people.view` lookup for
`responsiblePersonId` is denied, the edit leaves domain rows, asset history
and counters unchanged; the identity denial audit remains recorded.

Virtualized and container categories use logical inspection tasks, not physical
cleaning.

### Overrides are snapshots

An explicit plan override copies the template values it inherits at the moment
it is created. Later template edits affect plans that still inherit the
template, but never rewrite an override or a plan that already transitioned.
This keeps a completed/cancelled cycle and an asset exception stable.

`responsiblePersonId` follows the same rule:

- omitted on create/edit: inherit the template owner or keep the current owner;
- explicit `null`: clear the owner;
- explicit person UUID: bind the active directory person, whose label is
  exposed as `responsibleLabel`.

## Recurrence

- `scheduledOn` is the recurrence base. For an inherited plan it is the asset
  registration date; for a first explicit plan without a previous completion it
  is the plan creation date. When a first completion is imported, it is that
  completion date.
- `lastCompletedOn` is `null` until a real completion. It is never inferred from
  `createdAt`.
- `dueOn` is the next due date. First due is `addMonths(scheduledOn, interval)`.
  After a completion it is `addMonths(actualCompletionDate, interval)`.
- Month arithmetic clamps at the end of the target month: Jan 31 + 1 month is
  Feb 28/29; Jan 10 + 6 months is Jul 10. The next completion is anchored to the
  actual day achieved, not to the original January anchor.
- `intervalMonths` is 1..120.

## Lifecycle

- **Complete** sets `lastCompletedOn`, status `active` and recalculates `dueOn`
  from the actual completion date. `completedOn` defaults to today, cannot be
  in the future, and must be after the previous completion.
- **Postpone** changes only `dueOn` and status `postponed`; completion facts are
  untouched.
- **Cancel** sets status `cancelled`; due date and last completion are
  preserved. A cancelled plan cannot be completed, postponed or cancelled again.
- Every successful transition appends one structured asset-history event with
  `entityType: "maintenance_plan"` and `entityId` equal to the plan id, plus one
  terminal identity audit event.
- A rejected transition leaves the plan row, history and counters unchanged.

The scheduler helper `iter_due_plans(...)` is a trusted, read-only seam. It
requires no principal and writes nothing. Reminder persistence, uniqueness and
delivery belong to the scheduler adapter; periodic work never completes a plan
autonomously.

## HTTP contract

All routes are mounted by the composition root under the versioned API prefix.
DTOs are camelCase, errors use the shared `{"error": {"code", "message"}}`
envelope, and pages are `{items, total, limit, offset}` with `limit` 1..200.

| Method | Path | Permission |
| --- | --- | --- |
| GET | `/maintenance/templates` | `config.general` |
| POST | `/maintenance/templates` | `config.general` |
| PATCH | `/maintenance/templates/{id}` | `config.general` |
| DELETE | `/maintenance/templates/{id}` | `config.general` |
| GET | `/maintenance/plans` | `assets.view` |
| GET | `/maintenance/plans/{id}` | `assets.view` |
| POST | `/maintenance/plans` | `assets.edit` on the asset |
| PATCH | `/maintenance/plans/{id}` | `assets.edit` on the asset |
| POST | `/maintenance/plans/{id}/complete` | `assets.edit` on the asset |
| POST | `/maintenance/plans/{id}/postpone` | `assets.edit` on the asset |
| POST | `/maintenance/plans/{id}/cancel` | `assets.edit` on the asset |

Plan filters: `state` (`pending`, `upcoming`, `overdue`), `status`, `category`,
`site`, `siteId`, `assetId`, `maintenanceType`, `dueFrom`, `dueTo`,
`completedFrom`, `completedTo`, `upcomingDays`, `archived`, `limit`, `offset`.
`pending` excludes cancelled plans; `upcoming` uses the next `upcomingDays`
window; `overdue` is strictly before today.

## Data model

Migration `0013_maintenance` (down revision `0012_workflows`) creates
`maintenance_templates` and `maintenance_plans`.

- `maintenance_plans.asset_id` references `assets.id` with `RESTRICT`, so a
  persisted plan blocks a permanent asset purge until the plan is handled.
- `responsible_person_id` stores an active directory-person UUID validated by
  `DirectoryService`; it is intentionally not a cross-metadata foreign key
  because inventory and directory use separate declarative bases. A person
  reference is a label snapshot plus id, never an authorization grant.
- Unique `(asset_id, maintenance_type)` prevents duplicate cycles for the same
  asset and type.
- Dates are SQL `DATE`; timestamps are timezone-aware in the application models.

`MaintenanceService.complete_in_transaction(...)` is an internal, non-committing
seam for a linked preventive intervention and its plan completion in one transaction
with one terminal audit. It is not exposed by the HTTP router and must not be
composed as a second public mutation.

## Periodic preparation

Migration `0015_maintenance_reminders` adds durable reminder preparation rows.
The existing Huey consumer registers `maintenance_due_scan` every five minutes,
with bounded retries. Run only one periodic scheduler per queue; additional
consumers may execute work with periodic scheduling disabled.

Each scan includes overdue plans and plans due within thirty days. It shares
the inventory write mutex with completion and cancellation, and a unique
`(plan_id, due_on, stage)` key prevents duplicate preparation across retries or
competing scans. The stages are `upcoming` and `overdue`; a new due date is a
new reminder cycle. Interrupted scans can be retried without completing a plan.

Preparation emits `maintenance.reminders_prepared` and stores no delivery claim.
SMTP, Telegram and Apprise delivery remain outside Phase 7.
