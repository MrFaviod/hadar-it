"""Read-only Compose rendering contract; no containers, builds or downloads."""
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def render(mode):
    env = {key: value for key, value in os.environ.items() if not key.startswith("ITSM_")}
    env.update(
        RELEASE_MODE=mode,
        ITSM_SELINUX_LEVEL="s0:c100",
        ITSM_AUTH_ORIGIN="https://test.invalid",
        ITSM_DATABASE_URL="sqlite:////data/app/prod.db",
        ITSM_DEV_ADMIN_PASSWORD="test-only-not-an-installed-secret",
    )
    result = subprocess.run(
        ["docker", "compose", "--env-file", "/dev/null", "-f", "compose.yaml", "-f",
         f"deploy/compose.{mode}.yaml", "config", "--format", "json"],
        cwd=ROOT, env=env, text=True, capture_output=True, timeout=20,
    )
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
        if mode == "demo":
            assert "worker" not in services
            assert services["backend"]["environment"]["OPENAI_API_KEY"] == ""
            assert services["backend"]["environment"]["ITSM_TASK_STORAGE"] == "sqlite"
        if mode == "prod":
            assert services["initialize"]["image"] == "itsm-ops:0.1.0"
            assert any(v["target"] == "/data/backups" for v in services["initialize"]["volumes"])
        volumes.append({value["name"] for value in model.get("volumes", {}).values()})
        print(f"PASS {mode}: project, gate, mode and maintenance isolation")
    assert not any(a & b for i, a in enumerate(volumes) for b in volumes[i + 1:])
    print("PASS mode-owned named volumes do not overlap")


if __name__ == "__main__":
    main()
