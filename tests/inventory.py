"""Public F3 smoke. Use an isolated migrated installation with an installed administrator.

Creates uniquely named test assets; no deletion or provider inference is performed.
"""
import http.cookiejar
import json
import os
import uuid
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener

base = os.environ.get('ITSM_TEST_API_URL', 'http://127.0.0.1:18080').rstrip('/')
origin = os.environ.get('ITSM_AUTH_ORIGIN', base)
client = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
csrf = ''


def request(path, body=None, method=None, authenticated=True):
    headers = {'Accept': 'application/json', 'Origin': origin}
    if csrf and authenticated:
        headers['X-CSRF-Token'] = csrf
    data = None
    if body is not None:
        headers['Content-Type'] = 'application/json'
        data = json.dumps(body).encode()
    req = Request(base + '/api/v1' + path, data=data, headers=headers, method=method)
    try:
        with client.open(req, timeout=10) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        raw = error.read().decode()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            # OAuth/MCP transport errors need not use the REST JSON envelope.
            payload = {'transportBody': raw}
        return error.code, payload


def main():
    global csrf
    assert request('/assets')[0] == 401
    status, login = request('/auth/login', {
        'username': os.environ['ITSM_TEST_USERNAME'],
        'password': os.environ['ITSM_TEST_PASSWORD'],
    })
    assert status == 200, (status, login)
    csrf = login['csrfToken']
    suffix = uuid.uuid4().hex[:12]
    code = 'F3-' + suffix
    name = 'Inventory smoke ' + suffix
    status, asset = request('/assets', {
        'quickCode': code, 'name': name, 'category': 'servidores',
        'brand': 'Aruba', 'site': 'Matriz', 'status': 'in_use',
    })
    assert status == 201, (status, asset)
    asset_id = asset['id']
    assert str(uuid.UUID(asset_id)) == asset_id
    assert asset['quickCode'] == code
    assert request('/assets/' + asset_id) == (200, asset)
    status, page = request('/assets/search?query=' + code + '&limit=1&offset=0')
    assert status == 200 and page['total'] == 1 and len(page['items']) == 1, page
    assert page['items'][0]['id'] == asset_id
    status, changed = request('/assets/' + asset_id, {
        'quickCode': 'REN-' + suffix, 'responsible': 'Inventory smoke operator',
    }, method='PATCH')
    assert status == 200 and changed['id'] == asset_id, changed
    assert changed['quickCode'] == 'REN-' + suffix
    assert changed['responsible'] == 'Inventory smoke operator'
    assert request('/assets/' + asset_id, {'id': str(uuid.uuid4())}, method='PATCH')[0] == 422
    assert request('/assets', {'quickCode': 'ren-' + suffix, 'name': name})[0] == 409
    assert request('/assets/' + asset_id) == (200, changed)
    rollback_name = 'Atomic rollback ' + suffix
    assert request('/assets/batch', {'create': [
        {'quickCode': 'ROLL-' + suffix, 'name': rollback_name},
        {'quickCode': 'REN-' + suffix, 'name': 'Duplicate'},
    ], 'update': []})[0] == 409
    status, page = request('/assets?query=ROLL-' + suffix)
    assert status == 200 and page['total'] == 0, page
    assert request('/assets/' + str(uuid.uuid4()))[0] == 404
    assert request('/assets', {'name': '', 'unexpected': 'rejected'})[0] == 422
    # MCP authenticates its own machine bearer transport, never the browser cookie.
    assert request('/mcp', {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
        'protocolVersion': '2025-03-26', 'capabilities': {},
        'clientInfo': {'name': 'itsm-smoke', 'version': '0.1.0'},
    }})[0] == 401
    if os.environ.get('ITSM_TEST_EXPECT_AGENT_UNAVAILABLE') == '1':
        status, result = request('/agent/chat', {'message': 'Mostrame los servidores de Matriz'})
        assert status == 503 and result['error']['code'] == 'unavailable', result
        assert request('/assets/' + asset_id) == (200, changed)
    assert request('/auth/logout', {}, method='POST')[0] == 200
    assert request('/assets/' + asset_id)[0] == 401
    print('PASS SQL inventory create/search/detail/update, immutable UUID, unique quick code, '
          'atomic rollback, validation, MCP cookie denial and logout')


if __name__ == '__main__':
    main()
