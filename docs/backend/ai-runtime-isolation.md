# AI runtime isolation

This note is the operator contract for ordinary-User conversational inference.
It covers the API-to-broker connection, the host broker process, the per-run
container boundary and the failure modes that must stay fail-closed.

[Agent integrations and conversational control](agent-integrations.md) owns the HTTP chat contract. [External agent engines](external-engines.md)
owns installed Hermes/OpenCode engines, which remain an administrator surface.

## Trust boundary

```text
browser -> API container (no Docker authority)
                    |
                    | WebSocket + bearer token
                    v
           host broker process (Docker authority)
                    |
                    | docker run, one container per run
                    v
           read-only User container (no DB, no host files)
                    |
                    | provider network through the dedicated egress path
                    v
                 model endpoint
```

The API resolves the signed-in human and performs every canonical tool call. It
never receives or mounts `/var/run/docker.sock`, never starts a process, and
never falls back to an in-process provider for an ordinary User. The broker is
the only component that may launch containers; it has no application database
access and never accepts a caller-supplied image, command, network, mount or
environment.

An active `admin` or `superadmin` may still use the built-in in-process Pydantic
runtime. Every other human — including a demoted administrator with an older
browser session — is limited to the isolated Pydantic runtime. External
Hermes/OpenCode discovery, instance creation or update, preference switching,
session creation and turns return `403` for those roles.

## API configuration

| Variable | Required | Meaning |
| --- | --- | --- |
| `ITSM_AI_BROKER_URL` | paired | Broker WebSocket URL, for example `ws://host.docker.internal:19132/runs` or a private address reachable from the API container |
| `ITSM_AI_BROKER_TOKEN` | paired | Shared bearer secret, at least 32 characters, no whitespace |

`ITSM_AI_BROKER_URL` and `ITSM_AI_BROKER_TOKEN` are both-or-neither. Configuring
only one is a startup validation error. The token is a secret: inject it from
the operator environment, never from source, an image layer, an API request or a
checked-in file. It is redacted from settings serialization and must not be
logged.

The URL should stay on a private/loopback network shared only by the API and the
broker. Do not point it at a public endpoint and do not put credentials in the
URL; the bearer header is the only credential.

## Broker configuration

The broker entry point is:

```bash
python -m itsm.agents.runtime_broker
```

It reads only server-side environment variables:

| Variable | Required | Default | Meaning |
| --- | --- | --- | --- |
| `ITSM_AI_BROKER_TOKEN` | yes | — | Must exactly match the API token |
| `ITSM_AI_BROKER_IMAGE` | yes | — | Worker image reference; no shell text |
| `ITSM_AI_BROKER_COMMAND` | yes | — | Bounded argv appended to the image, normally `python -m itsm.agents.isolated_worker` |
| `ITSM_AI_BROKER_NETWORK` | no | `bridge` | Dedicated Docker network for provider egress; never `host` |
| `ITSM_AI_BROKER_MEMORY` | no | `256m` | Per-container memory limit |
| `ITSM_AI_BROKER_CPUS` | no | `0.5` | Per-container CPU limit |
| `ITSM_AI_BROKER_PIDS_LIMIT` | no | `64` | Per-container PID limit |
| `ITSM_AI_BROKER_HOST` | no | `127.0.0.1` | Literal bind address |
| `ITSM_AI_BROKER_PORT` | no | `8765` | Listen port |
| `ITSM_AI_BROKER_PATH` | no | `/runs` | Authenticated WebSocket path |
| `ITSM_AI_BROKER_DOCKER` | no | `docker` | Docker binary path |
| `ITSM_AI_BROKER_START_TIMEOUT` | no | `20` | Seconds to accept the start frame |

Example host launch (values shown as placeholders; keep the token out of shell
history and process listings where possible):

```bash
ITSM_AI_BROKER_TOKEN="<shared-secret>" \
ITSM_AI_BROKER_IMAGE="<worker-image>" \
ITSM_AI_BROKER_COMMAND="python -m itsm.agents.isolated_worker" \
ITSM_AI_BROKER_NETWORK="<dedicated-egress-network>" \
ITSM_AI_BROKER_HOST="127.0.0.1" \
ITSM_AI_BROKER_PORT=19132 \
python -m itsm.agents.runtime_broker
```

The API container must be able to reach that host and port. The broker process,
not the API, owns Docker access and must run as a dedicated service account. Do
not expose the broker port publicly; authenticate every connection with the
shared bearer token.

## Per-run container contract

The broker starts a fresh container for each WebSocket run and removes it
afterwards. It passes the run start frame on the container's stdin and uses a
bounded JSON-lines protocol over stdin/stdout. The start frame carries the
server-resolved provider selection, prompt, history and canonical tool schemas;
the worker has no database, filesystem, shell or HTTP tools.

Docker arguments are fixed by the broker and include:

