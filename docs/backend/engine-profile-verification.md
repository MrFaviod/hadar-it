# Engine profile verification

This note records the supported OpenCode 2.1.2 profile contract used by the
installer. It is deliberately narrower than "the engine started": evidence must
prove the runtime is bound to the selected workspace, the managed ITSM agent and
MCP endpoint are effective, and only selected ITSM skills are available.

## Official protocol facts

- `GET /api/config` returns `Config.Entry[]`. A `document` entry has
  `{type, path?, info}`; a `directory` entry has `{type, path}`. The official
  loader always attaches a `path` (`packages/core/src/config.ts:142-148,211-216`).
  Directory entries can precede the target document in the returned list.
- `GET /api/agent/{agentID}` returns `{location, data: Agent.Info}`;
  `Agent.Info` requires `id`, `name`, `mode`, `hidden`, and `permissions`.
- `GET /api/skill?location[directory]=...` returns
  `{location: {directory}, data: Skill.Info[]}`. `Skill.Info` requires `id`,
  `name`, `path`, and `content`. Skill IDs come from the skill directory name
  (`packages/core/src/config/plugin/skill-file.ts`).
- OpenCode registers embedded `opencode.skill` and report skills at
  `/builtin/*` on every runtime. An exact "only these skill entries exist"
  check is impossible; the restricted agent's last-match `skill * deny` makes
  all unselected skills unavailable.
- Config sources are folded in this order: managed policies, wellknown,
  global directory, explicit file, direct project files, project `.opencode`
  directories, content, managed settings
  (`packages/core/src/config.ts:281-290`). The inspector therefore accepts only
  the selected `.opencode` directory plus the selected configuration document.
  Any additional directory or document is a broader authority and fails.

## Supported startup controls

`serve` itself exposes only hostname/port/CORS/service/stdio
(`packages/cli/src/commands/handlers/serve.ts:10-15`). The server process maps
these environment variables into `Config.Options`
(`packages/cli/src/server-process.ts:121-133`):

| Variable | Required value for a selected profile | Effect |
| --- | --- | --- |
| `OPENCODE_CONFIG_DIR` | `<workspace>/.opencode` | global config directory; also the directory entry whose `skills/` tree is scanned |
| `OPENCODE_CONFIG` | `<workspace>/opencode.json` | explicit selected document written by the installer |
| `OPENCODE_CONFIG_PROJECT_DISABLE` | `1` | disables the ancestor/project walk (`config.ts` option `project: false`) |
| `OPENCODE_DISABLE_CLAUDE_CODE` | `1` | disables `.claude` roots (the `_SKILLS` variant is an equivalent alias); project `.agents` roots disappear with the project walk, while the user-global `.agents` root remains and its unselected skills stay denied |

`OPENCODE_CONFIG_CONTENT` must not be set for a verified profile: it adds a
document with no path and the inspector rejects it. `OPENCODE_TEST_HOME` is a
test-only path (`packages/util/src/global.ts:17`); do not use it in production.
The platform system directory (`/etc/opencode`) and the user's global `.agents`
skill root are not removable by these server flags. The strict `Config.Entry`
check fails closed if the system directory contributes an entry, and any
unselected `.agents` skill remains denied by the agent ruleset. Do not weaken
the inspector because an uncontrolled inherited source exists.

## Evidence shape

The runtime inspector must project, and the installer must revalidate:

- `source`, `verified`, `configDigest`, `targetPath`, `location.directory`,
  non-empty passing `checks`;
- `agent`: `id=itsm`, selectable `mode`, `hidden=false`, effective permissions
  containing `* * deny`, only `itsm_*` allows, and exactly the selected skill
  allows;
- `config`: exactly one `directory` entry at
  `<target>/.opencode` and exactly one `document` entry at
  `<target>/opencode.json` (or `.jsonc`) whose effective `default_agent` is
  `itsm`;
- `skills`: the `/api/skill` location/data envelope. Each selected skill appears
  once with `id == selected name` and a path equal to
  `<target>/.opencode/skills/<name>/SKILL.md`; every other listed skill must
  evaluate to `deny` under the combined agent plus saved rules;
- `savedPermissions`: no `ask`, no allow outside ITSM tools or selected skills.

Synthetic/caller-supplied evidence never verifies. A missing trusted inspector
returns `configured` with `profileSafetyVerified=false` and a failing
`profile.safety` check.

## Hermes

Hermes 0.22.5 native serve is a dashboard JSON-RPC/WebSocket API, not the
`/v1` HTTP API. The connector uses:

