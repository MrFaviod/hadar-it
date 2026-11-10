# Agent skill catalog and module extensions

The backend ships an inert, versioned catalog of `SKILL.md` packages and a
permission-aware registry for MCP tools supplied by ITSM modules.

This is product distribution, not an agent-global skill registry. The catalog
never writes to a home skill directory, an agent profile or a mounted server,
and it never turns skill text into a prompt. The installer copies selected
packages; the agent loads one on demand.

## Official packages

`itsm/agent_integrations/skills/` contains the seven official packages at
version `1.0.0`:

| Skill | Domain |
| --- | --- |
| `itsm-inventory` | assets, assignment, imports |
| `itsm-infrastructure` | locations, relationships, redundancy |
| `itsm-monitoring` | availability, metrics, alerts |
| `itsm-incidents` | incidents, interventions, technical history |
| `itsm-maintenance` | preventive plans and completion |
| `itsm-reporting` | templates, previews, exports, labels |
| `itsm-operations` | summary, cross-entity search, graph, saved views |

Each `SKILL.md` declares frontmatter (`name`, one-line `description` starting
with `Trigger:`, `license`, `metadata.author`, `metadata.version`, `tools`,
`permissions`, `capabilities`) and six sections: Activation Contract, Hard
Rules, Decision Gates, Execution Steps, Output Contract, Example. Declared
tools are current `itsm.mcp.server.TOOL_NAMES`; a skill never invents a tool or
a deployment-maintenance command.

`package_digest(files)` is SHA-256 over sorted relative file names, each
followed by `b"\0"`, the file bytes and another `b"\0"`. The digest is stable
across checkouts and is the package-version proof. An installer still computes
its own per-file digests for tamper and conflict checks.

## Catalog API

```python
from itsm.agent_integrations.catalog import SkillCatalog

catalog = SkillCatalog()                 # optional official_root for embedded tests
catalog.list_skills()                    # metadata only; enabled modules
catalog.get_skill("itsm-inventory")      # metadata + files: dict[str, bytes]
catalog.list_modules()
catalog.register_module(manifest, root=Path("/opt/itsm/module"))
catalog.set_module_enabled("vendor.demo", False)
```

Metadata keys are `name`, `description`, `version`, `module`, `permissions`,
`capabilities` and `digest`; `get_skill` adds `files` with POSIX relative names.
An unknown or disabled skill raises `SkillNotFound` without exposing a path.
Module manifests must declare `id`, `name`, `version`, `capabilities` and
`permissions`. `skills` lists packages under `<root>/skills/<name>/SKILL.md`;
`skillDigests` may pin each package digest. Registration validates the bounded
manifest, rejects unknown permissions/capabilities, rejects skill packages whose
permissions exceed the module manifest, rejects symlinks and paths outside the
module root, and applies atomically: a failure leaves no partial module.

Disabling a module immediately removes its skills from `list_skills` and
`get_skill`, and its tools from registry listing and invocation. Re-enabling
restores them without re-registration.

A module manifest is explicit about its authority:

```python
manifest = {
    "id": "vendor.demo",
    "name": "Demo module",
    "version": "1.2.0",
    "capabilities": ["inventory.read", "operations.read"],
    "permissions": ["assets.view", "assets.edit"],
    "skills": ["demo-skill"],
    "skillDigests": {"demo-skill": "<sha256 of the package files>"},
}
```

`skillDigests` is optional, but when present every declared digest must match
the loaded bytes. A skill under `<root>/skills/<name>/SKILL.md` may narrow the
manifest's permissions and capabilities; it can never widen them.

## Module tools

A module tool is a real synchronous callable, not a declaration:

```python
registry.register_tool(
    "vendor.demo",
    name="demo_saved_views",
    description="Read the caller's saved ITSM views.",
    permissions=("assets.view",),
    capabilities=("operations.read",),
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    },
    handler=handler,                     # handler(context, **arguments)
)
```

The tool name must be lowercase and must not collide with the core surface or
another extension. Permissions must be known ITSM permission codes and a subset
of the module manifest; capabilities must be a subset of the module manifest.
Every invocation validates arguments, re-reads module state and calls
`IdentityService.authorize` once per declared permission before running the
handler. Handlers receive:

```python
ExtensionContext(settings, session, identity, principal, source="mcp")
```

