#!/usr/bin/env python3
"""Bounded runtime verification of `dev`, `prod` and `demo` through real Compose.

This script is the executable form of the T6/S19 launch check: it renders the
real root `compose.yaml` plus the mode overlay, starts one uniquely named local
Compose project per mode with `--env-file /dev/null`, waits for the preparation
gate and bounded HTTP readiness (never a startup assumption), asserts the mode's
observable contract, then removes only that project's containers and network.

Boundaries that are deliberate, not omissions:

* It never builds or downloads. The three images must already exist:
  ``itsm-backend:release-modes-verify``, ``itsm-frontend:release-modes-verify``
  and ``itsm-ops:release-modes-verify``. Compose is always invoked with
  ``--no-build --pull never``, so a missing image fails the run instead of
  pulling or rebuilding something else.
* It never creates a `.env` file. Image tags are selected by a temporary
  override file created inside the gitignored project ``.verification/``
  directory and removed by this script afterwards. Every variable is passed
  explicitly on the process environment, test-only, and never printed.
* It never deletes volumes. Cleanup is `down` (containers + project network)
  without `-v`; the run then asserts the mode-owned volumes still exist.
* It never touches another Compose project, unrelated container or shared
  service: the project name is unique per mode and run, ports are allocated on
  loopback, and no profile that consumes local Postgres/Redis/search or a TLS
  certificate is enabled.
* `prod` is verified on a fresh SQLite database (`sqlite:////data/app/prod.db`)
  because that is what this environment can prove honestly. No PostgreSQL 16
  server runtime, MSSQL tooling or public deployment is claimed here.
* Synthetic demo telemetry is checked through the demo discovery endpoint, not
  through a real Prometheus scrape; that path has separate evidence.

Usage (from the repository root):

    python3 tests/release_modes_runtime.py --structural-only   # render only
    python3 tests/release_modes_runtime.py                     # all three modes
    python3 tests/release_modes_runtime.py --mode demo --keep   # one mode, no cleanup

Exit codes: ``0`` all requested checks passed, ``1`` a check failed (owned
container logs are printed, bounded), ``2`` the environment cannot run the
requested verification at all.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERIFICATION_DIR = ROOT / ".verification"

IMAGE_BACKEND = "itsm-backend:release-modes-verify"
IMAGE_FRONTEND = "itsm-frontend:release-modes-verify"
IMAGE_OPS = "itsm-ops:release-modes-verify"
STALE_IMAGES = frozenset({"itsm-backend:0.1.0", "itsm-frontend:0.1.0", "itsm-ops:0.1.0"})
REQUIRED_IMAGES = (IMAGE_BACKEND, IMAGE_FRONTEND, IMAGE_OPS)

MODES = ("dev", "prod", "demo")

# One distinct MCS level per mode, reused by every consumer of that project's
# volumes: the base service block requires it and Compose refuses a project
# without it. These are reserved, test-only levels.
SELINUX_LEVELS = {"dev": "s0:c410", "prod": "s0:c411", "demo": "s0:c412"}

EXPECTED_SERVICES = {
    "dev": {"initialize", "backend", "worker", "frontend", "setup", "setup-volume-init"},
    "prod": {"initialize", "backend", "worker", "frontend", "setup", "setup-volume-init"},
    "demo": {"initialize", "backend", "frontend"},
}

PROD_DATABASE_URL = "sqlite:////data/app/prod.db"
INSTALLATION_DIR = "/data/installation"
INSTALLATION_FILE = "/data/installation/installation.json"
INSTALLATION_VOLUME = "installation-config"
PROD_STATUS_TARGET = "/data/backup-status"
PROD_STATUS_PATH = "/data/backup-status/status.json"
PROD_BACKUP_TARGET = "/data/backups"

# Test-only secrets and integrations are supplied here, never read from a file.
# Provider keys and unrelated ITSM_* values from the operator shell are dropped,
# so an exported credential cannot silently reach a verification container.
_DROPPED_EXACT = frozenset(
    {
        "RELEASE_MODE",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "ITSM_SNMP_AUTHS",
    }
)

_PROD_EMPTY_PROBE = """
import json, sqlite3

db = sqlite3.connect('/data/app/prod.db')
tables = {row[0] for row in db.execute("select name from sqlite_master where type='table'")}


def count(name):
    if name not in tables:
        return None
    return db.execute("select count(*) from " + name).fetchone()[0]


print("RESULT " + json.dumps({"assets": count("assets"),
                              "identities": count("identity_identities")}))