- `POST /auth/password-login` with the bundled `basic` provider and the
  dashboard username/password, then `POST /api/auth/ws-ticket` and
  `GET /api/ws?ticket=...`;
- for a loopback serve with authentication disabled, the process token published
  at `/` and `GET /api/ws?token=...`, only when the page explicitly reports
  `__HERMES_AUTH_REQUIRED__ = false`;
- `model.options`, `session.create` (`source: "cli"`), `session.resume`,
  `session.interrupt`, and `prompt.submit`;
- `config.set` with a session-scoped
  `"<model> --session --provider <provider>"` value, rejecting
  `confirm_required` instead of assuming the switch applied;
- `tools.list`, `mcp.servers.list`, and `skills.manage` for inspection. The
  connector creates a disposable `session.create` with `source: "cli"` and
  `close_on_disconnect: true`, calls `tools.list` with that runtime session id
  (so the launch-bound `HERMES_HOME` profile applies instead of the dashboard
  profile roster), then closes and deletes the stored session. `skills.manage`
  and `mcp.servers.list` are called without a profile override. The reported
  surface includes every enabled toolset and every enabled MCP server,
  including plugin-provided servers, and requires at least one
  `mcp__itsm__*` tool.

The server does not expose `runtime.describe` on the dashboard `/api/ws`
sidecar (`-32601`). `profiles.list` is a roster: it reported the root profile as
`is_default=true` while the process ran with `HERMES_HOME` pointing at the
`itsm` profile. `profiles.describe(name)` reads any named profile. Neither is an
active-HOME proof. The dashboard also has no official active-profile
attestation, so installer verification is based on a trusted launcher
attestation plus live native surface inspection.

### Trusted launch contract

The `profile_inspector` callback is the trust boundary. A Hermes inspector must
be supplied by the host/service and must return:

```json
{
  "source": "hermes:http://127.0.0.1:<port>",
  "verified": true,
  "configDigest": "<sha256 of the managed config>",
  "targetPath": "<realpath of the selected profile home>",
  "checks": [{"name": "runtime.profile", "status": "pass", "detail": "..."}],
  "launch": {
    "protocol": "itsm-hermes-launch-v1",
    "profileHome": "<same realpath>",
    "endpoint": "http://127.0.0.1:<port>",
    "launchId": "<host launch identity>",
    "processId": 1234,
    "configDigest": "<same digest>"
  },
  "runtime": {
    "protocol": "hermes-native-serve-v1",
    "profileHome": "<same realpath>",
    "endpoint": "http://127.0.0.1:<port>",
    "toolsets": ["itsm", "skills"],
    "mcpServers": [{"name": "itsm", "url": "<managed URL>", "enabled": true}],
    "skills": ["hermes-agent", "itsm-inventory"]
  }
}
```

The launcher must record `HERMES_HOME`, endpoint, child process identity, and
the config digest before the child accepts native requests. The installer
validates the receipt and compares the live native `tools.list` (enabled
toolsets only), `mcp.servers.list`, and effective skill list with the config.
It requires a loopback endpoint and a matching digest/target, and rejects extra
toolsets, MCP servers, or skills. `hermes-agent` is the one documented
upstream-essential builtin (`ESSENTIAL_SKILLS`) that cannot be disabled; when
skills are selected the allowlist is exactly the selected catalog skills plus
that builtin, with no other native tools or permissions. The installer writes
the remaining profile-local bundled skill names to `skills.disabled` (union
with pre-existing user-disabled names, preserving them for uninstall), so an
already-provisioned `HERMES_HOME` does not keep every bundled skill enabled.
The receipt is trusted because only the
host-controlled inspector can reach this gate; caller-supplied
`profile_safety` evidence is rejected. A missing or incomplete receipt keeps
the installation `configured`, with `profileSafetyVerified=false`.

The native MCP server configuration uses only `url`, `headers`, and `enabled`.
`tools` is an MCP tool include/exclude map, not a protocol-feature switch; the
installer does not write prompts/resources flags. The CLI toolset allowlist is
`platform_toolsets.cli: [itsm, skills]`; existing conflicting `cli` values are
a conflict rather than being overwritten.

## Native conversational events

For OpenCode 2.1.2, the event contract is as follows. `session.tool.input.started` declares the
tool name; subsequent called/success/failed events correlate through the call
ID. `session.execution.succeeded` completes the turn while the global SSE
connection remains open. A step-ended event does not complete the turn.
