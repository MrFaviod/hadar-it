"""Launch one dedicated development Hermes profile and attest only its own child.

Ownership covers the live child, any proven descendant, and the loopback listener
those processes actually hold. Run with the backend virtualenv (PyYAML is already
installed). Secrets are supplied in the environment; --omp-config is an explicit
opt-in to reading that provider. No installation, production account creation or
arbitrary launch endpoint exists.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import signal
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import yaml

PROC = Path("/proc")


def _socket_inodes(pid: int) -> set[int]:
    """Sockets held by pid; unreadable ownership fails closed, gone processes hold none."""
    try:
        entries = list((PROC / str(pid) / "fd").iterdir())
    except FileNotFoundError:
        return set()
    except OSError as exc:
        raise ValueError("listener ownership is unavailable") from exc
    inodes: set[int] = set()
    for entry in entries:
        try:
            target = os.readlink(entry)
        except OSError:
            continue
        if target.startswith("socket:[") and target.endswith("]"):
            try:
                inodes.add(int(target[len("socket:["):-1]))
            except ValueError:
                continue
    return inodes


def _parent_pid(pid: int) -> int | None:
    try:
        stat = (PROC / str(pid) / "stat").read_text()
    except OSError:
        return None
    try:
        return int(stat.rsplit(")", 1)[1].split()[1])
    except (IndexError, ValueError):
        return None


def _descendants(pid: int) -> set[int]:
    """Live pids whose parent chain reaches pid, read only from /proc stat."""
    children: dict[int, list[int]] = {}
    try:
        entries = list(PROC.iterdir())
    except OSError as exc:
        raise ValueError("listener ownership is unavailable") from exc
    for entry in entries:
        if not entry.name.isdigit():
            continue
        parent = _parent_pid(int(entry.name))
        if parent is not None:
            children.setdefault(parent, []).append(int(entry.name))
    found: set[int] = set()
    pending = [pid]
    while pending:
        for child in children.get(pending.pop(), ()):
            if child not in found:
                found.add(child)
                pending.append(child)
    return found


def _listening_inodes(port: int) -> set[int]:
    """Socket inodes listening on the IPv4 loopback port, per /proc/net/tcp."""
    try:
        lines = (PROC / "net" / "tcp").read_text().splitlines()
    except OSError as exc:
        raise ValueError("listener ownership is unavailable") from exc
    inodes: set[int] = set()
    for line in lines[1:]:
        fields = line.split()
        if len(fields) < 10 or fields[3] != "0A":
            continue
        address, _, raw_port = fields[1].partition(":")
        if address != "0100007F" or not raw_port:
            continue
        try:
            if int(raw_port, 16) == port:
                inodes.add(int(fields[9]))
        except ValueError:
            continue
    return inodes


def owned_listener(pid: int, port: int) -> bool:
    """True only when every loopback listener on port belongs to pid or a descendant."""
    listeners = _listening_inodes(port)
    if not listeners:
        return False
    owned = _socket_inodes(pid)
    if listeners <= owned:
        return True
    for descendant in _descendants(pid):
        owned |= _socket_inodes(descendant)
        if listeners <= owned:
            return True
    return False


def prepare_profile(home: Path, omp_config: Path | None) -> dict[str, str]:
    """Create a secret-free dedicated config, preserving existing installer files."""
    environment = dict(os.environ)
    provider_url = environment.get("ITSM_HERMES_PROVIDER_URL", "")
    provider_key = environment.get("ITSM_HERMES_PROVIDER_KEY", "")
    headers = json.loads(environment.get("ITSM_HERMES_HEADERS_JSON", "{}"))
    if omp_config is not None:
        source = yaml.safe_load(omp_config.read_text())
        provider_name = environment.get("ITSM_HERMES_OMP_PROVIDER", "omniroute")
        provider = source["providers"][provider_name]
        provider_url, provider_key = provider["baseUrl"], provider["apiKey"]
        headers = provider.get("headers", {})
    if not provider_url.startswith(("https://", "http://")) or not provider_key:
        raise ValueError("supply the provider URL/key or explicitly select an omp config")
    if not isinstance(headers, dict) or any(not isinstance(k, str) for k in headers):
        raise ValueError("provider headers must be an object with string names")
    model = environment.get("ITSM_HERMES_MODEL", "")
    if not model:
        raise ValueError("ITSM_HERMES_MODEL must identify the chosen provider model")
    if not environment.get("HERMES_DASHBOARD_BASIC_AUTH_PASSWORD"):
        raise ValueError("supply HERMES_DASHBOARD_BASIC_AUTH_PASSWORD explicitly")
    environment["HERMES_DASHBOARD_BASIC_AUTH_USERNAME"] = environment.get(
        "HERMES_DASHBOARD_BASIC_AUTH_USERNAME", "admin"
    )
    environment.setdefault("HERMES_DASHBOARD_BASIC_AUTH_SECRET", secrets.token_urlsafe(40))
    environment["ITSM_HERMES_PROVIDER_KEY"] = str(provider_key)
    header_refs = {}
    for number, (name, value) in enumerate(headers.items()):
        key = f"ITSM_HERMES_HEADER_{number}"
        environment[key] = str(value)
        header_refs[name] = "${" + key + "}"
    # Do not forward the raw JSON credential carrier to the child.
    environment.pop("ITSM_HERMES_HEADERS_JSON", None)
    environment["HERMES_HOME"] = str(home.resolve())
    environment["HERMES_TUI_TOOLSETS"] = "itsm,skills"
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    config_path = home / "config.yaml"
    if not config_path.exists():
        url = provider_url.rstrip("/")
        if not url.endswith("/v1"):
            url += "/v1"
        config = {
            "model": {"provider": "itsm-omp", "default": model},
            "providers": {"itsm-omp": {"name": "ITSM provider", "base_url": url,
                                      "key_env": "ITSM_HERMES_PROVIDER_KEY",
                                      "extra_headers": header_refs}},
            "platform_toolsets": {"cli": ["itsm", "skills"]},
            "agent": {"max_turns": 4, "disabled_toolsets": ["project"]},
            "max_turns": 4,
        }
        # Exclusive creation avoids overwriting an operator/installer change.
        descriptor = os.open(config_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            yaml.safe_dump(config, stream, sort_keys=False)
    return environment


class Launcher:
    """Own one fixed serve child; proof cannot select a binary or another profile."""

    def __init__(self, binary: Path, home: Path, port: int,
                 environment: dict[str, str]) -> None:
        self.binary = binary.resolve(strict=True)
        self.home = home.resolve(strict=True)
        self.endpoint = f"http://127.0.0.1:{port}"
        self.port = port
        self.environment = dict(environment, HERMES_HOME=str(self.home))
        self.child: subprocess.Popen[bytes] | None = None
        self.receipt: dict[str, Any] = {}
        self.lock = threading.Lock()

    def start(self) -> None:
        """Record the managed config digest and child identity at launch."""
        # Never mistake an already-running, unrelated endpoint for our child.
        with socket.socket() as reservation:
            reservation.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                reservation.bind(("127.0.0.1", self.port))
            except OSError as exc:
                raise ValueError("Hermes port is already in use") from exc
        digest = "sha256:" + hashlib.sha256((self.home / "config.yaml").read_bytes()).hexdigest()
        child = subprocess.Popen(
            [str(self.binary), "serve", "--isolated", "--skip-build", "--host",
             "127.0.0.1", "--port", str(self.port)],
            cwd=self.home, env=self.environment,
        )
        self.child = child
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            if child.poll() is not None:
                raise ValueError("managed Hermes child exited before readiness")
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.25):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            self.close()
            raise ValueError("managed Hermes child did not become ready")
        try:
            self._require_owned_listener()
        except ValueError:
            self.close()
            self.child = None
            raise
        self.receipt = {"protocol": "itsm-hermes-launch-v1", "profileHome": str(self.home),
                        "endpoint": self.endpoint, "launchId": secrets.token_hex(24),
                        "processId": child.pid, "configDigest": digest}

    def _require_owned_listener(self) -> None:
        """The port must be held by this child or a proven descendant, never a foreign process."""
        child = self.child
        if child is None or child.poll() is not None:
            raise ValueError("managed child is not running")
        if not owned_listener(child.pid, self.port):
            raise ValueError("endpoint listener is not owned by the managed child")

    def close(self) -> None:
        if self.child is not None and self.child.poll() is None:
            self.child.terminate()
            try:
                self.child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.child.kill()
                self.child.wait(timeout=5)

    def proof(self, request: dict[str, Any]) -> dict[str, Any]:
        """Reject foreign/dead/stale claims; reload only this fixed managed child."""
        with self.lock:
            if set(request) != {"profileHome", "endpoint", "configDigest"}:
                raise ValueError("invalid proof request")
            if request["profileHome"] != str(self.home) or request["endpoint"] != self.endpoint:
                raise ValueError("proof belongs to another profile or endpoint")
            if self.child is None or self.child.poll() is not None:
                raise ValueError("managed child is not running")
            digest = "sha256:" + hashlib.sha256((self.home / "config.yaml").read_bytes()).hexdigest()
            if request["configDigest"] != digest:
                raise ValueError("proof does not match the current config")
            if self.receipt.get("configDigest") != digest:
                # Installation changed the file. Never attest stale loaded settings.
                self.close()
                self.start()
            if self.child.poll() is not None:
                raise ValueError("managed child stopped during verification")
            if self.receipt.get("processId") != self.child.pid:
                raise ValueError("managed launch receipt does not match the live child")
            self._require_owned_listener()
            return dict(self.receipt)


def profile_proof(
    launchers: dict[tuple[str, str], Launcher], request: dict[str, Any]
) -> dict[str, Any]:
    """Dispatch only to a profile/endpoint registered before the server starts."""
    home, endpoint = request.get("profileHome"), request.get("endpoint")
    if not isinstance(home, str) or not isinstance(endpoint, str):
        raise ValueError("invalid profile/endpoint pair")
    launcher = launchers.get((home, endpoint))
    if launcher is None:
        raise ValueError("profile/endpoint pair was not approved at startup")
    return launcher.proof(request)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True, help="Pinned Hermes executable")
    parser.add_argument("--home", type=Path, required=True, help="Dedicated ITSM profile directory")
    parser.add_argument("--port", type=int, default=19119)
    parser.add_argument("--inspector-port", type=int, default=19120)
    parser.add_argument("--additional-profile", action="append", default=[], metavar="HOME=PORT",
                        help="Additional fixed profile home and loopback serve port")
    parser.add_argument("--omp-config", type=Path, help="Explicitly authorized omp provider config")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535 or not 1 <= args.inspector_port <= 65535:
        parser.error("ports must be within 1..65535")
    if args.port == args.inspector_port:
        parser.error("serve and inspector ports must differ")
    token = os.environ.get("ITSM_HERMES_INSPECTOR_TOKEN", "")
    if len(token) < 32 or any(character.isspace() for character in token):
        parser.error("supply a distinct ITSM_HERMES_INSPECTOR_TOKEN of at least 32 characters")
    try:
        profiles = [(args.home, args.port)]
        for value in args.additional_profile:
            home, port = value.rsplit("=", 1)
            profiles.append((Path(home), int(port)))
        ports = [port for _, port in profiles] + [args.inspector_port]
        homes = [str(home.resolve()) for home, _ in profiles]
        if (any(not 1 <= port <= 65535 for port in ports)
                or len(set(ports)) != len(ports) or len(set(homes)) != len(homes)):
            raise ValueError("profiles need distinct homes and ports")
        launchers = {}
        for home, port in profiles:
            environment = prepare_profile(home, args.omp_config)
            launcher = Launcher(args.binary, home, port, environment)
            launchers[(str(launcher.home), launcher.endpoint)] = launcher
    except (KeyError, OSError, ValueError):
        parser.error("invalid profile/provider configuration; secret values are not displayed")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *arguments: Any) -> None:
            pass  # Do not log authentication headers or request bodies.

        def do_POST(self) -> None:
            if self.path != "/profile-proof":
                self.send_error(404)
                return
            if not secrets.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token):
                self.send_error(401)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 4096:
                    raise ValueError("invalid proof request size")
                request = json.loads(self.rfile.read(length))
                if not isinstance(request, dict):
                    raise ValueError("proof request must be an object")
                proof = profile_proof(launchers, request)
            except (OSError, ValueError):
                self.send_error(409, "managed launch proof is unavailable")
                return
            body = json.dumps(proof).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = HTTPServer(("127.0.0.1", args.inspector_port), Handler)
    def stop(signum: int, frame: Any) -> None:
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    try:
        for launcher in launchers.values():
            launcher.start()
        print("ITSM_HERMES_MANAGER_READY", flush=True)
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        for launcher in launchers.values():
            launcher.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