"""


class VerificationError(RuntimeError):
    """A bounded verification check failed; the mode run stops immediately."""


# --------------------------------------------------------------------- helpers
def _expect(condition: object, description: str) -> None:
    if not condition:
        raise VerificationError(description)
    print(f"PASS {description}")


def _field(entry: dict, name: str):
    """Read a Compose `ps --format json` field regardless of its casing."""
    for key, value in entry.items():
        if key.lower() == name.lower():
            return value
    return None


def _free_loopback_ports(count: int) -> list[int]:
    """Return distinct loopback ports held open until both are resolved."""
    sockets: list[socket.socket] = []
    try:
        for _ in range(count):
            holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            holder.bind(("127.0.0.1", 0))
            sockets.append(holder)
        return [int(holder.getsockname()[1]) for holder in sockets]
    finally:
        for holder in sockets:
            holder.close()


def _origin(frontend_port: int) -> str:
    return f"http://127.0.0.1:{frontend_port}"


def _base_environment() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if key not in _DROPPED_EXACT and not key.startswith("ITSM_")
    }


def _mode_environment(mode: str, api_port: int, frontend_port: int, dev_password: str):
    """Explicit, test-only configuration for one mode; nothing is inherited."""
    env = _base_environment()
    env["RELEASE_MODE"] = mode
    env["ITSM_SELINUX_LEVEL"] = SELINUX_LEVELS[mode]
    env["ITSM_API_PORT"] = str(api_port)
    env["ITSM_FRONTEND_PORT"] = str(frontend_port)
    env["ITSM_AUTH_ORIGIN"] = _origin(frontend_port)
    env["ITSM_LOG_LEVEL"] = "INFO"
    if mode == "dev":
        env["ITSM_DEV_ADMIN_PASSWORD"] = dev_password
    elif mode == "prod":
        # Fresh, project-owned SQLite file: the only engine this environment can
        # prove without contacting a shared server.
        env["ITSM_DATABASE_URL"] = PROD_DATABASE_URL
        # Production refuses to render without the public origins; the edge
        # under test is that origin here.
        env["ITSM_REPORT_BASE_URL"] = _origin(frontend_port)
        env["ITSM_MONITORING_PUBLIC_URL"] = _origin(frontend_port)
    return env


def _project_name(mode: str, run_id: str) -> str:
    # Unique per mode and run so containers, network and named volumes are new;
    # the project is the only thing cleanup is allowed to touch.
    return f"itsm-verify-{mode}-{run_id}"


def _override_document(mode: str) -> str:
    """Pin every service that can start in this mode to a verification image."""
    lines = ["# Generated by tests/release_modes_runtime.py; do not commit.", "services:"]
    lines += ["  initialize:", f"    image: {IMAGE_OPS if mode == 'prod' else IMAGE_BACKEND}"]
    lines += ["  backend:", f"    image: {IMAGE_BACKEND}"]
    if mode != "demo":
        lines += ["  worker:", f"    image: {IMAGE_BACKEND}"]
    lines += ["  frontend:", f"    image: {IMAGE_FRONTEND}"]
    if mode != "demo":
        # Setup is absent from demo. Its own command stays; only the image tag
        # is pinned so the verification build is the one under test.
        lines += ["  setup:", f"    image: {IMAGE_BACKEND}"]
        # The one-shot initializer shares that image: without the pin it would
        # still name itsm-backend:0.1.0 and Compose would refuse the stale tag.
        lines += ["  setup-volume-init:", f"    image: {IMAGE_BACKEND}"]
    if mode == "prod":
        # Only `prod` declares the backup service; adding it elsewhere would
        # create a service instead of overriding an existing one.
        lines += ["  backup:", f"    image: {IMAGE_OPS}"]
    return "\n".join(lines) + "\n"


def _compose_argv(
    project: str, mode: str, override: Path, *args: str, profiles: tuple[str, ...] = ()
) -> list[str]:
    return [
        "docker",
        "compose",
        "--env-file",
        "/dev/null",
        "--project-name",
        project,
        *[part for profile in profiles for part in ("--profile", profile)],
        "-f",
        "compose.yaml",
        "-f",
        f"deploy/compose.{mode}.yaml",
        "-f",
        str(override),
        *args,
    ]


def _run(argv: list[str], env: dict[str, str], timeout: int) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            argv, cwd=ROOT, env=env, text=True, capture_output=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        raise VerificationError(
            f"command exceeded {timeout}s: {' '.join(argv[:6])} ..."
        ) from None


class Response:
    def __init__(self, status: int, headers, body: bytes) -> None:
        self.status = status
        self.headers = headers
        self.body = body

    def json(self):
        try:
            return json.loads(self.body.decode("utf-8", "replace"))
        except json.JSONDecodeError:
            raise VerificationError("response was not JSON") from None

    def set_cookies(self) -> list[str]:
        return list(self.headers.get_all("Set-Cookie") or [])


def _request(
    url: str,
    *,
    method: str = "GET",
    body: dict | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 10,
) -> Response:
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, method=method)
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return Response(response.status, response.headers, response.read(1_000_000))
    except urllib.error.HTTPError as exc:
        return Response(exc.code, exc.headers, exc.read(1_000_000))


def _session_cookie(response: Response) -> str:
    cookies = [value.split(";", 1)[0].strip() for value in response.set_cookies()]
    cookies = [value for value in cookies if "=" in value]
    if not cookies:
        raise VerificationError("login did not set a session cookie")
    return cookies[0]


def _wait_ready(base_url: str, mode: str, timeout: int) -> dict:
    """Bounded readiness poll; a 503 during preparation is retried, never assumed."""
    deadline = time.monotonic() + timeout
    last = "no response"
    while time.monotonic() < deadline:
        try:
            response = _request(f"{base_url}/api/v1/health/ready", timeout=5)
        except OSError as exc:
            last = f"transport error: {exc.__class__.__name__}"
        else:
            if response.status == 200:
                payload = response.json()
                if payload.get("releaseMode") == mode:
                    return payload
                last = f"releaseMode={payload.get('releaseMode')!r}"
            else:
                last = f"HTTP {response.status}"
        time.sleep(2)
    raise VerificationError(f"readiness did not report releaseMode={mode} ({last})")


def _ps_entries(project: str, mode: str, override: Path, env: dict[str, str]) -> list[dict]:
    result = _run(
        _compose_argv(project, mode, override, "ps", "-a", "--format", "json"), env, 30
    )
    if result.returncode != 0:
        raise VerificationError(f"compose ps failed: {result.stderr.strip()[:300]}")
    text = (result.stdout or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = [json.loads(line) for line in text.splitlines() if line.strip()]
    return parsed if isinstance(parsed, list) else [parsed]


def _assert_initialize_succeeded(
    project: str, mode: str, override: Path, env: dict[str, str]
) -> None:
    entries = _ps_entries(project, mode, override, env)
    initialize = next(
        (entry for entry in entries if _field(entry, "service") == "initialize"), None
    )
    _expect(initialize is not None, f"{mode}: preparation gate container exists")
    state = str(_field(initialize, "state") or "").lower()
    exit_code = _field(initialize, "exitcode")
    _expect(state == "exited", f"{mode}: preparation gate finished (state={state})")
    _expect(
        str(exit_code) == "0", f"{mode}: preparation gate exited 0 (exit={exit_code})"
    )


# ------------------------------------------------------------- rendered schema
def _render(
    project: str,
    mode: str,
    override: Path,
    env: dict[str, str],
    *extra: str,
    profiles: tuple[str, ...] = (),
) -> dict:
    result = _run(
        _compose_argv(
            project, mode, override, "config", "--format", "json", *extra, profiles=profiles
        ),
        env,
        30,
    )
    if result.returncode != 0:
        raise VerificationError(
            f"{mode}: compose config failed: {result.stderr.strip()[:400]}"
        )
    return json.loads(result.stdout)


def _published(service: dict) -> set[tuple[str, str, str]]:
    published = set()
    for entry in service.get("ports", []) or []:
        published.add(
            (
                str(entry.get("host_ip", "")),
                str(entry.get("published", "")),
                str(entry.get("target", "")),
            )
        )
    return published


def _mount_targets(service: dict) -> dict[str, dict]:
    return {str(mount.get("target")): mount for mount in service.get("volumes", []) or []}


def _security_labels(service: dict) -> list[str]:
    return [str(option) for option in service.get("security_opt", []) or []]


def _check_render(model: dict, mode: str, project: str, api_port: int, frontend_port: int,
                  dev_password: str = ""):
    services = model.get("services", {})
    _expect(model.get("name") == project, f"{mode}: compose project name is {project}")
    _expect(
        set(services) == EXPECTED_SERVICES[mode],
        f"{mode}: services are {sorted(EXPECTED_SERVICES[mode])} (got {sorted(services)})",
    )

    for name, service in services.items():
        image = str(service.get("image", ""))
        _expect(image not in STALE_IMAGES, f"{mode}: {name} does not use a stale image tag")
    _expect(
        services["backend"]["image"] == IMAGE_BACKEND,
        f"{mode}: backend image is {IMAGE_BACKEND}",
    )
    _expect(
        services["frontend"]["image"] == IMAGE_FRONTEND,
        f"{mode}: frontend image is {IMAGE_FRONTEND}",
    )
    if mode != "demo":
        _expect(
            services["setup"]["image"] == IMAGE_BACKEND,
            f"{mode}: setup image is {IMAGE_BACKEND}",
        )
    expected_initialize = IMAGE_OPS if mode == "prod" else IMAGE_BACKEND
    _expect(
        services["initialize"]["image"] == expected_initialize,
        f"{mode}: preparation image is {expected_initialize}",
    )
    if "worker" in services:
        _expect(
            services["worker"]["image"] == IMAGE_BACKEND,
            f"{mode}: worker image is {IMAGE_BACKEND}",
        )

    for name in ("initialize", "backend", "worker", "setup"):
        if name not in services:
            continue
        _expect(
            services[name]["environment"].get("RELEASE_MODE") == mode,
            f"{mode}: {name} carries RELEASE_MODE={mode}",
        )

    _expect(
        services["backend"]["depends_on"]["initialize"]["condition"]
        == "service_completed_successfully",
        f"{mode}: backend waits for a successful preparation gate",
    )
    if "worker" in services:
        _expect(
            services["worker"]["depends_on"]["initialize"]["condition"]
            == "service_completed_successfully",
            f"{mode}: worker waits for a successful preparation gate",
        )

    _expect(
        "depends_on" not in services["frontend"],
        f"{mode}: the UI edge boots without waiting for the API",
    )
    if mode != "demo":
        setup = services["setup"]
        _expect(
            set(setup.get("depends_on") or {}) == {"setup-volume-init"},
            f"{mode}: setup waits only for its volume initializer",
        )
        _expect(
            setup["depends_on"]["setup-volume-init"]["condition"]
            == "service_completed_successfully",
            f"{mode}: setup starts after the volume initializer succeeded",
        )
        _expect(
            setup.get("user") == "10001:10001",
            f"{mode}: setup runs as 10001:10001, never root",
        )
        _expect(
            _published(setup) == set(),
            f"{mode}: setup publishes no host port",
        )
        _expect(
            setup.get("read_only") is True,
            f"{mode}: setup root filesystem is read-only",
        )
        _expect(
            setup.get("cap_drop") == ["ALL"],
            f"{mode}: setup drops every capability",
        )
        init = services["setup-volume-init"]
        _expect(
            init.get("image") == setup.get("image"),
            f"{mode}: the volume initializer shares the setup image",
        )
        _expect(
            init.get("user") == "0:0"
            and init.get("network_mode") == "none"
            and init.get("read_only") is True
            and init.get("restart") == "no",
            f"{mode}: the volume initializer is a bounded offline one-shot",
        )
        _expect(
            init.get("cap_drop") == ["ALL"]
            and {"CHOWN", "FOWNER"} <= set(init.get("cap_add") or []),
            f"{mode}: the volume initializer holds only CHOWN and FOWNER",
        )
        setup_mounts = _mount_targets(setup)
        # Verification observes what the worker will use: setup enqueues a real
        # setup ping onto the worker's queue and writes a real probe into the
        # attachment directory, so its private state and settings volumes are
        # joined by the mode-owned queue and attachment targets.
        shared = ("/data/dev",) if mode == "dev" else ("/data/tasks", "/data/attachments")
        _expect(
            set(setup_mounts) == {"/var/lib/itsm-setup", INSTALLATION_DIR, *shared},
            f"{mode}: setup mounts its private volumes and the data it verifies",
        )
        installation_mount = setup_mounts.get(INSTALLATION_DIR)
        _expect(
            installation_mount is not None
            and installation_mount.get("read_only") is not True,
            f"{mode}: setup is the only writer of the installation settings",
        )
        worker_mounts = _mount_targets(services["worker"])
        for target in shared:
            mount = setup_mounts[target]
            _expect(
                mount.get("type") == "volume"
                and mount.get("read_only") is not True
                and str(mount.get("source"))
                == str(worker_mounts.get(target, {}).get("source")),
                f"{mode}: setup writes {target} on the worker's volume",
            )
        for key in ("ITSM_TASK_SQLITE_PATH", "ITSM_ATTACHMENT_STORAGE_PATH"):
            path = setup.get("environment", {}).get(key)
            _expect(
                path == services["worker"].get("environment", {}).get(key),
                f"{mode}: setup and the worker agree on {key}",
            )
        _expect(
            setup.get("environment", {}).get("ITSM_INSTALLATION_CONFIG")
            == INSTALLATION_FILE,
            f"{mode}: setup writes the installation settings file",
        )
        _expect(
            all(mount.get("type") == "volume" for mount in setup_mounts.values())
            and "docker.sock" not in json.dumps(setup_mounts),
            f"{mode}: setup mounts no host path and no Docker socket",
        )
        _expect(
            setup.get("environment", {}).get("ITSM_SETUP_STATE_DIR")
            == "/var/lib/itsm-setup",
            f"{mode}: setup is told where its state volume is",
        )
        # One shared settings volume, one writer: the API, the worker and the
        # preparation gate read the operator's storage choice read-only.
        sources = set()
        for name in ("initialize", "backend", "worker", "setup"):
            _expect(name in services, f"{mode}: {name} exists")
            service = services[name]
            _expect(
                service.get("environment", {}).get("ITSM_INSTALLATION_CONFIG")
                == INSTALLATION_FILE,
                f"{mode}: {name} reads the installation settings file",
            )
            mount = _mount_targets(service).get(INSTALLATION_DIR)
            _expect(
                mount is not None and mount.get("type") == "volume",
                f"{mode}: {name} mounts the installation settings volume",
            )
            sources.add(str(_mount_targets(service).get(INSTALLATION_DIR, {}).get("source")))
        _expect(
            sources == {INSTALLATION_VOLUME},
            f"{mode}: the four services share one installation volume",
        )
        for name in ("initialize", "backend", "worker"):
            mount = _mount_targets(services[name]).get(INSTALLATION_DIR)
            _expect(
                mount is not None and mount.get("read_only") is True,
                f"{mode}: {name} never writes the installation settings",
            )

    _expect(
        _published(services["backend"]) == {("127.0.0.1", str(api_port), "8000")},
        f"{mode}: backend publishes only 127.0.0.1:{api_port}",
    )
    _expect(
        _published(services["frontend"]) == {("127.0.0.1", str(frontend_port), "8080")},
        f"{mode}: frontend publishes only 127.0.0.1:{frontend_port}",
    )

    # Every container that mounts this project's data must carry the same
    # reserved SELinux level, otherwise a shared volume becomes unreadable.
    level_label = f"label=level:{SELINUX_LEVELS[mode]}"
    for name in ("initialize", "backend", "worker", "setup", "setup-volume-init"):
        if name not in services:
            continue
        _expect(
            level_label in _security_labels(services[name]),
            f"{mode}: {name} uses the project SELinux level",
        )

    volume_names = {
        str(value.get("name", "")) for value in (model.get("volumes") or {}).values()
    }
    _expect(
        volume_names and all(name.startswith(project) for name in volume_names),
        f"{mode}: every named volume is owned by project {project}",
    )

    if mode == "dev":
        targets = {"initialize", "backend", "worker"}
        for name in targets:
            mounts = _mount_targets(services[name])
            _expect(
                set(mounts) == {"/data/dev", INSTALLATION_DIR},
                f"dev: {name} mounts the mode-owned /data/dev and settings volumes",
            )
            _expect(
                mounts[INSTALLATION_DIR].get("read_only") is True,
                f"dev: {name} never writes the installation settings",
            )
        settings = services["backend"]["environment"]
        _expect(
            settings.get("ITSM_DATABASE_URL") == "sqlite:////data/dev/dev.db",
            "dev: database is the project-owned SQLite file",
        )
        # This run is the explicit headless seed: the wizard-first dev path
        # starts ownerless when ITSM_DEV_ADMIN_PASSWORD is absent. Ownerlessness
        # needs a second stack, so the runtime check stays with E2E.
        _expect(
            services["initialize"]["environment"].get("ITSM_DEV_ADMIN_PASSWORD")
            == dev_password,
            "dev: the administrator password comes from the environment",
        )
        _expect(
            settings.get("ITSM_AUTH_COOKIE_SECURE") == "false",
            "dev: cookies are limited to loopback HTTP",
        )
    elif mode == "prod":
        initialize = services["initialize"]
        _expect(
            PROD_BACKUP_TARGET in _mount_targets(initialize),
            "prod: preparation owns the persistent backup volume",
        )
        _expect(
            PROD_STATUS_TARGET in _mount_targets(initialize),
            "prod: preparation publishes the backup status volume",
        )
        backend_mounts = _mount_targets(services["backend"])
        _expect(
            PROD_BACKUP_TARGET not in backend_mounts,
            "prod: the API never mounts backup artifacts",
        )
        status_mount = backend_mounts.get(PROD_STATUS_TARGET)
        _expect(
            status_mount is not None and status_mount.get("read_only") is True,
            "prod: the API reads backup status through a read-only mount",
        )
        settings = services["backend"]["environment"]
        _expect(
            settings.get("ITSM_DATABASE_URL") == PROD_DATABASE_URL,
            "prod: the run uses the explicit fresh SQLite DSN",
        )
        _expect(
            settings.get("ITSM_BACKUP_STATUS_PATH") == PROD_STATUS_PATH,
            "prod: the API status path matches the published summary",
        )
        _expect(
            initialize["environment"].get("ITSM_OPS_STATUS_PATH") == PROD_STATUS_PATH,
            "prod: preparation writes the same status path",
        )
        _expect(
            settings.get("ITSM_AUTH_COOKIE_SECURE") == "true",
            "prod: cookies stay Secure",
        )
        _expect(
            initialize.get("restart") == "no",
            "prod: the maintenance gate runs once",
        )
    else:
        for name in ("initialize", "backend"):
            mounts = _mount_targets(services[name])
            _expect(
                set(mounts) == {"/data"},
                f"demo: {name} mounts only the mode-owned /data parent volume",
            )
            _expect(
                services[name]["environment"].get("ITSM_INSTALLATION_CONFIG") == "",
                f"demo: {name} reads no installation settings file",
            )
        settings = services["backend"]["environment"]
        _expect(
            settings.get("ITSM_DATABASE_URL") == "sqlite:////data/demo/demo.db",
            "demo: database is the project-owned SQLite file",
        )
        _expect(
            settings.get("ITSM_PROMETHEUS_URL") == "http://demo-prometheus:9090",
            "demo: telemetry points at the private synthetic scraper",
        )
        _expect(
            settings.get("ITSM_TASK_STORAGE") == "sqlite",
            "demo: task storage is local SQLite",
        )
        for key in (
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "ITSM_AI_CREDENTIAL_KEY",
            "ITSM_AI_BROKER_URL",
            "ITSM_SYSTEM_EXECUTOR_URL",
            "ITSM_HERMES_INSPECTOR_URL",
            "ITSM_EXTENSION_VALIDATOR_URL",
            "ITSM_ALERTMANAGER_URL",
            "ITSM_MEILISEARCH_URL",
        ):
            _expect(
                settings.get(key) == "",
                f"demo: {key} is blank (no real integration from this mode)",
            )


def _check_prod_backup_render(project: str, mode: str, override: Path, env: dict[str, str]):
    model = _render(project, mode, override, env, profiles=("backup",))
    backup = model.get("services", {}).get("backup")
    _expect(backup is not None, "prod: the backup service exists behind its profile")
    _expect(
        backup.get("image") == IMAGE_OPS,
        f"prod: the backup service uses the maintenance image {IMAGE_OPS}",
    )
    _expect(
        PROD_BACKUP_TARGET in _mount_targets(backup),
        "prod: the backup service owns the artifact volume",
    )
    _expect(
        backup.get("environment", {}).get("ITSM_OPS_STATUS_PATH") == PROD_STATUS_PATH,
        "prod: the backup service publishes the status summary",
    )


# ---------------------------------------------------------------- mode runtime
def _check_dev_runtime(base: str, origin: str, dev_password: str, ready: dict) -> None:
    _expect(ready.get("releaseMode") == "dev", "dev: readiness reports mode dev")

    denied = _request(
        f"{base}/api/v1/auth/login",
        method="POST",
        body={"username": "dev.admin", "password": secrets.token_urlsafe(24)},
        headers={"Origin": origin},
    )
    _expect(
        denied.status in (401, 403),
        f"dev: a password that was not supplied is rejected (HTTP {denied.status})",
    )

    login = _request(
        f"{base}/api/v1/auth/login",
        method="POST",
        body={"username": "dev.admin", "password": dev_password},
        headers={"Origin": origin},
    )
    _expect(login.status == 200, f"dev: the supplied dev administrator logs in (HTTP {login.status})")
    session = login.json()
    _expect(
        session.get("user", {}).get("username") == "dev.admin",
        "dev: the session belongs to the supplied account",
    )
    _expect(
        session.get("user", {}).get("roleId") == "superadmin",
        "dev: the supplied account keeps the development Superadmin role",
    )
    _expect(session.get("demoMode") is False, "dev: the session is not a demo session")
    cookie = _session_cookie(login)

    assets = _request(f"{base}/api/v1/assets?limit=1", headers={"Cookie": cookie})
    _expect(assets.status == 200, f"dev: seeded inventory is readable (HTTP {assets.status})")
    payload = assets.json()
    total = payload.get("total", len(payload.get("items", [])))
    _expect(total > 0, f"dev: the fictional development dataset is present ({total} assets)")

    demo_status = _request(f"{base}/api/v1/demo/status")
    _expect(
        demo_status.json().get("enabled") is False,
        "dev: demo reset surfaces stay disabled",
    )


def _check_prod_runtime(base: str, project: str, override: Path, env: dict, ready: dict):
    _expect(ready.get("releaseMode") == "prod", "prod: readiness reports mode prod")

    denied = _request(f"{base}/api/v1/assets")
    _expect(
        denied.status in (401, 403),
        f"prod: an anonymous inventory request is refused (HTTP {denied.status})",
    )
    demo_status = _request(f"{base}/api/v1/demo/status")
    _expect(
        demo_status.json().get("enabled") is False,
        "prod: demo reset surfaces stay disabled",
    )
    telemetry = _request(f"{base}/api/v1/demo/telemetry/targets")
    _expect(telemetry.status == 404, "prod: synthetic discovery does not exist")

    # Fresh-installation proof: read the project-owned database inside an
    # ephemeral, project-owned container (`--rm`), never a host path.
    probe = _run(
        _compose_argv(
            project,
            "prod",
            override,
            "run",
            "--rm",
            "-T",
            "--no-deps",
            "--pull",
            "never",
            "backend",
            "python",
            "-c",
            _PROD_EMPTY_PROBE,
        ),
        env,
        60,
    )
    _expect(
        probe.returncode == 0, f"prod: the empty-database probe ran (exit {probe.returncode})"
    )
    line = next(
        (row for row in (probe.stdout or "").splitlines() if row.startswith("RESULT ")), None
    )
    _expect(line is not None, "prod: the empty-database probe reported its counts")
    counts = json.loads(line.removeprefix("RESULT "))
    _expect(
        counts.get("assets") == 0,
        f"prod: a fresh installation has no assets ({counts.get('assets')})",
    )
    _expect(
        counts.get("identities") == 0,
        f"prod: a fresh installation has no identities ({counts.get('identities')})",
    )


def _check_demo_runtime(base: str, origin: str) -> None:
    status = _request(f"{base}/api/v1/demo/status")
    _expect(status.status == 200, f"demo: the public cycle status answers (HTTP {status.status})")
    cycle = status.json()
    _expect(cycle.get("enabled") is True, "demo: the shared demonstration is enabled")
    _expect(cycle.get("resetting") is False, "demo: the demonstration is not resetting")
    _expect(int(cycle.get("generation") or 0) >= 1, "demo: the cycle generation is known")
    remaining = (
        datetime.fromisoformat(cycle["nextResetAt"]) - datetime.fromisoformat(cycle["serverTime"])
    ).total_seconds()
    _expect(
        0 < remaining <= 3600,
        f"demo: the server countdown is inside the 60-minute cycle ({remaining:.0f}s)",
    )

    login = _request(
        f"{base}/api/v1/auth/login",
        method="POST",
        body={"username": "admin", "password": "admin"},
        headers={"Origin": origin},
    )
    _expect(login.status == 200, f"demo: the visitor account logs in (HTTP {login.status})")
    session = login.json()
    _expect(session.get("user", {}).get("username") == "admin", "demo: the visitor identity is admin")
    _expect(
        session.get("user", {}).get("roleId") == "admin",
        "demo: the visitor is a demonstration administrator, not a Superadmin",
    )
    _expect(session.get("demoMode") is True, "demo: the session is flagged as a demo session")
    permissions = set(session.get("permissions") or [])
    _expect(
        not {code for code in permissions if code.startswith("system.")},
        "demo: the visitor holds no installation/secret authority",
    )
    cookie = _session_cookie(login)

    reserved = _request(f"{base}/api/v1/system/status", headers={"Cookie": cookie})
    _expect(
        reserved.status in (403, 404),
        f"demo: installation status stays refused for the visitor (HTTP {reserved.status})",
    )

    assets = _request(f"{base}/api/v1/assets?limit=1", headers={"Cookie": cookie})
    _expect(assets.status == 200, f"demo: fictional inventory is readable (HTTP {assets.status})")

    targets = _request(f"{base}/api/v1/demo/telemetry/targets")
    _expect(targets.status == 200, f"demo: synthetic discovery answers (HTTP {targets.status})")
    discovered = targets.json()
    _expect(isinstance(discovered, list) and discovered, "demo: discovery returns synthetic nodes")
    labels = discovered[0].get("labels", {})
    for key in ("asset_id", "check_type", "module", "__metrics_path__"):
        _expect(key in labels, f"demo: discovery target carries {key}")
    _expect(labels.get("check_type") == "node", "demo: discovery targets node checks")


def _check_setup_edge(base: str, mode: str) -> None:
    """The wizard answers through the edge while the database-backed API is up.

    A setup container that cannot own its state volume crash-loops, and the
    edge turns that into 502: the shell still loads, so only asking the wizard
    proves the first-start path works.
    """
    allowed = {
        "state", "mode", "release_mode", "setup_enabled", "claim_available",
        "backend", "version", "instance_id", "checks",
    }
    # Mirrors the setup service's own anonymous allowlist: `checks` carries short
    # status words for the wizard, never a setting or a secret.
    forbidden = ("password", "secret", "credential", "ciphertext", "api_key", "token", "dsn")
    deadline = time.monotonic() + 30
    last = "no response"
    while time.monotonic() < deadline:
        try:
            response = _request(f"{base}/api/setup/v1/status", timeout=5)
        except OSError as exc:
            last = exc.__class__.__name__
        else:
            if response.status == 200:
                payload = response.json()
                _expect(
                    isinstance(payload, dict) and set(payload) <= allowed,
                    "setup: the anonymous status carries only its allowlist",
                )
                raw_checks = payload.get("checks")
                checks: dict[str, str] = {}
                for key, value in (raw_checks.items() if isinstance(raw_checks, dict) else ()):
                    _expect(
                        isinstance(key, str) and isinstance(value, str),
                        "setup: the anonymous checks are plain status words",
                    )
                    checks[str(key)] = str(value)
                leaked = [
                    text
                    for text in [*checks, *checks.values()]
                    if any(token in text.lower() for token in forbidden)
                ]
                _expect(
                    not leaked,
                    f"setup: the anonymous status names no setting or secret {leaked}",
                )
                _expect(
                    payload.get("release_mode") == mode,
                    f"setup: status reports release_mode={mode}",
                )
                _expect(
                    payload.get("state") == "disabled"
                    and payload.get("claim_available") is False,
                    "setup: a fresh installation offers no claim yet",
                )
                return
            last = f"HTTP {response.status}"
        time.sleep(2)
    raise VerificationError(f"the setup wizard did not answer through the edge ({last})")


def _check_setup_identity(
    project: str, mode: str, override: Path, env: dict[str, str]
) -> None:
    """The running wizard and its state volume are unprivileged.

    Compose rendering proves the requested user; only `docker inspect` and a
    stat inside the container prove what the kernel actually applied.
    """
    result = _run(_compose_argv(project, mode, override, "ps", "-q", "setup"), env, 30)
    containers = [
        line.strip() for line in (result.stdout or "").splitlines() if line.strip()
    ]
    _expect(bool(containers), f"{mode}: the setup container is running")
    inspect = _run(
        ["docker", "inspect", "--format", "{{.Config.User}}", containers[0]], env, 30
    )
    observed_user = (inspect.stdout or "").strip()
    _expect(
        inspect.returncode == 0 and observed_user == "10001:10001",
        f"{mode}: docker inspect reports setup user 10001:10001 (got {observed_user!r})",
    )
    stat = _run(
        _compose_argv(
            project, mode, override, "exec", "-T", "setup",
            "stat", "-c", "%a %u:%g", "/var/lib/itsm-setup",
        ),
        env,
        30,
    )
    observed_mode = (stat.stdout or "").strip()
    _expect(
        stat.returncode == 0 and observed_mode == "700 10001:10001",
        f"{mode}: the setup state volume is 0700 owned by 10001 (got {observed_mode!r})",
    )
    installation = _run(
        _compose_argv(
            project, mode, override, "exec", "-T", "setup",
            "stat", "-c", "%a %u:%g", INSTALLATION_DIR,
        ),
        env,
        30,
    )
    observed_installation = (installation.stdout or "").strip()
    _expect(
        installation.returncode == 0 and observed_installation == "700 10001:10001",
        f"{mode}: the installation settings volume is 0700 owned by 10001 "
        f"(got {observed_installation!r})",
    )


def _check_frontend(base: str) -> None:
    deadline = time.monotonic() + 30
    last = "no response"
    while time.monotonic() < deadline:
        try:
            response = _request(f"{base}/", timeout=5)
        except OSError as exc:
            last = exc.__class__.__name__
        else:
            if response.status == 200 and "text/html" in str(
                response.headers.get("Content-Type", "")
            ):
                body = response.body
                _expect(
                    b"<html" in body and len(body) > 1000,
                    "frontend: the built application shell is served",
                )
                return
            last = f"HTTP {response.status}"
        time.sleep(2)
    raise VerificationError(f"frontend did not serve its shell ({last})")


# ------------------------------------------------------------------- lifecycle
def _capture_logs(project: str, mode: str, override: Path, env: dict[str, str]) -> None:
    services = sorted(EXPECTED_SERVICES[mode])
    print(f"--- bounded logs for project {project} ({mode}) ---", file=sys.stderr)
    for service in services:
        try:
            result = _run(
                _compose_argv(project, mode, override, "logs", "--no-color", "--tail", "40", service),
                env,
                30,
            )
        except VerificationError:
            print(f"  [{service}] log capture timed out", file=sys.stderr)
            continue
        output = (result.stdout or "") + (result.stderr or "")
        lines = output.splitlines()[-40:]
        print(f"  [{service}] {len(lines)} line(s)", file=sys.stderr)
        for line in lines:
            print(f"  | {line[:400]}", file=sys.stderr)


def _cleanup(project: str, mode: str, override: Path, env: dict[str, str]) -> None:
    """Remove only this project's containers and network; volumes are kept."""
    result = _run(
        _compose_argv(project, mode, override, "down", "--remove-orphans", "--timeout", "20"),
        env,
        120,
    )
    if result.returncode != 0:
        print(
            f"WARN cleanup of {project} returned {result.returncode}: "
            f"{(result.stderr or '').strip()[:200]}",
            file=sys.stderr,
        )


