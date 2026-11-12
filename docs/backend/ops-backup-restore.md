# Backup, restore, retention and guarded upgrade

`itsm/ops/` is the operational library behind the backup/upgrade services. It is
a separate entry point, not part of the API or the worker: the backend image
gains no engine tools and no additional sockets. The Compose wiring of these
commands belongs to the release-mode deployment task.

```bash
python -m itsm.ops backup
python -m itsm.ops verify    <backup-id>
python -m itsm.ops restore   <backup-id> --target-file <new-file>
python -m itsm.ops restore   <backup-id> --target-database <new-database>
python -m itsm.ops restore   <backup-id> --target-extensions <new-data-directory>
python -m itsm.ops restore   <backup-id> --replace-live --confirm <backup-id>
python -m itsm.ops prune     --keep 7 --max-age-days 30
python -m itsm.ops status
python -m itsm.ops upgrade
```

Every command prints one JSON object. Exit codes: `0` success, `1` failure
(including a failed verification or a failed upgrade), `2` usage error, `3`
refused for safety (overwriting the live database without consent, missing
consent token, another upgrader holding the lock).

## Configuration

The database location stays under the application settings authority
(`ITSM_DATABASE_URL`, `ITSM_*` prefix). Credentials are supplied only through
the environment or a private option file, never on the command line:

| Engine | Secret channel |
|---|---|
| PostgreSQL | `PGPASSWORD` |
| MySQL / MariaDB | `ITSM_...` password through a temporary `0600` option file passed as `--defaults-extra-file` (`MYSQL_PWD` is not used, it leaks into the environment of child processes) |
| SQL Server | `SQLCMDPASSWORD` |

Operator settings for this tool:

