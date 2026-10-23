"""Real Phase 6 flows against an owned fresh-SQLite API, worker and Vite process."""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.request
from contextlib import ExitStack

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_ready(url: str, process: subprocess.Popen, timeout: int = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"owned server exited {process.returncode}: {url}")
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        time.sleep(0.1)
    raise TimeoutError(f"server readiness exceeded {timeout}s: {url}")


def main() -> None:
    fixture = ROOT / ".verification" / "phase6" / f"browser-{time.time_ns()}"
    fixture.mkdir(parents=True)
    api_port, ui_port = free_port(), free_port()
    origin = f"http://127.0.0.1:{ui_port}"
    env = {k: v for k, v in os.environ.items() if not k.startswith("ITSM_")}
    env.update({
        "PYTHONPATH": str(BACKEND), "ITSM_ENVIRONMENT": "test",
        "ITSM_DATABASE_URL": f"sqlite:///{fixture / 'app.db'}",
        "ITSM_TASK_SQLITE_PATH": str(fixture / "queue.db"),
        "ITSM_ATTACHMENT_STORAGE_PATH": str(fixture / "attachments"),
        "ITSM_AUTH_ORIGIN": origin, "ITSM_AUTH_COOKIE_SECURE": "false",
        "ITSM_TASK_RETRY_DELAY_SECONDS": "1", "ITSM_LOG_LEVEL": "WARNING",
    })
    python = str(BACKEND / ".venv" / "bin" / "python")
    subprocess.run([python, "-m", "alembic", "upgrade", "head"], cwd=BACKEND,
                   env=env, check=True, timeout=30)
    subprocess.run([python, "-c", "from itsm.config import get_settings; from tests.conftest import bootstrap_admin; bootstrap_admin(get_settings())"],
                   cwd=BACKEND, env=env, check=True, timeout=30)
    processes = []
    with ExitStack() as stack:
        def start(args, cwd, environment, name):
            log = stack.enter_context((fixture / f"{name}.log").open("wb"))
            proc = subprocess.Popen(args, cwd=cwd, env=environment, stdout=log, stderr=log)
            processes.append(proc)
            return proc
        try:
            api = start([python, "-m", "uvicorn", "itsm.main:create_app", "--factory", "--host", "127.0.0.1", "--port", str(api_port)], BACKEND, env, "api")
            start([python, "-m", "huey.bin.huey_consumer", "itsm.tasks.runtime.huey", "-w", "1", "-k", "thread"], BACKEND, env, "worker")
            ui_env = dict(env, ITSM_DEV_API_URL=f"http://127.0.0.1:{api_port}")
            ui = start(["npm", "run", "dev", "--", "--host", "127.0.0.1", "--port", str(ui_port), "--strictPort"], ROOT / "frontend", ui_env, "frontend")
            wait_ready(f"http://127.0.0.1:{api_port}/api/v1/health/live", api)
            wait_ready(origin, ui)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                errors = []
                def capture_error(exc):
                    errors.append(str(exc))
                    print('BROWSER_PAGEERROR: ' + str(exc), flush=True)
                page.on("pageerror", capture_error)
                page.on('response', lambda response: print(
                    'BROWSER_HTTP_ERROR: ' + str(response.status) + ' ' + response.url,
                    flush=True
                ) if response.status >= 400 and '/api/' in response.url else None)
                page.goto(origin, wait_until="networkidle")
                page.get_by_label("Usuario", exact=True).fill("ana.admin")
                page.get_by_label("Contraseña", exact=True).fill("installer-password-2026")
                page.get_by_role("button", name="Entrar", exact=True).click()
                expect(page.locator('.app-shell')).to_be_visible()
                page.get_by_role('link', name='Datos', exact=True).click()
                expect(page.locator('[data-od-id="transfer-step-1"]')).to_be_visible()
                page.locator('#tx-real-file').set_input_files({"name": "browser.csv", "mimeType": "text/csv", "buffer": b"name,category,serial\nBrowser Phase6,switch,BROWSER-SERIAL\n"})
                expect(page.get_by_text("browser.csv", exact=True).first).to_be_visible()
                page.locator('[data-od-id="transfer-continue"]').click()
                page.locator('[data-od-id="transfer-continue"]').click()
                expect(page.locator('[data-od-id="transfer-step-panel-3"]')).to_be_visible()
                expect(page.get_by_text("Browser Phase6", exact=True).first).to_be_visible()
                page.locator('[data-od-id="transfer-continue"]').click()
                page.locator('[data-od-id="transfer-continue"]').click()
                page.locator('[data-od-id="transfer-apply"]').click()
                page.locator('[data-od-id="transfer-confirm-apply"]').click()
                expect(page.get_by_text("Importación completada", exact=True)).to_be_visible(timeout=20000)
                page.screenshot(path=str(fixture / 'original-import-complete.png'), full_page=True)
                # Public API assertion via the same real browser cookie session, not DB inspection.
                found = page.evaluate("""async () => {const r=await fetch('/api/v1/assets/search?q=Browser%20Phase6');if(!r.ok)throw Error(await r.text());return r.json();}""")
                assert found["total"] == 1, found
                asset_id = found["items"][0]["id"]
                page.locator('[data-od-id="transfer-tab-export"]').click()
                page.locator('[data-od-id="export-generate"]').click()
                expect(page.locator('[data-od-id="export-download"]')).to_be_visible()
                with page.expect_download() as downloaded:
                    page.locator('[data-od-id="export-download"]').click()
                export_path = fixture / 'assets.csv'
                downloaded.value.save_as(export_path)
                assert asset_id in export_path.read_text(encoding='utf-8-sig')
                page.screenshot(path=str(fixture / 'original-export.png'), full_page=True)
                page.goto(origin + '/#/inventario', wait_until='networkidle')
                expect(page.locator('[data-od-id="inventory-bulk-open"]')).to_be_visible()
                page.locator('[data-od-id="inventory-bulk-open"]').click()
                bulk_dialog = page.get_by_role('dialog').filter(has=page.get_by_role('heading', name='Edición masiva', exact=True))
                bulk_dialog.locator('[data-od-id="bulk-continue"]').click()
                bulk_dialog.get_by_label('Marca', exact=True).check()
                bulk_dialog.locator('#bulk-brand').fill('Browser batch brand')
                bulk_dialog.locator('[data-od-id="bulk-preview"]').click()
                bulk_dialog.locator('[data-od-id="bulk-apply"]').click()
                expect(bulk_dialog.get_by_text('Edición masiva aplicada', exact=True)).to_be_visible()
                after_bulk = page.evaluate("""async (id) => {
                    const r=await fetch('/api/v1/assets/'+id);if(!r.ok)throw Error(await r.text());return r.json();
                }""", asset_id)
                assert after_bulk['id'] == asset_id
                assert after_bulk['brand'] == 'Browser batch brand'
                assert after_bulk['serial'] == 'BROWSER-SERIAL'
                page.screenshot(path=str(fixture / 'original-bulk-result.png'), full_page=True)
                bulk_dialog.get_by_role('button', name='Cerrar', exact=True).click()
                expect(bulk_dialog).not_to_be_visible()
                page.goto(origin + "/#/activo/" + asset_id, wait_until="networkidle")
                expect(page.get_by_role("heading", name="Adjuntos del activo")).to_be_visible()
                page.get_by_label("Archivo", exact=True).set_input_files({"name":"receipt.pdf","mimeType":"application/pdf","buffer":b"%PDF-1.7\nreceipt\n%%EOF"})
                expect(page.get_by_text("receipt.pdf", exact=True).first).to_be_visible()
                warranty_panel = page.locator('[data-od-id="asset-warranty-panel"]')
                warranty_panel.get_by_role('button', name='Editar garantía', exact=True).click()
                warranty = page.locator('[data-od-id="warranty-edit-form"]')
                warranty.get_by_label("Proveedor", exact=True).fill("Browser supplier")
                warranty.get_by_label("Fecha de compra", exact=True).fill("2026-01-31")
                warranty.locator('select').filter(has=page.locator('option[value="duration"]')).select_option('duration')
                warranty.get_by_label("Duración en meses", exact=True).fill("12")
                warranty.locator('input[type="file"]').set_input_files({"name":"warranty-receipt.pdf","mimeType":"application/pdf","buffer":b"%PDF-1.7\nwarranty receipt\n%%EOF"})
                expect(warranty.get_by_role('button', name='Quitar la referencia a warranty-receipt.pdf', exact=True)).to_be_visible()
                page.locator('[form="warranty-edit-form"]').click()
                expect(page.get_by_text("Browser supplier", exact=True).first).to_be_visible()
                page.reload(wait_until="networkidle")
                expect(page.get_by_text("Browser supplier", exact=True).first).to_be_visible()
                expect(page.get_by_text("receipt.pdf", exact=True).first).to_be_visible()
                # Verify persistence and expiry through authenticated public endpoints only.
                persisted = page.evaluate("""async (id) => {
                    const [w,a,h] = await Promise.all(['warranty','attachments','history'].map(async suffix => {
                        const r = await fetch('/api/v1/assets/'+id+'/'+suffix);
                        if(!r.ok) throw Error(await r.text()); return r.json();
                    })); return {w,a,h};
                }""", asset_id)
                assert persisted['w']['supplier'] == 'Browser supplier'
                assert persisted['w']['expiresOn'] == '2027-01-31'
                assert {item['filename'] for item in persisted['a']['items']} == {'receipt.pdf', 'warranty-receipt.pdf'}
                assert persisted['w']['receiptId'] in {item['id'] for item in persisted['a']['items'] if item['filename'] == 'warranty-receipt.pdf'}
                assert any(item['action'] == 'warranty_updated' for item in persisted['h']['items'])
                assert any(item['action'] == 'attachment_uploaded' for item in persisted['h']['items'])
                for width in (390, 1440):
                    page.set_viewport_size({"width":width,"height":1000})
                    page.screenshot(path=str(fixture / f"asset-{width}.png"), full_page=True)
                    overflow = page.evaluate("""() => Array.from(document.querySelectorAll('body *'))
                        .map(e => ({tag:e.tagName,cls:String(e.className||''),left:e.getBoundingClientRect().left,right:e.getBoundingClientRect().right}))
                        .filter(e => e.right > innerWidth + 1).sort((a,b) => b.right-a.right).slice(0,20)""")
                    if page.evaluate("document.documentElement.scrollWidth > innerWidth"):
                        print('BROWSER_OVERFLOW: ' + json.dumps({'width':width,'elements':overflow}), flush=True)
                        raise AssertionError(f'Horizontal overflow at {width}px')
                assert not errors, errors
                browser.close()
                print(json.dumps({"status":"PASS","fixture":str(fixture.relative_to(ROOT)),"assetId":asset_id,"flows":["original five-step import","human approval","real CSV export","original bulk preview approval execution","persistent asset","attachment upload","individual warranty","reload","390/1440 overflow"]}))
        finally:
            for proc in reversed(processes):
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=5)


if __name__ == "__main__":
    main()
