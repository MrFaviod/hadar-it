# Disposable managed native runs

`itsm.agents.managed` launches one throwaway native Hermes or OpenCode `serve`
process per managed AI run, binds it to the ITSM gateway with a run-scoped key
and destroys its private profile afterwards. It never reuses a shared instance,
never edits a shared instance's provider settings. Its generated profile and
explicit child environment contain gateway/MCP identities, not a real provider
credential; the child is not prevented from reading host files.

The upstream provider a run spends through is chosen by the ITSM service before
the child starts, never by the native process. A session uses the instance's
managed global provider by default, or the selecting person's own personal
provider when that session was pinned to it (see “Personal providers” below).
Either way the native process only ever receives the run-scoped gateway key, so
no personal provider secret is written to a shared instance, the disposable
profile, the child environment, event payloads or logs.

The gateway (`itsm.ai_gateway`) enforces budget admission, model pinning, output
caps and per-call accounting. This runner owns process/profile placement and the
native transport. It cannot prove the native process has no other egress route,
so the capability it reports is always `admission_only`, never `strict`.

## API

```python
from itsm.agents.managed import (
    ManagedEngineRunner,
    ManagedEngineSettings,
    ManagedProfileInputs,
)

runner = ManagedEngineRunner(
    ManagedEngineSettings(
        hermes_binary=settings.ai_managed_hermes_binary,
        opencode_binary=settings.ai_managed_opencode_binary,
        profile_root=settings.ai_managed_profile_root,
        startup_timeout_seconds=settings.ai_managed_startup_timeout_seconds,
        shutdown_timeout_seconds=settings.ai_managed_shutdown_timeout_seconds,
    ),
    instance,                     # .engine is "hermes" or "opencode"
    lease,                        # .lease_id, .bearer_token, .run_id, .model,
                                  # .context_tokens, .output_tokens
    gateway_v1_url,               # e.g. http://127.0.0.1:8000/api/v1/agent/gateway/v1
    profile=ManagedProfileInputs(
        mcp_url=canonical_mcp_url,
        mcp_token=resolved_integration_secret,
        skill_packages=selected_catalog_packages,  # name -> {relative path: bytes}
        skill_paths=verified_skill_directories,
        project_root=project_root,
    ),
)
```

`ManagedEngineSettings` fields are server configuration only. `lease` is
duck-typed so the gateway's `IssuedLease` can be passed unchanged: its identifier,
opaque bearer token, run id, model and positive integer context/output bounds are
required. Booleans, missing/nonpositive bounds and values above the gateway's
existing ceilings fail before a profile or process is created. Binary names may
be absolute paths or `PATH` lookups; a missing, non-executable or unconfigured
binary fails closed.

`gateway_v1_url` must be a credential-free `http(s)` URL whose path ends in
`/v1`; that is the OpenAI-compatible base the gateway serves. Query strings,
fragments and embedded userinfo are rejected, and the URL is never derived from
chat input.

`ManagedProfileInputs` is the only profile material the runner accepts:

- `mcp_url` and `mcp_token`: the canonical ITSM MCP endpoint and the resolved
  integration-identity secret. Both must be present or both absent. The token is
  supplied to the child as an environment variable (default
  `ITSM_AGENT_MCP_TOKEN`) and only an environment reference is written to disk.
- `skill_paths` and `project_root`: verified skill directories (`SKILL.md`
  present, regular files only, no symbolic links) that must resolve inside the
  project root.
- `skill_packages`: a mapping of verified catalog skill name to its complete
  relative-path -> bytes file map, exactly as `SkillCatalog.get_skill(name)`
  returns it. Packages are self-contained, so `project_root` is not required and
  they may originate outside the project. Every path must be a relative POSIX
  path without `..`, backslashes or control characters, `SKILL.md` must be
  present, file/directory conflicts are rejected, and every file is written
  byte-for-byte without re-encoding. Limits are 2 MiB and 200 files per skill,
  and 20 skills, 8 MiB and 600 files per profile; path and package skill names
  share one case-insensitive namespace.

Provider credentials, a client-supplied URL/key/model or argv fragments have no
API surface here.

