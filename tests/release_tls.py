"""Exercise the checked-in nginx TLS recipe on owned loopback listeners only."""
from __future__ import annotations

import http.server
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        payload = ("api" if self.path.startswith("/api/") else "frontend").encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


def main():
    scratch = ROOT / ".verification"
    scratch.mkdir(exist_ok=True)
    upstream = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="tls-handshake-", dir=scratch) as directory:
            path = Path(directory).resolve()
            port = free_port()
            subprocess.run([
                "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                "-keyout", str(path / "key.pem"), "-out", str(path / "cert.pem"),
                "-days", "1", "-subj", "/CN=localhost", "-addext", "subjectAltName=IP:127.0.0.1",
            ], check=True, capture_output=True)
            text = (ROOT / "deploy/nginx-tls.conf").read_text()
            substitutions = {
                "/run/secrets/tls_certificate_key": str(path / "key.pem"),
                "/run/secrets/tls_certificate": str(path / "cert.pem"),
                "backend:8000": f"127.0.0.1:{upstream.server_port}",
                "frontend:8080": f"127.0.0.1:{upstream.server_port}",
                "listen 8080 ssl;": f"listen 127.0.0.1:{port} ssl;",
                "/tmp/nginx.pid": str(path / "nginx.pid"),
                "/dev/stderr": str(path / "error.log"),
                "/dev/stdout": str(path / "access.log"),
            }
            for original, replacement in substitutions.items():
                text = text.replace(original, replacement)
            for name in ("client", "proxy", "fastcgi", "uwsgi", "scgi"):
                text = text.replace(f"/tmp/{name};", f"{path / name};")
            config = path / "nginx.conf"
            config.write_text(text)
            with (path / "process.log").open("wb") as log:
                process = subprocess.Popen([
                    "nginx", "-e", str(path / "bootstrap.log"), "-p", str(path),
                    "-c", str(config), "-g", "daemon off; master_process off;",
                ], stdout=log, stderr=log)
                try:
                    context = ssl.create_default_context(cafile=str(path / "cert.pem"))
                    for attempt in range(50):
                        try:
                            with urllib.request.urlopen(f"https://127.0.0.1:{port}/api/v1/health/live", context=context, timeout=1) as response:
                                assert response.read() == b"api"
                                assert response.headers["Strict-Transport-Security"] == "max-age=31536000"
                                assert response.headers["X-Content-Type-Options"] == "nosniff"
                                break
                        except OSError:
                            if process.poll() is not None or attempt == 49:
                                raise AssertionError((path / "process.log").read_text()) from None
                            time.sleep(0.1)
                    with urllib.request.urlopen(f"https://127.0.0.1:{port}/", context=context, timeout=2) as response:
                        assert response.read() == b"frontend"
                        assert response.headers["X-Frame-Options"] == "SAMEORIGIN"
                    print("PASS certificate-verified loopback HTTPS, API/UI routing and security headers")
                    print("Scope: native host nginx with substituted owned upstreams; not container/deployed proof")
                finally:
                    process.terminate()
                    process.wait(timeout=5)
    finally:
        upstream.shutdown()
        upstream.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    main()
