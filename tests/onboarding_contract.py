#!/usr/bin/env python3
"""Validate the first-start setup contract (T0).

Reads ``tests/onboarding-contract.json`` and ``docs/onboarding-contract.md``.
Every check is structural and read-only: no database, no network, no container,
no secret. Exit 0 when the contract is internally consistent and every
repository anchor it names exists; exit 1 otherwise.
"""

from __future__ import annotations

import fnmatch
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "tests" / "onboarding-contract.json"
DOCUMENT_PATH = ROOT / "docs" / "onboarding-contract.md"

STATES = (
    "unclaimed",
    "claimed",
    "ai_configured",
    "ai_deferred",
    "storage_ready",
    "owner_ready",
    "configuring",
    "verifying",
    "complete",
)
AUTH_KINDS = {"anonymous", "claim", "session", "operator_cli"}
HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
SETTING_OWNERS = {"env", "installation", "domain_service"}
SOURCE_PRECEDENCE = ["env", "installation", "default"]
REQUIRED_TOP_LEVEL = (
    "contract",
    "contract_version",
    "modes",
    "states",
    "initial_state",
    "terminal_state",
    "transitions",
    "operations",
    "operator_commands",
    "claim_credential",
    "sanitized_status",
    "settings_seam",
    "settings",
    "ownership",
    "session",
    "provider",
    "compose",
    "frontend",
    "docs_pack",
    "tools",
    "requirements",
    "known_gaps",
    "recovery",
)
REQUIRED_EDGES = {
    ("unclaimed", "claimed"),
    ("claimed", "ai_configured"),
    ("claimed", "ai_deferred"),
    ("ai_configured", "storage_ready"),
    ("ai_deferred", "storage_ready"),
    ("storage_ready", "owner_ready"),
    ("owner_ready", "configuring"),
    ("configuring", "verifying"),
    ("verifying", "complete"),
    ("complete", "configuring"),
}
REQUIRED_SETTINGS = {
    "database_url",
    "auth_origin",
    "auth_cookie_secure",
    "auth_cookie_name",
    "auth_session_minutes_default",
    "task_storage",
    "agent_model",
    "ai_credential_keys",
    "dev_admin_password",
    "release_mode",
    "monitoring_public_url",
    "appearance_default_theme",
    "smtp_host",
    "backup_policy",
}
MANDATORY_TOOLS = [
    "get_project_context",
    "list_project_capabilities",
    "search_project_docs",
    "read_project_doc",
]
CORE_REQUIREMENTS = {"database_ready", "owner_present", "ai_explicit", "worker_ready"}
POSTPONABLE_REQUIREMENTS = (
    "smtp",
    "monitoring",
    "external_search",
    "external_engines",
    "integrations",
)
KNOWN_GAP_IDS = (
    "agent_credentials_env_only",
    "no_organization_table",
    "no_backup_policy_writer",
    "origin_session_validated_not_applied",
    "prod_requires_database_url_env",
)
# Tokens each gap statement must keep: the short form of the meaning it records.
KNOWN_GAP_TOKENS = {
    "agent_credentials_env_only": ("environment", "personal"),
    "no_organization_table": ("organization", "appearance"),
    "no_backup_policy_writer": ("backup", "risk"),
    "origin_session_validated_not_applied": ("origin", "session"),
    "prod_requires_database_url_env": ("ITSM_DATABASE_URL",),
}
API_SOURCE = ROOT / "backend" / "itsm" / "setup" / "api.py"
SETUP_ENTRY_SOURCE = ROOT / "backend" / "itsm" / "setup" / "__main__.py"
COMPOSE_SOURCES = (
    ROOT / "compose.yaml",
    ROOT / "deploy" / "compose.dev.yaml",
    ROOT / "deploy" / "compose.prod.yaml",
    ROOT / "deploy" / "compose.demo.yaml",
)


def setup_block(path: Path) -> str:
    """Return the ``setup:`` service block of a Compose file, matched by indentation."""
    block: list[str] = []
    inside = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if not inside:
            if re.fullmatch(r"  setup:\s*", line):
                inside = True
                block.append(line)
            continue
        if re.fullmatch(r"  [A-Za-z0-9_.-]+:\s*", line):
            break
        block.append(line)
    return "\n".join(block)


ROUTE_DECORATOR = re.compile(r'@router\.(get|post|put|patch|delete)\("([^"]*)"\)')
SETUP_PREFIX_PATH = "/api/setup/v1"
FORBIDDEN_STATUS_TOKENS = (
    "password",
    "secret",
    "credential",
    "ciphertext",
    "api_key",
    "apikey",
    "api-key",
    "token",
    "dsn",
)
OPERATION_PATH = re.compile(
    r"^/api/setup/v1/(?:[a-z0-9_-]+|\{[a-z_]+\})(?:/(?:[a-z0-9_-]+|\{[a-z_]+\}))*$"
)
IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")


