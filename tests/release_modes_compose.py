"""Read-only Compose rendering contract; no containers, builds or downloads."""
import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLATION_DIR = "/data/installation"
INSTALLATION_FILE = "/data/installation/installation.json"
INSTALLATION_VOLUME = "installation-config"


def compose(mode, omit=()):
    env = {key: value for key, value in os.environ.items() if not key.startswith("ITSM_")}
    env.update(
        RELEASE_MODE=mode,
        ITSM_SELINUX_LEVEL="s0:c100",
        ITSM_AUTH_ORIGIN="https://test.invalid",
        ITSM_DATABASE_URL="sqlite:////data/app/prod.db",
        ITSM_DEV_ADMIN_PASSWORD="test-only-not-an-installed-secret",
        ITSM_REPORT_BASE_URL="https://test.invalid",
        ITSM_MONITORING_PUBLIC_URL="https://test.invalid",
    )
    for key in omit:
        env.pop(key)
    return subprocess.run(
        ["docker", "compose", "--env-file", "/dev/null", "-f", "compose.yaml", "-f",
         f"deploy/compose.{mode}.yaml", "config", "--format", "json"],
        cwd=ROOT, env=env, text=True, capture_output=True, timeout=20,
    )


def render(mode):
    result = compose(mode)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def assert_variable_proxy_pass_keeps_the_uri():
    """Every variable proxy_pass must append $request_uri.

    nginx treats a URI inside a variable proxy_pass as the complete upstream
    URI; a variable with no path forwards the request as "/", so the wizard and
    the API would answer from the wrong path. Both edge configs share the rule.
    """
    pattern = re.compile(r"^\s*proxy_pass\s+([^;]+);")
    checked = 0
    for path in (ROOT / "deploy" / "nginx-tls.conf", ROOT / "frontend" / "nginx.conf"):
        assert path.is_file(), f"missing edge config {path}"
        for number, line in enumerate(path.read_text().splitlines(), 1):
            match = pattern.match(line)
            if match is None:
                continue
            target = match.group(1).strip()
            if "$" not in target:
                continue
            checked += 1
            assert target.endswith("$request_uri"), (
                f"{path.name}:{number}: variable proxy_pass must append "
                f"$request_uri (got {target})"
            )
    assert checked >= 4, f"expected four variable proxy_pass targets, found {checked}"
    print(f"PASS edge configs keep the request URI on {checked} variable proxy_pass targets")


