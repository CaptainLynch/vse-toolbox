import io
import json
import zipfile
import uuid

import pytest
from flask import Flask, jsonify
from core.diagnostic_recording import Recorder
from web.diagnostics import install_diagnostics


@pytest.fixture
def setup(tmp_path):
    app = Flask(__name__)
    recorder = Recorder(tmp_path)
    install_diagnostics(app, recorder)
    @app.post('/api/synthetic')
    def synthetic():
        return jsonify(ok=False, error={'diagnostic': {'apiCode': 1}, 'message': 'SYNTHETIC_SECRET'}), 502
    return app.test_client(), recorder


def test_capture_request_business_failure_and_export(setup):
    client, recorder = setup
    assert client.post('/api/diagnostics/start', json={}).status_code == 200
    trace = uuid.uuid4().hex
    response = client.post('/api/synthetic', headers={'X-VSE-Trace-ID': trace}, json={'password': 'SYNTHETIC_SECRET'})
    assert response.status_code == 502
    assert response.headers['X-VSE-Trace-ID'] == trace
    assert client.post('/api/diagnostics/stop', json={}).status_code == 200
    identity = recorder.status()['latest']['id']
    response = client.get('/api/diagnostics/bundles/' + identity)
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.data)) as bundle:
        events = bundle.read('events.jsonl')
        assert b'SYNTHETIC_SECRET' not in events
        assert trace.encode() in events
        assert any(e['data'].get('apiCode') == 1 for e in map(json.loads, events.splitlines()))


@pytest.mark.parametrize('method,path', [('get',''),('post','/start'),('post','/stop'),('post','/events'),('post','/mark'),('get','/bundles/'+'a'*32)])
def test_all_diagnostic_routes_are_local_only(setup, method, path):
    client, _ = setup
    send = getattr(client, method)
    assert send('/api/diagnostics'+path, environ_overrides={'REMOTE_ADDR':'192.0.2.1'}).status_code == 403
    assert send('/api/diagnostics'+path, headers={'Origin':'https://evil.test'}).status_code == 403


def test_frontend_input_bounded_and_unknown_fields_not_recorded(setup):
    client, recorder = setup
    client.post('/api/diagnostics/start', json={})
    assert client.post('/api/diagnostics/events', json={'kind':'frontend_error','line':15,'message':'SYNTHETIC_SECRET'}).status_code == 202
    assert client.post('/api/diagnostics/events', data='x'*5000, content_type='application/json').status_code == 413
    assert client.post('/api/diagnostics/events', json={'kind':'arbitrary'}).status_code == 400
    with zipfile.ZipFile(io.BytesIO(recorder.export(recorder.status()['latest']['id']))) as bundle:
        assert b'SYNTHETIC_SECRET' not in bundle.read('events.jsonl')