- `--read-only`, a small `noexec,nosuid` `/tmp` tmpfs, and `--user 65534:65534`
- `--cap-drop ALL` and `no-new-privileges`
- `--pids-limit`, `--memory`, `--cpus` and a file-descriptor ulimit
- the configured dedicated network, never `--network host`
- no `-v`/`--mount`, no `-e`/`--env`, no published ports, no `--privileged`

The provider secret and endpoint are delivered to the worker only in the run
start frame. They do not appear in argv or the base image environment. The
worker may request only a canonical tool name and arguments; the API validates
both against its own toolset and performs the call under the requesting
principal. A container compromise cannot widen its tool set, read the ITSM
database or read host files.

Each human gets a container name derived from a hash of the user id and the run
id, with `itsm.ai.user` and `itsm.ai.run` labels. Two users never share a
container or a run. Sessions and transcripts remain in the API database, not in
the container.

## Fail-closed behavior

- Broker URL or token absent: ordinary-User chat and built-in session turns
  return `503` and no model call or container is attempted. Administrators may
  still use the in-process runtime.
- Broker unreachable, wrong token, connection timeout or rejected handshake:
  `503` with a sanitized message. The API does not retry in process.
- Worker exits, times out, emits malformed frames or requests an unknown or
  out-of-schema tool: the run ends with a sanitized error; tool calls outside the
  API toolset are never executed.
- Provider failure: the worker reports only the exception class name and a
  sanitized message. Prompts, headers, provider URLs and keys never enter logs.
- A demoted or deactivated human loses external and isolated access on the next
  request because the persisted identity is reloaded for every turn.

## Cleanup and known root cause

The API closes the per-turn runtime in the SSE stream's `finally` block. The
isolated runtime originally exposed a synchronous `aclose`, so `await
owned_runtime.aclose()` raised `TypeError` and logged:

```text
agent provider client could not be closed
```

`IsolatedRuntime.aclose` is now `async`, matching `AgentRuntime`; the broker owns
all transport cleanup and the method is intentionally a no-op. The warning was
not suppressed. A worker image built before that source change still contains
the synchronous method, so rebuild and redeploy the worker/API image before
expecting the warning to disappear.

## Daily quota admission inside the isolated worker

The API reserves a durable run receipt before dispatch. Each paid model request
then crosses the existing broker bridge with `quota.call` (`reserve` or `settle`)
and a matching `quota.result` acknowledgement. The worker cannot call the model
until the parent confirms admission. The parent derives the actor, funding,
original local day and context/output bounds from its own run; it never accepts
these authorities from a worker frame. Unknown or duplicate call identifiers
and mismatched/negative acknowledgements fail closed.

Provider evidence settles each child receipt, not the accumulated session
counter. Missing usage, cancellation or an uncertain provider outcome retains
the reservation. Ending a runtime only releases an unused pre-dispatch sentinel;
it does not refund potentially active calls. Personal provider selection charges
only the personal policy, even when the company limit is zero.

`ITSM_AGENT_CONTEXT_TOKEN_BOUND`, when supplied, is an operator declaration,
not a tokenizer count. Trusted admission serializes run input excluding provider
credentials and binary image/document bodies, adds existing estimates (2048 per
image, 4096 per document), accumulated trusted tool-result bytes and prior output
caps, then the next output cap. Text attachments, history and schemas retain
their floor; worker-declared values cannot lower it. Attachment byte/count/frame
limits still apply. Flat modality estimates cannot bound every provider, image
resolution or document page count: this is admission accounting, not a strict
token/billing upper bound.

The API enforces `ITSM_AGENT_MAX_STEPS * 4` trusted tool calls and one absolute
monotonic `ITSM_AGENT_RUN_TIMEOUT_SECONDS` deadline. Repeated ready/usage frames
do not restart the deadline. Socket cleanup occurs on success and rejection.
A synchronous in-process trusted tool cannot safely be forcibly interrupted:
if it overruns, the API rejects continuation when it returns. This is not a hard
wall-clock cancellation guarantee for blocking tools; no new supervisor/thread
killer is introduced.

### Multimodal admission estimate boundary

Binary image/PDF accounting uses the existing 2048/4096 estimate, raised to the
UTF-8 byte size of readable runs of at least 64 characters in the decoded body.
Control/invalid bytes separate runs; they do not erase a long neighboring text
run. Thus merely labelling a long plain-text body as PNG/PDF does not obtain the
flat estimate. The accounting copy does not alter the forwarded bytes.

This heuristic is not file validation or a universal token/billing upper bound.
Compressed/encoded text, text split into short runs and genuine multimodal token
costs are provider-dependent and can exceed the reservation. Ordinary text,
history, schemas and tool results retain their full serialized byte floor. The
configured context declaration, existing attachment byte limits and output cap
remain independent controls; measured usage settles through the existing ledger,
and unavailable usage keeps its unresolved hold. No tokenizer is installed.
