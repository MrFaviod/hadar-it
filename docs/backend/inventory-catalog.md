# Inventory catalog and form configuration

The inventory catalog supplies persisted installation metadata. The shared inventory service
uses it for typed fields, status transitions and configurable code allocation;
the Vue adapter consumes the same public configuration.
`InventoryCatalog` owns configuration authorization and validation. REST and
future agent adapters must call this service rather than mutate metadata rows.

## Installation and storage

Run the existing explicit Alembic upgrade command. Revision
`0004_inventory_catalog`, based on `0003_inventory`, creates `inventory_catalog`
with `(kind, key)` as its primary key and a portable JSON payload. It installs
an immutable snapshot of categories, fields, statuses and identification rules.
There is no startup seeding, asset creation, account creation or new dependency.
The asset core revision is a sibling; revision `0005_inventory_merge` joins both
before `0006_inventory_codes`, leaving one Alembic head.

Defaults retain the existing Spanish UI vocabulary and stable form keys:
computadoras, notebooks, servidores, virtualizacion, docker, lxc, contenedores,
switches, routers, impresoras, ups, camaras, monitores and otros. Camera forms
have a separate FOV capability. Each has quick/advanced common fields and shared
technical-field references. Existing English status IDs remain `in_use`,
`in_storage`, `maintenance` and `retired`.

Revision `0041_i18n_labels` adds no column here: the payload is already JSON, so
each installed record simply gains a `labels` key (`{"es": ..., "en": ...}`).
It also adds nullable `forward_labels`/`inverse_labels` JSON columns to
`relationship_types`, because those labels live in `String(80)` columns. The
backfill only adds the English caption of a known id and takes the `es` entry
from the stored text, so an installation that edited a label keeps showing it.

## Public configuration routes

All paths are prefixed by `/api/v1` (or the configured API prefix):

- `GET /inventory/config`: requires `assets.view`. Returns `fields`,
  `categories`, `statuses`, `rules` keyed by rule ID, and `commonFields`.
- `PUT /inventory/config/{kind}/{key}`: updates one complete record, where kind
  is `fields`, `categories`, `statuses` or `rules`. Field/category writes require
  `config.categories`; status/rule writes require `config.general`. Cookie
  mutations require the existing Origin and CSRF guards.

Service: `InventoryCatalog(session, settings, identity=None, locale=None)` exposes
`get(principal)`, `put(principal, kind, key, payload)`, `category(key_or_label)`,
`validate_status(value)`, `validate_transition(category, old, new)` and
`validate_technical(category, values, previous=None, defaults=True)`.
The validation helpers are intended for an already-authorized InventoryService,
not unauthenticated routes. All metadata mutations are authorized before any
write, audited as `inventory.config_updated` and committed with that audit.
Invalid input returns 422, incompatible evolution or duplicate category labels
409, denied writes 403. Validation/denials leave metadata unchanged (a denial can
append an identity audit record). There is no destructive metadata DELETE.

### Record contracts

Fields use immutable `key`, `label`, `type` (`text`, `textarea`, `number`, `date`,
`select`, `boolean`, `url`), `active`, `required`, `unit`, `hint`, `options`,
`maxLength` (1–500), optional `minimum`, `maximum`, and optional `default`.
Numbers are finite, non-boolean and bounded to absolute 10^12; dates are canonical
ISO dates; URL values are HTTP(S), without credentials, and are never fetched.
Select options are configured bounded string lists. Defaults undergo the same
validation as actual values. Scalar values remain correctly typed in JSON.

Category records use immutable `id`, `label`, `prefix`, `type`, `icon`, `active`,
`fov`, `quick`, `advanced`, `tech` and nullable `transitions`. Prefixes are 1–6
alphanumeric characters. A technical field can belong to multiple categories;
quick and advanced common-field lists cannot overlap. Categories resolve by ID
or case-insensitive label text in any installed locale for compatibility with
existing free-text assets; the stored asset text and the id never change.
Unrecognized legacy labels remain readable; integration decides when to require
registered fields for new technical values.

Every `label` (and relationship forward/inverse label) is either a plain string
or a locale map; see [i18n](i18n.md). Reads return the resolved `label` for the
request locale plus the full `labels` map (`{}` for a legacy string), writes
accept either form, and `category()` matches the id or any locale's label text.

Status records use immutable `id` (at most 24 characters), `label`, `tone`
(`ok`, `hold`, `warn`, `down`), `final`, `active`. Identification rules contain
`separator`, `quickPad` (2–5), `siteCodeLength` (2–5), `includeSite`, `order`
(`site-type` or `type-site`) and `siteCodes` (at most 200 explicit abbreviations).
Default formatting is site-type-sequence, two decimal digits, e.g. `DC-SER-01`.
These are allocator metadata, not a claim of implemented atomic allocation.
Permanent UUID format and runtime environment cannot be edited here.

`rules/transitions` contains nullable `transitions`, a mapping of source status
IDs to allowed target IDs. Null permits all active targets. A category's non-null
mapping overrides the organization rule; an absent source in a configured map
permits no outgoing transition. An unchanged status is not a transition. Rules
do not contain or mutate location, archive flags or responsible identities.

## Non-destructive evolution

Labels and associations can change. Keys never change. Types cannot be replaced,
select options cannot be removed, and validation cannot be narrowed; create a new
field instead. Deactivation retains the definition and every association.
Validation preserves unchanged stored values of disabled/unassociated fields,
rejects new changes through those fields, and never silently deletes old values.
This intentionally favors retention over coercion or a destructive bulk rewrite.
No asset data or UUIDs are migrated by this metadata revision.
