"""Real isolated Vue/REST inventory smoke; requires installed test credentials."""
import os
import uuid
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

base = os.environ.get('ASSET_URL', 'http://127.0.0.1:5174').rstrip('/')
username = os.environ['ITSM_TEST_USERNAME']
password = os.environ['ITSM_TEST_PASSWORD']
name = 'Browser switch ' + uuid.uuid4().hex[:10]
code = 'UI-' + uuid.uuid4().hex[:10]
with sync_playwright() as p:
    browser = p.chromium.launch()
    context = browser.new_context(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
    page = context.new_page()
    page.set_default_timeout(7000)
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.add_init_script("localStorage.setItem('asset-manager.assets', JSON.stringify([{id:'FORGED-LOCAL',name:'Forged inventory',category:'switches'}]));")
    page.goto(base, wait_until='networkidle')
    page.get_by_label('Usuario', exact=True).fill(username)
    page.get_by_label('Contraseña', exact=True).fill(password)
    page.get_by_role('button', name='Entrar', exact=True).click()
    expect(page.locator('.app-shell')).to_be_visible()
    page.goto(base + '/#/inventario', wait_until='networkidle')
    expect(page.get_by_role('heading', name='Inventario de activos')).to_be_visible()
    expect(page.locator('main')).not_to_contain_text('Forged inventory')
    page.get_by_role('button', name='Nuevo activo', exact=True).click()
    form = page.locator('#asset-editor-form')
    expect(form).to_be_visible()
    form.locator('input[id$="-name"]').fill(name)
    form.locator('input[id$="-quickCode"]').fill(code)
    form.locator('input[id$="-site"]').fill('Example Site')
    form.locator('input[id$="-responsible"]').fill('Operador de prueba')
    page.get_by_role('button', name='Registrar activo', exact=True).click()
    expect(form).not_to_be_visible()
    page.locator('#inventory-search').fill(code)
    expect(page.locator('main')).to_contain_text(name)
    records = page.evaluate("async code=>{const r=await fetch('/api/v1/assets/search?query='+encodeURIComponent(code));return await r.json()}", code)
    assert records['total'] == 1, records
    asset = records['items'][0]
    asset_id = asset['id']
    assert str(uuid.UUID(asset_id)) == asset_id
    assert asset['name'] == name and asset['site'] == 'Example Site'
    page.goto(base + '/#/activo/' + asset_id, wait_until='networkidle')
    expect(page.get_by_role('heading', name=name, exact=True)).to_be_visible()
    page.get_by_role('button', name='Editar activo', exact=True).click()
    expect(form).to_be_visible()
    changed_code = 'EDIT-' + uuid.uuid4().hex[:10]
    form.locator('input[id$="-quickCode"]').fill(changed_code)
    page.get_by_role('button', name='Guardar cambios', exact=True).click()
    expect(form).not_to_be_visible()
    page.reload(wait_until='networkidle')
    expect(page.get_by_role('heading', name=name, exact=True)).to_be_visible()
    expect(page.locator('main')).to_contain_text(changed_code)
    assert page.evaluate('location.hash') == '#/activo/' + asset_id
    response = page.evaluate("async id=>{const r=await fetch('/api/v1/assets/'+id);return await r.json()}", asset_id)
    assert response['id'] == asset_id and response['quickCode'] == changed_code
    page.get_by_role('link', name='Consultar sobre este activo', exact=True).click()
    expect(page.get_by_role('heading', name='Conversación', exact=True)).to_be_visible()
    assert page.evaluate('location.hash') == '#/conversacion/activo/' + asset_id
    expect(page.locator('select').filter(has=page.locator('option[value="' + asset_id + '"]'))).to_have_value(asset_id)
    page.locator('#conversation-input').fill('Mostrame los servidores de Matriz')
    page.get_by_role('button', name='Enviar', exact=True).click()
    expect(page.get_by_role('alert')).to_contain_text('modelo configurado')
    for width in [390, 1440]:
        page.set_viewport_size({'width': width, 'height': 1000})
        # Measure after the browser applies the new viewport layout.
        page.evaluate('() => new Promise(requestAnimationFrame)')
        overflow = page.evaluate('document.documentElement.scrollWidth > innerWidth')
        if overflow:
            print(page.evaluate("[...document.querySelectorAll('body *')].map(e=>({tag:e.tagName,cls:e.className,right:e.getBoundingClientRect().right,width:e.getBoundingClientRect().width})).filter(e=>e.right>innerWidth+1).slice(0,15)"))
            page.screenshot(path='.verification/phase3/browser-overflow.png', full_page=True)
        assert not overflow, width
    assert not errors, errors
    output = Path('.verification/phase3'); output.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(output / 'conversation-unconfigured.png'), full_page=True)
    context.close(); browser.close()
print('PASS Vue SQL inventory create/detail/edit/reload, immutable UUID, browser storage ignored, real unavailable-agent response and responsive UI')
