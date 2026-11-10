# Shared demo reset

The first delivery uses one shared fictional dataset, not per-visitor isolation.
`GET /api/v1/demo/status` returns `enabled`, server UTC `serverTime`, persisted
`nextResetAt`, `generation`, and `resetting`; responses are `Cache-Control: no-store`.
Other modes return only `{"enabled": false}`.

Migration `0030_demo_cycle` must run explicitly before startup. The initial deadline
is 60 minutes from first cycle access; an API restart does not move it.

## Reset ownership and execution

Set `RELEASE_MODE=demo` and `ITSM_DEMO_DATA_DIRECTORY` to an explicit, existing,
private directory. Main SQLite DB, attachment directory and SQLite Huey file must
be separate, non-overlapping descendants of that directory. Symlinks are refused.
No Redis/Postgres queue or shared attachment storage is eligible for this reset.
If the directory is omitted, the automatic reset is **not enabled**; do not claim
that configuration is a public resetting demo.

Run exactly one API process and no external demo Huey consumer. The API holds an
advisory lock on `<directory>/api.lock` for its lifetime, so a second API process on
the same directory refuses to start with a clear error instead of running a second
scheduler; the kernel releases the lock when the process dies, so a crash never
blocks the next start. `recover` takes the same lock and refuses while the API owns
the directory. The API scheduler checks the persisted deadline every second. Ordinary requests take a counted shared
slot and run concurrently, bounded by `ITSM_DEMO_MAX_IN_FLIGHT` (`503 server_busy`
with `Retry-After` above the cap). The gate covers the full HTTP response, including
streaming and response background work. A due reset stops admitting requests, drains
the ones in flight and only then clears state, so one slow upload neither blocks the
other visitors nor postpones the deadline. Requests arriving during the reset receive
`503 demo_reset_unavailable` with `Retry-After`, never a queued wait.
All database-backed sessions, fictional business rows, attachments and queued/result
rows are cleared. The schema, deployment owner, migration reference data and cycle
record survive. The canonical fictional dataset and demo administrator are recreated.
A successful reset increments the generation and schedules another 60 minutes.
A failed/partial reset keeps the process unavailable; it never silently serves a
partially reset dataset. The `resetting` flag stays persisted, so a restart is
unavailable too and the startup log names the exact recovery command. Recovery is
an explicit maintainer operation, not an automatic destructive retry. Stop the API
first — recovery works on the owned directory, not on a live process — then run:

```bash
python -m itsm.demo recover --directory /data/demo
```

It clears the stuck flag and reseeds through the same guarded reset the scheduler
uses, so the demo serves again with a new generation. It refuses a database that is
not marked as a demonstration installation, and it expects the demo layout
`<directory>/demo.db`, `<directory>/tasks/huey.db` and `<directory>/attachments`
(the Compose overlay's layout). Errors do not log credentials.
