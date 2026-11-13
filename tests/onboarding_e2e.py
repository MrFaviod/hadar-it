#!/usr/bin/env python3
"""Disposable end-to-end onboarding harness — T7 skeleton.

One run creates a uniquely named Compose project and starts only what a first
installation has before a database exists: the setup service, its volume
initializer, the frontend edge and a fixture AI provider on the project
network. It then walks the implemented onboarding steps:

    boot      the wizard answers through the edge while no database exists
    claim     enable-claim, a rejected credential, the real claim and a session
    ai        configure the fixture provider and prove get_setup_status ran
    restart   state and session survive a setup container restart
    storage   start the stack's own database, classify it empty, prepare it,
              and prove the API, the worker and the gate read the private
              settings file the wizard wrote
    owner     create the first owner, log in to the normal API as superadmin,
              and read the transferred AI provider back through that API

The remaining steps (configuration, verify, complete, recovery, docs-in-image)
are declared stubs: they print ``SKIP`` and are listed in the report. A stub
never passes.

Boundaries that are deliberate:

* Only this project is addressed. Every Docker call carries the project name or
  a ``com.docker.compose.project`` label filter for it; the unrelated
  ``itsm-human-review-demo`` stack or any other project is never named.
* The claim credential, the fixture provider key and the Fernet ring live in
  memory. They are never printed, never written to the report and never placed
  on a command line: the ring travels through the Compose process environment
  and the credential only through an exec pipe and an HTTP body.
* Cleanup in ``finally`` is ``down -v --remove-orphans`` for this project only;
  the run then asserts that no container, volume or network of the project
  remains. ``--keep-on-failure`` keeps the project and prints the exact command
  that removes it.
* Images are never built or pulled: ``--images-tag`` must already exist.

Usage (from the repository root):

    python3 tests/onboarding_e2e.py --mode dev
    python3 tests/onboarding_e2e.py --mode prod --report /tmp/prod.json
    python3 tests/onboarding_e2e.py --mode dev --steps boot,claim --keep-on-failure

Exit codes: ``0`` every requested implemented step passed, ``1`` a step failed
or cleanup left project resources, ``2`` the environment cannot run the
harness at all.
"""

from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
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
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_SCRIPT = ROOT / "tests" / "fixtures" / "ai_provider_fixture.py"

SETUP_PREFIX = "/api/setup/v1"
COOKIE_NAME = "itsm_setup_session"
CSRF_HEADER = "X-CSRF-Token"

# The private settings file the wizard writes and every other process reads.
INSTALLATION_DIR = "/data/installation"
INSTALLATION_FILE = "/data/installation/installation.json"
DEV_DATABASE_URL = "sqlite:////data/dev/dev.db"
PROD_DATABASE_HOST = "postgres"
PROD_DATABASE_NAME = "itsm"
DEV_DATA_INITIALIZER = "e2e-dev-data-init"

# Read-only proof from inside the prepared API container: how many human
# identities exist and how many of them are superadmins. It opens its settings
# the same way the API does, so a file the process cannot read fails here.
HUMAN_COUNT_SCRIPT = """import json
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from itsm.config import get_settings
from itsm.database import create_engine_from_settings
from itsm.identity.models import Identity
from itsm.identity.permissions import HUMAN_ACTOR_KIND

engine = create_engine_from_settings(get_settings())
with Session(engine) as db:
    humans = db.scalar(
        select(func.count())
        .select_from(Identity)
        .where(Identity.actor_kind == HUMAN_ACTOR_KIND)
    )
    superadmins = db.scalar(
        select(func.count())
        .select_from(Identity)
        .where(
            Identity.actor_kind == HUMAN_ACTOR_KIND,
            Identity.role_id == "superadmin",
        )
    )
print(json.dumps({"humans": humans, "superadmins": superadmins}))
"""

FIXTURE_SERVICE = "ai-fixture"
FIXTURE_PORT = 8080
FIXTURE_MODEL = "probe-model"
FIXTURE_BASE_URL = f"http://{FIXTURE_SERVICE}:{FIXTURE_PORT}/v1"

STEP_ORDER = ("boot", "claim", "ai", "restart", "storage", "owner")
STUB_STEPS: dict[str, str] = {
    "configuration": "not implemented yet; waits for the configuration step (T5)",
    "verify": "not implemented yet; waits for the verified transfer step (T5)",
    "complete": "not implemented yet; waits for the completion step (T6)",
    "recovery": "not implemented yet; waits for the recovery step (T6)",
    "docs-in-image": "not implemented yet; waits for the bundled-docs step (T6)",
}

# The anonymous status allowlist from itsm.setup.schemas, restated so the
# harness fails when the wire grows a field before this contract is updated.
STATUS_ALLOWLIST = frozenset(
    {
        "state",
        "mode",
        "release_mode",
        "setup_enabled",
        "claim_available",
        "backend",
        "version",
        "instance_id",
        "checks",
    }
)
FORBIDDEN_STATUS_TOKENS = ("password", "secret", "credential", "ciphertext", "api_key", "token", "dsn")

# One reserved, test-only MCS level per mode, distinct from the levels
# tests/release_modes_runtime.py reserves, so concurrent runs cannot share a
# volume label.
SELINUX_LEVELS = {"dev": "s0:c430", "prod": "s0:c431"}

_DROPPED_ENV = frozenset({"RELEASE_MODE", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "ITSM_SNMP_AUTHS"})

DEFAULT_IMAGES_TAG = "release-modes-verify"


class HarnessBlocked(RuntimeError):
    """The environment cannot run this harness; nothing was asserted."""


class StepFailure(RuntimeError):
    """One implemented step failed; its reason is recorded and printed."""


class CommandError(RuntimeError):
    """A Docker command could not be completed (timeout or transport)."""


def _expect(condition: object, description: str) -> None:
    if not condition:
        raise StepFailure(description)


def _field(entry: dict, name: str):
    """Read a Compose ``ps --format json`` field regardless of its casing."""
    for key, value in entry.items():
        if key.lower() == name.lower():
            return value
    return None


def _free_loopback_ports(count: int) -> list[int]:
    holders: list[socket.socket] = []
    try:
        for _ in range(count):
            holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            holder.bind(("127.0.0.1", 0))
            holders.append(holder)
        return [int(holder.getsockname()[1]) for holder in holders]
    finally:
        for holder in holders:
            holder.close()


def _run(
    argv: list[str], env: dict[str, str], timeout: int, cwd: Path = ROOT
) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            argv,
            cwd=str(cwd),
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise CommandError(f"command exceeded {timeout}s: {' '.join(argv[:6])} ...") from None
    except OSError as exc:
        raise CommandError(f"command could not start: {exc.__class__.__name__}") from None