def _assert_volumes_kept(project: str, env: dict[str, str]) -> None:
    result = _run(
        [
            "docker",
            "volume",
            "ls",
            "--filter",
            f"label=com.docker.compose.project={project}",
            "--format",
            "{{.Name}}",
        ],
        env,
        30,
    )
    names = [line for line in (result.stdout or "").splitlines() if line.strip()]
    _expect(bool(names), f"volumes of {project} are preserved after cleanup ({len(names)})")


def run_mode(mode: str, run_id: str, *, structural_only: bool, ready_timeout: int,
             up_timeout: int, keep: bool) -> bool:
    project = _project_name(mode, run_id)
    api_port, frontend_port = _free_loopback_ports(2)
    dev_password = secrets.token_urlsafe(18)
    env = _mode_environment(mode, api_port, frontend_port, dev_password)
    backend_base = f"http://127.0.0.1:{api_port}"
    frontend_base = _origin(frontend_port)
    origin = _origin(frontend_port)

    VERIFICATION_DIR.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w",
        dir=VERIFICATION_DIR,
        prefix=f"compose-override-{mode}-{run_id}-",
        suffix=".yaml",
        delete=False,
    )
    override = Path(handle.name)
    override.write_text(_override_document(mode), encoding="utf-8")
    handle.close()

    started = False
    ok = True
    try:
        print(f"=== {mode}: project {project}, api {api_port}, frontend {frontend_port}")
        model = _render(project, mode, override, env)
        _check_render(model, mode, project, api_port, frontend_port, dev_password)
        if mode == "prod":
            _check_prod_backup_render(project, mode, override, env)
        if structural_only:
            print(f"PASS {mode}: rendered schema only (no containers started)")
            return True

        result = _run(
            _compose_argv(
                project,
                mode,
                override,
                "up",
                "-d",
                "--no-build",
                "--pull",
                "never",
            ),
            env,
            up_timeout,
        )
        started = True
        if result.returncode != 0:
            raise VerificationError(
                f"{mode}: compose up failed ({result.returncode}): "
                f"{(result.stderr or '').strip()[:400]}"
            )
        print(f"PASS {mode}: project started from prebuilt images (no build, no pull)")

        ready = _wait_ready(backend_base, mode, ready_timeout)
        print(f"PASS {mode}: bounded readiness is green")
        _assert_initialize_succeeded(project, mode, override, env)
        _check_frontend(frontend_base)
        if mode != "demo":
            _check_setup_edge(frontend_base, mode)
            _check_setup_identity(project, mode, override, env)

        if mode == "dev":
            _check_dev_runtime(frontend_base, origin, dev_password, ready)
        elif mode == "prod":
            _check_prod_runtime(frontend_base, project, override, env, ready)
        else:
            _check_demo_runtime(frontend_base, origin)
    except VerificationError as exc:
        ok = False
        print(f"FAIL {mode}: {exc}", file=sys.stderr)
        if started:
            _capture_logs(project, mode, override, env)
    finally:
        if started and keep:
            print(f"KEEP {mode}: project {project} left running (--keep)", file=sys.stderr)
        elif started:
            _cleanup(project, mode, override, env)
            try:
                _assert_volumes_kept(project, env)
            except VerificationError as exc:
                ok = False
                print(f"FAIL {mode}: {exc}", file=sys.stderr)
        try:
            override.unlink()
        except OSError as exc:
            print(f"WARN could not remove {override.name}: {exc}", file=sys.stderr)
    return ok