| Variable | Meaning |
|---|---|
| `ITSM_OPS_BACKUP_ROOT` | Artifact root, default `/data/backups` (`--backup-root` overrides) |
| `ITSM_OPS_RETENTION_KEEP` | Default for `prune --keep` |
| `ITSM_OPS_RETENTION_MAX_AGE_DAYS` | Default for `prune --max-age-days` |
| `ITSM_EXTENSION_DATA_PATH` | Extension data root, default `/data/extensions/data` (see [extension data](#extension-data-files)) |

Database locators are always rendered with the password removed
(`postgresql://itsm@db:5432/itsm`), in JSON output, in status, in failures and in
rendered commands. argv lists never carry a secret.

## Artifact layout

One directory per backup under the backup root:

```text
<root>/<engine>-<20260101T021500123456Z>-<6 hex>/
├── database.db | database.dump | database.sql | database.bak
├── attachments/<32 hex blob key>
├── extensions/<extension-id>/
│   ├── data.sqlite3
│   ├── snapshots/*.sqlite3
│   └── files/**
└── manifest.json
```

The directory is assembled as `.partial-<id>` and moved into place with
`os.replace`, so an interrupted run never appears as a complete backup. The dump
and the manifest are `0600`, every archived extension file is `0600` and the
artifact, extension and module directories are `0700`.

Restore admits only this extension layout, checks every source/destination ancestor
for existing symlinks before writing, and refuses invalid layouts before a combined
core/extension restore changes the core. This preflight is not protection against
a hostile concurrent filesystem writer; restore requires exclusive local ownership.

`manifest.json`:

```json
{
  "id": "sqlite-20261030T130746021866Z-60b418",
  "engine": "sqlite",
  "format": "sqlite",
  "dumpFile": "database.db",
  "createdAt": "2026-10-30T13:07:46.021866+00:00",
  "database": "sqlite:////srv/itsm/app.db",
  "alembicRevision": "0028_demo_installation",
  "appVersion": "0.1.0",
  "sha256": "f659c86…",
  "size": 1388544,
  "toolVersions": {"sqlite": "sqlite 3.51.2"},
  "versionInfo": {"client": "pg_dump (PostgreSQL) 16.13", "clientMajor": 16,
                  "server": "16.13", "serverMajor": 16},
  "aiCredentialKeyFingerprints": ["0b1f9c7d4e21"],
  "attachments": [{"key": "0123456789abcdef0123456789abcdef",
                   "sha256": "8b1f…", "size": 24576}],
  "extensions": [
    {
      "id": "software-license",
      "files": [
        {"path": "data.sqlite3", "sha256": "9c1d…", "size": 28672},
        {"path": "files/licences/contract.pdf", "sha256": "41ab…", "size": 91234},
        {"path": "snapshots/2.sqlite3", "sha256": "770e…", "size": 24576}
      ]
    }
  ],
  "ignoredExtensions": ["linked-module: symlink"],
  "verified": null,
  "verifiedAt": null
}
```

`versionInfo` records the client tools that wrote the archive and the server the
data came from. It is empty for SQLite and for artifacts written before the
field existed.

`attachments` describes the archived attachment blobs. The attachment *metadata*
lives in the main database; the bytes live in `ITSM_ATTACHMENT_STORAGE_PATH`, so
a backup that does not archive them restores a catalogue whose downloads answer
`503 attachment storage unavailable`. Every archived blob is `0600` and carries
its SHA-256 and size. An artifact written before attachment blobs were archived
has no `attachments` key and stays valid: absence means "no blobs archived".

`verified` is set by `verify`, which checks the recorded checksum, the recorded
size, the archived extension files, the archived attachment blobs, the AI
credential key ring and an engine-specific integrity check. A backup that fails verification is
never reported as usable, and retention protects the newest *verified* artifact
as well as the newest artifact of any state. An artifact written before
extension data existed has no `extensions` key and stays valid: absence means
"no extension data", not "unverified".

## Verification and restore

```bash
$ python -m itsm.ops verify sqlite-20261030T130746021866Z-60b418
{"backupId": "...", "checks": {"checksum": true, "integrity": "ok", "size": true},
 "credentialKeys": {"current": ["0b1f9c7d4e21"], "missing": [],
                    "recorded": ["0b1f9c7d4e21"], "status": "ok",
                    "warning": null, "error": null},
 "attachments": {"count": 2, "bytes": 24576, "verified": true, "missing": [], "errors": []},
 "error": null, "extensions": [], "status": "ok", "verified": true, "warnings": []}
```

A recorded key fingerprint that the current process cannot provide makes
`verify` fail (`checks.credentialKeys: "missing"`) with the fingerprints and the
remedy: the sealed provider credentials stay unreadable until
`ITSM_AI_CREDENTIAL_KEYS` contains the recorded key. A backup taken without a
key ring cannot prove that, so it reports `credentialKeys.status: "unrecorded"`,
which is reported in `status`, in the published summary and in the warnings but
does not fail verification. `status` and the published summary carry
`credentialKeys` so backup automation sees the condition without running a
verify.

`extensions` lists one report per archived extension module; it is empty for an
artifact without extension data (including artifacts written before extension
data was archived).

Per-engine mechanism:

| Engine | Backup | Verify | Restore |
|---|---|---|---|
| SQLite | `sqlite3.Connection.backup` (online-safe, `PRAGMA journal_mode=DELETE`, integrity-checked source) | `PRAGMA integrity_check` on the dump | copy to a staging file, integrity check, atomic rename |
| PostgreSQL | `pg_dump --format=custom` | recorded/installed client-major check plus a bounded trial restore into a throwaway database | `pg_restore --exit-on-error --no-owner --no-privileges` into the target |
| MySQL / MariaDB | `mysqldump`/`mariadb-dump --single-transaction --quick --skip-lock-tables --routines --events` | dump completion marker plus checksum | client reading the dump on stdin |
| SQL Server | `BACKUP DATABASE … WITH INIT, COMPRESSION, CHECKSUM` via `sqlcmd` | `RESTORE VERIFYONLY … WITH CHECKSUM` | `RESTORE DATABASE … WITH REPLACE, RECOVERY` (MOVE clauses optional) |

SQL Server database identifiers are bracket-delimited with embedded `]` doubled;
string literals retain single-quote escaping. This is command-construction evidence,
not live SQL Server certification.

### PostgreSQL client major must match the server

A custom-format archive is only restorable by a `pg_restore` of the same major
version that wrote it. A newer client against an older server fails on its own
session settings (`unrecognized configuration parameter "transaction_timeout"`)
and an older client refuses the newer archive header (`unsupported version`).
The ops image must therefore ship client tools of the **server's major**
(`FROM postgres:<major>-alpine`). On this host `pg_dump`/`pg_restore` are 18.6
while the disposable server is 16.13, which is exactly the mismatch described in
the recovery review.

`verify` refuses the artifact with `checks.integrity: "incompatible"` and names
both majors when the recorded client major, the recorded server major or the
locally installed `pg_restore` major disagree, before any tool or connection
runs. When they agree it proves restorability with a trial restore into a
throwaway database (`itsm_verify_<12 hex>`) that is dropped again; the payload
reports `trialRestore`. A role without `CREATEDB`, or a server that cannot be
reached, reports `integrity: "unavailable"` with the reason instead of
certifying the archive from its table of contents. `restore` refuses a
mismatched artifact with the concrete remedy.

Restore never targets the live database implicitly. SQLite requires a
`--target-file` that does not exist yet; external engines require a
`--target-database` different from the configured one. Overwriting the live
database requires both `--replace-live` and `--confirm <backup-id>`, and the
backup must pass verification first. The SQLite path stages the copy next to the
destination, checks integrity and only then renames it into place, so a failed
restore leaves the old file untouched.

Attachment blobs are restored with `--target-attachments <directory>` (or
together with the database). A missing directory is created; a populated one
requires `--replace-live` and the repeated backup id, and unrelated files in it
are preserved and reported.

### Restore over a running instance

Replacing a SQLite file under a live process does not fail: the process keeps
writing to the unlinked inode and its acknowledged writes disappear, so the
restore looks successful while the running API serves a database that no longer
exists. The API and the worker therefore register a marker next to the database
(`<database>.runtime/<role>-<pid>.json`) and a live restore refuses with exit
code 3 when a live marker or an exclusive lock is present:

```text
restore refused: the database is in use by api pid 4242, worker pid 4243;
stop the API and the worker, restore, and start them again
```

Stop the API and the worker, restore, then start them again. Stale markers from
dead processes are removed automatically. A marker whose recorded pid now belongs
to an unrelated live process is refused conservatively (the restore exits 3 and
names the role and pid): delete that `<database>.runtime/` entry after confirming
nothing of this installation is running. After a restore the API revalidates
the deployment identity of the restored database within
`IDENTITY_REVALIDATE_SECONDS` (2 s) and refuses business requests with
`503 release_identity_unavailable` when the restored database belongs to
another release mode.

## Extension data files

Every installed extension owns its data outside the core database:

```text
<ITSM_EXTENSION_DATA_PATH>/<extension-id>/
├── data.sqlite3            module database (WAL allowed)
├── snapshots/*.sqlite3     pre-upgrade snapshots
└── files/**                other module-owned files
```

`backup` archives every valid module directory into the artifact as
`extensions/<id>/…` and records one manifest entry per module with the relative
path, SHA-256 and size of every file. `data.sqlite3` and each snapshot are read
through `sqlite3.Connection.backup`, so a WAL database is archived consistently
even when recent writes have not been checkpointed. Module ids are lowercase
hyphen identifiers; symlinks, unexpected names and non-regular files are never
followed — they are skipped and listed in `ignoredExtensions`. A missing data
root archives an empty list and is not an error.

`verify` re-checks every archived extension file (checksum and size) and runs
`PRAGMA integrity_check` on each archived `.sqlite3` file. Any mismatch fails the
whole artifact, and `restore` refuses an artifact that does not pass:

```json
"extensions": [
  {"id": "software-license", "status": "ok", "checksum": true, "size": true,
   "integrity": "ok",
   "files": [{"path": "data.sqlite3", "checksum": true, "size": true,
              "integrity": "ok"}],
   "error": null}
]
```

`restore --target-extensions <directory>` writes the archived module files into
that directory after verification. A new directory is created; an existing one
requires the same `--replace-live --confirm <backup-id>` consent as the live core
database. Each file is staged next to its target and renamed atomically,
directories are `0700` and files `0600`, and module directories the artifact does
not contain are preserved and reported under `preserved` — restore never deletes
unknown module data. The core database and the extension data are independent
targets: `--target-file`/`--target-database` select the database,
`--target-extensions` selects the extension root, and both may be combined in one
invocation.

Disabling an extension never deletes its database, so a later backup still
archives it and an older artifact still restores the data files it contains.
`status` reports the extension footprint (`count`, `bytes`) as an additive field.

## AI credential keys

Provider API keys and unexpired managed-gateway lease snapshots are sealed with
the externally supplied key ring (`ITSM_AI_CREDENTIAL_KEYS`, legacy
`ITSM_AI_CREDENTIAL_KEY`; see
[agent-integrations.md](agent-integrations.md#credential-key-ring-and-rotation)).
The keys live in the process environment, never in the database, so a database
backup cannot contain them.

Each manifest therefore records `aiCredentialKeyFingerprints`: twelve hex
characters derived from a SHA-256 digest of a domain label plus the key. It is an
identifier, not a key or a key fragment, and it is the only credential material
a backup carries. `verify` and `restore` compare the recorded fingerprints with
the ring of the running process and report:

```json
"credentialKeys": {
  "status": "missing",
  "recorded": ["0b1f9c7d4e21", "7d2c4a90ff13"],
  "current": ["0b1f9c7d4e21"],
  "missing": ["7d2c4a90ff13"],
  "warning": "the current AI credential key ring lacks 1 recorded fingerprint(s): …",
  "error": "the current AI credential key ring lacks 1 recorded fingerprint(s): …"
},
"warnings": ["the current AI credential key ring lacks 1 recorded fingerprint(s): …"]
```

A missing fingerprint **fails verification** (`verified: false`,
`checks.credentialKeys: "missing"`, exit code `1`) and is reported by `status`
and by the published summary, so the backup service cannot publish "ok" and
rotation cannot prune the last good artifact while the restored installation is
unable to read its provider credentials. The dump itself is still intact; the
failure means the credential state is not proven, and the error names the
remedy: put the recorded key back into `ITSM_AI_CREDENTIAL_KEYS`. A missing ring
never blocks `restore`: the dump and the files are intact, and refusing to
recover data because a secret is missing would turn a key problem into an
outage. `verify` reports `integrityVerified: true` alongside `verified: false`,
so the artifact is known-good for recovery while the credential state stays
visibly unproven. An artifact
recorded without a ring reports `status: "unrecorded"` instead, which stays a
reported warning rather than a failure because there is nothing to compare. Restoring a backup into a process without any key ring
keeps the application running: provider credentials are reported as unavailable
or unreadable, keyless provider records keep working, credential writes return
`503`, and `python -m itsm.credentials status` exits `1` while rows stay
unreadable. In that case re-supply the keys, confirm `status`, and run
`python -m itsm.credentials rotate` if the ring order changed.

Back the key ring up separately from the database (secret manager or offline
medium, never inside the artifact root). Deleting a key before `status` reports
no `older` rows makes those credentials permanently unreadable, because the
database holds no copy of the key and the backup holds only its fingerprint.

## Retention

`prune` deletes artifacts, never the newest one: the newest artifact and the
newest verified artifact are always protected, whatever the policy says. With
`--keep N` everything beyond the newest `N` is deleted; with `--max-age-days D`
everything older than `D` days is deleted; both may be combined. `--dry-run`
reports the decision without deleting. Running `prune` without a rule is a usage
error, so a misconfigured service never deletes everything.

An interrupted backup leaves a `.partial-<id>` directory behind. It is never a
candidate for `--keep`/`--max-age-days` (it is not an artifact) and it used to
be invisible, so it could hold disk space forever. `status` now lists them as
`partials: [{name, bytes, ageDays}]`, and `prune --partials-older-than D`
reclaims those older than `D` days (reported in `reclaimedPartials`, honouring
`--dry-run`). It is the only reclaim rule that does not touch complete
artifacts, so it is safe to combine with the count/age rules or run alone.

## Status

```json
{
  "status": "ok",
  "engine": "sqlite",
  "database": "sqlite:////srv/itsm/app.db",
  "backupRoot": "/data/backups",
  "backupCount": 1,
  "partials": [],
  "credentialKeys": {"status": "ok", "missing": []},
  "extensions": {"count": 1, "bytes": 307200},
  "lastBackup": {"id": "...", "createdAt": "...", "size": 1388544, "engine": "sqlite",
                 "sha256": "f659c86…", "checksum": true, "verified": true,
                 "alembicRevision": "0028_demo_installation", "path": "..."},
  "failures": [{"at": "...", "operation": "verify", "reason": "..."}],
  "lastUpgrade": {"status": "upgraded", "fromRevision": "0027_native_extensions",
                  "toRevision": "0028_demo_installation", "backupId": "..."},
  "updatedAt": "..."
}
```

`checksum` is recomputed when status is read, so a truncated or replaced dump is
reported as `checksum: false` instead of a stale success. `failures` keeps the
last ten failed operations (backup, verify, restore, prune, upgrade) with the
redacted reason. The structure is stable and safe for a service to read; it
contains no credentials and no SQL dump content.

## Guarded upgrade

`upgrade` is the production updater. It takes a lock file
(`<root>/upgrade.lock`), refuses to run while another upgrader holds it, and
reclaims a lock whose process is gone.

Preflight, in order:

1. the database is reachable (`probe_database`);
2. the current Alembic revision is known and is an ancestor of the code head — a
   database newer than the code is refused, not migrated backwards;
3. the backup root is usable and has free space for source size × 3 (minimum
   32 MiB);
4. no other upgrader holds the lock.

If the current revision already is the head, the command is a no-op: no backup is
taken, `{"status": "up to date"}` is printed and it exits `0`.

Otherwise it takes a backup, verifies it, runs `alembic upgrade head`
(`alembic.command`, so no shell is involved), then verifies that the observed
revision is the head and performs a smoke read (`identity_identities`, `assets`).
The result is recorded in `status.lastUpgrade`.

SQLite DDL is transactional in this release: the migration environment opens an
explicit transaction (`BEGIN IMMEDIATE`), disables Alembic's non-transactional
DDL path for SQLite, and commits only when the whole run reaches the head, so a
failing revision leaves neither its tables nor a half-written version row. When
a migration is nevertheless interrupted — a killed process, a revision that
committed before its own failure — the upgrader records the attempt in
`<root>/upgrade-attempt.json` and classifies the schema:

```json
{"status": "failed", "stage": "preflight", "schemaStatus": "partial",
 "error": "a previous upgrade attempt left this database partially migrated
           (attempted 0035_extension_isolation -> 0036_entity_change_events, found 0035).
           Restore the pre-upgrade backup and retry: python -m itsm.ops restore <backup>
           --replace-live --confirm <backup>",
 "backupId": "sqlite-...", "restoreCommand": "..."}
```

A plain re-run is refused while `schemaStatus` is `partial`; `status` exposes the
attempt as `upgradeAttempt.schemaStatus`. Restoring the reported backup over the
live file (or reaching the head) clears it. The API and the worker both refuse to
serve a schema that is not at the code head: business routes answer
`503 database_not_migrated` while `/health/live` and `/health/ready` stay
reachable, and the worker exits `2` instead of consuming tasks.

Any failure after the backup stops the process instead of pushing forward:

```json
{"status": "failed", "stage": "migration", "schemaStatus": "unchanged", "error": "...",
 "fromRevision": "0027_native_extensions", "observedRevision": "0027_native_extensions",
 "headRevision": "0028_demo_installation", "backupId": "sqlite-...",
 "backupPath": "/data/backups/sqlite-...",
 "restoreCommand": "python -m itsm.ops restore sqlite-... --backup-root /data/backups --target-file /srv/itsm/app.db --replace-live --confirm sqlite-...",
 "message": "upgrade stopped; no automatic downgrade was attempted; data preserved"}
```

The command exits non-zero and reports the backup path and the exact restore
command. It never downgrades automatically: the operator decides between
restoring the reported backup and repairing forward.

## Live restore proof

`tests/test_ops_local_restore.py` is the opt-in proof for external engines. It
never starts a database server: it consumes a disposable database URL, drives
`python -m itsm.ops backup|verify|restore|status` in a subprocess exactly as
documented above, then inspects the restored database with SQLAlchemy.

```bash
# prerequisites: a disposable loopback database per engine, plus client tools
# whose major matches the server, both discoverable on PATH
ITSM_TEST_OPS_RESTORE_POSTGRES_URL='postgresql+psycopg://user:…@127.0.0.1:56116/itsm_s9' \
ITSM_TEST_OPS_RESTORE_MARIADB_URL='mysql+pymysql://root:…@127.0.0.1:34116/itsm_s9' \
  .venv/bin/python -m pytest tests/test_ops_local_restore.py -s -q
```

Per engine the harness migrates to head through the explicit Alembic CLI, seeds
three marker rows, and asserts: manifest engine, revision and tool versions;
dump mode `0600`; `verify` returns `integrity: ok`; `status` reports the verified
backup; `restore --target-database <new>` reports `live: false` and the head
revision; the new database holds the same three rows; and the source database
keeps its rows and revision. A missing URL or a missing client tool skips with an
explicit reason — a skip is missing proof, never a pass.