class Response:
    def __init__(self, status: int, headers, body: bytes) -> None:
        self.status = status
        self.headers = headers
        self.body = body

    def json(self):
        try:
            return json.loads(self.body.decode("utf-8", "replace"))
        except json.JSONDecodeError:
            raise StepFailure("response was not JSON") from None

    def text(self) -> str:
        return self.body.decode("utf-8", "replace")


class Client:
    """Small browser-shaped client: cookie jar plus an explicit Origin header.

    Production issues the setup cookie with ``Secure`` while the harness talks
    to loopback HTTP, exactly like a browser that treats loopback as a secure
    context. ``secure_protocols`` therefore admits http for this test client
    only; the cookie's own flags are asserted separately.
    """

    def __init__(self, base_url: str, origin: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.origin = origin
        policy = http.cookiejar.DefaultCookiePolicy(secure_protocols=("https", "http"))
        self.jar = http.cookiejar.CookieJar(policy)
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = 15,
    ) -> Response:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(self.base_url + path, data=data, method=method)
        request.add_header("Accept", "application/json")
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with self.opener.open(request, timeout=timeout) as response:
                return Response(response.status, response.headers, response.read(1_000_000))
        except urllib.error.HTTPError as exc:
            return Response(exc.code, exc.headers, exc.read(1_000_000))

    def cookie_names(self) -> list[str]:
        return [cookie.name for cookie in self.jar]