class Report:
    """Collects PASS/FAIL lines and keeps the exit status honest."""

    def __init__(self) -> None:
        self.checks = 0
        self.failures = 0

    def check(self, name: str, condition: object, detail: str = "") -> bool:
        self.checks += 1
        if condition:
            print(f"PASS {name}")
            return True
        self.failures += 1
        print(f"FAIL {name}: {detail or 'failed'}")
        return False

    def equal(self, name: str, value: object, expected: object) -> bool:
        return self.check(name, value == expected, f"expected {expected!r}, got {value!r}")


def obj(value: object, name: str, report: Report) -> dict:
    if not isinstance(value, dict):
        report.check(name, False, "must be a JSON object")
        return {}
    return value


def array(value: object, name: str, report: Report) -> list:
    if not isinstance(value, list):
        report.check(name, False, "must be a JSON array")
        return []
    return value


def text(value: object, name: str, report: Report) -> str:
    if not isinstance(value, str) or not value.strip():
        report.check(name, False, "must be a non-empty string")
        return ""
    return value


def boolean(value: object, name: str, report: Report) -> bool | None:
    if not isinstance(value, bool):
        report.check(name, False, "must be true or false")
        return None
    return value


def check_shape(report: Report, data: dict) -> None:
    for key in REQUIRED_TOP_LEVEL:
        report.check(f"schema key present: {key}", key in data, "missing top-level key")
    report.check(
        "contract version is a positive integer",
        isinstance(data.get("contract_version"), int) and data["contract_version"] >= 1,
        f"got {data.get('contract_version')!r}",
    )
    report.equal("modes are dev and prod", data.get("modes"), ["dev", "prod"])
    report.check("demo mode is not part of this contract", "demo" not in (data.get("modes") or []))


def check_states(report: Report, data: dict) -> None:
    states = array(data.get("states"), "states", report)
    report.equal("states are the nine contract states in order", states, list(STATES))
    report.check("states are unique", len(states) == len(set(states)), "duplicate state name")
    report.equal("initial state is unclaimed", data.get("initial_state"), "unclaimed")
    report.equal("terminal state is complete", data.get("terminal_state"), "complete")


def check_transitions(report: Report, data: dict) -> list[dict]:
    transitions = array(data.get("transitions"), "transitions", report)
    report.check("transition table is not empty", bool(transitions))
    edges: set[tuple[str, str]] = set()
    adjacency: dict[str, list[str]] = {}
    parsed: list[dict] = []
    for index, raw in enumerate(transitions):
        item = obj(raw, f"transitions[{index}]", report)
        source = text(item.get("from"), f"transitions[{index}].from", report)
        target = text(item.get("to"), f"transitions[{index}].to", report)
        trigger = text(item.get("trigger"), f"transitions[{index}].trigger", report)
        actor = text(item.get("actor"), f"transitions[{index}].actor", report)
        via = text(item.get("via"), f"transitions[{index}].via", report)
        report.check(
            f"transition {source or '?'} -> {target or '?'} uses known states",
            source in STATES and target in STATES,
            f"unknown state in {source!r} -> {target!r}",
        )
        report.check(
            f"transition {source or '?'} -> {target or '?'} declares an actor",
            actor in AUTH_KINDS,
            f"actor {actor!r} is not one of {sorted(AUTH_KINDS)}",
        )
        report.check(
            f"transition {source or '?'} -> {target or '?'} is not a duplicate",
            (source, target) not in edges,
            "two rows declare the same edge",
        )
        report.check(
            f"transition {source or '?'} -> {target or '?'} never returns to unclaimed",
            target != "unclaimed",
            "unclaimed is reachable again",
        )
        if trigger and via:
            edges.add((source, target))
            adjacency.setdefault(source, []).append(target)
        parsed.append(item)
        if source == "complete":
            report.check(
                f"exit from complete ({target or '?'}) runs through the operator CLI",
                actor == "operator_cli" and item.get("recovery") is True,
                "only the operator recovery command may leave complete",
            )
    for source, target in sorted(REQUIRED_EDGES):
        report.check(
            f"transition exists: {source} -> {target}",
            (source, target) in edges,
            "missing transition",
        )
    report.equal(
        "unclaimed has exactly one exit",
        len(adjacency.get("unclaimed", [])),
        1,
    )
    reachable = {"unclaimed"}
    pending = ["unclaimed"]
    while pending:
        current = pending.pop()
        for following in adjacency.get(current, []):
            if following not in reachable:
                reachable.add(following)
                pending.append(following)
    for state in STATES:
        report.check(f"state reachable from unclaimed: {state}", state in reachable, "unreachable")
        if state != "complete":
            report.check(
                f"state has an outgoing transition: {state}",
                bool(adjacency.get(state)),
                "dead end before complete",
            )
    return parsed


