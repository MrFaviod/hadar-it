"""Opt-in Docker regression: shared SQLite storage in both startup orders.

Run from the workspace root. Creates two isolated projects with fresh volumes,
uses test-only credentials and stops its containers in finally. Never deletes
volumes, changes host services, or retries a failed worker process.
"""
import http.cookiejar
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]


def command(args, **kwargs):
    return subprocess.run(args, check=True, text=True, **kwargs)


def exercise(order, port):
    project = "itsm-cold-" + order + "-" + uuid.uuid4().hex[:8]
    origin = f"http://127.0.0.1:{port}"
    password = uuid.uuid4().hex + "Aa1!"
    env = os.environ | {
        "ITSM_POSTGRES_PASSWORD": "cold-start-disposable-test-only",
        "ITSM_API_PORT": str(port),
        "ITSM_AUTH_ORIGIN": origin,
        "ITSM_AUTH_COOKIE_SECURE": "false",
    }
    config = json.loads(subprocess.check_output(
        ["docker", "compose", "--env-file", "/dev/null", "--profile", "local-postgres",
         "--profile", "tools", "-p", project, "config", "--format", "json"],
        cwd=ROOT, env=env, text=True,
    ))
    config["services"] = {name: service for name, service in config["services"].items()
                          if name in ("postgres", "backend", "worker", "migrate")}
    for service in config["services"].values():
        service["restart"] = "no"
    config["services"]["backend"]["environment"]["ITSM_BOOTSTRAP_PASSWORD"] = password
    compose = ["docker", "compose", "--env-file", "/dev/null", "--project-directory",
               str(ROOT), "-p", project, "-f", "-"]

    def run(*args):
        command(compose + list(args), input=json.dumps(config), timeout=90)

    client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    csrf = ""

    def request(path, data=None):
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/v1" + path,
                                     data=body, headers={"Content-Type": "application/json",
                                                         "Origin": origin, "X-CSRF-Token": csrf})
        with client.open(req, timeout=5) as response:
            return json.load(response)

    try:
        run("--profile", "local-postgres", "up", "-d", "--wait", "postgres")
        run("run", "--rm", "migrate")
        # Disposable credentials exist only in this generated test environment.
        run("run", "--rm", "-T", "backend", "python", "-m", "itsm.identity.cli",
            "bootstrap-admin", "--username", "cold-test", "--name", "Cold test")
        if order == "api-first":
            run("up", "-d", "--wait", "backend")
            session = request("/auth/login", {"username": "cold-test", "password": password})
            csrf = session["csrfToken"]
            task = request("/tasks/demo", {"message": project})["task_id"]
            run("up", "-d", "worker")
        else:
            run("up", "-d", "worker")
            deadline = time.monotonic() + 10
            while True:
                logs = subprocess.check_output(["docker", "logs", project + "-worker-1"],
                                               stderr=subprocess.STDOUT, text=True)
                if "worker.started" in logs:
                    break
                state = json.loads(subprocess.check_output(
                    ["docker", "inspect", project + "-worker-1"], text=True))[0]
                assert state["State"]["Running"], logs
                assert time.monotonic() < deadline, logs
                time.sleep(.2)
            run("up", "-d", "--wait", "backend")
            session = request("/auth/login", {"username": "cold-test", "password": password})
            csrf = session["csrfToken"]
            task = request("/tasks/demo", {"message": project})["task_id"]
        deadline = time.monotonic() + 15
        while True:
            state = json.loads(subprocess.check_output(
                ["docker", "inspect", project + "-worker-1"], text=True))[0]
            assert state["State"]["Running"] and state["RestartCount"] == 0, state["State"]
            result = request("/tasks/" + task)
            if result["state"] == "complete":
                break
            assert result["state"] != "error", result
            assert time.monotonic() < deadline, result
            time.sleep(.2)
        assert result["result"] == {"message": project}, result
        assert request("/tasks/" + task) == result
        for service in ("backend", "worker"):
            command(["docker", "exec", project + "-" + service + "-1", "python", "-c",
                     "import sqlite3; c=sqlite3.connect('/data/app/shared-probe.db');"
                     "c.execute('create table if not exists probe (id integer)');c.close()"])
        print(f"PASS {order}: PostgreSQL migrated, shared app/task volumes, real result, zero restarts", flush=True)
    finally:
        ids = subprocess.check_output(["docker", "ps", "-q", "--filter",
                                       "label=com.docker.compose.project=" + project], text=True).split()
        if ids:
            command(["docker", "stop", "--timeout", "5", *ids], timeout=30)


if __name__ == "__main__":
    exercise("api-first", 18005)
    exercise("worker-first", 18006)
