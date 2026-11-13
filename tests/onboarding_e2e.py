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

The later steps drive assisted configuration, verification, completion and
recovery through the setup API, and read the bundled documentation pack from
inside the API image. Every observation is recorded; an item the operator
postponed stays postponed and a production backup accepted as a risk stays a
risk, never a pass.

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
import ssl
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

STEP_ORDER = (
    "boot",
    "claim",
    "ai",
    "restart",
    "storage",
    "owner",
    "configuration",
    "verify",
    "complete",
    "recovery",
    "docs-in-image",
)
STUB_STEPS: dict[str, str] = {}

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


class StepBlocked(RuntimeError):
    """A step cannot be asserted in this environment; never a pass and never a skip."""


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
        self.ssl_context = (
            ssl._create_unverified_context() if self.base_url.startswith("https://") else None
        )
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar),
            urllib.request.HTTPSHandler(context=self.ssl_context),
        )

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
        ports = _free_loopback_ports(3 if self.mode == "prod" else 2)
        self.api_port, self.frontend_port = ports[:2]
        self.tls_port = ports[2] if self.mode == "prod" else None
        if self.mode == "prod" and self.tls_port is not None:
            # Production refuses a loopback origin: the wizard must be reached
            # through a TLS edge on a public name, exactly like the documented
            # reverse-proxy deployment. The disposable edge terminates TLS with
            # a self-signed certificate and proxies the frontend container.
            self.origin = f"https://itsm-e2e.test:{self.tls_port}"
            client_base = f"https://127.0.0.1:{self.tls_port}"
        else:
            self.origin = f"http://127.0.0.1:{self.frontend_port}"
            client_base = self.origin
        self.client = Client(client_base, self.origin)
        self.credential_key = self._fernet_key()
        self.provider_key = secrets.token_urlsafe(24)
        self.csrf = ""
        self.env = self._environment()
        self.temp_dir = Path(tempfile.mkdtemp(prefix=f"onboarding-e2e-{self.mode}-"))
        self.override = self.temp_dir / "compose.override.yaml"
        if self.mode == "prod":
            self._write_tls_edge()
        self.override.write_text(self._override_document(), encoding="utf-8")

        self.started = False
        self.failed_steps: list[str] = []
        self.blocked_steps: list[str] = []
        self.blocked_sources: dict[str, str] = {}
        self.snapshot_archive: Path | None = None
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
        # The assisted agent section reads its credential from the process
        # environment, exactly like an operator-provided key. The disposable
        # value is the fixture's and the OpenAI-compatible base URL points at
        # the same fixture, so the probe is a real tool-calling round trip.
        env["OPENAI_API_KEY"] = self.provider_key
        env["ITSM_AGENT_OPENAI_BASE_URL"] = FIXTURE_BASE_URL
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
        ]
        if self.mode == "prod":
            # A disposable TLS edge on the public name the harness configured as
            # ITSM_AUTH_ORIGIN. It is the only origin the client speaks to, so
            # production's Secure-cookie/public-origin rule is exercised for real.
            lines += [
                "  tls-edge:",
                "    image: nginx:stable",
                "    depends_on: [frontend]",
                "    ports:",
                f'      - "127.0.0.1:{self.tls_port}:8443"',
                "    volumes:",
                f"      - {self.temp_dir}/nginx.conf:/etc/nginx/nginx.conf:ro",
                f"      - {self.temp_dir}/cert.pem:/etc/tls/cert.pem:ro",
                f"      - {self.temp_dir}/key.pem:/etc/tls/key.pem:ro",
            ]
        lines += [
            "  setup:",
            f"    image: {self.backend_image}",
            "    environment:",
            "      # Values are interpolated from the harness process; the file holds",
            "      # variable names so no credential is ever written to disk.",
            "      ITSM_AI_CREDENTIAL_KEYS: ${ITSM_AI_CREDENTIAL_KEYS:-}",
            "      ITSM_AI_PERSONAL_PRIVATE_ENDPOINTS: ${ITSM_AI_PERSONAL_PRIVATE_ENDPOINTS:-}",
            "      OPENAI_API_KEY: ${OPENAI_API_KEY:-}",
            "      ITSM_AGENT_OPENAI_BASE_URL: ${ITSM_AGENT_OPENAI_BASE_URL:-}",
        ]
        # The queue and attachment volumes the wizard verifies are part of the
        # shipped Compose wiring; the override only supplies the disposable AI
        # fixture and image pins.
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

    def _write_tls_edge(self) -> None:
        """Generate the disposable certificate and nginx config for prod."""
        cert = self.temp_dir / "cert.pem"
        key = self.temp_dir / "key.pem"
        generated = _run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "1",
                "-subj",
                "/CN=itsm-e2e.test",
                "-addext",
                "subjectAltName=DNS:itsm-e2e.test",
                "-keyout",
                str(key),
                "-out",
                str(cert),
            ],
            self.env,
            timeout=60,
        )
        _expect(
            generated.returncode == 0,
            f"the disposable TLS certificate is generated ({(generated.stderr or '').strip()[:200]})",
        )
        (self.temp_dir / "nginx.conf").write_text(
            "\n".join(
                [
                    "events {}",
                    "http {",
                    "  server {",
                    "    listen 8443 ssl;",
                    "    ssl_certificate /etc/tls/cert.pem;",
                    "    ssl_certificate_key /etc/tls/key.pem;",
                    "    location / {",
                    "      proxy_pass http://frontend:8080;",
                    "      proxy_http_version 1.1;",
                    "      proxy_set_header Host $host;",
                    "      proxy_set_header X-Forwarded-Proto https;",
                    "      proxy_set_header X-Forwarded-For $remote_addr;",
                    "    }",
                    "  }",
                    "}",
                    "",
                ]
            ),
            encoding="utf-8",
        )

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
        if self.args.browser:
            if shutil.which("uv") is None:
                raise HarnessBlocked(
                    "uv is required for --browser (uv run --no-project --with playwright)"
                )
            if not (ROOT / "tests" / "onboarding_browser.py").is_file():
                raise HarnessBlocked("tests/onboarding_browser.py is missing")

        existing = self.project_resources()
        found = {name: values for name, values in existing.items() if values}
        if found:
            raise HarnessBlocked(
                f"refusing project {self.project}: it already has resources {found}"
            )

    # ------------------------------------------------------------------- steps
    def step_boot(self) -> dict:
        services = ["setup-volume-init", "setup", "frontend", FIXTURE_SERVICE]
        if self.mode == "prod":
            services.append("tls-edge")
        up = self.compose(
            "up",
            "-d",
            "--no-build",
            "--pull",
            "never",
            *services,
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

    def _enable_claim(self) -> dict:
        """Issue the one-time credential and wait until the wizard offers it."""

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
        return {"credential": credential, "status": status}

    def step_claim(self) -> dict:
        anonymous = self.client.request("GET", f"{SETUP_PREFIX}/session", timeout=10)
        _expect(anonymous.status == 401, f"an anonymous session is refused (got {anonymous.status})")

        grant = self._enable_claim()
        credential = grant["credential"]
        status = grant["status"]

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

    def _start_api(self) -> dict:
        """Start the API over the installation file the wizard wrote."""

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
        checks = ready.json().get("checks") or {}
        _expect(
            checks.get("database") == "ok",
            f"the API reports its database ready (got {checks.get('database')!r})",
        )
        _expect(
            checks.get("migrations") == "ok",
            f"the wizard left the schema at the current head "
            f"(got {checks.get('migrations')!r})",
        )
        return checks

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
        checks = self._start_api()

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

    # --------------------------------------------------------- configuration
    @staticmethod
    def _checklist_by_id(body: dict) -> dict[str, dict]:
        return {
            str(item.get("id")): item
            for item in body.get("checklist") or []
            if isinstance(item, dict)
        }

    def _section(self, name: str) -> dict:
        response = self.client.request(
            "GET", f"{SETUP_PREFIX}/configuration/{name}", timeout=30
        )
        _expect(
            response.status == 200,
            f"the {name} section is readable (got {response.status}: {response.text()[:160]})",
        )
        return response.json()

    def step_configuration(self) -> dict:
        started = self.setup_mutation("/configuration", {})
        _expect(
            started.status == 200,
            f"configuration starts (got {started.status}: {started.text()[:200]})",
        )
        _expect(
            started.json().get("state") == "configuring",
            "the wizard reports the configuring state",
        )

        overview = self.client.request("GET", f"{SETUP_PREFIX}/configuration", timeout=30)
        _expect(
            overview.status == 200,
            f"the configuration overview is readable (got {overview.status})",
        )
        sections = {
            str(item.get("section")): item
            for item in overview.json().get("sections") or []
            if isinstance(item, dict)
        }
        _expect(
            (sections.get("appearance") or {}).get("status") == "pending",
            "appearance starts undecided",
        )

        appearance = self._section("appearance")
        current = appearance.get("current") or {}
        preset_before = str(current.get("preset") or "")
        builtins = [str(value) for value in current.get("builtinIds") or []]
        target = next(
            (
                name
                for name in ("blue", "forest", "generic")
                if name != preset_before and (not builtins or name in builtins)
            ),
            None,
        )
        _expect(target is not None, f"a different appearance preset exists (current {preset_before!r})")

        preview = self.setup_mutation(
            "/configuration/appearance", {"values": {"preset": target}}
        )
        _expect(
            preview.status == 200,
            f"the appearance change previews (got {preview.status}: {preview.text()[:200]})",
        )
        preview_body = preview.json()
        _expect(
            preview_body.get("status") == "preview" and preview_body.get("preview_only") is True,
            "the preview reports itself as a preview",
        )
        changes = preview_body.get("changes") or []
        _expect(
            any(
                change.get("field") == "preset" and change.get("to") == target
                for change in changes
                if isinstance(change, dict)
            ),
            f"the preview lists the preset change to {target!r}",
        )
        _expect(
            (self._section("appearance").get("current") or {}).get("preset") == preset_before,
            "the preview wrote nothing",
        )

        applied = self.setup_mutation(
            "/configuration/appearance/apply",
            {"values": {"preset": target}, "action": "apply", "confirm": True},
        )
        _expect(
            applied.status == 200,
            f"the appearance change applies (got {applied.status}: {applied.text()[:200]})",
        )
        _expect(
            applied.json().get("status") == "passed",
            f"the appearance receipt is green (got {applied.json().get('status')!r})",
        )
        readback = self._section("appearance")
        _expect(readback.get("status") == "passed", "the appearance decision is stored as green")
        _expect(
            (readback.get("current") or {}).get("preset") == target,
            f"the applied appearance reads back as {target!r}",
        )

        postponed = self.setup_mutation(
            "/configuration/notifications/apply",
            {
                "values": {"reason": "e2e defers notification channels"},
                "action": "postpone",
                "confirm": True,
            },
        )
        _expect(
            postponed.status == 200,
            f"notifications can be postponed (got {postponed.status}: {postponed.text()[:200]})",
        )
        _expect(
            postponed.json().get("status") == "postponed",
            f"notifications are recorded as postponed (got {postponed.json().get('status')!r})",
        )
        notification = self._section("notifications")
        _expect(
            notification.get("status") == "postponed",
            f"the postponed decision reads back (got {notification.get('status')!r})",
        )
        _expect(
            notification.get("status") != "passed",
            "a postponed section is never reported green",
        )

        return {
            "state": started.json().get("state"),
            "preset_before": preset_before,
            "preset_after": (readback.get("current") or {}).get("preset"),
            "changed_fields": [change.get("field") for change in changes if isinstance(change, dict)],
            "notifications": notification.get("status"),
        }

    # -------------------------------------------------------------- verify
    def _start_worker(self) -> None:
        started = self.compose(
            "up",
            "-d",
            "--no-build",
            "--pull",
            "never",
            "--no-deps",
            "worker",
            timeout=self.args.startup_timeout,
        )
        _expect(
            started.returncode == 0,
            f"the worker starts ({started.returncode}): {(started.stderr or '').strip()[:300]}",
        )

    def _apply_agent_section(self) -> dict:
        applied = self.setup_mutation(
            "/configuration/agent/apply",
            {
                "values": {"provider": "openai", "model": FIXTURE_MODEL},
                "action": "apply",
                "confirm": True,
            },
            timeout=180,
        )
        _expect(
            applied.status == 200,
            f"the agent section applies (got {applied.status}: {applied.text()[:240]})",
        )
        body = applied.json()
        receipt = body.get("receipt") or {}
        return {
            "status": body.get("status"),
            "capability": receipt.get("capability"),
            "tool": receipt.get("tool"),
            "reason": receipt.get("reason"),
        }

    def step_verify(self) -> dict:
        self._start_worker()
        agent = self._apply_agent_section()
        _expect(
            agent.get("capability") == "verified",
            f"the agent probe observed the model calling a tool (got {agent!r})",
        )
        _expect(
            agent.get("status") == "passed",
            f"the agent section is green after the observed probe (got {agent.get('status')!r})",
        )

        response = self.setup_mutation("/verify", {}, timeout=180)
        for _ in range(3):
            if response.status == 200:
                break
            body = _safe_json(response) or {}
            if "worker_ready" not in set(body.get("blocking") or []):
                break
            time.sleep(5)
            response = self.setup_mutation("/verify", {}, timeout=180)

        body = _safe_json(response) or {}
        items = self._checklist_by_id(body)
        blocking = [str(name) for name in body.get("blocking") or []]

        if self.mode == "prod":
            backup = items.get("backup_policy_declared") or {}
            _expect(backup.get("required") is True, "the production backup is required")
            _expect(
                backup.get("status") != "passed",
                "an undeclared production backup is not green before it is decided",
            )
            risk = self.setup_mutation(
                "/configuration/operational/apply",
                {
                    "values": {
                        "item": "backup_policy_declared",
                        "reason": "e2e accepts the backup risk",
                    },
                    "action": "accept_risk",
                    "confirm": True,
                },
            )
            _expect(
                risk.status == 200,
                f"the backup risk is accepted (got {risk.status}: {risk.text()[:200]})",
            )
            _expect(
                risk.json().get("status") == "risk",
                f"the accepted backup is reported as a risk (got {risk.json().get('status')!r})",
            )
            _expect(
                (self._section("operational").get("status")) == "risk",
                "the accepted risk reads back as a risk",
            )
            response = self.setup_mutation("/verify", {}, timeout=180)
            body = _safe_json(response) or {}
            items = self._checklist_by_id(body)
            blocking = [str(name) for name in body.get("blocking") or []]
            backup = items.get("backup_policy_declared") or {}
            _expect(
                backup.get("status") == "risk" and backup.get("acceptedRisk") is True,
                f"the checklist keeps the backup as an accepted risk (got {backup!r})",
            )
            _expect(
                backup.get("blocking") is False,
                "the accepted backup risk no longer blocks",
            )

        if response.status != 200:
            _expect(
                body.get("error") == "verification_blocked",
                f"a refused verification reports verification_blocked (got {body.get('error')!r})",
            )
            if "ai_explicit" in blocking:
                pending = items.get("ai_explicit") or {}
                raise StepBlocked(
                    "verify refused: required ai_explicit is "
                    f"{pending.get('status')!r} ({pending.get('evidence')})"
                )
            if "session_valid" in blocking:
                pending = items.get("session_valid") or {}
                raise StepBlocked(
                    "verify refused: required session_valid is "
                    f"{pending.get('status')!r} ({pending.get('evidence')}); production "
                    "requires Secure cookies on a public origin and the harness edge is loopback"
                )
            raise StepFailure(
                "verify refused with blocking "
                f"{blocking}: "
                + "; ".join(
                    f"{item.get('id')}={item.get('status')}: {str(item.get('evidence'))[:140]}"
                    for item in items.values()
                    if item.get("id") in blocking
                )
            )

        _expect(body.get("state") == "verifying", f"verify opens verifying (got {body.get('state')!r})")
        _expect(body.get("ready") is True, "the checklist reports ready")
        required = [item for item in items.values() if item.get("required")]
        non_green = [
            str(item.get("id"))
            for item in required
            if item.get("status") != "passed" and item.get("acceptedRisk") is not True
        ]
        _expect(not non_green, f"every required checklist item is green (non-green: {non_green})")
        worker = items.get("worker_ready") or {}
        _expect(worker.get("status") == "passed", "the worker round-trip is green")
        _expect(
            "worker completed the setup ping" in str(worker.get("evidence")),
            f"the worker evidence is an observed round trip (got {worker.get('evidence')!r})",
        )
        ai = items.get("ai_explicit") or {}
        _expect(ai.get("status") == "passed", f"ai_explicit is green (got {ai.get('status')!r})")
        smtp = items.get("smtp") or {}
        _expect(smtp.get("status") == "postponed", "the postponed notification stays postponed")
        postponed = [identifier for identifier, item in items.items() if item.get("status") == "postponed"]
        unavailable = [
            identifier
            for identifier, item in items.items()
            if identifier in {"external_search", "external_engines"}
            and item.get("status") == "unavailable"
        ]
        _expect(
            sorted(unavailable) == ["external_engines", "external_search"],
            f"both absent capabilities are unavailable (got {unavailable})",
        )
        integrations = items.get("integrations") or {}
        _expect(
            integrations.get("required") is False and integrations.get("blocking") is False,
            "the integrations item exists, is not required and does not block",
        )

        return {
            "state": body.get("state"),
            "agent": agent,
            "worker": worker.get("evidence"),
            "postponed": sorted(postponed),
            "unavailable": sorted(unavailable),
            "checklist": {
                identifier: {
                    "status": item.get("status"),
                    "blocking": item.get("blocking"),
                    "acceptedRisk": item.get("acceptedRisk"),
                }
                for identifier, item in items.items()
            },
        }

    # -------------------------------------------------------------- complete
    def _project_volume(self, logical: str) -> str:
        result = self.docker(
            "volume",
            "ls",
            "-q",
            "--filter",
            f"label=com.docker.compose.project={self.project}",
            "--filter",
            f"label=com.docker.compose.volume={logical}",
            check=True,
        )
        names = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
        _expect(len(names) == 1, f"exactly one {logical} volume exists (got {names})")
        return names[0]

    def _snapshot_setup_state(self) -> dict:
        """Copy the private setup store volume aside before completion."""

        volume = self._project_volume("setup-state")
        archive = self.temp_dir / "setup-state-before-complete.tar"
        result = self.docker(
            "run",
            "--rm",
            "--user",
            "0:0",
            "--entrypoint",
            "tar",
            "-v",
            f"{volume}:/from:ro",
            "-v",
            f"{self.temp_dir}:/snapshot",
            self.backend_image,
            "-cf",
            f"/snapshot/{archive.name}",
            "-C",
            "/from",
            ".",
            timeout=120,
        )
        _expect(
            result.returncode == 0,
            f"the setup store snapshot is written ({result.returncode}): "
            f"{(result.stderr or '').strip()[:300]}",
        )
        _expect(
            archive.is_file() and archive.stat().st_size > 0,
            "the setup store snapshot is non-empty",
        )
        self.snapshot_archive = archive
        return {"volume": volume, "bytes": archive.stat().st_size}

    def _assert_no_report_secret(self, report: dict) -> None:
        def walk(value) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    lowered = str(key).lower()
                    _expect(
                        not any(token in lowered for token in FORBIDDEN_STATUS_TOKENS),
                        f"the report has no secret-like key (got {key!r})",
                    )
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(report)
        text = json.dumps(report, sort_keys=True)
        in_play = {
            "provider_key": self.provider_key,
            "credential_key": self.credential_key,
        }
        if self.mode == "prod":
            in_play["database_password"] = self.env["ITSM_POSTGRES_PASSWORD"]
        leaked = [name for name, value in in_play.items() if value and value in text]
        _expect(not leaked, f"the report carries no secret value (leaked: {leaked})")

    def step_complete(self) -> dict:
        exported = self.client.request("GET", f"{SETUP_PREFIX}/report", timeout=60)
        _expect(
            exported.status == 200,
            f"the pre-completion report is readable (got {exported.status}: {exported.text()[:200]})",
        )
        preview = exported.json()
        _expect(preview.get("state") == "verifying", "the exported report is a verifying preview")
        _expect(preview.get("contract") == "onboarding/v1", "the report names its contract")
        self._assert_no_report_secret(preview)

        old_session = next(
            (cookie.value for cookie in self.client.jar if cookie.name == COOKIE_NAME), None
        )
        _expect(bool(old_session), "the pre-completion setup session is present")
        snapshot = self._snapshot_setup_state()

        completed = self.setup_mutation("/complete", {}, timeout=120)
        _expect(
            completed.status == 200,
            f"the installation completes (got {completed.status}: {completed.text()[:240]})",
        )
        body = completed.json()
        _expect(body.get("state") == "complete", f"completion reports complete (got {body.get('state')!r})")
        digest = str(body.get("report_digest") or "")
        _expect(
            len(digest) == 64 and all(character in "0123456789abcdef" for character in digest),
            f"completion returns a sha256 report digest (got {digest[:16]!r})",
        )
        _expect(bool(body.get("completed_at")), "completion records a timestamp")

        status = self.wait_status(
            timeout=60, predicate=lambda payload: payload.get("state") == "complete"
        )
        _expect(status.get("setup_enabled") is False, "a complete installation disables setup")
        _expect(status.get("claim_available") is False, "a complete installation offers no claim")

        ready = self.wait_http(
            "/api/v1/health/ready",
            lambda response: response.status == 200
            and (_safe_json(response) or {}).get("installation_complete") is True,
            timeout=60,
            description="installation_complete in the normal API",
        )
        compatibility = ready.json()
        _expect(
            compatibility.get("installation_state") == "complete",
            f"the normal API labels the installation complete (got "
            f"{compatibility.get('installation_state')!r})",
        )

        refused = self.setup_mutation(
            "/configuration/notifications/apply",
            {"values": {"reason": "after complete"}, "action": "postpone", "confirm": True},
        )
        _expect(
            refused.status == 409,
            f"a setup mutation after completion is refused (got {refused.status})",
        )
        _expect(
            (_safe_json(refused) or {}).get("error") == "setup_complete",
            f"the refusal is setup_complete (got {refused.text()[:160]})",
        )

        rejected = self.client.request(
            "GET",
            f"{SETUP_PREFIX}/session",
            headers={"Cookie": f"{COOKIE_NAME}={old_session}"},
            timeout=15,
        )
        _expect(
            rejected.status == 401,
            f"the pre-completion setup session is rejected (got {rejected.status})",
        )
        after = self.client.request("GET", f"{SETUP_PREFIX}/report", timeout=15)
        _expect(
            after.status in {401, 409},
            "the report is closed after completion and the old session is rejected "
            f"(got {after.status})",
        )

        return {
            "state": body.get("state"),
            "completed_at": body.get("completed_at"),
            "report_digest": digest,
            "snapshot_bytes": snapshot["bytes"],
            "installation_complete": compatibility.get("installation_complete"),
            "mutation_after_complete": refused.status,
            "old_session": rejected.status,
        }

    # -------------------------------------------------------------- recovery
    def step_recovery(self) -> dict:
        archive = self.snapshot_archive
        if archive is None or not archive.is_file():
            raise StepFailure("a pre-completion setup snapshot exists")

        restarted = self.compose("restart", timeout=240)
        _expect(
            restarted.returncode == 0,
            f"every service restarts ({restarted.returncode}): "
            f"{(restarted.stderr or '').strip()[:300]}",
        )
        status = self.wait_status(
            timeout=120, predicate=lambda payload: payload.get("state") == "complete"
        )
        _expect(status.get("state") == "complete", "completion survives a full restart")
        ready = self.wait_http(
            "/api/v1/health/ready",
            lambda response: response.status == 200
            and (_safe_json(response) or {}).get("installation_complete") is True,
            timeout=120,
            description="installation_complete after the restart",
        )
        _expect(
            ready.json().get("installation_state") == "complete",
            "the normal API still reports the installation complete after a restart",
        )

        volume = self._project_volume("setup-state")
        stopped = self.compose("stop", "setup", timeout=60)
        _expect(
            stopped.returncode == 0,
            f"the wizard stops before the restore ({stopped.returncode})",
        )
        restored = None
        try:
            restored = self.docker(
                "run",
                "--rm",
                "--user",
                "0:0",
                "--entrypoint",
                "tar",
                "-v",
                f"{volume}:/d",
                "-v",
                f"{self.temp_dir}:/snapshot",
                self.backend_image,
                "-xf",
                f"/snapshot/{archive.name}",
                "-C",
                "/d",
                timeout=120,
            )
        finally:
            started = self.compose("start", "setup", timeout=60)
        _expect(
            restored is not None and restored.returncode == 0,
            "the pre-completion store snapshot is restored",
        )
        _expect(
            started.returncode == 0,
            f"the wizard starts on the restored store ({started.returncode})",
        )

        status = self.wait_status(
            timeout=120, predicate=lambda payload: payload.get("state") == "complete"
        )
        _expect(
            status.get("state") == "complete",
            f"the database marker still reports complete (got {status.get('state')!r})",
        )

        claim = self.client.request(
            "POST",
            f"{SETUP_PREFIX}/claim",
            body={"credential": secrets.token_urlsafe(32)},
            headers={"Origin": self.origin},
            timeout=30,
        )
        _expect(
            claim.status == 409,
            f"a restored store cannot reopen the claim (got {claim.status})",
        )
        _expect(
            (_safe_json(claim) or {}).get("error") == "setup_complete",
            "the claim refusal is setup_complete",
        )

        recovery = self.compose(
            "exec", "-T", "setup", "python", "-m", "itsm.setup.cli", "recover", timeout=60
        )
        _expect(
            recovery.returncode != 0,
            "the setup CLI refuses to reopen a complete installation",
        )
        output = (recovery.stdout or "") + (recovery.stderr or "")
        lines = [line for line in output.splitlines() if line.strip()]
        try:
            refusal = json.loads(lines[-1]) if lines else {}
        except json.JSONDecodeError:
            raise StepFailure("the recover refusal did not print JSON") from None
        _expect(
            refusal.get("status") == "error" and refusal.get("code") == "installation_complete",
            f"recover reports installation_complete (got {refusal!r})",
        )

        return {
            "restarted": True,
            "state_after_restart": "complete",
            "restored_from": archive.name,
            "claim": claim.status,
            "recover_exit": recovery.returncode,
            "recover_code": refusal.get("code"),
        }

    # --------------------------------------------------------- docs in image
    def step_docs_in_image(self) -> dict:
        backend = self.container_id("backend")
        inspected = self.docker("inspect", "--format", "{{json .Mounts}}", backend, check=True)
        mounts = json.loads((inspected.stdout or "[]").strip() or "[]")
        repository = ROOT.resolve()
        repo_binds = []
        for mount in mounts:
            if isinstance(mount, dict) and str(mount.get("Type")) == "bind":
                source = Path(str(mount.get("Source") or "")).resolve()
                if source == repository or source.is_relative_to(repository):
                    repo_binds.append(str(source))
        _expect(
            not repo_binds,
            f"the API container has no bind mount of the repository (got {repo_binds})",
        )

        code = (
            "import json\n"
            "from itsm.project_context.service import ProjectContextService, UnknownDocument\n"
            "service = ProjectContextService()\n"
            "found = service.search_project_docs('setup', limit=5).model_dump(mode='json')\n"
            "first = found['matches'][0]\n"
            "document = service.read_project_doc(\n"
            "    first['path'], section=first['section'], limit=400\n"
            ").model_dump(mode='json')\n"
            "refused = False\n"
            "try:\n"
            "    service.read_project_doc('../../etc/passwd')\n"
            "except UnknownDocument:\n"
            "    refused = True\n"
            "print(json.dumps({\n"
            "    'matches': len(found['matches']),\n"
            "    'path': first['path'],\n"
            "    'section': first['section'],\n"
            "    'chars': len(document['text']),\n"
            "    'refused': refused,\n"
            "    'pack': str(service.pack_path),\n"
            "    'fixture': service.fixture,\n"
            "    'digest': service.pack.source_digest,\n"
            "}))\n"
        )
        result = self._json_in("backend", code)
        _expect(int(result.get("matches") or 0) >= 1, "the documentation search returns a match")
        _expect(str(result.get("path") or "").endswith(".md"), "the match names a document")
        _expect(int(result.get("chars") or 0) > 0, "the document read returns text")
        _expect(result.get("fixture") is False, "the image ships the generated, not fixture, pack")
        _expect(result.get("refused") is True, "a traversal path is refused")
        pack = str(result.get("pack") or "")
        _expect(
            bool(pack) and str(repository) not in pack and "/itsm/project_context/pack.json" in pack,
            f"the pack is loaded from inside the image (got {pack!r})",
        )

        return {
            "backend": backend,
            "bind_mounts_of_repo": repo_binds,
            "match": {
                "path": result.get("path"),
                "section": result.get("section"),
                "chars": result.get("chars"),
            },
            "traversal_refused": result.get("refused"),
            "pack": pack,
            "source_digest": result.get("digest"),
        }

    # ----------------------------------------------------------------- control
    def _cleanup_profiles(self) -> tuple[str, ...]:
        """Profiles whose services were started on purpose, so ``down`` sees them."""
        return ("local-postgres",) if self.mode == "prod" else ()

    def _capture_logs(self) -> dict[str, list[str]]:
        print(f"--- bounded logs for project {self.project} ({self.mode}) ---", file=sys.stderr)
        captured: dict[str, list[str]] = {}
        for service in ("setup", "backend", "worker", "postgres", "frontend", FIXTURE_SERVICE):
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
        dependents = {"verify": ("complete", "recovery"), "complete": ("recovery",)}
        for name in implemented:
            if blocker is not None:
                self._record(name, "SKIP", reason=f"not attempted: {blocker} failed")
                continue
            dependent = next(
                (
                    source
                    for source, children in dependents.items()
                    if name in children and source in self.blocked_sources
                ),
                None,
            )
            if dependent is not None:
                reason = f"depends on {dependent}: {self.blocked_sources[dependent]}"
                self.blocked_steps.append(name)
                self._record(name, "BLOCKED", reason=reason)
                print(f"BLOCKED {name}: {reason}", file=sys.stderr)
                continue
            try:
                observations = getattr(self, f"step_{name.replace('-', '_')}")()
            except StepBlocked as exc:
                reason = str(exc)
                self.blocked_steps.append(name)
                self.blocked_sources[name] = reason
                self._record(name, "BLOCKED", reason=reason)
                print(f"BLOCKED {name}: {reason}", file=sys.stderr)
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

    # ---------------------------------------------------------------- browser
    def _browser_phase(
        self,
        phase: str,
        evidence: Path,
        *,
        save: Path | None = None,
        load: Path | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> dict:
        argv = [
            "uv",
            "run",
            "--no-project",
            "--with",
            "playwright",
            "python",
            str(ROOT / "tests" / "onboarding_browser.py"),
            "--phase",
            phase,
            "--base-url",
            self.origin,
            "--evidence",
            str(evidence),
            "--mode",
            self.mode,
            "--locale",
            self.args.browser_locale,
            "--ai-base-url",
            FIXTURE_BASE_URL,
            "--ai-model",
            FIXTURE_MODEL,
            "--ai-provider",
            FIXTURE_SERVICE,
            "--owner-username",
            "owner",
            "--owner-display-name",
            "Installation Owner",
            "--owner-email",
            "owner@example.invalid",
        ]
        if save is not None:
            argv += ["--save-storage-state", str(save)]
        if load is not None:
            argv += ["--storage-state", str(load)]
        if self.mode == "prod":
            argv += ["--resolve", "itsm-e2e.test=127.0.0.1"]
        env = dict(os.environ)
        env.update(extra_env or {})
        result = _run(argv, env, self.args.browser_timeout)
        evidence.mkdir(parents=True, exist_ok=True)
        log = evidence / f"{phase}.browser.log"
        log.write_text(
            (result.stdout or "") + (result.stderr or ""), encoding="utf-8"
        )
        print(f"LOG browser {phase}: {log}")
        for line in (result.stdout or "").splitlines():
            if line.startswith("PASS "):
                print(line)
        summary_path = evidence / f"{phase}.json"
        summary: dict = {}
        if summary_path.is_file():
            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                summary = {}
        if result.returncode != 0:
            detail = str(summary.get("error") or "").strip()
            if not detail:
                tail = [
                    line.strip()
                    for line in (result.stderr or "").splitlines()
                    if line.strip()
                ]
                detail = tail[-1] if tail else f"exit {result.returncode}"
            raise StepFailure(
                f"browser {phase} failed: {detail[:600]} (log {log})"
            )
        return {
            "phase": phase,
            "checks": summary.get("checks"),
            "screenshots": len(summary.get("screenshots") or []),
            "log": str(log),
        }

    def _run_browser(self) -> None:
        evidence = Path(
            self.args.browser_evidence
            or (Path(tempfile.gettempdir()) / "onboarding-browser")
        ).expanduser() / self.mode
        evidence.mkdir(parents=True, exist_ok=True)
        state = self.temp_dir / "browser-storage-state.json"
        print(f"BROWSER {self.mode}: {self.origin} -> {evidence}")
        try:
            boot = self.step_boot()
            self._record(
                "browser-boot",
                "PASS",
                observations={"edge": self.origin, "evidence": str(evidence), **boot},
            )
            claim = self._enable_claim()
            database = self._start_database()
            owner_password = secrets.token_urlsafe(24)
            setup = self._browser_phase(
                "setup",
                evidence,
                save=state,
                extra_env={
                    "SETUP_CLAIM_CREDENTIAL": claim["credential"],
                    "SETUP_DATABASE_URL": self._database_url(),
                    "SETUP_DATABASE_ENGINE": (
                        "sqlite" if database["engine"] == "sqlite" else "postgresql"
                    ),
                    "AI_FIXTURE_KEY": self.provider_key,
                },
            )
            self._record("browser-setup", "PASS", observations=setup)
            api = self._start_api()
            self._start_worker()
            self._record(
                "browser-api",
                "PASS",
                observations={"database": api.get("database"), "migrations": api.get("migrations")},
            )
            finish = self._browser_phase(
                "finish",
                evidence,
                load=state,
                extra_env={"SETUP_OWNER_PASSWORD": owner_password},
            )
            self._record("browser-finish", "PASS", observations=finish)
        except StepBlocked as exc:
            self.blocked_steps.append("browser")
            self.blocked_sources["browser"] = str(exc)
            self._record("browser", "BLOCKED", reason=str(exc))
            print(f"BLOCKED browser: {exc}", file=sys.stderr)
        except StepFailure as exc:
            self.failed_steps.append("browser")
            self._record("browser", "FAIL", reason=str(exc))
            print(f"FAIL browser: {exc}", file=sys.stderr)

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
            "version": "t7-browser",
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
            if self.args.browser:
                self._run_browser()
            else:
                self._run_steps()
            if self.blocked_steps and not self.failed_steps:
                self.exit_code = 2
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
            detail = "; ".join(
                f"{name}: {self.blocked_sources.get(name, 'dependency blocked')}"
                for name in self.blocked_steps
            )
            print(f"RESULT blocked: {self.mode} ({detail or 'environment cannot assert the run'})")
            return 2
        if self.args.browser:
            print(
                f"RESULT passed: {self.mode} "
                f"({len(self.steps)} browser step(s), real Chromium)"
            )
            return 0
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
    parser.add_argument(
        "--browser",
        action="store_true",
        help="drive the wizard in Chromium against the disposable stack "
        "instead of walking the API steps",
    )
    parser.add_argument(
        "--browser-evidence",
        default=None,
        help="directory for per-phase screenshots, summaries and logs "
        "(default: $TMPDIR/onboarding-browser); a <mode> subdirectory is added",
    )
    parser.add_argument(
        "--browser-locale",
        choices=("en", "es"),
        default="en",
        help="wizard locale the browser asks for (default en)",
    )
    parser.add_argument(
        "--browser-timeout",
        type=int,
        default=900,
        help="bounded wait for one browser phase, in seconds (default 900)",
    )
    args = parser.parse_args(argv)
    args.steps = _parse_steps(args.steps, parser)
    return Harness(args).run()


if __name__ == "__main__":
    sys.exit(main())
