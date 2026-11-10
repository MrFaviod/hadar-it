# Notifications

Monitoring alerts reach people through durable SQL work, not through the
monitoring request or an in-memory queue. The default experience needs no
credentials: every alert creates an owned inbox notification for each active
human identity.

## Delivery model

| State | Meaning | Automatic retry |
| --- | --- | --- |
| `pending` | queued, not attempted yet | — |
| `claimed` | a worker reserved the row for one attempt | stale claims become `uncertain` |
| `delivered` | internal inbox row exists, or Apprise confirmed success | no |
| `failed` | Apprise confirmed a non-delivery | yes, after the rule's retry interval |
| `uncertain` | the transport may have delivered: exception, timeout or partial result | **never** |
| `exhausted` | unconfigured channel, disabled channel, attempts spent, or retention | no |
| `suppressed` | the alert was acknowledged or recovered before delivery | no |

The outbox unique key contains the alert, the stable event row, the rule, the
recipient, the channel and the escalation bucket. The same key therefore cannot
be inserted twice by retries, concurrent schedulers or duplicate alert payloads.
A repeated `(alert_id, event_key)` ingestion is a no-op.

SMTP and Telegram cannot prove exactly-once delivery after a lost
acknowledgement. An ambiguous attempt is retained as `uncertain` for an
operator; it is not resent blindly. A confirmed failure is retried up to
`maxAttempts`. Only failures that prove nothing left the process are confirmed:
an SMTP preflight TCP refusal or DNS failure, Apprise authentication refusal,
or an explicit HTTP 4xx response. A generic connection reset or HTTP 5xx stays
`uncertain` because the peer may already have accepted the request.

External messages include the alert title, body and the canonical record URL so
the recipient can open the corresponding alert. The URL is the record link, not
the Apprise service URL; the service URL and any credentials are never part of
the message.

## Default configuration

Migration `0017_notifications` installs:

* `internal-default` — the internal inbox channel, enabled, no secret.
* `default-operations` — enabled, minimum severity `info`, channel
  `internal-default`, all active human identities (an empty recipient list on
  the built-in rule means *everyone active*), retry every 60 s, 3 attempts,
  escalation disabled.
* `notification_runtime_state` row `1`, used as the serialized SQL maintenance
  lock.

Tests and deployments can add SMTP or Telegram channels later. The internal
channel keeps working regardless.

## Secret references

External channels store `secretRef` and a non-secret `config` only. The
reference is resolved from `ITSM_MONITORING_SECRETS`, a JSON object of
`reference -> secret` supplied by the deployment process environment. The API
returns `secretRef` and `configured` (boolean) but never the value.

Allowed channel configuration:

| Kind | `config` |
| --- | --- |
| `internal` | `{}` |
| `smtp` | `{"subjectPrefix"?: string}`; the secret is a `mailto://` or `mailtos://` Apprise URL |
| `telegram` | `{"chatId"?: string}`; the secret is a bot token, or a complete `tgram://` URL |

Only these two Apprise schemes are accepted. A stored secret cannot turn the
endpoint into a generic arbitrary-URL notifier. Apprise plugin exceptions,
URLs and tokens are reduced to bounded codes (`transport_failure`,
`transport_timeout`, `channel_unconfigured`, …) before logging or storage.
Apprise's and the HTTP transports' own loggers are silenced for the duration of
each plugin call because they emit full service URLs at debug and warning
levels; classification uses the result's structured log entries instead.

## Rules

A rule selects a minimum severity, recipients, channels, an optional local
schedule, a retry interval, an acknowledgement window and an escalation delay.
`escalateAfterSeconds > 0` requires at least one escalation recipient. External
channels deliver once per event/channel; internal channels deliver once per
recipient.

Recipients are canonical identity IDs. They must exist, be active and be human
identities; machine identities are rejected. Rule and channel ids are optional
on create; sending an id updates that record. Disable with `enabled: false`.
There is no delete endpoint.

`schedule` is `null` (always) or
`{"timezone": "America/Costa_Rica", "start": "08:00", "end": "18:00"}`. Windows
may cross midnight. Delivery is deferred to the next opening; an in-window
notification is immediate. Acknowledgements and recoveries are ingested and
suppression applies immediately even outside the window.

## Acknowledgement, recovery and escalation

* `acknowledged` (or an `acknowledged` event type) marks the cycle acknowledged,
  suppresses its `pending`/`failed` rows and prevents escalation. No delivery
  is produced for the acknowledgement itself; the operator already knows.