def check_operations(report: Report, data: dict) -> tuple[list[dict], set[str]]:
    operations = array(data.get("operations"), "operations", report)
    report.check("operations table is not empty", bool(operations))
    identifiers: set[str] = set()
    parsed: list[dict] = []
    for index, raw in enumerate(operations):
        item = obj(raw, f"operations[{index}]", report)
        identifier = text(item.get("id"), f"operations[{index}].id", report)
        report.check(
            f"operation id is snake_case: {identifier or '?'}",
            bool(IDENTIFIER.match(identifier)),
            "id must match ^[a-z][a-z0-9_]*$",
        )
        report.check(
            f"operation id is unique: {identifier or '?'}",
            identifier not in identifiers,
            "duplicate operation id",
        )
        identifiers.add(identifier)
        method = item.get("method")
        report.check(
            f"operation {identifier or '?'} declares an HTTP method",
            method in HTTP_METHODS,
            f"method {method!r} is not one of {sorted(HTTP_METHODS)}",
        )
        path = text(item.get("path"), f"operations[{index}].path", report)
        report.check(
            f"operation {identifier or '?'} lives under /api/setup/v1",
            bool(OPERATION_PATH.match(path)) and "//" not in path and not path.endswith("/"),
            f"path {path!r} is outside the setup prefix",
        )
        required = array(item.get("required_states"), f"operations[{index}].required_states", report)
        report.check(
            f"operation {identifier or '?'} declares at least one required state",
            bool(required),
            "required_states is empty",
        )
        for state in required:
            report.check(
                f"operation {identifier or '?'} state is known: {state}",
                state in STATES,
                "unknown state",
            )
        auth = item.get("auth")
        report.check(
            f"operation {identifier or '?'} declares its authority",
            auth in AUTH_KINDS,
            f"auth {auth!r} is not one of {sorted(AUTH_KINDS)}",
        )
        report.check(
            f"operation {identifier or '?'} declares idempotency",
            isinstance(item.get("idempotent"), bool),
            "idempotent must be true or false",
        )
        if auth == "anonymous":
            report.check(
                f"anonymous operation {identifier or '?'} is a read-only GET",
                method == "GET" and item.get("read_only") is True,
                "anonymous surface must not mutate",
            )
            returned = array(item.get("returns"), f"operations[{index}].returns", report)
            report.check(
                f"anonymous operation {identifier or '?'} declares sanitized returns",
                bool(returned),
                "returns is empty",
            )
            item["_returns"] = returned
        if method != "GET":
            report.check(
                f"mutating operation {identifier or '?'} requires the Origin header",
                item.get("origin_check") is True,
                "non-GET requests need an Origin check",
            )
            if auth == "session":
                report.check(
                    f"session operation {identifier or '?'} requires X-CSRF-Token",
                    item.get("csrf") is True,
                    "non-GET session requests need the CSRF header",
                )
        parsed.append(item)
    for kind in ("anonymous", "claim", "session"):
        report.check(
            f"contract declares at least one {kind} operation",
            any(item.get("auth") == kind for item in parsed),
            f"no {kind} operation",
        )
    return parsed, identifiers


def declared_routes() -> dict[tuple[str, str], str]:
    """Every ``@router.<method>("<path>")`` the setup app actually serves.

    The contract is the operator-facing promise; this is the shipped surface. The
    two are compared in both directions so a route added to or dropped from
    ``backend/itsm/setup/api.py`` cannot leave the document silently wrong.
    """

    if not API_SOURCE.is_file():
        return {}
    source = API_SOURCE.read_text(encoding="utf-8")
    return {
        (method.upper(), SETUP_PREFIX_PATH + path): f"@router.{method}(\"{path}\")"
        for method, path in ROUTE_DECORATOR.findall(source)
    }


def check_operation_routes(report: Report, operations: list[dict]) -> None:
    """Compare the contract table with the route decorators in ``api.py``.

    The contract is the operator-facing promise; the decorators are the shipped
    surface. Both directions are checked so neither a documented path that no
    route serves nor an undocumented setup route can survive the gate.
    """

    routes = declared_routes()
    report.check(
        "backend setup router is readable",
        bool(routes),
        f"no @router route found in {API_SOURCE}",
    )
    declared: dict[tuple[str, str], str] = {}
    for operation in operations:
        identifier = str(operation.get("id"))
        key = (str(operation.get("method")), str(operation.get("path")))
        declared[key] = identifier
        report.check(
            f"operation {identifier} is served by the backend router",
            key in routes,
            f"{key[0]} {key[1]} is not a route in backend/itsm/setup/api.py",
        )
    for key, decorator in sorted(routes.items()):
        report.check(
            f"backend route {key[0]} {key[1]} is in the contract",
            key in declared,
            f"{decorator} has no declared operation",
        )