def main():
    volumes = []
    for mode in ("dev", "prod", "demo"):
        model = render(mode)
        assert model["name"] == f"itsm-{mode}"
        services = model["services"]
        for name in ("initialize", "backend"):
            assert services[name]["environment"]["RELEASE_MODE"] == mode
        assert services["backend"]["depends_on"]["initialize"]["condition"] == "service_completed_successfully"
        # Off by default: an edge that does not append X-Forwarded-For must not be trusted.
        assert services["backend"]["environment"]["ITSM_TRUSTED_PROXY"] == "false"
        assert services["backend"]["environment"]["ITSM_AGENT_RUN_TIMEOUT_SECONDS"] == "180"
        assert services["backend"]["environment"]["ITSM_AI_SECRET_DESTINATIONS"] == "{}"
        if mode == "demo":
            assert "worker" not in services
            assert services["backend"]["environment"]["OPENAI_API_KEY"] == ""
            assert services["backend"]["environment"]["ITSM_TASK_STORAGE"] == "sqlite"
            # The demonstration has no wizard and no shared settings volume: the
            # demo database is owned by its overlay and never read from a file.
            assert INSTALLATION_VOLUME not in (model.get("volumes") or {}), (
                "demo must not carry the installation settings volume"
            )
            for name in ("initialize", "backend"):
                assert services[name]["environment"]["ITSM_INSTALLATION_CONFIG"] == "", (
                    f"demo {name} must not read an installation settings file"
                )
                assert [mount["target"] for mount in services[name]["volumes"]] == ["/data"]
            print("PASS demo: no installation settings volume or file")
        if mode == "prod":
            assert services["initialize"]["image"] == "itsm-ops:0.1.0"
            assert any(v["target"] == "/data/backups" for v in services["initialize"]["volumes"])
            api_volumes = services["backend"]["volumes"]
            assert not any(v["target"] == "/data/backups" for v in api_volumes)
            status_mount = next(v for v in api_volumes if v["target"] == "/data/backup-status")
            assert status_mount["read_only"] is True
            assert services["backend"]["environment"]["ITSM_BACKUP_STATUS_PATH"] == (
                "/data/backup-status/status.json"
            )
            assert services["initialize"]["environment"]["ITSM_OPS_STATUS_PATH"] == (
                "/data/backup-status/status.json"
            )
        # Setup must answer before the database and the API exist. It shares the
        # API image but none of its dependencies, ports or Docker access.
        if mode == "demo":
            assert "setup" not in services, "demo must not offer the claim flow"
            assert "setup-volume-init" not in services, (
                "demo must not carry the wizard's volume initializer"
            )
        else:
            setup = services["setup"]
            assert setup["image"] == "itsm-backend:0.1.0"
            assert setup["command"] == ["python", "-m", "itsm.setup"]
            # The one-shot initializer is the only prerequisite: the wizard must
            # not wait on the API, the datastore or the preparation gate.
            assert set(setup["depends_on"]) == {"setup-volume-init"}, (
                "setup waits only for its volume initializer"
            )
            assert (
                setup["depends_on"]["setup-volume-init"]["condition"]
                == "service_completed_successfully"
            )
            assert not setup.get("ports"), "setup is reached only through the edge"
            assert setup["read_only"] is True
            assert setup["cap_drop"] == ["ALL"]
            assert setup["pids_limit"] == 64
            assert "/tmp" in str(setup["tmpfs"])
            assert setup["environment"]["RELEASE_MODE"] == mode
            assert setup["environment"]["ITSM_SETUP_STATE_DIR"] == "/var/lib/itsm-setup"
            assert setup["environment"]["ITSM_INSTALLATION_CONFIG"] == INSTALLATION_FILE
            # The claim endpoint compares Origin exactly and refuses a claim
            # with origin_not_configured when it has no origin: the wizard must
            # carry a non-empty origin, and it must be the one the API pins.
            backend_origin = services["backend"]["environment"]["ITSM_AUTH_ORIGIN"]
            explicit = setup["environment"].get("ITSM_SETUP_ALLOWED_ORIGINS", "")
            claim_origin = (explicit.split(",")[0].strip() if explicit else "") or (
                setup["environment"].get("ITSM_AUTH_ORIGIN", "").strip()
            )
            assert claim_origin, f"{mode}: setup has no claim origin"
            assert claim_origin == backend_origin, (
                f"{mode}: setup validates {claim_origin!r}, the API pins {backend_origin!r}"
            )
            # The wizard never holds root or a capability: the one-shot init
            # container below owns the volume instead.
            assert setup.get("user") == "10001:10001", "the wizard runs unprivileged"
            # One-shot volume initializer: same image, root only long enough to
            # chown/chmod the state volume, no network, no restart.
            init = services["setup-volume-init"]
            assert init["image"] == setup["image"]
            assert init["user"] == "0:0"
            assert init["command"][:2] == ["sh", "-c"]
            assert "chown 10001:10001 /var/lib/itsm-setup" in init["command"][2]
            assert "chmod 0700 /var/lib/itsm-setup" in init["command"][2]
            assert init["network_mode"] == "none"
            assert init["read_only"] is True
            assert init["cap_drop"] == ["ALL"]
            assert {"CHOWN", "FOWNER"} <= set(init["cap_add"])
            assert set(init["cap_add"]) <= {"CHOWN", "FOWNER", "DAC_OVERRIDE"}
            assert init["restart"] == "no"
            assert [mount["target"] for mount in init["volumes"]] == [
                "/var/lib/itsm-setup",
                INSTALLATION_DIR,
            ]
            assert "chmod 0700" in init["command"][2]
            assert f"chmod 0700 /var/lib/itsm-setup {INSTALLATION_DIR}" in init["command"][2]
            assert f"chown 10001:10001 /var/lib/itsm-setup {INSTALLATION_DIR}" in init["command"][2]
            assert any("label=level:s0:c100" in value for value in init["security_opt"])
            if mode == "prod":
                assert setup["environment"]["ITSM_SETUP_ALLOWED_ORIGINS"] == (
                    "https://test.invalid"
                ), "production pins the exact https origin the wizard validates"
            assert [mount["target"] for mount in setup["volumes"]] == [
                "/var/lib/itsm-setup",
                INSTALLATION_DIR,
            ]
            assert all(mount["type"] == "volume" for mount in setup["volumes"])
            assert "docker.sock" not in json.dumps(setup)
            # One shared settings volume: setup is its only writer, so it is the
            # only service that mounts it read-write. The API, the worker and the
            # preparation gate read the same file and must never write it.
            sources = set()
            for name in ("initialize", "backend", "worker", "setup"):
                assert services[name]["environment"]["ITSM_INSTALLATION_CONFIG"] == (
                    INSTALLATION_FILE
                ), f"{mode}: {name} must read the installation settings file"
                mount = next(
                    (
                        value
                        for value in services[name]["volumes"]
                        if value["target"] == INSTALLATION_DIR
                    ),
                    None,
                )
                assert mount is not None, f"{mode}: {name} mounts {INSTALLATION_DIR}"
                assert mount["type"] == "volume", f"{mode}: {name} uses a named volume"
                sources.add(mount["source"])
            assert sources == {INSTALLATION_VOLUME}, (
                f"{mode}: the four services share one installation volume (got {sources})"
            )
            assert model["volumes"][INSTALLATION_VOLUME]["name"] == (
                f"itsm-{mode}_{INSTALLATION_VOLUME}"
            )
            for name in ("initialize", "backend", "worker"):
                mount = next(
                    value
                    for value in services[name]["volumes"]
                    if value["target"] == INSTALLATION_DIR
                )
                assert mount.get("read_only") is True, (
                    f"{mode}: {name} must not write the installation settings"
                )
            setup_mount = next(
                value for value in setup["volumes"] if value["target"] == INSTALLATION_DIR
            )
            assert not setup_mount.get("read_only"), (
                f"{mode}: setup is the only writer of the installation settings"
            )
            assert any("label=level:s0:c100" in value for value in setup["security_opt"])
        # The UI edge boots alone: a fresh installation has no API to wait for,
        # and the wizard is served through this same edge.
        assert "depends_on" not in services["frontend"]
        # Every application container: read-only root, /tmp as tmpfs, bounded PIDs.
        # Writable state stays on the named volumes; no memory limit is asserted
        # because the default is unlimited (operator knob ITSM_APP_MEM_LIMIT).
        for name in ("initialize", "backend", "worker", "frontend", "proxy"):
            if name not in services:
                continue
            assert services[name]["read_only"] is True, name
            assert services[name]["pids_limit"] == 256, name
            if name in ("initialize", "backend", "worker"):
                assert "/tmp" in str(services[name]["tmpfs"]), name
        print(f"PASS {mode}: application containers are read-only with bounded PIDs")
        volumes.append({value["name"] for value in model.get("volumes", {}).values()})
        print(f"PASS {mode}: project, gate, mode and maintenance isolation")
    assert not any(a & b for i, a in enumerate(volumes) for b in volumes[i + 1:])
    print("PASS mode-owned named volumes do not overlap")
    for name in ("ITSM_REPORT_BASE_URL", "ITSM_MONITORING_PUBLIC_URL"):
        result = compose("prod", omit=(name,))
        assert result.returncode != 0 and name in result.stderr, result.stderr
    print("PASS prod refuses to start without its public URLs")
    assert_variable_proxy_pass_keeps_the_uri()


if __name__ == "__main__":
    main()
