# Isolated demonstration installation

This is fictional data, not a production seed or an automatic startup step. Run
from the backend checkout with its existing virtual environment. The initializer
requires a **new directory whose parent already exists**. It refuses every
existing directory, including an empty one; there is no overwrite/reset option.
Directory paths containing `?` or `#` are refused before creating state, because
SQL database URL parsers interpret those characters as URL delimiters.

```bash
# Supply a new password through the process environment, not a command argument.
read -rsp 'Demo password: ' ITSM_BOOTSTRAP_PASSWORD; echo
export ITSM_BOOTSTRAP_PASSWORD
.venv/bin/python -m itsm.demo init \
  --directory "$PWD/../<local-artifacts>" --username demo.owner
unset ITSM_BOOTSTRAP_PASSWORD
```

The command creates a private directory, explicitly applies Alembic migrations,
then calls the canonical services to create a fictional installation in use: two
sites with buildings, floors and four rooms, two departments, five directory
people, an explicitly named installation owner and `demo.operator`, fourteen
assets (servers, virtual machines, switches, a router, IP cameras, a notebook, a
printer and a monitor) with plan positions, thirteen typed relationships, two
redundancy groups, assignment/return/transfer history, four incidents covering
every status, two corrective interventions, four maintenance plans covering
overdue, upcoming, completed and postponed work, five warranties, three small
local attachments (one used as a warranty receipt), three firing monitoring
alerts plus one resolved cycle, one completed CSV import that creates two further
assets, and one saved workspace view. Every row is authored through the public
services, so history and audit records exist for it. Dates are relative to the
demo clock, so a reset keeps the same mix of overdue, current and upcoming work.
The operator initially receives the supplied demo password too;
this is a disposable demonstration, not a recommended production account policy.
There is no built-in/default password. Directory people are not login accounts.
IP addresses use documentation-only `192.0.2.0/24`; email uses `example.invalid`.
The initializer never probes these assets or contacts their addresses.

The success JSON identifies `mode: demo`, the dataset and the new database URL.
It never outputs the password. Set that exact database URL explicitly on the API
and worker; do not reuse a production queue, attachment path or extension storage.
The initializer ignores `ITSM_DATABASE_URL` as a target: it can only own its newly
created `demo.db`. `ITSM_ENVIRONMENT=production` refuses initialization before any
state is created. Failure after directory reservation leaves owned state for
diagnosis; choose a new directory rather than retrying into partial data.

The database contains a durable `demo_installation` marker written **before**
seed service commits. Notification dispatch re-reads it and suppresses external
channels before any SMTP connection or Apprise send, including channel tests
and already queued messages. Internal notifications remain functional. Restarting
without a demo environment flag cannot remove this protection. Ordinary migrated
databases have an empty marker table and retain their previous delivery behavior.
No settings API can clear the marker. Do not manually clear it or repurpose a demo
DB as production. This boundary is not a hostile-code sandbox: an operator or a
trusted native extension with arbitrary Python/SQL authority can alter its DB.

Report templates, labels and per-asset QR images are usable because they render
synchronously. No report job is seeded, and the demo overlay starts no worker by
default: a job created by a visitor stays queued until a worker runs, and the seed
never pretends a render finished. The seeded import is executed inline during
initialization, not by a worker.

Synthetic telemetry is a separate, explicit step; creating the dataset alone never
configures monitoring and the CLI never contacts these assets. The second half of
this document describes that step. The visible browser notice is documented next.

## Visible demo notice

The authenticated login and `GET /auth/me` envelopes carry one additive boolean,
`demoMode`. It is derived on the server from the durable `demo_installation`
marker on every request, defaults to `false`, and is never read from a query
parameter, header, cookie or body. Legacy payloads that omit it stay ordinary
installations, and an unauthenticated request still receives only the usual
`401` error envelope.

Reading the marker requires the applied migrations; the schema is an explicit
prerequisite, not something the API creates or detects. If the marker cannot be
read, login and `GET /auth/me` fail with the ordinary `500 internal_error`
envelope rather than reporting an ordinary installation. A database whose
migrations stop before the marker table, or whose read fails for any other
reason, therefore behaves as a broken installation, not as a non-demo one.