def check_known_gaps(report: Report, data: dict) -> None:
    gaps = array(data.get("known_gaps"), "known_gaps", report)
    report.check("known gaps are recorded", bool(gaps), "known_gaps is empty")
    seen: set[str] = set()
    for index, raw in enumerate(gaps):
        item = obj(raw, f"known_gaps[{index}]", report)
        identifier = text(item.get("id"), f"known_gaps[{index}].id", report)
        report.check(
            f"known gap id is snake_case: {identifier or '?'}",
            bool(IDENTIFIER.match(identifier)),
            "id must match ^[a-z][a-z0-9_]*$",
        )
        report.check(
            f"known gap id is unique: {identifier or '?'}",
            identifier not in seen,
            "duplicate known gap",
        )
        seen.add(identifier)
        statement = text(item.get("statement"), f"known_gaps[{index}].statement", report)
        report.check(
            f"known gap states its meaning: {identifier or '?'}",
            len(statement) >= 80,
            "statement is too short to carry the meaning",
        )
        tokens = KNOWN_GAP_TOKENS.get(identifier, ())
        missing = [token for token in tokens if token.lower() not in statement.lower()]
        report.check(
            f"known gap keeps its vocabulary: {identifier or '?'}",
            not missing,
            f"statement no longer names {missing}",
        )
        source = text(item.get("source"), f"known_gaps[{index}].source", report)
        report.check(
            f"known gap cites the code that causes it: {identifier or '?'}",
            source.startswith(("backend/", "deploy/", "frontend/")),
            f"source {source!r} must name a repository path",
        )
    for identifier in KNOWN_GAP_IDS:
        report.check(f"known gap recorded: {identifier}", identifier in seen, "missing known gap")


def check_sanitized_status(report: Report, data: dict, operations: list[dict]) -> list[str]:
    block = obj(data.get("sanitized_status"), "sanitized_status", report)
    fields = array(block.get("fields"), "sanitized_status.fields", report)
    report.check("sanitized status allowlist is not empty", bool(fields))
    report.check(
        "sanitized status excludes secrets",
        block.get("secrets_excluded") is True,
        "secrets_excluded must be true",
    )
    for field in fields:
        normalized = str(field).lower()
        report.check(
            f"sanitized field carries no secret shape: {field}",
            not any(token in normalized for token in FORBIDDEN_STATUS_TOKENS),
            "field name implies secret material",
        )
    for operation in operations:
        if operation.get("auth") != "anonymous":
            continue
        for field in operation.get("_returns", []):
            report.check(
                f"anonymous {operation.get('id')} returns only allowlisted {field}",
                field in fields,
                "field is not in sanitized_status.fields",
            )
    return fields


def check_transition_via(
    report: Report, data: dict, transitions: list[dict], operations: list[dict], commands: set[str]
) -> None:
    by_id = {operation.get("id"): operation for operation in operations}
    for item in transitions:
        via = item.get("via")
        source = item.get("from")
        target = item.get("to")
        report.check(
            f"transition {source} -> {target} names a declared action ({via})",
            via in by_id or via in commands,
            "via is neither an operation id nor an operator command id",
        )
        if via in by_id:
            report.check(
                f"transition {source} -> {target} is allowed in {via}",
                source in by_id[via].get("required_states", []),
                f"{via} does not list {source} in required_states",
            )