class Harness:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.mode: str = args.mode
        self.images_tag: str = args.images_tag
        self.project = self._project_name()
        self.api_port, self.frontend_port = _free_loopback_ports(2)
        self.origin = f"http://127.0.0.1:{self.frontend_port}"
        self.client = Client(self.origin, self.origin)
        self.credential_key = self._fernet_key()
        self.provider_key = secrets.token_urlsafe(24)
        self.csrf = ""
        self.env = self._environment()
        self.temp_dir = Path(tempfile.mkdtemp(prefix=f"onboarding-e2e-{self.mode}-"))
        self.override = self.temp_dir / "compose.override.yaml"
        self.override.write_text(self._override_document(), encoding="utf-8")

        self.started = False
        self.failed_steps: list[str] = []
        self.exit_code = 1
        self.steps: list[dict] = []
        self.leftovers: dict[str, list[str]] = {}
        self.cleanup = "not started"
        self.report_path = self._report_path()

    # ------------------------------------------------------------- construction
    @staticmethod
    def _fernet_key() -> str:
        """A fresh valid Fernet key; the setup process never generates one."""
        import base64

        return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")

    def _project_name(self) -> str:
        # Unique per mode and run: containers, network and the setup volume are
        # new, and cleanup can only ever address this one project.
        return f"itsm-e2e-{self.mode}-{int(time.time())}-{secrets.token_hex(3)}"

    def _report_path(self) -> Path:
        if self.args.report:
            return Path(self.args.report).expanduser()
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        return Path(tempfile.gettempdir()) / f"onboarding-e2e-{self.mode}-{stamp}.json"

    def _base_environment(self) -> dict[str, str]:
        return {
            key: value
            for key, value in os.environ.items()
            if key not in _DROPPED_ENV and not key.startswith("ITSM_")
        }

    def _environment(self) -> dict[str, str]:
        env = self._base_environment()
        env["RELEASE_MODE"] = self.mode
        env["ITSM_SELINUX_LEVEL"] = SELINUX_LEVELS[self.mode]
        env["ITSM_API_PORT"] = str(self.api_port)
        env["ITSM_FRONTEND_PORT"] = str(self.frontend_port)
        env["ITSM_AUTH_ORIGIN"] = self.origin
        env["ITSM_LOG_LEVEL"] = "INFO"
        # Interpolated into the generated override, never written into it.
        env["ITSM_AI_CREDENTIAL_KEYS"] = self.credential_key
        # The fixture's exact DNS name (no port so any port matches) is the only
        # private destination this project authorizes.
        env["ITSM_AI_PERSONAL_PRIVATE_ENDPOINTS"] = FIXTURE_SERVICE
        if self.mode == "dev":
            env["ITSM_DEV_ADMIN_PASSWORD"] = secrets.token_urlsafe(18)
        else:
            # The same explicit values tests/release_modes_runtime.py supplies:
            # a project-owned SQLite file and the edge as the public origin.
            # The stack's own postgres service is started by the storage step.
            # compose.prod.yaml requires an explicit production database, so the
            # environment carries the same candidate the wizard is given. The API
            # still has to read it back through the shared settings volume; the
            # dev mode is where the file alone drives the process.
            password = secrets.token_urlsafe(24)
            env["ITSM_POSTGRES_PASSWORD"] = password
            env["ITSM_DATABASE_URL"] = (
                f"postgresql+psycopg://itsm:{password}@postgres:5432/itsm"
            )
            env["ITSM_REPORT_BASE_URL"] = self.origin
            env["ITSM_MONITORING_PUBLIC_URL"] = self.origin
        return env

    @property
    def backend_image(self) -> str:
        return f"itsm-backend:{self.images_tag}"

    @property
    def frontend_image(self) -> str:
        return f"itsm-frontend:{self.images_tag}"

    def _override_document(self) -> str:
        lines = [
            "# Generated by tests/onboarding_e2e.py; disposable, never committed.",
            "services:",
            "  setup:",
            f"    image: {self.backend_image}",
            "    environment:",
            "      # Values are interpolated from the harness process; the file holds",
            "      # variable names so no credential is ever written to disk.",
            "      ITSM_AI_CREDENTIAL_KEYS: ${ITSM_AI_CREDENTIAL_KEYS:-}",
            "      ITSM_AI_PERSONAL_PRIVATE_ENDPOINTS: ${ITSM_AI_PERSONAL_PRIVATE_ENDPOINTS:-}",
        ]
        if self.mode == "dev":
            # The wizard needs a writable directory for the dev SQLite target.
            # A root one-shot owns it exactly like setup-volume-init owns the
            # wizard state, and the API reads the same volume.
            lines += [
                "    volumes:",
                "      - dev-data:/data/dev",
            ]
        lines += [
            "  setup-volume-init:",
            f"    image: {self.backend_image}",
            "  frontend:",
            f"    image: {self.frontend_image}",
        ]
        if self.mode == "dev":
            lines += [
                f"  {DEV_DATA_INITIALIZER}:",
                f"    image: {self.backend_image}",
                '    user: "0:0"',
                '    command: [sh, -c, "chown 10001:10001 /data/dev && chmod 0700 /data/dev"]',
                "    network_mode: none",
                "    volumes:",
                "      - dev-data:/data/dev",
                '    security_opt: ["no-new-privileges:true", "label=level:${ITSM_SELINUX_LEVEL:-}"]',
                "    cap_drop: [ALL]",
                "    cap_add: [CHOWN, FOWNER]",
                "    read_only: true",
                '    restart: "no"',
                "    pids_limit: 16",
            ]
        if self.mode == "dev":
            # Dev has no database env at all: the API must read the settings file
            # the wizard wrote, and an explicit variable would win over that file.
            for name in ("backend", "worker"):
                lines += [
                    f"  {name}:",
                    f"    image: {self.backend_image}",
                    "    environment:",
                    "      ITSM_DATABASE_URL: null",
                ]
            lines += [
                "  initialize:",
                "    environment:",
                "      ITSM_DATABASE_URL: null",
            ]
        else:
            # Prod keeps its required explicit URL; only the image is pinned.
            for name in ("backend", "worker"):
                lines += [f"  {name}:", f"    image: {self.backend_image}"]
        lines += [
            f"  {FIXTURE_SERVICE}:",
            f"    image: {self.backend_image}",
            "    command: [python, /opt/itsm-fixture/ai_provider_fixture.py]",
            '    user: "10001:10001"',
            "    read_only: true",
            "    tmpfs: [/tmp]",
            "    cap_drop: [ALL]",
            '    security_opt: ["no-new-privileges:true"]',
            '    restart: "no"',
            "    pids_limit: 32",
            "    environment:",
            f"      FIXTURE_MODEL: {FIXTURE_MODEL}",
            '      PYTHONDONTWRITEBYTECODE: "1"',
            "    volumes:",
            f"      - {FIXTURE_SCRIPT}:/opt/itsm-fixture/ai_provider_fixture.py:ro",
        ]
        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------ docker
    def compose_argv(self, *args: str, profiles: tuple[str, ...] = ()) -> list[str]:
        argv = ["docker", "compose", "--env-file", "/dev/null", "--project-name", self.project]
        for profile in profiles:
            argv += ["--profile", profile]
        return [
            *argv,
            "-f",
            "compose.yaml",
            "-f",
            f"deploy/compose.{self.mode}.yaml",
            "-f",
            str(self.override),
            *args,
        ]

    def compose(
        self,
        *args: str,
        timeout: int = 60,
        check: bool = False,
        profiles: tuple[str, ...] = (),
    ):
        result = _run(self.compose_argv(*args, profiles=profiles), self.env, timeout)
        if check and result.returncode != 0:
            raise StepFailure(
                f"docker compose {' '.join(args[:2])} failed ({result.returncode}): "
                f"{(result.stderr or '').strip()[:300]}"
            )
        return result

    def docker(self, *args: str, timeout: int = 30, check: bool = False):
        result = _run(
            ["docker", *args],
            self.env,
            timeout,
        )
        if check and result.returncode != 0:
            raise StepFailure(
                f"docker {' '.join(args[:2])} failed ({result.returncode}): "
                f"{(result.stderr or '').strip()[:300]}"
            )
        return result

    def ps_entries(self) -> list[dict]:
        result = self.compose("ps", "-a", "--format", "json", timeout=30, check=True)
        text = (result.stdout or "").strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = [json.loads(line) for line in text.splitlines() if line.strip()]
        return parsed if isinstance(parsed, list) else [parsed]

    def container_id(self, service: str) -> str:
        result = self.compose("ps", "-q", service, timeout=30, check=True)
        values = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
        _expect(values and len(values) == 1, f"exactly one {service} container exists")
        return values[0]

    def container_started_at(self, container: str) -> str:
        result = self.docker("inspect", "--format", "{{.State.StartedAt}}", container, check=True)
        return (result.stdout or "").strip()

    def container_health(self, container: str) -> str:
        result = self.docker(
            "inspect",
            "--format",
            "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}",
            container,
            check=True,
        )
        return (result.stdout or "").strip()

    def project_resources(self) -> dict[str, list[str]]:
        """Only this project's resources, resolved through its Compose label."""
        label = f"label=com.docker.compose.project={self.project}"
        checks = {
            "containers": ["docker", "ps", "-a", "--filter", label, "--format", "{{.ID}}"],
            "volumes": ["docker", "volume", "ls", "--filter", label, "--format", "{{.Name}}"],
            "networks": ["docker", "network", "ls", "--filter", label, "--format", "{{.Name}}"],
        }
        resources: dict[str, list[str]] = {}
        for name, argv in checks.items():
            result = _run(argv, self.env, 30)
            resources[name] = [
                line.strip() for line in (result.stdout or "").splitlines() if line.strip()
            ]
        return resources

    # -------------------------------------------------------------------- http
    def wait_http(
        self,
        path: str,
        predicate,
        *,
        timeout: int,
        description: str,
        headers: dict[str, str] | None = None,
        client: Client | None = None,
        interval: float = 1.0,
    ) -> Response:
        active = client or self.client
        deadline = time.monotonic() + timeout
        last = "no response"
        while time.monotonic() < deadline:
            try:
                response = active.request("GET", path, headers=headers, timeout=5)
            except OSError as exc:
                last = f"transport error: {exc.__class__.__name__}"
            else:
                if predicate(response):
                    return response
                last = f"HTTP {response.status}"
            time.sleep(interval)
        raise StepFailure(f"{description} did not settle within {timeout}s ({last})")

    def wait_status(self, *, timeout: int, predicate=None) -> dict:
        response = self.wait_http(
            f"{SETUP_PREFIX}/status",
            lambda candidate: candidate.status == 200
            and (predicate is None or _safe_json(candidate) is not None and predicate(_safe_json(candidate))),
            timeout=timeout,
            description="setup status",
        )
        return response.json()

    # ------------------------------------------------------------------- guards
    def preflight(self) -> None:
        if shutil.which("docker") is None:
            raise HarnessBlocked("docker CLI is not available")
        missing = [
            image
            for image in (self.backend_image, self.frontend_image)
            if _run(["docker", "image", "inspect", "--format", "{{.Id}}", image], self.env, 30).returncode
            != 0
        ]
        if missing:
            raise HarnessBlocked(
                "prebuilt images are required; missing: " + ", ".join(missing)
            )
        if not FIXTURE_SCRIPT.is_file():
            raise HarnessBlocked(f"fixture provider script is missing: {FIXTURE_SCRIPT}")

        existing = self.project_resources()
        found = {name: values for name, values in existing.items() if values}
        if found:
            raise HarnessBlocked(
                f"refusing project {self.project}: it already has resources {found}"
            )

    # ------------------------------------------------------------------- steps
    def step_boot(self) -> dict:
        up = self.compose(
            "up",
            "-d",
            "--no-build",
            "--pull",
            "never",
            "setup-volume-init",
            "setup",
            "frontend",
            FIXTURE_SERVICE,
            timeout=self.args.startup_timeout,
        )
        self.started = True
        _expect(
            up.returncode == 0,
            f"compose up failed ({up.returncode}): {(up.stderr or '').strip()[:400]}",
        )

        entries = {str(_field(entry, "service")): entry for entry in self.ps_entries()}
        for service in ("setup", "frontend", FIXTURE_SERVICE):
            _expect(service in entries, f"{service} container exists")
            state = str(_field(entries[service], "state") or "").lower()
            _expect(state == "running", f"{service} is running (state={state})")

        frontend = self.container_id("frontend")
        deadline = time.monotonic() + 60
        health = self.container_health(frontend)
        while health != "healthy" and time.monotonic() < deadline:
            time.sleep(2)
            health = self.container_health(frontend)
        _expect(health == "healthy", f"the frontend edge reports healthy (got {health!r})")

        shell = self.wait_http(
            "/",
            lambda response: response.status == 200
            and "text/html" in str(response.headers.get("Content-Type", "")),
            timeout=60,
            description="the application shell",
        )
        _expect(
            b"<html" in shell.body and len(shell.body) > 1000,
            "the served shell is the built application",
        )

        status = self.wait_status(timeout=self.args.startup_timeout)
        body_text = json.dumps(status, sort_keys=True)
        _expect(
            set(status) <= STATUS_ALLOWLIST,
            f"the anonymous status carries only its allowlist (got {sorted(status)})",
        )
        _expect(
            status.get("mode") == self.mode and status.get("release_mode") == self.mode,
            f"status reports release_mode={self.mode} (got {status.get('release_mode')!r})",
        )
        _expect(
            status.get("state") == "disabled",
            f"a fresh installation is disabled (got {status.get('state')!r})",
        )
        _expect(status.get("setup_enabled") is False, "setup is not enabled before enable-claim")
        _expect(status.get("claim_available") is False, "a fresh installation offers no claim yet")
        _expect(status.get("backend") == "unknown", "the wizard never reports the API state")
        leaked = [token for token in FORBIDDEN_STATUS_TOKENS if token in body_text.lower()]
        _expect(not leaked, f"the anonymous status carries no secret token (got {leaked})")

        # The database-backed API is absent on purpose: the edge must degrade to
        # a gateway error, never a 404 page and never a working API.
        api = self.client.request("GET", "/api/v1/health/ready", timeout=10)
        _expect(
            api.status in (502, 503),
            f"an API request without the API degrades to 502/503 (got {api.status})",
        )

        return {
            "edge": self.origin,
            "frontend_container": frontend,
            "frontend_health": health,
            "status": status,
            "api_without_backend": api.status,
        }

    def step_claim(self) -> dict:
        anonymous = self.client.request("GET", f"{SETUP_PREFIX}/session", timeout=10)
        _expect(anonymous.status == 401, f"an anonymous session is refused (got {anonymous.status})")

        enabled = self.compose(
            "exec",
            "-T",
            "setup",
            "python",
            "-m",
            "itsm.setup.cli",
            "enable-claim",
            timeout=60,
        )
        _expect(
            enabled.returncode == 0,
            f"enable-claim failed ({enabled.returncode}): {(enabled.stderr or '').strip()[:300]}",
        )
        lines = [line for line in (enabled.stdout or "").splitlines() if line.strip()]
        _expect(bool(lines), "enable-claim printed a result")
        try:
            grant = json.loads(lines[-1])
        except json.JSONDecodeError:
            raise StepFailure("enable-claim did not print JSON") from None
        _expect(grant.get("status") == "ok", f"enable-claim reported ok (got {grant.get('status')!r})")
        _expect(grant.get("action") == "enable-claim", "enable-claim reported its action")
        _expect(grant.get("state") == "unclaimed", "enable-claim left the installation unclaimed")
        credential = grant.get("credential")
        _expect(
            isinstance(credential, str) and len(credential) >= 20,
            "enable-claim returned a bounded credential",
        )

        status = self.wait_status(
            timeout=30,
            predicate=lambda payload: payload.get("claim_available") is True,
        )
        _expect(status.get("state") == "unclaimed", "the wizard now offers the claim step")
        _expect(status.get("setup_enabled") is True, "setup is enabled after enable-claim")

        wrong = self.client.request(
            "POST",
            f"{SETUP_PREFIX}/claim",
            body={"credential": secrets.token_urlsafe(32)},
            headers={"Origin": self.origin},
        )
        _expect(wrong.status == 401, f"a wrong claim credential is refused (got {wrong.status})")
        _expect(
            COOKIE_NAME not in self.client.cookie_names(),
            "a rejected claim sets no session cookie",
        )

        claim = self.client.request(
            "POST",
            f"{SETUP_PREFIX}/claim",
            body={"credential": credential},
            headers={"Origin": self.origin},
        )
        _expect(claim.status == 200, f"the real claim is accepted (got {claim.status})")
        claimed = claim.json()
        _expect(claimed.get("state") == "claimed", "the claim reports the claimed state")
        csrf = claimed.get("csrf_token")
        _expect(isinstance(csrf, str) and len(csrf) >= 20, "the claim returned a CSRF token")
        self.csrf = csrf

        cookies = claim.headers.get_all("Set-Cookie") or []
        session_cookie = next(
            (value for value in cookies if value.startswith(f"{COOKIE_NAME}=")), None
        )
        _expect(session_cookie is not None, "the claim set the setup session cookie")
        session_cookie = session_cookie or ""
        _expect("HttpOnly" in session_cookie, "the session cookie is HttpOnly")
        secure_flag = "Secure" in session_cookie
        # The shipped default is Secure everywhere and no overlay turns it off,
        # so the flag is recorded rather than tied to the mode. The client jar
        # carries it over the loopback origin the same way a browser does.
        _expect(
            "samesite=strict" in session_cookie.lower(),
            "the session cookie is SameSite=strict",
        )
        _expect(
            "Path=/api/setup/v1" in session_cookie,
            "the session cookie is scoped to the setup API path",
        )
        _expect(
            COOKIE_NAME in self.client.cookie_names(),
            "the cookie jar keeps the setup session",
        )

        session = self.client.request("GET", f"{SETUP_PREFIX}/session", timeout=10)
        _expect(session.status == 200, f"the claimed session is accepted (got {session.status})")
        _expect(session.json().get("state") == "claimed", "the session reports the claimed state")

        return {
            "anonymous_session": anonymous.status,
            "state_after_enable": status.get("state"),
            "wrong_credential": wrong.status,
            "claim": claim.status,
            "cookie_secure": secure_flag,
            "session": session.status,
            "csrf_present": True,
        }

    def _wait_fixture(self) -> dict:
        deadline = time.monotonic() + 60
        last = "no response"
        while time.monotonic() < deadline:
            result = self.compose(
                "exec",
                "-T",
                FIXTURE_SERVICE,
                "python",
                "-c",
                "import urllib.request;"
                "print(urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2).status)",
                timeout=15,
            )
            if result.returncode == 0 and "200" in (result.stdout or ""):
                return {"health": "ok"}
            last = (result.stderr or "").strip()[:200]
            time.sleep(1)
        raise StepFailure(f"the fixture provider did not answer healthz ({last})")

    def _fixture_log(self) -> str:
        result = self.compose(
            "logs", "--no-color", "--tail", "200", FIXTURE_SERVICE, timeout=30
        )
        return (result.stdout or "") + (result.stderr or "")

    def step_ai(self) -> dict:
        self._wait_fixture()

        configure = self.client.request(
            "POST",
            f"{SETUP_PREFIX}/ai",
            body={
                "base_url": FIXTURE_BASE_URL,
                "model": FIXTURE_MODEL,
                "api_key": self.provider_key,
            },
            headers={"Origin": self.origin, CSRF_HEADER: self.csrf},
            timeout=60,
        )
        _expect(
            configure.status == 200,
            f"the provider configuration is accepted (got {configure.status}: "
            f"{configure.text()[:120]})",
        )
        _expect(
            self.provider_key not in configure.text(),
            "the response never echoes the provider credential",
        )
        payload = configure.json()
        _expect(payload.get("state") == "ai_configured", "the wizard reports ai_configured")
        receipt = payload.get("ai") or {}
        _expect(receipt.get("status") == "configured", "the AI receipt is configured")
        _expect(
            receipt.get("provider") == FIXTURE_SERVICE,
            f"the receipt names the fixture host (got {receipt.get('provider')!r})",
        )
        _expect(receipt.get("model") == FIXTURE_MODEL, "the receipt names the probed model")
        _expect(
            receipt.get("tool") == "get_setup_status",
            f"the receipt proves get_setup_status ran (got {receipt.get('tool')!r})",
        )
        _expect(
            int(payload.get("discovered_models") or 0) >= 1,
            "model discovery returned at least one model",
        )

        status = self.wait_status(timeout=30, predicate=lambda body: body.get("state") == "ai_configured")
        _expect(status.get("state") == "ai_configured", "the status reflects the AI step")

        # Provider-side observation: the fixture saw a completion offer tools
        # and later a tool result, not merely a receipt the service wrote.
        log = self._fixture_log()
        offered = [
            int(line.split("tools=", 1)[1].split()[0])
            for line in log.splitlines()
            if "REQUEST POST /v1/chat/completions tools=" in line
        ]
        _expect(any(count > 0 for count in offered), "the provider received a tool-enabled turn")
        _expect(
            "tool_result=true" in log,
            "the provider received the get_setup_status result",
        )

        return {
            "ai_state": payload.get("state"),
            "receipt": {
                key: receipt.get(key)
                for key in ("status", "provider", "model", "tool", "latency_ms")
            },
            "discovered_models": payload.get("discovered_models"),
            "provider_tool_turns": offered,
        }

    def step_restart(self) -> dict:
        before = self.wait_status(timeout=30, predicate=lambda body: body.get("state") == "ai_configured")
        session_before = self.client.request("GET", f"{SETUP_PREFIX}/session", timeout=10)
        _expect(session_before.status == 200, "the session is valid before the restart")

        container = self.container_id("setup")
        started_before = self.container_started_at(container)
        restart = self.compose("restart", "--no-deps", "setup", timeout=90)
        _expect(
            restart.returncode == 0,
            f"the setup container could not restart ({restart.returncode}): "
            f"{(restart.stderr or '').strip()[:300]}",
        )

        after = self.wait_status(
            timeout=60,
            predicate=lambda body: body.get("instance_id") == before.get("instance_id"),
        )
        _expect(after.get("state") == "ai_configured", "the AI state survives the restart")
        _expect(
            after.get("instance_id") == before.get("instance_id"),
            "the installation id survives the restart",
        )
        started_after = self.container_started_at(container)
        _expect(
            started_after != started_before,
            "the setup process actually restarted",
        )

        session_after = self.client.request("GET", f"{SETUP_PREFIX}/session", timeout=10)
        _expect(
            session_after.status == 200,
            f"the session survives the restart (got {session_after.status})",
        )
        _expect(
            session_after.json().get("state") == "ai_configured",
            "the surviving session reports the AI state",
        )

        return {
            "instance_id": after.get("instance_id"),
            "state": after.get("state"),
            "restarted": started_before != started_after,
            "session": session_after.status,
        }

    # ---------------------------------------------------------------- storage
    def _database_url(self) -> str:
        """The candidate the operator would type into the wizard."""

        if self.mode == "dev":
            return DEV_DATABASE_URL
        password = quote(self.env["ITSM_POSTGRES_PASSWORD"], safe="")
        return (
            f"postgresql+psycopg://itsm:{password}@{PROD_DATABASE_HOST}:5432/"
            f"{PROD_DATABASE_NAME}"
        )

    def _start_database(self) -> dict:
        """Start the stack's own database and leave it ready to be probed."""

        if self.mode == "dev":
            # The wizard needs a writable directory for the dev SQLite target;
            # the one-shot owns the volume exactly like setup-volume-init owns
            # the wizard state, and the API reads the same volume.
            prepared = self.compose(
                "run", "--rm", "--no-deps", DEV_DATA_INITIALIZER, timeout=120
            )
            _expect(
                prepared.returncode == 0,
                f"the dev data volume could not be prepared ({prepared.returncode}): "
                f"{(prepared.stderr or '').strip()[:300]}",
            )
            return {"engine": "sqlite", "service": DEV_DATA_INITIALIZER}

        started = self.compose(
            "up",
            "-d",
            "--no-build",
            "--pull",
            "never",
            "postgres",
            profiles=("local-postgres",),
            timeout=self.args.startup_timeout,
        )
        _expect(
            started.returncode == 0,
            f"the stack's postgres service did not start ({started.returncode}): "
            f"{(started.stderr or '').strip()[:300]}",
        )
        container = self.container_id("postgres")
        deadline = time.monotonic() + 120
        health = self.container_health(container)
        while health != "healthy" and time.monotonic() < deadline:
            time.sleep(2)
            health = self.container_health(container)
        _expect(
            health == "healthy",
            f"the stack's postgres service becomes healthy (got {health!r})",
        )
        return {"engine": "postgresql", "service": "postgres", "health": health}

    def setup_mutation(self, path: str, body: dict, timeout: int = 60) -> Response:
        return self.client.request(
            "POST",
            f"{SETUP_PREFIX}{path}",
            body=body,
            headers={"Origin": self.origin, CSRF_HEADER: self.csrf},
            timeout=timeout,
        )

    def _json_in(self, service: str, code: str, timeout: int = 60) -> dict:
        """Run bounded Python inside a service and parse its last JSON line."""

        result = self.compose("exec", "-T", service, "python", "-c", code, timeout=timeout)
        _expect(
            result.returncode == 0,
            f"the {service} helper failed ({result.returncode}): "
            f"{(result.stderr or '').strip()[:300]}",
        )
        lines = [line for line in (result.stdout or "").splitlines() if line.strip()]
        try:
            return json.loads(lines[-1]) if lines else {}
        except json.JSONDecodeError:
            raise StepFailure(f"the {service} helper printed no JSON") from None

    def step_storage(self) -> dict:
        database = self._start_database()
        database_url = self._database_url()

        checked = self.setup_mutation("/storage/check", {"database_url": database_url})
        _expect(
            checked.status == 200,
            f"the storage probe is accepted (got {checked.status}: {checked.text()[:160]})",
        )
        probe = checked.json()
        _expect(probe.get("reachable") is True, "the wizard reaches the database")
        _expect(
            probe.get("status") == "empty",
            f"an unclaimed database is classified empty (got {probe.get('status')!r})",
        )
        _expect(probe.get("adoptable") is True, "an empty database is adoptable")

        prepared = self.setup_mutation(
            "/storage", {"database_url": database_url}, timeout=180
        )
        _expect(
            prepared.status == 200,
            f"the storage step is accepted (got {prepared.status}: {prepared.text()[:200]})",
        )
        payload = prepared.json()
        _expect(
            payload.get("state") == "storage_ready",
            f"the wizard reports storage_ready (got {payload.get('state')!r})",
        )
        storage = payload.get("storage") or {}
        _expect(
            storage.get("status") == "ours",
            f"the database is claimed for this installation (got {storage.get('status')!r})",
        )
        _expect(
            storage.get("config_source") == "installation",
            "the wizard wrote the installation settings file",
        )
        _expect(storage.get("migrated") is True, "the wizard applied the migrations")
        _expect(
            storage.get("identity_claimed") is True,
            "the wizard claimed the deployment identity",
        )

        stat = self.compose(
            "exec", "-T", "setup", "stat", "-c", "%a %u:%g", INSTALLATION_FILE, timeout=30
        )
        file_mode = (stat.stdout or "").strip()
        _expect(
            stat.returncode == 0 and file_mode == "600 10001:10001",
            f"the installation file is 0600 owned by 10001 (got {file_mode!r})",
        )
        directory = self.compose(
            "exec", "-T", "setup", "stat", "-c", "%a %u:%g", INSTALLATION_DIR, timeout=30
        )
        directory_mode = (directory.stdout or "").strip()
        _expect(
            directory.returncode == 0 and directory_mode == "700 10001:10001",
            f"the installation directory is 0700 owned by 10001 "
            f"(got {directory_mode!r})",
        )

        written = self._json_in(
            "setup",
            "import hashlib, json\n"
            f"payload = json.load(open({INSTALLATION_FILE!r}, encoding='utf-8'))\n"
            "url = payload.get('database_url') or ''\n"
            "print(json.dumps({'keys': sorted(payload),"
            " 'sha256': hashlib.sha256(url.encode('utf-8')).hexdigest()}))\n",
        )
        _expect(
            "database_url" in (written.get("keys") or []),
            "the installation file names a database",
        )
        _expect(
            written.get("sha256")
            == hashlib.sha256(database_url.encode("utf-8")).hexdigest(),
            "the installation file names the database the operator prepared",
        )

        # No initialize here: the API must start from the file the wizard wrote.
        started = self.compose(
            "up",
            "-d",
            "--no-build",
            "--pull",
            "never",
            "--no-deps",
            "backend",
            timeout=self.args.startup_timeout,
        )
        _expect(
            started.returncode == 0,
            f"the API did not start ({started.returncode}): "
            f"{(started.stderr or '').strip()[:300]}",
        )
        ready = self.wait_http(
            "/api/v1/health/ready",
            lambda response: response.status == 200,
            timeout=120,
            description="API readiness through the edge",
        )
        checks = (ready.json().get("checks") or {})
        _expect(
            checks.get("database") == "ok",
            f"the API reports its database ready (got {checks.get('database')!r})",
        )
        _expect(
            checks.get("migrations") == "ok",
            f"the wizard left the schema at the current head "
            f"(got {checks.get('migrations')!r})",
        )

        readable = self._json_in(
            "backend",
            "import hashlib, json\n"
            f"payload = json.load(open({INSTALLATION_FILE!r}, encoding='utf-8'))\n"
            "url = payload.get('database_url') or ''\n"
            "print(json.dumps({'keys': sorted(payload),"
            " 'sha256': hashlib.sha256(url.encode('utf-8')).hexdigest()}))\n",
        )
        _expect(
            readable.get("sha256")
            == hashlib.sha256(database_url.encode("utf-8")).hexdigest(),
            "the API process reads the settings file the wizard wrote",
        )

        safe_url = self._json_in(
            "backend",
            "import json\n"
            "from itsm.config import get_settings\n"
            "print(json.dumps({'database': get_settings().safe_database_url()}))\n",
        ).get("database")
        expected = (
            DEV_DATABASE_URL
            if self.mode == "dev"
            else f"postgresql+psycopg://itsm:***@{PROD_DATABASE_HOST}:5432/"
            f"{PROD_DATABASE_NAME}"
        )
        _expect(
            safe_url == expected,
            f"the API serves the database the wizard prepared (got {safe_url!r})",
        )

        counts = self._json_in("backend", HUMAN_COUNT_SCRIPT)
        _expect(
            counts.get("humans") == 0,
            f"the wizard seeds no human user (got {counts.get('humans')!r})",
        )

        return {
            "engine": database["engine"],
            "probe": probe.get("status"),
            "storage": storage.get("status"),
            "config_source": storage.get("config_source"),
            "installation_mode": file_mode,
            "readiness": checks.get("migrations"),
            "database": safe_url,
            "humans": counts.get("humans"),
        }

    # ------------------------------------------------------------------ owner
    def step_owner(self) -> dict:
        password = secrets.token_urlsafe(24)
        owner_body = {
            "username": "owner",
            "display_name": "Installation Owner",
            "email": "owner@example.invalid",
            "password": password,
        }

        created = self.setup_mutation("/owner", owner_body, timeout=180)
        _expect(
            created.status == 200,
            f"the first owner is created (got {created.status}: {created.text()[:200]})",
        )
        payload = created.json()
        _expect(
            payload.get("state") == "owner_ready",
            f"the wizard reports owner_ready (got {payload.get('state')!r})",
        )
        receipt = payload.get("owner") or {}
        _expect(
            receipt.get("username") == "owner",
            f"the receipt names the new owner (got {receipt.get('username')!r})",
        )
        _expect(
            payload.get("ai") == "transferred",
            f"the early AI provider is handed over (got {payload.get('ai')!r})",
        )

        # The backend replays owner_ready idempotently instead of refusing, so
        # the safety property asserted here is that no second human appears.
        replay = self.setup_mutation("/owner", owner_body, timeout=180)
        _expect(
            replay.status in (200, 409),
            f"a second owner is refused or replayed (got {replay.status})",
        )
        if replay.status == 200:
            _expect(
                (replay.json().get("owner") or {}).get("username") == "owner",
                "a replayed owner request answers with the first owner",
            )

        counts = self._json_in("backend", HUMAN_COUNT_SCRIPT)
        _expect(
            counts.get("humans") == 1,
            f"exactly one human identity exists (got {counts.get('humans')!r})",
        )
        _expect(
            counts.get("superadmins") == 1,
            f"the first owner is the only superadmin (got {counts.get('superadmins')!r})",
        )

        api = Client(f"http://127.0.0.1:{self.api_port}", self.origin)
        login = api.request(
            "POST",
            "/api/v1/auth/login",
            body={"username": "owner", "password": password},
            headers={"Origin": self.origin},
            timeout=30,
        )
        _expect(
            login.status == 200,
            f"the new owner can log in to the API (got {login.status}: {login.text()[:200]})",
        )
        envelope = login.json()
        user = envelope.get("user") or {}
        _expect(
            user.get("username") == "owner",
            f"the API session names the new owner (got {user.get('username')!r})",
        )
        _expect(
            user.get("roleId") == "superadmin",
            f"the new owner is superadmin (got {user.get('roleId')!r})",
        )
        me = api.request("GET", "/api/v1/auth/me", timeout=30)
        _expect(
            me.status == 200,
            f"the API session is reusable (got {me.status})",
        )

        listing = api.request("GET", "/api/v1/agent/providers", timeout=30)
        _expect(
            listing.status == 200,
            f"the owner can list providers (got {listing.status}: {listing.text()[:200]})",
        )
        items = listing.json().get("items") or []
        _expect(
            len(items) == 1,
            f"the AI step leaves exactly one provider (got {len(items)})",
        )
        provider = items[0]
        _expect(
            provider.get("baseUrl") == FIXTURE_BASE_URL,
            f"the transferred provider keeps the configured endpoint "
            f"(got {provider.get('baseUrl')!r})",
        )
        _expect(
            provider.get("scope") == "personal",
            f"the transferred provider is personal (got {provider.get('scope')!r})",
        )
        _expect(
            provider.get("name") == "Onboarding provider",
            f"the transferred provider keeps its name (got {provider.get('name')!r})",
        )

        # Reload resume: the wizard drops its CSRF value on reload, asks
        # /session for it again, and a mutation then succeeds.
        self.csrf = ""
        reloaded = self.client.request("GET", f"{SETUP_PREFIX}/session", timeout=10)
        _expect(
            reloaded.status == 200,
            f"a reloaded wizard still has its session (got {reloaded.status})",
        )
        token = reloaded.json().get("csrf_token")
        _expect(
            isinstance(token, str) and len(token) >= 20,
            "a reloaded wizard gets its CSRF token back",
        )
        self.csrf = token or ""
        resumed = self.setup_mutation(
            "/storage", {"database_url": self._database_url()}, timeout=60
        )
        _expect(
            resumed.status == 200,
            f"a mutation with the resumed CSRF token succeeds (got {resumed.status}: "
            f"{resumed.text()[:160]})",
        )
        _expect(
            resumed.json().get("state") == "owner_ready",
            "the resumed mutation changes no state",
        )

        return {
            "state": payload.get("state"),
            "owner": receipt.get("username"),
            "ai": payload.get("ai"),
            "replay": replay.status,
            "role": user.get("roleId"),
            "providers": len(items),
            "resumed_csrf": resumed.status,
        }

    # ----------------------------------------------------------------- control
    def _cleanup_profiles(self) -> tuple[str, ...]:
        """Profiles whose services were started on purpose, so ``down`` sees them."""
        return ("local-postgres",) if self.mode == "prod" else ()

    def _capture_logs(self) -> dict[str, list[str]]:
        print(f"--- bounded logs for project {self.project} ({self.mode}) ---", file=sys.stderr)
        captured: dict[str, list[str]] = {}
        for service in ("setup", "backend", "postgres", "frontend", FIXTURE_SERVICE):
            try:
                result = self.compose(
                    "logs", "--no-color", "--tail", "40", service, timeout=30
                )
            except CommandError as exc:
                print(f"  [{service}] log capture failed: {exc}", file=sys.stderr)
                continue
            lines = [
                line[:400]
                for line in ((result.stdout or "") + (result.stderr or "")).splitlines()[-40:]
            ]
            captured[service] = lines
            print(f"  [{service}] {len(lines)} line(s)", file=sys.stderr)
            for line in lines:
                print(f"  | {line}", file=sys.stderr)
        return captured

    def _record(self, name: str, status: str, *, reason: str = "", observations=None) -> None:
        entry = {"name": name, "status": status}
        if reason:
            entry["reason"] = reason
        if observations is not None:
            entry["observations"] = observations
        self.steps.append(entry)

    def _run_steps(self) -> None:
        implemented = [name for name in STEP_ORDER if name in self.args.steps]
        stubs = [name for name in STUB_STEPS if name in self.args.steps]
        print(
            f"=== e2e {self.mode}: project {self.project}, edge {self.origin}, "
            f"implemented={implemented or 'none'}"
        )

        blocker: str | None = None
        for name in implemented:
            if blocker is not None:
                self._record(name, "SKIP", reason=f"not attempted: {blocker} failed")
                continue
            try:
                observations = getattr(self, f"step_{name}")()
            except StepFailure as exc:
                blocker = name
                self.failed_steps.append(name)
                self._record(name, "FAIL", reason=str(exc))
                print(f"FAIL {name}: {exc}", file=sys.stderr)
            except CommandError as exc:
                blocker = name
                self.failed_steps.append(name)
                self._record(name, "FAIL", reason=str(exc))
                print(f"FAIL {name}: {exc}", file=sys.stderr)
            except Exception as exc:  # noqa: BLE001 - the report must name the class
                blocker = name
                self.failed_steps.append(name)
                reason = f"unexpected {exc.__class__.__name__}: {str(exc)[:200]}"
                self._record(name, "FAIL", reason=reason)
                print(f"FAIL {name}: {reason}", file=sys.stderr)
            else:
                self._record(name, "PASS", observations=observations)
                print(f"PASS {name}")

        for name in stubs:
            reason = STUB_STEPS[name]
            self._record(name, "SKIP", reason=reason)
            print(f"SKIP {name}: {reason}")

    # ---------------------------------------------------------------- lifecycle
    def _finish(self) -> None:
        keep = bool(self.args.keep_on_failure and self.failed_steps)
        logs: dict[str, list[str]] = {}
        if self.started and self.failed_steps:
            logs = self._capture_logs()

        if self.started and keep:
            self.cleanup = "kept"
            print(
                f"KEEP {self.project}: containers and volumes were kept for inspection "
                f"(--keep-on-failure)",
                file=sys.stderr,
            )
            print(
                "CLEAN docker compose --env-file /dev/null "
                f"--project-name {self.project} "
                f"{'--profile local-postgres ' if self.mode == 'prod' else ''}"
                f"-f compose.yaml -f deploy/compose.{self.mode}.yaml -f {self.override} "
                "down -v --remove-orphans",
                file=sys.stderr,
            )
            self.leftovers = self.project_resources()
        elif self.started:
            self.cleanup = "removed"
            try:
                self.compose(
                    "down", "-v", "--remove-orphans", "--timeout", "20",
                    profiles=self._cleanup_profiles(),
                    timeout=120,
                )
            except CommandError as exc:
                print(f"WARN cleanup could not complete: {exc}", file=sys.stderr)
            self.leftovers = self.project_resources()
            if any(self.leftovers.values()):
                print(f"FAIL cleanup: resources remain {self.leftovers}", file=sys.stderr)
                self.failed_steps.append("cleanup")
            else:
                print(f"PASS cleanup: no container, volume or network of {self.project} remains")
        else:
            self.leftovers = self.project_resources()

        if self.args.keep_on_failure and self.failed_steps:
            print(f"KEEP override: {self.override}", file=sys.stderr)
        else:
            shutil.rmtree(self.temp_dir, ignore_errors=True)

        if self.failed_steps:
            self.exit_code = 1
        elif self.exit_code != 2:
            # ``run`` arms 1 before the steps; a clean pass disarms it.
            self.exit_code = 0

        self._write_report(logs)

    def _write_report(self, logs: dict[str, list[str]]) -> None:
        skipped = [entry["name"] for entry in self.steps if entry["status"] == "SKIP"]
        overall = {0: "passed", 1: "failed"}.get(self.exit_code, "blocked")
        report = {
            "harness": "onboarding-e2e",
            "version": "t7-storage-owner",
            "status": overall,
            "mode": self.mode,
            "project": self.project,
            "images": {"backend": self.backend_image, "frontend": self.frontend_image},
            "edge": self.origin,
            "steps": self.steps,
            "skipped": skipped,
            "failed": self.failed_steps,
            "cleanup": self.cleanup,
            "leftovers": self.leftovers,
            "keep_on_failure": bool(self.args.keep_on_failure),
            "finished_at": datetime.now(UTC).isoformat(),
            "exit_code": self.exit_code,
        }
        if logs:
            report["captured_services"] = sorted(logs)
        try:
            self.report_path.parent.mkdir(parents=True, exist_ok=True)
            self.report_path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        except OSError as exc:
            print(f"WARN could not write report {self.report_path}: {exc}", file=sys.stderr)
        else:
            print(f"REPORT {self.report_path}")

    def run(self) -> int:
        self.exit_code = 2
        try:
            self.preflight()
            self.exit_code = 1
            self._run_steps()
        except HarnessBlocked as exc:
            self.exit_code = 2
            print(f"BLOCKED: {exc}", file=sys.stderr)
            self._record("blocked", "BLOCKED", reason=str(exc))
        except CommandError as exc:
            self.exit_code = 1
            self.failed_steps.append("command")
            print(f"FAIL command: {exc}", file=sys.stderr)
        finally:
            try:
                self._finish()
            except Exception as exc:  # noqa: BLE001 - cleanup must never mask the result
                print(f"WARN cleanup raised {exc.__class__.__name__}: {exc}", file=sys.stderr)
                self.exit_code = 1

        implemented = [name for name in STEP_ORDER if name in self.args.steps]
        if self.failed_steps:
            print(f"RESULT failed: {self.mode} (failed: {', '.join(self.failed_steps)})")
            return 1
        if self.exit_code == 2:
            print(f"RESULT blocked: {self.mode}")
            return 2
        skipped = [name for name in STUB_STEPS if name in self.args.steps]
        print(
            f"RESULT passed: {self.mode} "
            f"({len(implemented)} implemented step(s), {len(skipped)} skipped)"
        )
        return 0