It is presentation metadata, not authority: no route, permission, CSRF or origin
check reads it. The frontend shell renders a persistent Spanish notice reading
"Modo demostración" with the fictional-data statement and the blocked
notifications statement while the flag is exactly `true`, and clears it on logout
or an expired session. It keeps no copy in `localStorage` or `sessionStorage`.

The notice states what the marker enforces: **external notifications are
suppressed**. It does not claim that every outbound provider, monitoring or agent
request is blocked. Silence or resolve Prometheus/Alertmanager separately, and keep
external agent/provider/executor settings out of a demo installation.

## Synthetic telemetry: demo exporter and isolated Prometheus

Bulk metrics are generated by a loopback-only exporter and scraped by a real
Prometheus instance, so the Dashboard keeps using its existing read path
(`itsm/monitoring/prometheus.py` metric expressions) instead of invented values.
Nothing inserts samples into the database and no Vue component fabricates metrics.

### 1. Configure the exporter and node checks

```bash
read -rsp 'Demo password: ' ITSM_BOOTSTRAP_PASSWORD; echo
export ITSM_BOOTSTRAP_PASSWORD
.venv/bin/python -m itsm.demo setup \
  --directory "$PWD/../<local-artifacts>" --username demo.owner \
  --output "$PWD/../<local-artifacts>" \
  --exporter-port 19101
unset ITSM_BOOTSTRAP_PASSWORD
```

`setup` logs in as the existing demo owner and uses the canonical services, so it
writes ordinary `monitor_exporters`/`monitor_assets` rows: one `node` exporter at
`127.0.0.1:19101`, then an enabled `node` check for every canonical asset whose
category profile already resolves to node monitoring (the demo servers), with
target `127.0.0.1:19101`, the `cpu`/`memory`/`disk`/`temperature` metrics and
explicit warning/critical thresholds. It refuses, before any change, when the
database is missing, unmarked (any non-demo installation), when the demo directory
is absent, when `ITSM_ENVIRONMENT=production`, or when `--output` already exists.
The output file is written only after the configuration was committed; each refusal
prints one JSON error on stderr, nothing on stdout, and exits `1`. Re-running `setup`
without `--output` is an idempotent update of the same rows.

The generated file contains no `alerting:` block, no `rule_files:`, no Alertmanager
target and no service discovery: one job per monitored asset, `metrics_path:
/metrics/<asset-id>`, and the fixed labels `asset_id`, `check_type`, `module` and
`dataset`. `deploy/demo/prometheus.yml` is the same shape with a deliberately
invalid asset id for reference; always generate the real file.

### 2. Start the exporter

```bash
.venv/bin/python -m itsm.demo exporter --directory "$PWD/../<local-artifacts>" \
  --port 19101
```

It prints one `{"status":"ready",...}` JSON line with `host: 127.0.0.1`, the bound
port and the dataset, then serves until `SIGTERM`. `--port 0` binds a free port and
reports it. The bind address is not configurable: the server always listens on
`127.0.0.1`, and there is no proxy, no arbitrary URL and no upstream target.

| Request | Result |
| --- | --- |
| `GET /healthz` | `200 ok` |
| `GET /metrics/<asset-uuid>` | `200` node-exporter-shaped exposition for a marked demo asset configured for `node` |
| `GET /metrics`, `GET /metrics/<not-a-uuid>` | `400` with the exact reason |
| `GET /metrics/<unknown-uuid>`, `GET /metrics/<canonical-but-unmonitored-asset>` | `404` with the exact reason |
| `POST`/`PUT`/`PATCH`/`DELETE` | `405` |

The body exposes `node_cpu_seconds_total` (counter, `idle` plus `user`/`system`/
`iowait` modes), `node_memory_MemTotal_bytes`, `node_memory_MemAvailable_bytes`,
`node_filesystem_size_bytes` and `node_filesystem_avail_bytes` for `mountpoint="/"`,
and `node_hwmon_temp_celsius`. Values derive deterministically from the asset id and
elapsed time, so counters increase between scrapes and rates are real. The exporter
never emits `up` or its own `asset_id`/`check_type` labels: Prometheus adds `up`,
`instance` and `job`, and the generated scrape file carries the labels. It never
writes to the database; every request re-reads the durable demo marker and refuses
a database that lost it.

