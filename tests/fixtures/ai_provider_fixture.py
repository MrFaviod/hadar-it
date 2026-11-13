"""OpenAI-compatible provider fixture for the disposable onboarding run.

The setup service proves tool calling against a *real* HTTP peer: the first
completion answers with a ``tool_calls`` payload for ``get_setup_status``, the
second one closes the turn with text. This module is that peer, as a standalone
stdlib process so Compose can run it on the project network and the setup
container can reach it by DNS name.

It is a fixture, not a provider: nothing here leaves the Compose project and no
external model is contacted. The only thing written to stdout is one bounded
line per request (method, path, whether tools were offered, whether a tool
result came back); headers and bodies are never logged, so a credential cannot
leak into ``docker compose logs``.

Usage (inside the backend image, on the project network):

    FIXTURE_MODEL=probe-model python /opt/itsm-fixture/ai_provider_fixture.py
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

MODEL = os.environ.get("FIXTURE_MODEL", "probe-model")
TOOL = "get_setup_status"
HOST = os.environ.get("FIXTURE_HOST", "0.0.0.0")
PORT = int(os.environ.get("FIXTURE_PORT", "8080"))


def _tool_call_completion(model: str) -> dict[str, Any]:
    return {
        "id": "chatcmpl-fixture-tool",
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_fixture_1",
                            "type": "function",
                            "function": {"name": TOOL, "arguments": "{}"},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 9, "completion_tokens": 4, "total_tokens": 13},
    }


def _text_completion(model: str, text: str) -> dict[str, Any]:
    return {
        "id": "chatcmpl-fixture-final",
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 11, "completion_tokens": 6, "total_tokens": 17},
    }


class _Handler(BaseHTTPRequestHandler):
    server_version = "OnboardingProviderFixture/1.0"

    def log_message(self, *args: object) -> None:
        # The default access log includes the peer address only; keep stdout for
        # the bounded REQUEST lines this fixture is inspected through.
        return

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _record(self, method: str, path: str, tools: int, tool_result: bool) -> None:
        # No header, body, credential or client address is ever printed.
        print(
            f"REQUEST {method} {path} tools={tools} tool_result={str(tool_result).lower()}",
            flush=True,
        )

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        self._record("GET", path, 0, False)
        if path.rstrip("/") == "/v1/models":
            self._send(
                200,
                {
                    "object": "list",
                    "data": [{"id": MODEL, "object": "model", "owned_by": "fixture"}],
                },
            )
            return
        if path.rstrip("/") == "/healthz":
            self._send(200, {"status": "ok", "model": MODEL})
            return
        self._send(404, {"error": "not_found"})

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(length) if length else b""
        path = self.path.split("?", 1)[0]
        if path.rstrip("/") != "/v1/chat/completions":
            self._record("POST", path, 0, False)
            self._send(404, {"error": "not_found"})
            return
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            self._record("POST", path, 0, False)
            self._send(400, {"error": "invalid_json"})
            return
        model = str(body.get("model") or MODEL)
        messages = body.get("messages") or []
        tools = body.get("tools") or []
        answered = any(
            isinstance(item, dict) and item.get("role") == "tool" for item in messages
        )
        self._record("POST", path, len(tools), answered)
        if tools and not answered:
            self._send(200, _tool_call_completion(model))
            return
        self._send(200, _text_completion(model, "The installation is claimed."))


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main() -> int:
    server = _Server((HOST, PORT), _Handler)
    print(f"fixture listening on {HOST}:{PORT} model={MODEL}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