def _image_gaps() -> list[str]:
    gaps = []
    for image in REQUIRED_IMAGES:
        result = _run(["docker", "image", "inspect", "--format", "{{.Id}}", image],
                      _base_environment(), 30)
        if result.returncode != 0:
            gaps.append(image)
    return gaps


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", action="append", choices=MODES, dest="modes",
                        help="restrict to one mode (repeatable); default: all three")
    parser.add_argument("--structural-only", action="store_true",
                        help="render and assert the Compose schema; start nothing")
    parser.add_argument("--ready-timeout", type=int, default=180,
                        help="bounded readiness wait in seconds (default 180)")
    parser.add_argument("--up-timeout", type=int, default=300,
                        help="bounded `compose up` wait in seconds (default 300)")
    parser.add_argument("--keep", action="store_true",
                        help="leave the project running for inspection (volumes are never removed)")
    args = parser.parse_args(argv)

    if shutil.which("docker") is None:
        print("BLOCKED: docker CLI is not available", file=sys.stderr)
        return 2

    modes = tuple(args.modes) if args.modes else MODES
    run_id = f"{int(time.time())}-{secrets.token_hex(3)}"

    gaps = _image_gaps()
    if gaps:
        for image in gaps:
            print(f"GAP missing image: {image}", file=sys.stderr)
        if not args.structural_only:
            print("BLOCKED: prebuilt verification images are required; build them first",
                  file=sys.stderr)
            return 2

    results = {}
    for mode in modes:
        results[mode] = run_mode(
            mode,
            run_id,
            structural_only=args.structural_only,
            ready_timeout=args.ready_timeout,
            up_timeout=args.up_timeout,
            keep=args.keep,
        )

    failed = [mode for mode, passed in results.items() if not passed]
    for mode, passed in results.items():
        print(f"{'PASS' if passed else 'FAIL'} {mode}: {'green' if passed else 'failed'}")
    if failed:
        print(f"RESULT failed: {', '.join(failed)}", file=sys.stderr)
        return 1
    print(f"RESULT green: {', '.join(modes)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
