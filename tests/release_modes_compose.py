"""Read-only Compose rendering contract; no containers, builds or downloads."""
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


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


if __name__ == "__main__":
    main()