def check_settings(report: Report, data: dict, status_fields: list[str]) -> None:
    seam = obj(data.get("settings_seam"), "settings_seam", report)
    report.equal("settings builder stays get_settings", seam.get("builder"), "get_settings")
    report.equal(
        "settings resolver is resolve_settings_sources",
        seam.get("resolver"),
        "resolve_settings_sources",
    )
    report.equal(
        "installation pointer is ITSM_INSTALLATION_CONFIG",
        seam.get("env_var"),
        "ITSM_INSTALLATION_CONFIG",
    )
    report.check(
        "installation pointer keeps the ITSM_ prefix",
        str(seam.get("env_var", "")).startswith("ITSM_"),
        "worker_environment drops only ITSM_* variables; an unprefixed pointer would leak",
    )
    report.equal("installation file mode is 0600", seam.get("file_mode"), "0600")
    report.equal("installation directory mode is 0700", seam.get("directory_mode"), "0700")
    report.equal("settings precedence order", seam.get("precedence"), SOURCE_PRECEDENCE)
    report.equal("settings tri-state vocabulary", seam.get("tri_state"), ["unset", "empty", "applied"])
    report.check(
        "subprocess projection keeps the pointer ITSM_-prefixed",
        "ITSM_" in str(seam.get("subprocess_projection", "")),
        "name the environment projection that strips ITSM_*",
    )
    settings = array(data.get("settings"), "settings", report)
    report.check("settings ownership table is not empty", bool(settings))
    seen: set[str] = set()
    secret_keys: set[str] = set()
    owners: set[str] = set()
    for index, raw in enumerate(settings):
        item = obj(raw, f"settings[{index}]", report)
        key = text(item.get("key"), f"settings[{index}].key", report)
        env = text(item.get("env"), f"settings[{index}].env", report)
        owner = item.get("owner")
        precedence = item.get("precedence")
        report.check(f"setting key is unique: {key or '?'}", key not in seen, "duplicate setting")
        seen.add(key)
        report.check(
            f"setting owner is known: {key or '?'}",
            owner in SETTING_OWNERS,
            f"owner {owner!r} is not one of {sorted(SETTING_OWNERS)}",
        )
        if isinstance(owner, str):
            owners.add(owner)
        report.check(
            f"setting secret flag is explicit: {key or '?'}",
            isinstance(item.get("secret"), bool),
            "secret must be true or false",
        )
        if owner == "domain_service":
            report.equal(
                f"domain setting {key} has a single owner",
                precedence,
                ["domain_service"],
            )
        else:
            report.equal(
                f"setting {key} keeps env > installation > default",
                precedence,
                SOURCE_PRECEDENCE,
            )
            expected = f"ITSM_{key.upper()}"
            report.check(
                f"setting {key} names its environment variable",
                env == expected or env == "RELEASE_MODE",
                f"expected {expected!r} (or the pre-existing unprefixed RELEASE_MODE), got {env!r}",
            )
        report.check(
            f"setting {key} stays ITSM_-prefixed",
            env.startswith("ITSM_") or env == "RELEASE_MODE",
            "a new environment variable must keep the ITSM_ prefix",
        )
        if item.get("secret") is True:
            secret_keys.add(key)
            secret_keys.add(env.lower())
    for key in sorted(REQUIRED_SETTINGS):
        report.check(f"required setting declared: {key}", key in seen, "missing setting")
    for owner in sorted(SETTING_OWNERS):
        report.check(f"settings declare a {owner} owner", owner in owners, "owner unused")
    report.check("at least one setting is secret", bool(secret_keys), "no secret marked")
    for field in status_fields:
        normalized = str(field).lower()
        report.check(
            f"sanitized status never lists a secret setting: {field}",
            normalized not in secret_keys,
            "secret settings must stay out of the sanitized surface",
        )


def check_ownership(report: Report, data: dict) -> None:
    block = obj(data.get("ownership"), "ownership", report)
    report.equal("ownership table is deployment_identity", block.get("table"), "deployment_identity")
    report.equal("first owner uses bootstrap_superadmin", block.get("first_owner"), "bootstrap_superadmin")
    report.check(
        "first owner cites the identity service",
        "identity/service.py:1304" in str(block.get("first_owner_source", "")),
        "first_owner_source must cite backend/itsm/identity/service.py:1304",
    )
    report.check(
        "unmarked non-empty databases are never adopted",
        block.get("adopt_unmarked_nonempty") is False,
        "adopt_unmarked_nonempty must be false",
    )
    report.equal("existing databases start read-only", block.get("existing_database"), "read_only")
    report.check(
        "adoption risk cites release_identity",
        "release_identity.py:221" in str(block.get("risk_source", "")),
        "risk_source must cite backend/itsm/release_identity.py:221",
    )


def check_session(report: Report, data: dict) -> None:
    block = obj(data.get("session"), "session", report)
    cookie = text(block.get("cookie_name"), "session.cookie_name", report)
    report.check("setup cookie differs from the domain session cookie", cookie != "itsm_session", cookie)
    report.equal("setup cookie path", block.get("cookie_path"), "/api/setup/v1")
    report.equal("setup cookie is HttpOnly", block.get("http_only"), True)
    report.check(
        "setup cookie is SameSite=Strict",
        str(block.get("same_site", "")).lower() == "strict",
        f"got {block.get('same_site')!r}",
    )
    report.equal("setup session checks Origin", block.get("origin_header"), "Origin")
    report.equal("setup session checks CSRF", block.get("csrf_header"), "X-CSRF-Token")
    ttl = block.get("ttl_minutes")
    report.check("setup session TTL is bounded", isinstance(ttl, int) and 5 <= ttl <= 1440, f"got {ttl!r}")
    attempts = block.get("max_attempts")
    report.check(
        "setup attempt limit is bounded",
        isinstance(attempts, int) and 1 <= attempts <= 20,
        f"got {attempts!r}",
    )
    report.check(
        "setup app does not import the identity cookie helpers",
        block.get("imports_identity_cookie_helpers") is False,
        "identity helpers read app.state.settings; the setup contract declares its own session",
    )


