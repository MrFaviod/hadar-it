#!/usr/bin/env python3
"""Opt-in end-to-end proof of the demo telemetry chain.

Run it from the backend checkout with its virtual environment:

    .venv/bin/python ../tests/demo_telemetry.py

The script owns every moving part and uses no pre-existing service:

1. a disposable demo installation under ``<root>/.verification/``;
2. a loopback exporter on a free port, configured through ``itsm.demo setup`` so the
   generated scrape file names that exact port and the canonical asset uuids;
3. one pinned Prometheus container started here with ``--network host`` and
   ``--web.listen-address=127.0.0.1:<free port>``, read-only root filesystem, its
   TSDB on tmpfs, the generated config mounted ``:ro,Z``, and no alerting rules;
4. the real ``PrometheusAdapter`` through ``MonitoringService`` and
   ``DashboardService``, to prove the canonical read paths return measured samples.

The final step takes a few minutes and that is expected: the canonical 24h window is
evaluated in 289 second steps, so its last evaluation point trails the newest scrape
by up to 278 seconds. A brand-new TSDB only answers that window once enough history
exists; the helper waits for the real ``metric_series`` call to return a point and
never substitutes a shorter test-only window.

Only the container created by this run is stopped at the end. Nothing is pulled,
installed, deleted or reused from the main installation.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
PYTHON = BACKEND / ".venv" / "bin" / "python"
SCRATCH = ROOT / ".verification"
IMAGE = (
    "prom/prometheus:v3.14.0@sha256:"
    "5ce7540c3c00ef4ab0c9d2c995c6a5b9c421f44b4a115d97a2c7af3b1c21cbb0"
)
PASSWORD = "Demo-Telemetry-Script-Password-42"
SCRAPE_WAIT_SECONDS = 120
RANGE_WAIT_SECONDS = 420

CANONICAL_READS = '''\
"""Canonical read proof; runs inside the backend venv, prints one JSON object."""

import json
import sys
import time

from itsm.config import Settings
from itsm.dashboard.service import DashboardService
from itsm.database import create_engine_from_settings, create_session_factory
from itsm.identity.service import IdentityService
from itsm.monitoring.prometheus import PrometheusAdapter, metric_expression, range_window
from itsm.monitoring.service import MonitoringService

payload = json.loads(sys.argv[1])
settings = Settings(
    _env_file=None,
    environment="test",
    database_url=payload["databaseUrl"],
    prometheus_url=payload["prometheusUrl"],
)
engine = create_engine_from_settings(settings)
try:
    with create_session_factory(engine)() as session:
        identity = IdentityService(session, settings)
        principal = identity.login(payload["username"], payload["password"]).principal
        monitoring = MonitoringService(session, settings, identity=identity)
        adapter = PrometheusAdapter(settings)
        started = time.monotonic()
        window = range_window("24h")
        points = adapter.metric_series(payload["assetId"], "node", "memory", window) or []
        while not points and time.monotonic() - started < payload["rangeWaitSeconds"]:
            # The window must be rebuilt every attempt: its last evaluation point is
            # ``step - (86400 % step)`` seconds behind the current time, so a frozen
            # window can never reach history that is younger than that offset.
            print(
                "waiting for the newest 24h window step to reach stored history "
                f"(step {window.step_seconds}s)",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(10)
            window = range_window("24h")
            points = adapter.metric_series(payload["assetId"], "node", "memory", window) or []
        probe = {
            "stepSeconds": window.step_seconds,
            "expression": metric_expression("node", "memory", payload["assetId"]),
            "memoryPoints": len(points),
            "waitedSeconds": round(time.monotonic() - started, 1),
        }
        # Read the device only after the window has history: the same call before the
        # wait legitimately returns zero points on a brand-new TSDB.
        device = monitoring.get_device(principal, payload["assetId"], "24h")
        dashboard = DashboardService(session, identity, settings).summary(principal, "24h")
finally:
    engine.dispose()

row = next(
    (item for item in dashboard["rows"] if item["assetId"] == payload["assetId"]),
    None,
)
print(
    json.dumps(
        {
            "device": {
                "assetId": device["asset"]["assetId"],
                "status": device["status"],
                "reason": device["reason"],
                "uptime": device["uptime"],
                "latencyMs": (
                    round(device["latency"] * 1000, 2) if device["latency"] is not None else None
                ),
                "series": [
                    {
                        "metric": item["metric"],
                        "points": item["pointCount"],
                        "latest": item["points"][-1]["value"] if item["points"] else None,
                    }
                    for item in device["series"]
                ],
            },
            "probe": probe,
            "dashboard": {
                "availability": dashboard["availability"],
                "monitored": dashboard["stats"]["monitored"],
                "up": dashboard["stats"]["up"],
                "row": (
                    {
                        "status": row["status"],
                        "monitored": row["monitored"],
                        "uptimePct": row["uptimePct"],
                        "latencyMs": row["latencyMs"],
                    }
                    if row
                    else None
                ),
            },
        }
    )
)
'''


def _env(**overrides: str) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("ITSM_")}
    env.update(ITSM_ENVIRONMENT="test", ITSM_BOOTSTRAP_PASSWORD=PASSWORD)
    env.update(overrides)
    return env


def _cli(args: list[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [str(PYTHON), "-m", "itsm.demo", *args],
        cwd=BACKEND,
        env=_env(),
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode:
        raise SystemExit(f"command failed ({result.returncode}): {result.stderr.strip()}")
    return result


def _docker(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=180, check=False
    )


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _get(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()


def _counter(body: str) -> float:
    pattern = r'^node_cpu_seconds_total\{[^}]*mode="idle"[^}]*\} ([0-9.e+-]+)$'
    match = re.search(pattern, body, re.M)
    if not match:
        raise SystemExit("exporter body has no node_cpu_seconds_total idle counter")
    return float(match.group(1))


def _query(base: str, expression: str) -> list[dict]:
    query = urllib.parse.quote(expression)
    status, body = _get(f"{base}/api/v1/query?query={query}")
    if status != 200:
        raise SystemExit(f"Prometheus query failed with {status}: {body[:300]}")
    return json.loads(body)["data"]["result"]


def _wait_for_up(base: str, job: str, matches: list[dict]) -> None:
    deadline = time.monotonic() + SCRAPE_WAIT_SECONDS
    while time.monotonic() < deadline:
        matches[:] = _query(base, f'up{{job="{job}"}}')
        if matches and matches[0]["value"][1] == "1":
            return
        time.sleep(3)
    raise SystemExit(f"Prometheus never reported up=1 for job {job}: {matches}")


def _wait_for_scrapes(base: str, asset_id: str) -> int:
    """Wait for a second scrape so counter rates and range series are measurable."""
    expression = f'count_over_time(node_cpu_seconds_total{{asset_id="{asset_id}"}}[2m])'
    deadline = time.monotonic() + SCRAPE_WAIT_SECONDS
    count = 0
    while time.monotonic() < deadline:
        result = _query(base, expression)
        count = int(float(result[0]["value"][1])) if result else 0
        if count >= 2:
            return count
        time.sleep(5)
    raise SystemExit(f"Prometheus stored only {count} demo scrape(s) after {SCRAPE_WAIT_SECONDS}s")


def _start_prometheus(config: Path, port: int, name: str) -> str:
    if shutil.which("docker") is None:
        raise SystemExit("blocked: docker is not available in PATH")
    inspect = _docker("image", "inspect", "--format", "{{.Id}}", IMAGE)
    if inspect.returncode:
        raise SystemExit(f"blocked: pinned image is not present locally: {IMAGE}")
    started = _docker(
        "run",
        "-d",
        "--rm",
        "--pull=never",
        "--name",
        name,
        "--network",
        "host",
        "--read-only",
        "--security-opt",
        "no-new-privileges",
        "--cap-drop",
        "ALL",
        "--tmpfs",
        "/tmp:mode=1777",
        "-v",
        f"{config}:/etc/prometheus/prometheus.yml:ro,Z",
        "--entrypoint",
        "/bin/prometheus",
        IMAGE,
        "--config.file=/etc/prometheus/prometheus.yml",
        f"--web.listen-address=127.0.0.1:{port}",
        "--storage.tsdb.path=/tmp/prometheus",
        "--storage.tsdb.retention.time=2d",
    )
    if started.returncode:
        raise SystemExit(f"container start failed: {started.stderr.strip()[:400]}")
    base = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            if _get(f"{base}/-/ready")[0] == 200:
                return base
        except OSError:
            pass
        time.sleep(2)
    logs = _docker("logs", "--tail", "40", name)
    raise SystemExit(f"Prometheus never became ready.\n{logs.stdout}{logs.stderr}")


def _canonical_reads(scratch: Path, payload: dict) -> dict:
    helper = scratch / "canonical_reads.py"
    helper.write_text(CANONICAL_READS)
    result = subprocess.run(
        [str(PYTHON), str(helper), json.dumps(payload)],
        cwd=BACKEND,
        env=_env(PYTHONPATH=str(BACKEND)),
        capture_output=True,
        text=True,
        timeout=RANGE_WAIT_SECONDS + 120,
    )
    if result.returncode:
        raise SystemExit(f"canonical reads failed ({result.returncode}): {result.stderr.strip()}")
    return json.loads(result.stdout)


def main() -> int:
    if os.environ.get("ITSM_PROMETHEUS_URL"):
        raise SystemExit(
            "unset ITSM_PROMETHEUS_URL: this script starts its own isolated Prometheus"
        )
    SCRATCH.mkdir(exist_ok=True)
    scratch = SCRATCH / f"demo-telemetry-{uuid.uuid4().hex[:8]}"
    scratch.mkdir()
    directory = scratch / "demo"
    _cli(["init", "--directory", str(directory), "--username", "demo.owner"])
    exporter_port = _free_port()
    output = scratch / "prometheus-demo.yml"
    setup = json.loads(
        _cli(
            [
                "setup",
                "--directory",
                str(directory),
                "--username",
                "demo.owner",
                "--output",
                str(output),
                "--exporter-port",
                str(exporter_port),
            ]
        ).stdout
    )
    asset_id = setup["assetIds"][0]
    evidence: dict[str, object] = {
        "demoDirectory": str(directory),
        "prometheusConfig": str(output),
        "image": IMAGE,
        "assetId": asset_id,
        "exporterAddress": setup["exporterAddress"],
    }
    process = subprocess.Popen(
        [
            str(PYTHON),
            "-m",
            "itsm.demo",
            "exporter",
            "--directory",
            str(directory),
            "--port",
            str(exporter_port),
        ],
        cwd=BACKEND,
        env=_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    name = f"itsm-demo-prometheus-{uuid.uuid4().hex[:8]}"
    started = False
    problems: list[str] = []
    try:
        line = process.stdout.readline() if process.stdout else ""
        if not line:
            raise SystemExit("exporter did not report readiness")
        ready = json.loads(line)
        base = f"http://127.0.0.1:{ready['port']}"
        if (ready["host"], ready["port"]) != ("127.0.0.1", exporter_port):
            raise SystemExit(f"exporter bound the wrong address: {ready}")
        if _get(f"{base}/healthz") != (200, "ok\n"):
            raise SystemExit("exporter health check failed")
        first = _counter(_get(f"{base}/metrics/{asset_id}")[1])
        time.sleep(1.2)
        second = _counter(_get(f"{base}/metrics/{asset_id}")[1])
        if second <= first:
            raise SystemExit(f"idle counter did not increase: {first} -> {second}")
        if _get(f"{base}/metrics/not-a-uuid") != (400, "invalid asset uuid\n"):
            raise SystemExit("exporter accepted a malformed asset uuid")
        evidence["exporterReady"] = ready
        evidence["exporterIdleCounter"] = [first, second]

        prometheus_port = _free_port()
        prometheus = _start_prometheus(output, prometheus_port, name)
        started = True
        evidence["prometheusUrl"] = prometheus
        job = f"demo-node-{asset_id[:8]}"
        up: list[dict] = []
        _wait_for_up(prometheus, job, up)
        samples = _query(prometheus, f'node_memory_MemTotal_bytes{{asset_id="{asset_id}"}}')
        if not samples or float(samples[0]["value"][1]) <= 0:
            raise SystemExit("Prometheus stored no demo memory sample")
        scrapes = _wait_for_scrapes(prometheus, asset_id)
        evidence["prometheus"] = {
            "job": job,
            "up": up[0]["value"][1],
            "instance": up[0]["metric"].get("instance"),
            "memoryTotalBytes": float(samples[0]["value"][1]),
            "scrapes": scrapes,
        }
        canonical = _canonical_reads(
            scratch,
            {
                "databaseUrl": f"sqlite:///{directory / 'demo.db'}",
                "prometheusUrl": prometheus,
                "assetId": asset_id,
                "username": "demo.owner",
                "password": PASSWORD,
                "rangeWaitSeconds": RANGE_WAIT_SECONDS,
            },
        )
        evidence["canonical"] = canonical
        device = canonical["device"]
        if device["status"] != "up":
            problems.append(f"canonical device status is not up: {device['status']}")
        if canonical["probe"]["memoryPoints"] <= 0:
            problems.append("adapter range read returned no measured point")
        if not any(item["points"] > 0 for item in device["series"]):
            problems.append("canonical device read returned no measured points")
    finally:
        process.terminate()
        code = process.wait(timeout=15)
        evidence["exporterExit"] = code
        evidence["exporterStderr"] = process.stderr.read() if process.stderr else ""
        if started:
            stopped = _docker("stop", "--time", "10", name)
            evidence["containerStopped"] = stopped.returncode == 0
    print(json.dumps(evidence, indent=2, ensure_ascii=False))
    if evidence["exporterExit"] != 0 or evidence["exporterStderr"]:
        problems.append("exporter did not exit cleanly")
    if problems:
        raise SystemExit("; ".join(problems))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
