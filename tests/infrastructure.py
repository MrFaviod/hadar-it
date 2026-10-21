"""Public Phase-1 smoke against an already started, isolated Compose stack.

ITSM_TEST_API_URL defaults to http://127.0.0.1:18001. No Docker lifecycle or
production data changes are performed; only the bounded demo task is submitted.
"""
import json
import os
import time
import urllib.error
import urllib.request

BASE = os.environ.get("ITSM_TEST_API_URL", "http://127.0.0.1:18001").rstrip("/")


def request(path, data=None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(BASE + path, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


def result(task_id):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        status, payload = request("/api/v1/tasks/" + task_id)
        assert status == 200, (status, payload)
        if payload["state"] in ("complete", "error"):
            return payload
        time.sleep(0.2)
    raise AssertionError("Worker did not produce a terminal result within 30s")


def main():
    status, payload = request("/api/v1/health/live")
    assert (status, payload) == (200, {"status": "ok"}), (status, payload)
    status, health = request("/api/v1/health/ready")
    assert status == 200 and health["status"] == "ok", (status, health)
    assert health["migrations"]["current"] == health["migrations"]["head"], health
    status, schema = request("/openapi.json")
    assert status == 200 and "/api/v1/tasks/demo" in schema["paths"]
    status, rejected = request("/api/v1/tasks/demo", {"message": "", "unknown": True})
    assert status == 422 and rejected["error"]["code"] == "validation_error", (status, rejected)
    status, missing = request("/api/v1/tasks/unknown-task-123")
    assert status == 404 and missing["error"]["code"] == "not_found", (status, missing)
    status, accepted = request("/api/v1/tasks/demo", {"message": "phase-1-docker-smoke", "delay_seconds": 0})
    assert status == 202 and accepted["state"] == "pending", (status, accepted)
    task_id = accepted["task_id"]
    completed = result(task_id)
    assert completed["state"] == "complete" and completed["error"] is None, completed
    assert completed["result"]["message"] == "phase-1-docker-smoke", completed
    status, repeated = request("/api/v1/tasks/" + task_id)
    assert status == 200 and repeated == completed, (status, repeated)
    status, scheduled = request("/api/v1/tasks/demo", {"message": "scheduled-smoke", "delay_seconds": 2})
    assert status == 202 and scheduled["state"] == "scheduled", (status, scheduled)
    completed = result(scheduled["task_id"])
    assert completed["state"] == "complete" and completed["result"]["message"] == "scheduled-smoke", completed
    print("PASS live/readiness/migrations/OpenAPI, validation, unknown job, real worker result, nondestructive polling and scheduled task")


if __name__ == "__main__":
    main()