* `recovered` marks the cycle recovered, suppresses the firing cycle's pending
  rows, then enqueues the recovery notification under the same rules unless the
  cycle is already acknowledged or monitoring suppression is active. Both flags
  are retained when an acknowledged cycle recovers during a silence or window.
* Escalation looks for events older than
  `acknowledgeAfterSeconds + escalateAfterSeconds` that are neither acknowledged
  nor recovered, have at least one bucket-0 row for the rule and no bucket-1 row
  yet. It enqueues the escalation recipient set once per event, channel and
  recipient. A later acknowledgement stops further escalations because the event
  is marked acknowledged.
* There is no on-call roster. If no escalation recipients are configured the
  rule simply does not escalate.

Monitoring's canonical silence/maintenance-window evaluator is also consulted
before enqueueing lifecycle messages, before claiming pending/failed delivery,
and before creating escalation rows. New firing messages during suppression are
dropped, not replayed later. Previously queued work remains pending during a
silence or active window, without transport calls or retry-attempt changes. It
can resume at expiry only if no acknowledgement or recovery has superseded it.
Those lifecycle changes suppress queued work permanently even while silenced;
expiry never resends the old firing cycle. Immediate internal inbox delivery
still happens in the ingestion transaction when eligible, and delivered inbox
rows are neither withdrawn nor duplicated by later suppression.

## Processing and retention

`record_alert_event(session, settings, ...)` writes the event, inbox rows and
outbox rows inside the caller's transaction and **never commits** it. Monitoring
commits once; a crash leaves either everything or nothing.

`process_notifications(settings, as_of=None)` opens its own session, claims due
rows with a conditional `UPDATE`, commits the claim before calling Apprise, then
records the outcome. A worker that dies after the claim leaves an `uncertain`
row instead of a duplicate send. The same function runs escalation and
retention, so there is one scheduler and no parallel queue.

Retention (`ITSM_NOTIFICATION_RETENTION_DAYS`, default 90) retires overdue
`pending`/`failed` rows, removes old terminal outbox/inbox rows, and deletes old
events with no remaining outbox row. Work is bounded per run.

## Language

Notification text follows the **recipient**, not the request that produced it.
An event stores a language-neutral message — `message.title`/`message.body` as
`{"key", "params"}` catalog keys — in the additive `notification_events.message`
column (migration `0040_notification_i18n`). Fan-out renders it once per
recipient in that person's effective locale (`Identity.locale`, or the
installation default), and the rendered text is what the inbox row and every
Apprise/SMTP payload contain. External channels therefore enqueue one outbox row
per recipient; `recipient_id` stays `NULL` only when no recipient resolves.

Two rules keep stored history honest: an event without `message` (any row
written before this column existed) is delivered exactly as its stored
`title`/`body`, and free text such as an alert summary or an asset name is never
translated. Monitoring builds its keys from `api.monitoring.alert.*`, and the
sample message from `POST /notifications/channels/{id}/test` uses
`api.notifications.test_*`. The inbox DTO is unchanged and still returns the
rendered `title`/`body`; see `docs/backend/i18n.md` for the shared seam.

## HTTP API

All payloads are camelCase and lists use `{items,total,limit,offset}`.

| Method | Path | Permission |
| --- | --- | --- |
| `GET` | `/api/v1/notifications/inbox?limit=50&offset=0&unread=true` | `assets.view` |
| `POST` | `/api/v1/notifications/inbox/{id}/read` | `assets.view`, own notification only |
| `GET` | `/api/v1/notifications/config` | `config.integrations` |
| `POST` | `/api/v1/notifications/channels` | `config.integrations` |
| `POST` | `/api/v1/notifications/rules` | `config.integrations` |
| `POST` | `/api/v1/notifications/channels/{id}/test` | `config.integrations` |

`test_channel` enqueues one real delivery to the deployment-configured
destination and returns `202 {"channelId", "outboxId", "state": "pending"}`. It
never claims delivery. For an internal channel the test message appears in the
caller's inbox after processing; for external channels the outcome is recorded
in the outbox and only failure/uncertainty is logged as a code.

Configuration changes call the existing identity `record_operation` audit path
and commit once. `mark_read` commits its own read state. Notification inbox
access is always scoped to `principal.actor_id`; another user's notification is
reported as not found.