def _safe_json(response: Response):
    try:
        return response.json()
    except StepFailure:
        return None


def _parse_steps(raw: str, parser: argparse.ArgumentParser) -> tuple[str, ...]:
    known = set(STEP_ORDER) | set(STUB_STEPS)
    values = [part.strip() for part in raw.split(",")]
    if any(not value for value in values):
        parser.error("--steps must be a comma list without empty entries")
    unknown = [value for value in values if value not in known]
    if unknown:
        parser.error(
            f"unknown step(s) {unknown}; implemented: {', '.join(STEP_ORDER)}; "
            f"stubs: {', '.join(STUB_STEPS)}"
        )
    selected = tuple(dict.fromkeys(values))
    ordered_implemented = tuple(name for name in STEP_ORDER if name in selected)
    if ordered_implemented != STEP_ORDER[: len(ordered_implemented)]:
        parser.error(
            "implemented steps are sequential; select a prefix of "
            + ",".join(STEP_ORDER)
        )
    return selected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Disposable end-to-end onboarding harness (T7 skeleton)."
    )
    parser.add_argument("--mode", choices=("dev", "prod"), required=True)
    parser.add_argument(
        "--keep-on-failure",
        action="store_true",
        help="keep the project (containers and volumes) when a step fails",
    )
    parser.add_argument(
        "--images-tag",
        default=DEFAULT_IMAGES_TAG,
        help=f"existing image tag both images carry (default {DEFAULT_IMAGES_TAG})",
    )
    parser.add_argument(
        "--steps",
        default=",".join(STEP_ORDER),
        help="comma list; implemented steps are a prefix of " + ",".join(STEP_ORDER),
    )
    parser.add_argument(
        "--report",
        default=None,
        help="JSON report path (default: $TMPDIR/onboarding-e2e-<mode>-<stamp>.json)",
    )
    parser.add_argument(
        "--startup-timeout",
        type=int,
        default=180,
        help="bounded wait for the stack and the wizard, in seconds (default 180)",
    )
    args = parser.parse_args(argv)
    args.steps = _parse_steps(args.steps, parser)
    return Harness(args).run()


if __name__ == "__main__":
    sys.exit(main())
