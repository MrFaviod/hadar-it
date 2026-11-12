# Agent integration installer

The installer is a pure, engine-neutral boundary for writing the ITSM MCP
entry, restricted agent permissions and selected Agent Skills into an explicitly
chosen OpenCode workspace or Hermes profile. It never scans a home directory,
never writes an implicit default profile and never stores a bearer token.

## Public boundary

```python
IntegrationTarget(engine, path, profile=None, version=None)
IntegrationInstaller(catalog=None)
await detect_target(target) -> dict
await apply(
    target,
    *,
    mcp={"url": ..., "secretRef": "ENV_VAR", "identityId": ...},
    skills=["itsm-inventory", ...],
    operation="install",
    profile_inspector=None,  # trusted in-process async callable
) -> dict
```

`target.path` must be an absolute OpenCode workspace or Hermes profile root.
OpenCode supports the detected v1 and v2 schemas separately. Hermes requires an
explicit version with a supported MCP-header capability floor of `0.16.0`.
`mcp.secretRef` is an environment-variable name; the value is resolved only for
the MCP proof and is never written to configuration, a receipt or a log.

OpenCode v2 stores the managed remote server under the lowercase
`mcp.servers.itsm` key and writes its canonical fields `disabled` and
`codemode: false`. It never writes the v1-only `enabled` field. Disabling code
mode exposes the direct MCP tools, whose effective action names derive from the
lowercase server and tool names (`itsm_<tool>`), matching the restricted
`itsm_*` allow rule without granting the generic `execute` action. OpenCode v1
retains its `mcp.itsm.enabled` schema. Both generations are validated against
their generated entry, state and headers during profile verification.

`profile_inspector` is the only accepted source of runtime-profile proof. It is
an in-process async callback, so it cannot be supplied through JSON, a remote
helper request, an HTTP receipt or any other untrusted channel. The legacy
`profile_safety` keyword remains callable for compatibility but is never treated
as evidence; supplying it cannot produce `verified`.

Operations are `install`, `update`, `repair`, `verify`, `disable` and
`uninstall`. Successful mutation receipts use `configured`, `disabled` or
`removed`. `verified` is reserved for a receipt that has both a successful live
MCP proof and runtime profile evidence bound to the current configuration.
Conflicts and unsafe paths preserve all existing bytes.

## Managed state

The installer owns only:

- the lowercase `itsm` MCP server entry and restricted `itsm` agent sections;
- `default_agent: itsm` when it created that key;
- the selected skill files under the target's skills directory;
- `.itsm-agent/manifest.json`, with file digests, configuration digest, MCP
  metadata and created keys.

User configuration, unrelated MCP servers, unrelated agents, comments and
unmanaged files are preserved. Every write is staged through a rollback-safe
transaction. Duplicate JSONC keys, mixed OpenCode generations, malformed
configuration and symlinked managed paths fail before any write.

`repair` restores managed skill files that were changed or removed. `update`,
`verify`, `disable` and `uninstall` refuse to overwrite or delete a managed
skill whose digest no longer matches. `uninstall` removes the managed entries
from a configuration that a user has edited outside the installer, preserving
that user-authored content.

Reapplying identical inputs to a freshly configured target is byte-idempotent.
The manifest keeps the first installation's `existsBefore` provenance even
after the managed configuration file exists, so retries neither claim a
user-owned pre-existing file nor change the manifest on a repeated identical
apply.

## MCP proof

`verify_connection` performs a real FastMCP client handshake and an authorized,
non-mutating `search_assets` query with the configured bearer token. A passing
handshake proves only that the selected MCP endpoint answered; it does not prove
that the engine is running the selected workspace/profile.

## Runtime profile evidence

Configuration inspection alone cannot prove the connected engine process loaded
the selected profile. The hosting application may pass a trusted in-process
callback:

```python
async def profile_inspector(*, target, mcp, skills, config_digest):
    # Authenticated engine calls bound to the exact target and config digest.
    return evidence  # or None when the engine is unreachable/unsafe
```

The installer invokes it after writing and confirming the managed configuration,
passing the exact `IntegrationTarget`, MCP metadata, selected skill names and
SHA-256 `config_digest`. The callback must return evidence bound to those values,
or `None`. Missing callbacks, exceptions, `None`, non-mapping results, a digest
mismatch or a failed check leave the receipt at `configured` with a failed
`profile.safety` check. There is no success fallback.

A caller-supplied `profile_safety` mapping is never evidence, even when it has a
plausible `source`, `configDigest` or checks. HTTP/request data and remote helper
receipts cannot provide this callback.

Common returned fields:

```python
{
    "source": "opencode:http://127.0.0.1:15672",  # or "hermes:http://..."
    "verified": True,
    "configDigest": receipt["configDigest"],
    "targetPath": "/absolute/selected/target",
    "checks": [{"name": "runtime.agent", "status": "pass", "detail": "..."}],
}
```

### OpenCode

The evidence must come from authenticated calls for the exact selected workspace
and include the raw response values, not inferred defaults:

```python
{
    # common fields above
    "location": {"directory": "/absolute/workspace"},
    "agent": {  # GET /api/agent/itsm?location[directory]=<workspace>
        "id": "itsm",
        "name": "itsm",
        "mode": "primary",
        "permissions": [
            {"action": "*", "resource": "*", "effect": "deny"},
            {"action": "itsm_*", "resource": "*", "effect": "allow"},
            {"action": "skill", "resource": "*", "effect": "deny"},
            {"action": "skill", "resource": "itsm-inventory", "effect": "allow"},
        ],
    },
    "config": [  # raw top-level JSON array from GET /api/config
        {"type": "directory", "path": "/absolute/workspace"},
        {
            "type": "document",
            "path": "/absolute/workspace/opencode.json",
            "info": {"default_agent": "itsm"},
        },
    ],
    # Unwrapped data array from GET /api/permission/saved.
    "savedPermissions": [],
}
```

The installer requires:

- the selected directory to equal the target workspace;
- agent id `itsm` in `primary` or `all` mode;
- a final effective `deny` rule for `*`/`*`; because OpenCode uses last-match
  wins, earlier built-in defaults are shadowed by that rule, while every later
  `allow`/`ask` rule must remain inside the managed authority;
- effective `allow` for an ITSM tool action and every selected skill, with no
  unmanaged action allowed or asking after that deny;
- the selected workspace directory in the configuration entries and the
  highest-priority loaded `default_agent` equal to `itsm`;
- a raw saved-permission list containing only `deny` rules or exact managed
  allows, with the combined effective rules still allowing the ITSM tool and
  every selected skill.

An absent agent (`404`), a different workspace, an unsafe effective allow or a
missing saved-permission inspection keeps the receipt at `configured` with a
failed `profile.safety` check. It must not be reported as installed/verified.

`mcp.servers.itsm` entry with `disabled: false` and `codemode: false` (the v1
`enabled` key is omitted), and `/api/agent/itsm` returns the restricted agent
after the engine's agent registry is initialized. A fresh engine can return an
empty `/api/agent` and `404` until a session endpoint initializes that registry;
the inspector must not synthesize the agent or treat that `404` as proof. The
returned effective permission list includes OpenCode's built-in `allow`/`ask`
defaults before the generated wildcard `deny`; because evaluation is
last-match-wins, that final wildcard deny shadows the defaults, while the later
ITSM and selected-skill allows remain effective. Direct MCP tool names were not
claimed from an unreachable test endpoint; the inspector always checks the raw
returned rules and saved permissions.

### Hermes

```python
{
    # common fields above
    "runtime": {
        "profile": "itsm",
        "home": "/absolute/profile/root",
        "capabilities": {"chat": True, "mcp": True},
    },
}
```

The runtime profile and home must exactly match the selected target, and the
capabilities must come from the live API bound to that home. A valid YAML
allowlist is not runtime evidence.

## Remote helper

The same `apply` implementation runs on a destination host through:

```bash
python -m itsm.agent_integrations --request /absolute/request.json
```

The package requires `itsm/agent_integrations/__main__.py` and `cli.py`; no
console-script alias is required. The request is a scoped, digest-bound JSON
document containing the target, MCP metadata, skill names/versions/digests and
optional expected config/manifest digests. It contains no bearer token. The
helper resolves the secret from its own environment, validates the request and
catalog digests, applies one operation and prints one JSON receipt on stdout.
It has no remote-shell or arbitrary-command capability. Malformed requests and
failed preconditions return exit code `1` with a signed failure receipt.

`validate_receipt(receipt, request=request)` checks receipt integrity, request
bindings, target identity and skill digests. The helper has no trusted profile
inspector: a remote receipt (including its `profileSafetyVerified`, `verified`
and `profile.safety` fields) is never authoritative and must not self-certify.
The importing caller must independently run authenticated engine inspection for
the validated target/config digest, or record the installation as `configured`.

### Local file boundary

Hermes skill inventory never reads a `SKILL.md` whose resolved file is outside
the selected skills root; it disables that entry by directory name instead.
Rollback rechecks containment before parent creation, restoration, removal and
created-directory cleanup. If the tree was redirected, rollback refuses rather
than touching the external target; local manual recovery may be needed. These
checks reject existing redirection, not a TOCTOU-proof hostile-writer sandbox.