def check_provider(report: Report, data: dict) -> None:
    block = obj(data.get("provider"), "provider", report)
    report.equal("provider key ring is ITSM_AI_CREDENTIAL_KEYS", block.get("key_ring_env"), "ITSM_AI_CREDENTIAL_KEYS")
    report.equal("pre-DB credentials validate as personal scope", block.get("scope"), "personal")
    report.check("provider reuse is DB-free", block.get("db_free") is True, "db_free must be true")
    reuse = array(block.get("reuse"), "provider.reuse", report)
    for name in (
        "seal_credential",
        "unseal_credential",
        "validate_provider_endpoint",
        "ProviderNetworkPolicy",
        "discover_provider_models",
    ):
        report.check(f"provider reuses {name}", name in reuse, "missing reused primitive")
    report.check(
        "credentials stay blocked without a key ring",
        block.get("blocked_without_key") is True,
        "blocked_without_key must be true",
    )
    transfer = array(block.get("transfer"), "provider.transfer", report)
    report.check(
        "transfer verifies before deleting the transient copy",
        "verify_credential" in transfer
        and "delete_transient_copy" in transfer
        and transfer.index("verify_credential") < transfer.index("delete_transient_copy"),
        f"got {transfer!r}",
    )


def check_requirements(report: Report, data: dict) -> None:
    catalog = array(data.get("requirement_catalog"), "requirement_catalog", report)
    report.check("requirement catalog is not empty", bool(catalog))
    report.check("requirement ids are unique", len(catalog) == len(set(catalog)), "duplicate requirement")
    requirements = obj(data.get("requirements"), "requirements", report)
    report.equal("requirements cover dev and prod", sorted(requirements), ["dev", "prod"])
    for mode in ("dev", "prod"):
        block = obj(requirements.get(mode), f"requirements.{mode}", report)
        required = array(block.get("required"), f"requirements.{mode}.required", report)
        postponable = array(block.get("postponable"), f"requirements.{mode}.postponable", report)
        report.check(f"{mode} requires at least one check", bool(required))
        report.check(
            f"{mode} required and postponable do not overlap",
            not set(required) & set(postponable),
            f"overlap: {sorted(set(required) & set(postponable))}",
        )
        for entry in [*required, *postponable]:
            report.check(
                f"{mode} requirement is catalogued: {entry}",
                entry in catalog,
                "unknown requirement id",
            )
        missing = CORE_REQUIREMENTS - set(required)
        report.check(
            f"{mode} requires the core completion checks",
            not missing,
            f"missing {sorted(missing)}",
        )
        for entry in POSTPONABLE_REQUIREMENTS:
            report.check(
                f"{mode} can postpone {entry}",
                entry in postponable,
                "postponable list is incomplete",
            )
    dev = obj(requirements.get("dev"), "requirements.dev", report)
    prod = obj(requirements.get("prod"), "requirements.prod", report)
    report.check(
        "dev requires an explicit appearance choice",
        "appearance_decided" in (dev.get("required") or []),
        "appearance_decided missing from dev",
    )
    report.check(
        "prod requires a declared backup policy",
        "backup_policy_declared" in (prod.get("required") or []),
        "backup_policy_declared missing from prod",
    )


