"""Public F4 smoke for a fresh, isolated, migrated installation.

Uses only HTTP; test credentials and the base URL come from the process environment.
Creates and purges its own disposable assets. Never point it at an existing installation.
"""
from __future__ import annotations

import base64
import http.cookiejar
import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener

BASE = os.environ['ITSM_TEST_API_URL'].rstrip('/')
ORIGIN = os.environ.get('ITSM_AUTH_ORIGIN', BASE)
JAR = http.cookiejar.CookieJar()
CLIENT = build_opener(HTTPCookieProcessor(JAR))
CSRF = ''
PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII='
)


def request(path, body=None, method=None, *, raw=None, client=CLIENT, headers=None):
    outgoing = {'Origin': ORIGIN, 'Accept': 'application/json', **(headers or {})}
    if CSRF:
        outgoing['X-CSRF-Token'] = CSRF
    data = raw
    if body is not None:
        outgoing['Content-Type'] = 'application/json'
        data = json.dumps(body).encode()
    elif raw is not None:
        outgoing['Content-Type'] = 'application/octet-stream'
    req = Request(BASE + '/api/v1' + path, data=data, headers=outgoing, method=method)
    try:
        with client.open(req, timeout=15) as response:
            data = response.read()
            payload = json.loads(data) if 'application/json' in response.headers.get('Content-Type', '') else data
            return response.status, payload
    except HTTPError as error:
        return error.code, json.loads(error.read())


def main():
    global CSRF
    assert request('/inventory/config')[0] == 401
    status, signed_in = request('/auth/login', {
        'username': os.environ['ITSM_TEST_USERNAME'], 'password': os.environ['ITSM_TEST_PASSWORD'],
    })
    assert status == 200, (status, signed_in)
    CSRF = signed_in['csrfToken']
    status, config = request('/inventory/config')
    assert status == 200 and len(config['categories']) >= 14
    assert config['operations']['environment'] == 'test'
    assert config['operations']['purge']['permission'] == 'assets.edit'
    for resource, payload in [('statuses/probe', {'label': 'Probe', 'tone': ['ok']}),
                              ('rules/identification', {'separator': ['-']}),
                              ('rules/identification', {'order': {'a': 1}})]:
        assert request('/inventory/config/' + resource, payload, 'PUT')[0] == 422
        assert request('/inventory/config') == (200, config)
    suffix = uuid.uuid4().hex[:8]
    field_key = 'purchase' + suffix
    status, _ = request('/inventory/config/fields/' + field_key, {
        'label': 'Purchase date', 'type': 'date', 'default': '2026-01-01',
    }, 'PUT')
    assert status == 200
    form = next(row for row in config['categories'] if row['id'] == 'servidores')
    form['tech'].append(field_key)
    assert request('/inventory/config/categories/servidores', form, 'PUT')[0] == 200
    assert request('/inventory/config/rules/identification', {
        'siteCodes': {'Smoke site': 'DC'}, 'quickPad': 2,
    }, 'PUT')[0] == 200
    values = {'name': 'Public core smoke ' + suffix, 'category': 'servidores',
              'site': 'Smoke site', 'cost': '123.45', 'technical': {'ram': 32}}
    status, asset = request('/assets', values)
    assert status == 201, (status, asset)
    asset_id = asset['id']
    assert str(uuid.UUID(asset_id)) == asset_id
    assert asset['quickCode'] == 'DC-SER-01'
    assert asset['cost'] == '123.45' and asset['technical'] == {'ram': 32, field_key: '2026-01-01'}
    assert request('/assets/' + asset_id, {'id': str(uuid.uuid4())}, 'PATCH')[0] == 422
    assert request('/assets/' + asset_id, {'technical': {'ram': 'invalid'}}, 'PATCH')[0] == 422
    assert request('/assets/' + asset_id) == (200, asset)
    status, collision = request('/assets', {**values, 'quickCode': 'dc-ser-01'})
    assert status == 201 and collision['quickCode'] == 'dc-ser-02'
    cookie = '; '.join(f'{item.name}={item.value}' for item in JAR)
    def create_concurrent(index):
        code, created = request('/assets', {**values, 'name': f'Concurrent {suffix} {index}'},
                                client=build_opener(), headers={'Cookie': cookie})
        assert code == 201, (code, created)
        return created
    with ThreadPoolExecutor(max_workers=4) as workers:
        concurrent = list(workers.map(create_concurrent, range(4)))
    assert {row['quickCode'] for row in concurrent} == {f'DC-SER-{i:02d}' for i in range(3, 7)}
    before_page = request('/assets')
    assert request('/assets/batch', {'create': [
        {'name': 'Rollback', 'quickCode': 'ROLLBACK'},
        {'name': 'Rejected', 'quickCode': 'rollback'},
    ], 'update': []})[0] == 409
    assert request('/assets') == before_page
    assert request('/assets/' + asset_id + '/images/fov', method='PUT', raw=PNG)[0] == 422
    status, image = request('/assets/' + asset_id + '/images/photo', method='PUT', raw=PNG)
    assert status == 200 and image['role'] == 'photo'
    assert request('/assets/' + asset_id + '/images/photo') == (200, PNG)
    assert request('/assets/' + asset_id + '/images/photo', method='DELETE')[0] == 200
    assert request('/assets/' + asset_id + '/images/photo')[0] == 404
    status, archived = request('/assets/' + asset_id + '/archive', {'reason': 'Smoke archive'})
    assert status == 200 and archived['archived'] and archived['status'] == asset['status']
    status, restored = request('/assets/' + asset_id + '/restore', {}, 'POST')
    assert status == 200 and restored['archived'] is False and restored['id'] == asset_id
    status, cloned = request('/assets/' + asset_id + '/clone', {})
    assert status == 201 and cloned['id'] != asset_id and cloned['quickCode'] == 'DC-SER-07'
    assert cloned['technical'] == asset['technical']
    status, history = request('/assets/' + asset_id + '/history')
    # Media writes are not asset-history actions and clone records its row on the
    # new asset, so this source asset has exactly its own lifecycle trail.
    assert status == 200 and history['total'] == 3
    assert [row['action'] for row in history['items']] == ['created', 'archived', 'restored']
    assert [row['archivedNew'] for row in history['items']] == [False, True, False]
    assert {row['quickCodeNew'] for row in history['items']} == {'DC-SER-01'}
    sequences = [row['sequence'] for row in history['items']]
    assert sequences == sorted(set(sequences))
    assert request('/agent/chat', {'message': 'List inventory'})[0] == 503
    for row in [asset, collision, cloned, *concurrent]:
        target = '/assets/' + row['id']
        assert request(target + '/purge', {'confirm': True})[0] == 200
        assert request(target)[0] == 404
        assert request(target + '/history')[0] == 200
    assert request('/auth/logout', {}, 'POST')[0] == 200
    assert request('/assets')[0] == 401
    print('PASS F4 real HTTP catalog/forms/defaults/validation, sparse SQL assets, exact money, UUID, '
          'case-insensitive collisions, concurrent allocation, atomic rollback, media, clone/archive/restore, '
          'history after purge, unavailable model and session logout')


if __name__ == '__main__':
    main()
