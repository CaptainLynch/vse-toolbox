"""Synthetic checks for the public/persisted TDC failure boundary."""
import json

import pytest
from flask import Flask

from services.tdc_crawler import TDCCrawlerClient, TDCCrawlerError
from services.scheduled_archive_runner import _safe_exception_message
from web.app import _tdc_error_response


class Response:
    status_code = 200
    headers = {"Content-Type": "application/json"}

    def __init__(self, payload):
        self.payload = payload
        self.text = json.dumps(payload)
        self.content = self.text.encode()

    def json(self):
        return self.payload


class Session:
    def __init__(self, payload):
        self.response = Response(payload)

    def get(self, *args, **kwargs):
        return self.response


@pytest.mark.parametrize('payload,has_reason', [
    ({'code': 1}, False),
    ({'code': 1, 'error': {'message': 'Denied token=synthetic-secret'}}, True),
])
def test_export_failure_carries_safe_diagnostic_to_web_and_archive(tmp_path, payload, has_reason):
    with pytest.raises(TDCCrawlerError) as raised:
        TDCCrawlerClient(session=Session(payload), output_dir=tmp_path).export_sor()
    error = raised.value
    diagnostic = error.safe_diagnostic()
    assert diagnostic['source'] == 'tdc'
    assert diagnostic['operation'] == 'export'
    assert diagnostic['reportType'] == 'sor'
    assert diagnostic['stage'] == 'api-validation'
    assert diagnostic['upstreamHttpStatus'] == 200
    assert diagnostic['apiCode'] == 1
    assert diagnostic['reasonAvailable'] is has_reason
    assert len(diagnostic['requestId']) == 8
    assert not list(tmp_path.iterdir())
    archive = _safe_exception_message(error)
    assert 'stage=api-validation' in archive and 'api_code=1' in archive
    assert 'synthetic-secret' not in archive
    assert 'Denied' not in archive  # arbitrary upstream prose is never persisted
    assert 'fields=code' in archive
    with Flask(__name__).app_context():
        response, status = _tdc_error_response(error, 'sor', 'export')
        assert status == 502
        assert response.get_json()['error']['diagnostic'] == diagnostic
        assert 'synthetic-secret' not in response.get_data(as_text=True)


def test_diagnostic_allowlists_even_malformed_constructor_inputs():
    error = TDCCrawlerError('token=secret-value', stage='password=secret-value',
                            operation='secret-value', request_id='secret-value',
                            status_code=True, api_code={'secret-value': 'x'},
                            response_fields=('code', 'token', 'secret-value'), reason_available=True)
    text = json.dumps(error.safe_diagnostic()) + _safe_exception_message(error)
    assert 'secret-value' not in text and 'token' not in text
    assert error.safe_diagnostic()['responseFields'] == ['code']
    assert 'upstreamHttpStatus' not in error.safe_diagnostic()


def test_unexpected_json_success_is_not_written(tmp_path):
    with pytest.raises(TDCCrawlerError) as raised:
        TDCCrawlerClient(session=Session({'code': 200, 'data': []}), output_dir=tmp_path).export_sor()
    assert raised.value.safe_diagnostic()['stage'] == 'export-validation'
    assert raised.value.safe_diagnostic()['apiCode'] == 200
    assert not list(tmp_path.iterdir())


def test_project_options_never_substitute_display_name_for_missing_id():
    from web.app import _tdc_sor_project_options
    assert _tdc_sor_project_options([{'projectNo': 'MODEL-A'}]) == []


def test_nested_unrecognized_data_is_never_stringified(tmp_path):
    payload = {'code': {'private': 'unlabeled-secret'},
               'error': {'stack': 'unlabeled-secret'}, 'unlabeled-secret': 5}
    with pytest.raises(TDCCrawlerError) as raised:
        TDCCrawlerClient(session=Session(payload), output_dir=tmp_path).export_sor()
    assert 'unlabeled-secret' not in str(raised.value)
    assert 'unlabeled-secret' not in json.dumps(raised.value.safe_diagnostic())


@pytest.mark.parametrize('status_code', [429, 502, 503, 504])
def test_retryable_upstream_status_states_retry_semantics(status_code):
    """有界重试后仍是可重试上游状态 ⇒ 报"暂时不可用，可稍后重试"，不是配置错误。"""
    error = TDCCrawlerError(
        f'TDC HTTP {status_code} at /uwf/example/list',
        stage='status-validation',
        status_code=status_code,
        request_id='81f61e1f',
        operation='query',
        report_type='data_model',
    )
    diagnostic = error.safe_diagnostic()
    assert diagnostic['retryable'] is True

    with Flask(__name__).app_context():
        response, status = _tdc_error_response(error, 'data_model', 'query')
        assert status == 502
        body = response.get_json()['error']
        assert body['message'] == f'TDC 暂时不可用（{status_code}），请稍后重试；request_id=81f61e1f'
        assert body['diagnostic'] == diagnostic
        # 上游路径等运维细节只留在 diagnostic，不再进用户文案。
        assert '/uwf/example/list' not in body['message']


def test_non_retryable_status_keeps_legacy_message_shape():
    error = TDCCrawlerError(
        'TDC HTTP 400 at /uwf/example/list',
        stage='status-validation',
        status_code=400,
        request_id='abc12345',
        operation='query',
        report_type='sor',
    )
    assert 'retryable' not in error.safe_diagnostic()

    with Flask(__name__).app_context():
        response, status = _tdc_error_response(error, 'sor', 'query')
        assert status == 502
        body = response.get_json()['error']
        assert body['message'].startswith('TDC HTTP 400 at /uwf/example/list; TDC query failed')