def check_docs_pack(report: Report, data: dict) -> None:
    block = obj(data.get("docs_pack"), "docs_pack", report)
    report.equal("docs pack generator", block.get("generator"), "tools/build-project-context.py")
    report.equal(
        "docs pack output is committed inside the backend package",
        block.get("output"),
        "backend/itsm/project_context/pack.json",
    )
    report.check("docs pack has a drift check", block.get("drift_check") is True, "drift_check must be true")
    exclusions = array(block.get("exclusions"), "docs_pack.exclusions", report)
    for token in ("odd/", "docs/reviews/", "AGENTS.md"):
        report.check(f"docs pack excludes {token}", token in exclusions, "missing exclusion")
    report.check(
        "docs pack excludes .env files",
        any(str(entry).startswith(".env") for entry in exclusions),
        "missing .env* exclusion",
    )
    allowlist = array(block.get("allowlist"), "docs_pack.allowlist", report)
    report.check("docs allowlist is not empty", bool(allowlist))
    for relative in allowlist:
        report.check(f"allowlist entry is a relative path: {relative}", isinstance(relative, str) and not Path(relative).is_absolute(), "absolute paths are not portable")
        path = Path(str(relative))
        report.check(
            f"allowlist path exists: {relative}",
            (ROOT / path).is_file(),
            "documented file is missing from the repository",
        )
        report.check(f"allowlist entry is Markdown: {relative}", path.suffix == ".md", "only .md docs are packaged")
        report.check(
            f"allowlist entry is inside the repository: {relative}",
            ".." not in path.parts,
            "path escapes the repository root",
        )
        report.check(
            f"allowlist entry is not a private record: {relative}",
            "odd" not in path.parts
            and not str(path).startswith("docs/reviews/")
            and path.name != "AGENTS.md"
            and not fnmatch.fnmatch(path.name, ".env*"),
            "excluded material must never enter the runtime pack",
        )


def check_tools(report: Report, data: dict) -> None:
    block = obj(data.get("tools"), "tools", report)
    mandatory = array(block.get("mandatory"), "tools.mandatory", report)
    report.equal("mandatory core tools are the four contract names", mandatory, MANDATORY_TOOLS)
    registration = array(block.get("registration"), "tools.registration", report)
    for surface in ("backend/itsm/agents/runtime.py", "backend/itsm/mcp/server.py"):
        report.check(f"tools register in {surface}", surface in registration, "missing runtime surface")
    collision = text(block.get("collision_check"), "tools.collision_check", report)
    report.check(
        "tool collision check is recorded",
        "zero" in collision.lower(),
        "state the observed collision result",
    )


def check_runtime_surfaces(report: Report, data: dict, command_ids: set[str]) -> None:
    compose = obj(data.get("compose"), "compose", report)
    report.equal("setup is its own Compose service", compose.get("setup_service"), "setup")
    port = compose.get("port")
    report.check(
        "setup listens on an unprivileged port",
        isinstance(port, int) and 1024 <= port <= 65535,
        f"got {port!r}",
    )
    report.equal("setup port is implemented and unpublished", compose.get("port_state"), "implemented")
    report.check(
        "no host port is published for setup",
        compose.get("published_host_port") is None,
        f"got {compose.get('published_host_port')!r}",
    )
    entry = SETUP_ENTRY_SOURCE.read_text(encoding="utf-8")
    host = compose.get("bind_host")
    report.check(
        "setup binds the declared host inside the container",
        f'SETUP_HOST = "{host}"' in entry,
        f"{SETUP_ENTRY_SOURCE.relative_to(ROOT)} does not bind {host!r}",
    )
    report.check(
        "setup binds the declared port inside the container",
        isinstance(port, int) and f"SETUP_PORT = {port}" in entry,
        f"{SETUP_ENTRY_SOURCE.relative_to(ROOT)} does not bind port {port!r}",
    )
    for path in COMPOSE_SOURCES:
        block = setup_block(path)
        if path.name == "compose.yaml":
            report.check("compose.yaml declares the setup service", bool(block), "setup block missing")
        report.check(
            f"{path.relative_to(ROOT)} publishes no setup host port",
            not re.search(r"^\s+ports:", block, re.MULTILINE),
            "a ports: mapping on setup would expose the wizard",
        )
    report.equal("setup API prefix", compose.get("path_prefix"), "/api/setup/v1")
    report.equal("setup has no Compose dependencies", compose.get("depends_on"), [])
    report.check("demo keeps setup behind a profile", bool(compose.get("demo_profile")), "demo_profile is required")
    report.equal("nginx uses the Docker embedded resolver", compose.get("nginx_resolver"), "127.0.0.11")
    report.check("nginx uses a variable proxy_pass", compose.get("variable_proxy_pass") is True, "literal upstreams fail at boot")
    report.equal("backend absence is a gateway error, not setup", compose.get("backend_absent_status"), [502, 503])
    report.equal(
        "service-set update belongs to T1",
        compose.get("service_set_update_slice"),
        "T1",
    )
    frontend = obj(data.get("frontend"), "frontend", report)
    report.equal("frontend branches before mountLegacy", frontend.get("branch_before"), "mountLegacy")
    report.equal("frontend probes the sanitized status", frontend.get("probe"), "GET /api/setup/v1/status")
    files = array(frontend.get("files"), "frontend.files", report)
    for relative in ("frontend/src/main.tsx", "frontend/src/setup/SetupApp.tsx", "frontend/src/setup/client.ts"):
        report.check(f"frontend mount file is declared: {relative}", relative in files, "missing file")
    recovery = obj(data.get("recovery"), "recovery", report)
    report.check("recovery preserves ownership", recovery.get("owner_preserved") is True, "owner_preserved must be true")
    report.check("recovery never resets the database", recovery.get("resets_database") is False, "resets_database must be false")
    report.check("recovery does not depend on cookies", recovery.get("cookie_independent") is True, "cookie_independent must be true")
    commands = array(recovery.get("commands"), "recovery.commands", report)
    report.check("recovery names the recover command", "recover" in commands, "recover missing")
    report.check("recover command is declared", "recover" in command_ids, "operator command recover missing")
    claim = obj(data.get("claim_credential"), "claim_credential", report)
    report.check("claim credential is one-time", claim.get("one_time") is True, "one_time must be true")
    report.check("claim credential never appears in logs", claim.get("never_logged") is True, "never_logged must be true")
    report.check("claim credential never appears in URLs", claim.get("never_in_url") is True, "never_in_url must be true")


