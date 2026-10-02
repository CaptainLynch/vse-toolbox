from unittest.mock import Mock

from flask import Flask

from core.domain_identity import DomainSessionRegistry
from core.ewo_export_jobs import ExportJobConflict
from services.aras_auth import DEFAULT_ARAS_BASE_URL
from web.app import _local_web_mutation_error
from web.ewo_enrichment import register_ewo_enrichment


PREFIX = '/api/aras/ewo/enrichment/jobs'
ID = 'a' * 32


def fixture():
    app = Flask(__name__)
    registry = DomainSessionRegistry()
    service = Mock()
    service.prepare.return_value = {'id': ID, 'state': 'queued'}
    service.status.return_value = {'id': ID, 'state': 'queued'}
    service.run.return_value = {'id': ID, 'state': 'parsed'}
    factory = Mock()
    register_ewo_enrichment(app, service, registry, _local_web_mutation_error, crawler_factory=factory)
    return app.test_client(), registry, service, factory


def bind(registry, user='alice'):
    registry.mark_authenticated('aras', object(), principal=user, source_root=DEFAULT_ARAS_BASE_URL)


def test_new_endpoints_reject_unbound_and_nonlocal_callers():
    client, registry, service, _ = fixture()
    registry.mark_authenticated('aras', object())
    assert client.post(PREFIX, json={}).status_code == 401
    bind(registry)
    assert client.post(PREFIX, json={}, environ_overrides={'REMOTE_ADDR': '10.0.0.2'}).status_code == 403
    assert client.post(PREFIX, json={}, headers={'Origin': 'https://attacker.invalid'}).status_code == 403
    service.prepare.assert_not_called()


def test_prepare_uses_bound_session_and_explicit_filters_only():
    client, registry, service, factory = fixture()
    bind(registry)
    response = client.post(PREFIX, json={'filters': {'ewo_no': 'E-1'}})
    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'no-store'
    session, scope = registry.bound_session('aras', DEFAULT_ARAS_BASE_URL)
    assert factory.call_args.kwargs['session'] is session
    assert service.prepare.call_args.args[0] == scope
    service.run.assert_not_called()
    for body in [{'base_url': 'http://elsewhere'}, {'filters': {'bad': 'x'}},
                 {'filters': {'ewo_no': {'bad': 'x'}}}]:
        assert client.post(PREFIX, json=body).status_code == 400


def test_foreign_job_cannot_start_network_operation():
    client, registry, service, factory = fixture()
    bind(registry, 'bob')
    service.status.side_effect = ExportJobConflict('secret')
    response = client.post(PREFIX + '/' + ID + '/run', json={})
    assert response.status_code == 409
    assert 'secret' not in response.text
    service.run.assert_not_called()
    factory.assert_not_called()


def test_account_switch_during_read_does_not_return_previous_data():
    client, registry, service, _ = fixture()
    bind(registry)

    def switched(*args):
        bind(registry, 'bob')
        return {'private': 'alice-data'}

    service.status.side_effect = switched
    response = client.post(PREFIX + '/' + ID + '/status', json={})
    assert response.status_code == 401
    assert 'alice-data' not in response.text