`session` is an open SQLAlchemy session and `identity` is the trusted service;
handlers delegate to canonical domain services. There is no built-in shell,
HTTP, SQL or filesystem tool, and the capability vocabulary contains only ITSM
domain capabilities, so such a tool has no declaration path. A handler that
needs another domain still passes through that domain's service authorization.

`registry.list_tools(permissions=...)` returns only enabled tools whose
permissions the caller holds. `registry.invoke(...)` repeats all checks, so a
stale listing cannot authorize a call.

## Loading installed modules

There is no upload, arbitrary path import, directory scan or network discovery.
An operator installs a trusted Python distribution in the backend environment
and configures its dotted module names explicitly. `load_extension_modules`
imports only those names, in order, and requires one synchronous entry point:

```python
# demo_itsm_ext/__init__.py
from pathlib import Path

from itsm.operations import tools

def register_extensions(catalog, registry):
    catalog.register_module(manifest, root=Path(__file__).parent)
    registry.register_tool(
        "vendor.demo",
        name="demo_saved_views",
        description="Read the caller's saved ITSM views.",
        permissions=("assets.view",),
        capabilities=("operations.read",),
        parameters={"type": "object", "properties": {}, "required": []},
        handler=lookup_views,
    )

def lookup_views(context, **arguments):
    return tools.list_saved_views(
        context.session, context.identity, context.principal, source=context.source
    )
```

The distribution ships its `skills/<name>/SKILL.md` directories beside that
module and lists them in its manifest. At startup, before binding FastMCP:

```python
loaded = load_extension_modules(catalog, registry, configured_modules)
```

`configured_modules` is an explicit list of dotted names from deployment
configuration, never from browser input, chat, a skill file or a remote
registry. `load_extension_modules` returns the imported names. It fails startup
with `InvalidExtension` for an invalid or duplicate name, a missing
distribution, a missing or async `register_extensions`, or an entry point that
registers no module manifest. Import and registration errors propagate; no
partial "installed" state is reported. Disabling the module hides its skills
and tools immediately, and `mount.sync()` applies the FastMCP visibility delta.

## FastMCP integration

`create_mcp_server` owns the FastMCP instance; the catalog and registry stay
separate modules and never import it. After creating the server and loading
configured extensions:

```python
from itsm.agent_integrations.extensions import (
    ExtensionRegistry,
    bind_fastmcp_tools,
    load_extension_modules,
)
from itsm.agent_integrations.catalog import SkillCatalog
from itsm.mcp.server import TOOL_NAMES

catalog = SkillCatalog()
registry = ExtensionRegistry(catalog, reserved_names=TOOL_NAMES)
load_extension_modules(catalog, registry, configured_modules)
mount = bind_fastmcp_tools(
    server, registry, settings=settings, session_factory=session_factory
)
# after a persisted module toggle:
catalog.set_module_enabled(module_id, enabled)
mount.sync()
```

`bind_fastmcp_tools` adds one `FunctionTool` per registered tool with its
explicit JSON schema and a list-time token-scope gate, refusing name collisions
with existing local server tools. Each call extracts the `Authorization: Bearer`
header, authenticates it with `IdentityService.authenticate_token`, and reuses
the existing FastMCP `ToolError` mapping. Missing or invalid bearer is
`authentication required`; a denied permission is `permission denied`; a
disabled module is `tool is not available`; unexpected handler exceptions are
logged by type and returned as `tool failed` without provider details.

`mount.sync()` applies only enable/disable deltas with the pinned FastMCP
`server.disable(names=...)`/`server.enable(names=...)` API. Tools registered
after binding require a rebind. FastMCP 4.1.3 exposes tool lookup only as an
async method, so the synchronous duplicate check reads the local provider's
component map; this is tied to the pinned FastMCP version.

## Packaging

Skill files are data, not Python modules. The wheel must include them:

```toml
[tool.setuptools.package-data]
"itsm.agent_integrations" = ["skills/*/*", "skills/*/*/*"]
```

No `MANIFEST.in` and no `__init__.py` inside skill directories. The catalog
resolves packages from `Path(__file__).resolve().parent / "skills"`, so the
same code works from a source checkout, an installed wheel and the container.

Check a built wheel with:

```bash
unzip -l dist/*.whl | grep 'agent_integrations/skills/itsm-inventory/SKILL.md'
```