def check_operator_commands(report: Report, data: dict) -> set[str]:
    commands = array(data.get("operator_commands"), "operator_commands", report)
    report.check("operator commands are declared", bool(commands))
    identifiers: set[str] = set()
    for index, raw in enumerate(commands):
        item = obj(raw, f"operator_commands[{index}]", report)
        identifier = text(item.get("id"), f"operator_commands[{index}].id", report)
        report.check(
            f"operator command id is unique: {identifier or '?'}",
            identifier not in identifiers,
            "duplicate operator command",
        )
        identifiers.add(identifier)
        report.equal(
            f"operator command {identifier or '?'} uses operator authority",
            item.get("auth"),
            "operator_cli",
        )
        command = text(item.get("command"), f"operator_commands[{index}].command", report)
        report.check(
            f"operator command {identifier or '?'} runs the setup CLI",
            command.startswith("python -m itsm.setup.cli"),
            f"got {command!r}",
        )
        report.check(
            f"operator command {identifier or '?'} declares idempotency",
            isinstance(item.get("idempotent"), bool),
            "idempotent must be true or false",
        )
    return identifiers


def check_document(report: Report, data: dict, operations: list[dict]) -> None:
    report.check(
        "contract document exists",
        DOCUMENT_PATH.is_file(),
        f"missing {DOCUMENT_PATH.relative_to(ROOT)}",
    )
    if not DOCUMENT_PATH.is_file():
        return
    document = DOCUMENT_PATH.read_text(encoding="utf-8")
    report.check(
        "contract document closes every code fence",
        document.count("```") % 2 == 0,
        "unbalanced fenced block",
    )
    for state in STATES:
        report.check(
            f"document names state {state}",
            f"`{state}`" in document or state in document,
            "state is undocumented",
        )
    for operation in operations:
        identifier = operation.get("id", "")
        report.check(
            f"document names operation {identifier}",
            identifier in document,
            "operation is undocumented",
        )
    for heading in ("## Deviations from plan", "## Baseline", "## Known gaps"):
        report.check(f"document has section {heading}", heading in document, "required section missing")
    for token in ("## States and transitions", "## Operations", "## Settings"):
        report.check(f"document has section {token}", token in document, "required section missing")


def main() -> int:
    report = Report()
    if not CONTRACT_PATH.is_file():
        print(f"FAIL missing tests/onboarding-contract.json (looked for {CONTRACT_PATH})")
        print("RED: the setup contract files do not exist yet, so nothing can be validated")
        return 1
    try:
        data = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        print(f"FAIL tests/onboarding-contract.json is not valid JSON: {error}")
        return 1
    if not isinstance(data, dict):
        print("FAIL tests/onboarding-contract.json must contain one JSON object")
        return 1

    check_shape(report, data)
    check_states(report, data)
    transitions = check_transitions(report, data)
    operations, _ = check_operations(report, data)
    check_operation_routes(report, operations)
    check_known_gaps(report, data)
    status_fields = check_sanitized_status(report, data, operations)
    command_ids = check_operator_commands(report, data)
    check_transition_via(report, data, transitions, operations, command_ids)
    check_settings(report, data, status_fields)
    check_ownership(report, data)
    check_session(report, data)
    check_provider(report, data)
    check_requirements(report, data)
    check_docs_pack(report, data)
    check_tools(report, data)
    check_runtime_surfaces(report, data, command_ids)
    check_document(report, data, operations)

    print(f"contract checks: {report.checks} run, {report.failures} failed")
    if report.failures:
        print(f"FAIL onboarding contract: {report.failures} problem(s)")
        return 1
    print("all onboarding contract checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