## Provider binding (global or personal)

Managed sessions are created or switched with the existing session contract. An
optional `providerId` selects the provider that the run's gateway lease will
spend through:

```json
POST /api/v1/agent/sessions
{"instanceId": "<managed instance>", "model": "model-a", "providerId": "<provider>"}

PATCH /api/v1/agent/sessions/{id}
{"providerId": null}
```

- Omitted or `null` keeps the instance's configured managed global provider.
- A personal provider id must belong to the caller. Another person's provider id
  answers exactly like a nonexistent one (`404 not_found`, same message), so the
  API never discloses that someone else's provider exists.
- A disabled provider is rejected (`422 validation_error`); a deleted provider is
  `404` like any missing id. `providerId` on a direct (non-managed) engine is
  rejected with `422` and `direct engines cannot select a provider`; Pydantic AI
  sessions reject it as unsupported.
- The model must be one of the selected provider's configured models. Switching
  the provider without a model keeps the current model when it is still valid and
  otherwise uses the provider's first model.
- A session owner can switch between the instance's global provider and their own
  personal providers at any time; the response DTO and session summary expose
  only the stored `providerId`, which is always one the caller may use.

Every managed turn then issues its lease for that provider, with matching
`provider_id`/`provider_scope`/`provider_name` attribution. Personal scope means
personal funding and the personal balance; the gateway seals the resolved base
URL, model and API key, and the native child still sees only
`ITSM_AI_GATEWAY_TOKEN`. Direct Hermes/OpenCode instances share their configured
profile, so they never accept a personal provider selection.

## Usage

```python
runner = ManagedEngineRunner(settings, instance, lease, gateway_url, profile=profile)
try:
    await runner.start()
    session_id = await runner.create_session()
    async for event in runner.stream("…", session_id=session_id):
        ...
finally:
    await runner.aclose()
    gateway.revoke(lease.lease_id)
```

`start()` prepares a fresh profile, reserves a unique loopback port, launches the
native binary in its own session/process group, and waits for a real
authenticated discovery through the adapter, not a bare TCP probe. OpenCode must
first return authenticated, verifiable effective configuration origins. The
startup deadline is bounded; an unverified source, process exit, a non-retryable
protocol/auth failure or the deadline raises `ManagedEngineError` and tears the
run down first.

`discover`, `create_session`, `stream`, `cancel` and `close` delegate to the
existing engine adapters. `stream` is pinned: `model=None` uses the lease model
from the profile, `model=native_model` is accepted, and any other model raises
before the adapter is called. No caller can switch the run to another provider
or model.
OpenCode's source check is repeated before discovery, session creation and each
stream dispatch. A changed or unrecognized source prevents that adapter call;
cancellation and teardown remain available even when the source check fails.

`status()` returns the honest capability:

```json
{
  "mode": "managed",
  "engine": "opencode",
  "enforcement": "admission_only",
  "strict": false,
  "reason": "the run-scoped gateway key, model pinning and output caps are enforced, but the native process egress is not isolated or proven",
  "leaseId": "…",
  "runId": "…",
  "model": "itsm-quota/<model>"
}
```

## Generated profile

Each run gets a fresh `0700` directory under the configured profile root (or the
system temporary directory):

- Hermes: `HERMES_HOME` points at the profile. `config.yaml` pins
  `model.provider: itsm-quota`, `providers.itsm-quota.base_url` to the gateway,
  `key_env: ITSM_AI_GATEWAY_TOKEN`, the canonical `platform_toolsets.cli`
  allowlist (`itsm`, plus `skills` only when verified skills were supplied) and,
  when present, an `mcp_servers.itsm` entry with a bearer environment reference.
  The launch is `serve --isolated --skip-build --host 127.0.0.1 --port <free>`.
