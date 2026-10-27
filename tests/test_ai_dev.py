"""Behavior checks for the dedicated host-owned Hermes launcher."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import socket
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "itsm-ai-dev.py"


def load_launcher():
    spec = importlib.util.spec_from_file_location("itsm_ai_dev", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LaunchProofTest(unittest.TestCase):
    @staticmethod
    def free_port():
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            return probe.getsockname()[1]

    @staticmethod
    def executable(directory, body):
        binary = directory / "hermes"
        binary.write_text("#!" + sys.executable + "\n" + body)
        binary.chmod(0o700)
        return binary

    def test_startup_never_attests_foreign_listener_that_wins_spawn_race(self):
        module = load_launcher()
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            (home / "config.yaml").write_text("model: test\n")
            binary = self.executable(home, "import time\ntime.sleep(120)\n")
            manager = module.Launcher(binary, home, self.free_port(), {})
            original_popen = module.subprocess.Popen
            with socket.socket() as foreign:
                def spawn_then_bind(*args, **kwargs):
                    child = original_popen(*args, **kwargs)
                    foreign.bind(("127.0.0.1", manager.port))
                    foreign.listen()
                    return child

                try:
                    with patch.object(module.subprocess, "Popen",
                                      side_effect=spawn_then_bind):
                        with self.assertRaisesRegex(ValueError, "not owned|ownership"):
                            manager.start()
                    self.assertIsNone(manager.child)
                    self.assertEqual(manager.receipt, {})
                finally:
                    manager.close()

    def test_proof_rejects_foreign_listener_after_owned_listener_closes(self):
        module = load_launcher()
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            (home / "config.yaml").write_text("model: test\n")
            binary = self.executable(
                home,
                "import socket, sys, time\n"
                "from pathlib import Path\n"
                "port = int(sys.argv[sys.argv.index('--port') + 1])\n"
                "listener = socket.socket()\n"
                "listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
                "listener.bind(('127.0.0.1', port))\n"
                "listener.listen()\n"
                "while not Path('stop-serving').exists():\n"
                "    time.sleep(0.01)\n"
                "listener.close()\n"
                "Path('listener-closed').touch()\n"
                "time.sleep(120)\n",
            )
            manager = module.Launcher(binary, home, self.free_port(), {})
            digest = "sha256:" + hashlib.sha256(
                (home / "config.yaml").read_bytes()).hexdigest()
            request = {"profileHome": str(home), "endpoint": manager.endpoint,
                       "configDigest": digest}
            try:
                manager.start()
                self.assertEqual(manager.proof(request)["processId"],
                                 manager.child.pid)
                (home / "stop-serving").touch()
                deadline = time.monotonic() + 5
                while (not (home / "listener-closed").exists()
                       and time.monotonic() < deadline):
                    time.sleep(0.01)
                self.assertTrue((home / "listener-closed").exists())
                with socket.socket() as foreign:
                    foreign.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    foreign.bind(("127.0.0.1", manager.port))
                    foreign.listen()
                    self.assertIsNone(manager.child.poll())
                    with self.assertRaisesRegex(ValueError, "not owned|ownership"):
                        manager.proof(request)
            finally:
                manager.close()

    def test_proof_accepts_listener_owned_by_verified_child_descendant(self):
        module = load_launcher()
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            (home / "config.yaml").write_text("model: test\n")
            server = ("import http.server, sys\n"
                      "port = int(sys.argv[1])\n"
                      "http.server.HTTPServer(('127.0.0.1', port), "
                      "http.server.BaseHTTPRequestHandler).serve_forever()\n")
            binary = self.executable(
                home,
                "import subprocess, sys, time\n"
                "from pathlib import Path\n"
                "port = sys.argv[sys.argv.index('--port') + 1]\n"
                f"server = subprocess.Popen([sys.executable, '-c', {server!r}, port])\n"
                "Path('descendant-pid').write_text(str(server.pid))\n"
                "time.sleep(120)\n",
            )
            manager = module.Launcher(binary, home, self.free_port(), {})
            digest = "sha256:" + hashlib.sha256(
                (home / "config.yaml").read_bytes()).hexdigest()
            try:
                manager.start()
                proof = manager.proof({"profileHome": str(home),
                                       "endpoint": manager.endpoint,
                                       "configDigest": digest})
                self.assertEqual(proof["processId"], manager.child.pid)
            finally:
                manager.close()
                descendant = int((home / "descendant-pid").read_text())
                try:
                    os.kill(descendant, 15)
                except ProcessLookupError:
                    pass

    def test_start_fails_closed_when_listener_ownership_is_unavailable(self):
        module = load_launcher()
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            (home / "config.yaml").write_text("model: test\n")
            binary = self.executable(
                home,
                "import http.server, sys\n"
                "port = int(sys.argv[sys.argv.index('--port') + 1])\n"
                "http.server.HTTPServer(('127.0.0.1', port), "
                "http.server.BaseHTTPRequestHandler).serve_forever()\n",
            )
            manager = module.Launcher(binary, home, self.free_port(), {})
            try:
                with patch.object(module, "PROC", home / "missing-proc"):
                    with self.assertRaisesRegex(ValueError, "ownership"):
                        manager.start()
                self.assertIsNone(manager.child)
                self.assertEqual(manager.receipt, {})
            finally:
                manager.close()

    def test_proof_binds_live_child_home_endpoint_and_exact_config(self):
        module = load_launcher()
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "profiles" / "itsm"
            home.mkdir(parents=True)
            config = home / "config.yaml"
            config.write_text("model: test\n")
            binary = Path(temporary) / "hermes"
            binary.write_text(f"#!{sys.executable}\nimport http.server, sys\n"
                              "port = int(sys.argv[sys.argv.index('--port') + 1])\n"
                              "http.server.HTTPServer(('127.0.0.1', port), "
                              "http.server.BaseHTTPRequestHandler).serve_forever()\n")
            binary.chmod(0o700)
            manager = module.Launcher(binary, home, 19991, {})
            digest = "sha256:" + hashlib.sha256(config.read_bytes()).hexdigest()
            request = {"profileHome": str(home), "endpoint": manager.endpoint,
                       "configDigest": digest}
            try:
                manager.start()
                first = manager.proof(request)
                self.assertEqual(first["processId"], manager.child.pid)
                self.assertEqual(first["configDigest"], digest)
                for bad in ({**request, "profileHome": str(home.parent)},
                            {**request, "endpoint": "http://127.0.0.1:19992"},
                            {**request, "configDigest": "0" * 64},
                            {**request, "command": "touch unwanted"}):
                    with self.assertRaises(ValueError):
                        manager.proof(bad)
                self.assertEqual(manager.child.pid, first["processId"])
                config.write_text("model: changed\n")
                with self.assertRaises(ValueError):
                    manager.proof(request)
                second = manager.proof({**request, "configDigest":
                                        "sha256:" + hashlib.sha256(config.read_bytes()).hexdigest()})
                self.assertNotEqual(second["launchId"], first["launchId"])
                self.assertNotEqual(second["processId"], first["processId"])
                manager.child.terminate()
                manager.child.wait(timeout=5)
                with self.assertRaises(ValueError):
                    manager.proof({**request, "configDigest": second["configDigest"]})
            finally:
                manager.close()

    def test_foreign_listener_is_never_attested_as_owned_child(self):
        module = load_launcher()
        with tempfile.TemporaryDirectory() as temporary, socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            home = Path(temporary)
            (home / "config.yaml").write_text("model: test\n")
            manager = module.Launcher(Path(sys.executable), home, listener.getsockname()[1], {})
            try:
                with self.assertRaisesRegex(ValueError, "already in use"):
                    manager.start()
                self.assertIsNone(manager.child)
                self.assertEqual(manager.receipt, {})
            finally:
                manager.close()

    def test_restart_accepts_closed_owned_port_in_time_wait(self):
        module = load_launcher()
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            (home / "config.yaml").write_text("model: test\n")
            binary = home / "hermes"
            binary.write_text(
                f"#!{sys.executable}\nimport http.server, sys\n"
                "port = int(sys.argv[sys.argv.index('--port') + 1])\n"
                "http.server.HTTPServer(('127.0.0.1', port), "
                "http.server.BaseHTTPRequestHandler).serve_forever()\n"
            )
            binary.chmod(0o700)
            with socket.socket() as listener:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
                listener.listen()
                with socket.create_connection(("127.0.0.1", port)) as client:
                    connection, _ = listener.accept()
                    connection.close()
                    self.assertEqual(client.recv(1), b"")
            manager = module.Launcher(binary, home, port, {})
            try:
                manager.start()
                self.assertIsNone(manager.child.poll())
                self.assertEqual(manager.receipt["processId"], manager.child.pid)
            finally:
                manager.close()

    def test_profile_proof_routes_only_pre_registered_home_and_endpoint(self):
        module = load_launcher()
        from unittest.mock import Mock
        first, second = Mock(), Mock()
        first.proof.return_value = {"launchId": "first-owned-child"}
        second.proof.return_value = {"launchId": "second-owned-child"}
        registry = {("/profiles/itsm", "http://127.0.0.1:19119"): first,
                    ("/profiles/itsm-review", "http://127.0.0.1:19122"): second}
        request = {"profileHome": "/profiles/itsm-review",
                   "endpoint": "http://127.0.0.1:19122", "configDigest": "new-digest"}
        self.assertEqual(module.profile_proof(registry, request),
                         {"launchId": "second-owned-child"})
        first.proof.assert_not_called()
        second.proof.assert_called_once_with(request)
        for bad in ({**request, "profileHome": "/profiles/itsm"},
                    {**request, "endpoint": "http://127.0.0.1:19119"},
                    {**request, "profileHome": ["/profiles/itsm-review"]}):
            with self.assertRaises(ValueError):
                module.profile_proof(registry, bad)
        self.assertEqual(second.proof.call_count, 1)

    def test_profile_config_never_persists_provider_or_dashboard_secrets(self):
        module = load_launcher()
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "profiles" / "itsm"
            environment = {"ITSM_HERMES_PROVIDER_URL": "https://provider.example/v1",
                           "ITSM_HERMES_PROVIDER_KEY": "provider-private-value",
                           "ITSM_HERMES_MODEL": "test-model",
                           "ITSM_HERMES_HEADERS_JSON": json.dumps({"X-Routing": "private-header"}),
                           "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD": "private-password"}
            with patch.dict(os.environ, environment, clear=True):
                child_env = module.prepare_profile(home, None)
            text = (home / "config.yaml").read_text()
            self.assertNotIn("provider-private-value", text)
            self.assertNotIn("private-header", text)
            self.assertNotIn("private-password", text)
            self.assertEqual(child_env["ITSM_HERMES_PROVIDER_KEY"], "provider-private-value")
            self.assertEqual(child_env["ITSM_HERMES_HEADER_0"], "private-header")
            self.assertEqual((home / "config.yaml").stat().st_mode & 0o777, 0o600)
            (home / "config.yaml").write_text("operator: preserved\n")
            with patch.dict(os.environ, environment, clear=True):
                module.prepare_profile(home, None)
            self.assertEqual((home / "config.yaml").read_text(), "operator: preserved\n")


if __name__ == "__main__":
    unittest.main()
