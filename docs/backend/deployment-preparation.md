# Mode preparation and backup scheduler

`python -m itsm.deployment prepare` is a one-shot prerequisite for API/worker
startup, never an API startup hook. It requires an explicit `RELEASE_MODE`.

- `dev`: requires externally supplied `ITSM_DEV_ADMIN_PASSWORD`, initializes a
  local development database, strict-password Superadmin `dev.admin`, operator
  and fictional dataset. Repeating preparation does not duplicate data.
- `prod`: on an empty schema, applies migrations and claims production ownership
  without creating accounts or fictional assets. Installation must explicitly
  bootstrap its first administrator. Existing schemas use the guarded ops upgrade
  (backup/verify before pending migrations); failure prevents service startup.
- `demo`: requires `ITSM_DEMO_DATA_DIRECTORY` and contained SQLite storage, applies
  migrations, claims demo ownership, seeds fictional data and the `admin/admin`
  demonstration administrator, then persists the shared cycle deadline. Repeating
  preparation does not reseed an already installed dataset.

Invalid modes refuse before opening a database. Existing conflicting deployment
ownership refuses before migrations. No `.env` file is read or created by these
commands. They use process environment only. Preparation emits mode/status, never
passwords. API readiness and business-request ownership gates remain independent.

## Scheduled production backup

Run `python -m itsm.deployment backup-loop` in the separate ops service with:

| Variable | Default | Meaning |
|---|---|---|
| `RELEASE_MODE` | required `prod` | Scheduling is refused in other modes. |
| `ITSM_DATABASE_URL` | explicit installation URL | Same production database as API. |
| `ITSM_OPS_BACKUP_ROOT` | `/data/backups` | Private maintenance-owned backup storage. |
| `ITSM_OPS_STATUS_PATH` | unset | Optional absolute path for the separate published-summary copy. Its directory must already exist (owner-only `0700`); it is never created or widened here. |
| `ITSM_OPS_RETENTION_KEEP` | `7` | Number to retain, with existing ops protection rules. |
| `ITSM_OPS_BACKUP_INTERVAL_SECONDS` | `86400` | Interval after a successful cycle, minimum 60 seconds. |

Each cycle backs up, verifies integrity, then prunes, and finally publishes the
sanitized summary. A failure exits nonzero and never prunes based on an unverified
artifact; container restart policy belongs to deployment configuration. See
[ops-backup-restore.md](ops-backup-restore.md) for manual verification, restore
confirmation and engine limitations.

### Backup summary for the browser

The maintenance service publishes the summary; the API process only *reads* it.
The API never runs a dump, restore or integrity tool, never opens an engine
socket, never scans artifacts and never recomputes a digest.

Publication always updates the private `<ITSM_OPS_BACKUP_ROOT>/status.json` and,
when `ITSM_OPS_STATUS_PATH` is set, writes the same allow-listed summary to that
separate file with an atomic `0600` replace. Failure and upgrade history stays in
the private record as raw history for backward compatibility, while the external
copy carries only the sanitized allow-listed fields. `status` is `ok` only for a
newest artifact whose checksum matches and that was verified; a missing or
corrupt dump reports `failed` with `checksum`/`verified` false instead of
repeating stale success.

Configure the API with:

| Variable | Default | Meaning |
|---|---|---|
| `ITSM_BACKUP_STATUS_PATH` | unset (unavailable) | Path to the maintenance-published status JSON file. |

`GET /api/v1/system/backups/status` is reserved to the installation owner holding
`system.view`; ordinary administrator and operator roles are denied, and the
public demo denies the whole `/system` prefix before authentication. It returns:

- `available` and `reason`: `true` with `null`, or `false` with `unconfigured`,
  `missing`, `unreadable`, `not_a_file`, `too_large` or `malformed`. Reason codes
  never echo the configured path.
- `checkedAt`: the API read time, not the publish time.
- The allow-listed summary only: `status`, `engine`, `backupCount`, `updatedAt`,
  `lastBackup` (`id`, `createdAt`, `size`, `engine`, `verified`, `checksum`,
  `alembicRevision`), `lastUpgrade` (`status`, `currentRevision`, `headRevision`,
  `backupId`) and at most ten `failures` entries (`at`, `operation`, `reason`).

The read is bounded to 64 KiB of UTF-8 JSON; a larger or non-object document is
reported as unavailable. Locators, filesystem paths, dump names, digests, tool
versions and restore commands are never forwarded, and recognized carriers in
free text (URLs and DSNs, `key=value` credentials, bearer headers, path-like
tokens) are replaced with `[redacted]`. Fields the publisher does not write surface
as `null` instead of being invented, and a request never creates, rewrites or
scans a backup artifact.

Bounded deployment wiring: the ops service mounts the private backup volume and
the small summary volume read-write; the API mounts only the summary volume
read-only (for example `/data/backup-status/status.json`). The API therefore never
receives the backup root, the dumps or the private status record, and the ops
service never depends on an API process to publish.

`Dockerfile.ops` is a separate maintenance image, not the API/worker image.
The image keeps the backend runtime (`10001:10001`, `/data/backups`, the
`backup-loop` command, MariaDB client and unixodbc) but no longer installs the
distribution PostgreSQL client package. `pg_dump`/`pg_restore` are copied from a
multi-stage build of the same digest-pinned server image the local Compose
profile runs:

```text
postgres:16.13-bookworm@sha256:472efd9a66f2b2f1a5aeb18b28de74332e6ef88c2b93a1a5d812fb6db67a5f60
```

The donor stage collects only those two tools and the shared-library closure
`ldd` reports for them into `/pg-client`, and the image copies that tree to
`/opt/pg16-client`. The tools are taken from `/usr/lib/postgresql/16/bin`, not
from `PATH`: Debian's `/usr/bin/pg_dump` is a symlink to `pg_wrapper`, a shell
script that `ldd` rejects as "not a dynamic executable". The selected file must
be a regular, non-symlinked executable or the build stops. Each extraction step
(`cat`, `awk`, `sort`) writes its own file and is checked, so a failing step
stops the build instead of being hidden by a pipeline. Small `/usr/local/bin`
wrappers add
`LD_LIBRARY_PATH=/opt/pg16-client/lib` for those two processes only, so the
Python and MariaDB runtimes keep their own libraries.

The final build writes each `ldd` report to a file, refuses a nonzero `ldd`
explicitly, and only then rejects an unresolved entry; checking the report in a
pipeline would otherwise treat a failed `ldd` as "nothing unresolved". It also
runs `--version` on the imported tools and on their wrappers. The requirement is
the exact PostgreSQL 16.13 client release, not only major 16: overriding the
donor to 16.14 is deliberately refused, because 16.13 is the release pinned to
match the Compose server image and the only pairing this recipe is written for.
These build-time checks are
fail-closed, and the shipped shell fragments have executable regression tests.

Honest limits: the closure is whatever `ldd` resolves inside that donor image,
which is not a proof of full OS dependency reproducibility, and the `ldd`/version
checks are only proven by an actual build. Mixing this tree with a different
distribution or libc is unsupported; both stages are Debian bookworm by design.
MySQL/MariaDB dump compatibility must still be exercised, and MSSQL requires a
separately supplied licensed sqlcmd/ODBC variant.