- OpenCode: `HOME`, the four `XDG_*` directories, `OPENCODE_TEST_HOME`,
  `OPENCODE_CONFIG_DIR` (`<profile>/.opencode`) and `OPENCODE_CONFIG` live in the
  profile. Project/ancestor discovery, Claude discovery and model-catalog fetching
  are disabled with the pinned native CLI controls. `opencode.json` defines the
  `itsm-quota` provider (`@ai-sdk/openai-compatible`, gateway `baseURL`,
  `{env:ITSM_AI_GATEWAY_TOKEN}` API key, the lease model only), with model
  `limit.input=context_tokens`, `limit.output=output_tokens`, and
  `limit.context=context_tokens+output_tokens`. It pins the top-level `model` to
  `itsm-quota/<model>`, reuses the installer's canonical agent permission ceiling
  and, when present, its MCP server shape. The launch is
  `serve --hostname 127.0.0.1 --port <free>`.

OpenCode 2.1.2 can still discover system configuration. The runner therefore
checks the actual `GET /api/config` array using the existing canonical ITSM
`Config.Entry` validator: exactly the owned `.opencode` directory and generated
`opencode.json` document are required. Foreign/system/ancestor, pathless,
duplicate, nested or unknown sources fail closed; a guessed response envelope
does not pass. Configuration bodies, origins and credentials are not logged or
included in exceptions. This is a **post-start, pre-ITSM-dispatch** check, not
proof that native startup code never read a foreign file or ran a plugin.

Verified skill paths and inert catalog packages are copied into the profile's
skill directory (Hermes `skills/`, OpenCode `.opencode/skills/`) as `0600`
files; package bytes are preserved exactly. Without `profile=`, the run still
gets a fresh gateway-only profile, but no MCP identity or skills are invented:
the parent must pass the verified receipt material for ITSM tools.

The child environment is rebuilt from a whitelist (`PATH`, locale, `TZ`,
`TMPDIR`) plus the profile `HOME`/`XDG_*`, the gateway key, the optional MCP
token and per-run native credentials. Inherited provider keys such as
`OPENAI_API_KEY` are dropped. The lease token is never written to the profile,
events, logs or `status()`.

Native authentication is separate from the gateway and MCP identities and is
generated fresh for every runner with `secrets.token_urlsafe(32)`:

- Hermes: `HERMES_DASHBOARD_BASIC_AUTH_USERNAME=admin`,
  `HERMES_DASHBOARD_BASIC_AUTH_PASSWORD` and
  `HERMES_DASHBOARD_BASIC_AUTH_SECRET`.
- OpenCode: `OPENCODE_SERVER_PASSWORD`.

The same username/password pair is passed to the adapter's `EngineConfig` so
discovery can authenticate; the password is never the gateway lease token or
the MCP token, and it is never persisted in the profile.

## Teardown and failure modes

`aclose()` is idempotent and shielded: even a cancelled run finishes terminating
the owned process group and deleting the profile before `CancelledError`
propagates. Teardown closes the adapter, sends `SIGTERM` to the child's own
process group (only when the child leads it), waits `shutdown_timeout_seconds`,
escalates to `SIGKILL` and waits again. The teardown boundary is the process
group, not the leader: if the leader exits first, the runner still checks the
group and escalates, so a grandchild that ignores `SIGTERM` cannot survive
profile deletion. The profile is deleted only after the group is confirmed
gone; otherwise it is kept and `teardown_failed` is raised. Processes outside the
child's group are never signalled.

Errors are `EngineError`-shaped with `retryable=False`:

| Code | Situation |
| --- | --- |
| `misconfigured` | invalid settings, lease, gateway URL, MCP/skill input, or missing/non-executable binary |
| `unsupported` | engine other than `hermes`/`opencode`, or an unknown adapter |
| `unavailable` | run not started, already active or already closed |
| `startup_failed` | child exited, discovery failed (auth/protocol) or the readiness deadline expired |
| `teardown_failed` | the owned process did not exit; its profile was retained |

There is intentionally no fallback to a shared external instance or a direct
provider. The runner never releases or refunds quota; lease revocation is the
caller's responsibility after the child has stopped, because the native process
may still finish a request in flight.

## Limitations

## Restored environment-name boundary

Managed MCP token variables cannot collide, case-insensitively, with runner-owned gateway, profile, native-authentication, base environment, or OpenCode isolation variables. Dedicated custom token variables remain supported. Inputs are rejected before a native process starts.