### 3. Pinned, isolated Prometheus container

Use the **same port** for `--exporter-port` in step 1 and `--port` in step 2; the
generated file names exactly that port. A Docker bridge network cannot do this:
with `-p 127.0.0.1:19091:9090` a scrape of `127.0.0.1:<exporter-port>` inside the
container would reach the container itself, not the host exporter, and every target
would stay down. The verified topology shares the host network namespace and still
binds the Prometheus web listener to loopback:

```bash
docker run -d --rm --name itsm-demo-prometheus --pull=never \
  --network host \
  --read-only --security-opt no-new-privileges --cap-drop ALL --tmpfs /tmp:mode=1777 \
  -v "$PWD/../<local-artifacts>:/etc/prometheus/prometheus.yml:ro,Z" \
  --entrypoint /bin/prometheus \
  prom/prometheus:v3.14.0@sha256:5ce7540c3c00ef4ab0c9d2c995c6a5b9c421f44b4a115d97a2c7af3b1c21cbb0 \
  --config.file=/etc/prometheus/prometheus.yml \
  --web.listen-address=127.0.0.1:19091 \
  --storage.tsdb.path=/tmp/prometheus \
  --storage.tsdb.retention.time=2d
```

* `--network host` is what lets the generated `127.0.0.1:<exporter-port>` targets
  reach the exporter. There is no `-p` flag, because publishing a port does not help
  here; `--web.listen-address` keeps the Prometheus UI and API on loopback anyway.
* `:ro,Z` is required on Fedora with SELinux enforcing; the config is only read.
* The TSDB lives on the container's tmpfs, so nothing persists, no host volume is
  reused and stopping the container discards the demo history.
* There is no `alerting:` block, no `rule_files`, no Alertmanager and no service
  discovery: this instance can only scrape and store, never notify.
* `docker stop itsm-demo-prometheus` removes only this container (`--rm`).

Run the API and worker against the demo database with settings that cannot reach
production systems: `ITSM_DATABASE_URL` pointing at the demo `demo.db`,
`ITSM_PROMETHEUS_URL=http://127.0.0.1:19091`, `ITSM_ALERTMANAGER_URL` unset, and
separate `ITSM_TASK_SQLITE_PATH`, `ITSM_ATTACHMENT_STORAGE_PATH` and
`ITSM_EXTENSION_WORKSPACE_PATH` directories. Leave agent/provider tokens and
`ITSM_EXTENSION_VALIDATOR_URL` empty so no external provider or executor is
configured. External notification channels stay blocked by the database marker even
if a demo operator creates one, and this Prometheus has no Alertmanager to send to.

```bash
curl -s 'http://127.0.0.1:19091/api/v1/query?query=up' | head -c 400
curl -s 'http://127.0.0.1:19091/api/v1/query?query=node_memory_MemTotal_bytes' | head -c 400
```

The first minute is enough for `up{job="demo-node-<id8>"} = 1`, because that series is
generated per scrape. The Database series take longer: the monitoring service reads a
24h window in 289 second steps, so its last evaluation point trails the newest scrape
by up to 278 seconds and `metric_series` legitimately returns no point until that much
history exists. Wait about five minutes before expecting CPU, memory, disk or
temperature points; the absence is not a configuration error.

The opt-in script `tests/demo_telemetry.py` performs this whole chain by itself and
asserts the measured result through the canonical read paths:

* exporter ready on `127.0.0.1:<free exporter port>` with an increasing
  `node_cpu_seconds_total{mode="idle"}` counter;
* Prometheus reporting `up{job="demo-node-<id8>"} = 1` for that exact target and
  storing `node_memory_MemTotal_bytes`;
* `MonitoringService.get_device` returning `status: up`, real `uptime`, and series
  points from the adapter's range query;
* `DashboardService.summary` returning the measured availability, monitored count
  and the device row for that asset.

It creates its own container name, config file and ports, refuses to run while
`ITSM_PROMETHEUS_URL` is set (so it never queries an existing instance), never pulls
an image, and stops only the container it started. The interface still shows the
persistent demo notice described above; the Dashboard widget itself does not label
individual samples as synthetic.
