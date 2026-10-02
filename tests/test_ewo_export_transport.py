import pytest
from services.ewo_export_transport import EWOExportTransport, EWOExportError


class Response:
    status_code = 200
    headers = {'Content-Type': 'text/xml'}
    def __init__(self, text=''):
        self.text = text


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class Client:
    base_url = 'https://aras.example/innovatorserver'
    timeout = 30
    def __init__(self, session):
        self.session = session
    def _url(self, route):
        return self.base_url + '/' + route
    def _headers(self, action, mime):
        return {'SOAPAction': action, 'Content-Type': mime}


def test_generate_selected_ids_once_with_official_method():
    response = Response('<Result><Item type="sgmw_outputFileRecord"><_file>' + 'B'*32 + '</_file></Item></Result>')
    session = Session([response])
    result = EWOExportTransport(Client(session)).generate(['A' * 32])
    assert result == 'B' * 32
    payload = session.calls[0][1]['data']
    assert 'sgmw_mwt_downloadEworeportCall' in payload
    assert "'" + 'A'*32 + "'" in payload
    assert session.calls[0][1]['allow_redirects'] is False


def test_generation_timeout_is_not_retried_or_leaked():
    session = Session([TimeoutError('secret-source-text')])
    with pytest.raises(EWOExportError) as caught:
        EWOExportTransport(Client(session)).generate(['A'*32])
    assert len(session.calls) == 1
    assert 'secret-source-text' not in str(caught.value)


@pytest.mark.parametrize('text', ['<Result/>', '<Result><Item type="other"><_file>'+'B'*32+'</_file></Item></Result>', '<broken'])
def test_invalid_generation_response_rejected(text):
    with pytest.raises(EWOExportError):
        EWOExportTransport(Client(Session([Response(text)]))).generate(['A'*32])


def test_generation_redirect_rejected():
    response = Response('')
    response.status_code = 302
    with pytest.raises(EWOExportError):
        EWOExportTransport(Client(Session([response]))).generate(['A'*32])


def test_download_rejects_foreign_origin_before_token_request(tmp_path):
    from types import SimpleNamespace
    client = Client(Session([Response('<metadata/>')]))
    client._build_ncr_vault_metadata_payload = lambda file_id: '<metadata/>'
    client.parse_ncr_vault_metadata_response = lambda text, file_id: SimpleNamespace(
        vault_url='https://other.example/vault/vaultserver.aspx', file_name='file.xlsx', vault_id='C'*32)
    client.get_file_download_token = lambda *a, **k: pytest.fail('must not request token')
    with pytest.raises(EWOExportError):
        EWOExportTransport(client).download('B'*32, tmp_path)


def test_download_uses_fresh_token_no_redirect_and_fixed_local_filename(tmp_path):
    from types import SimpleNamespace
    import io
    import zipfile
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as z:
        z.writestr('[Content_Types].xml', '<Types/>')
    session = Session([Response('<metadata/>'), Response('{"d":"temporary-token"}')])
    observed = []
    def get(url, **kwargs):
        observed.append((url, kwargs))
        return SimpleNamespace(status_code=200, headers={'Content-Type': 'application/octet-stream'}, content=output.getvalue())
    session.get = get
    client = Client(session)
    client._build_ncr_vault_metadata_payload = lambda file_id: '<metadata/>'
    client.parse_ncr_vault_metadata_response = lambda text, file_id: SimpleNamespace(
        vault_url='https://aras.example/innovatorserver/vault/vaultserver.aspx', file_name='../../server.xlsx', vault_id='C'*32)
    client.get_file_download_token = lambda *a, **k: pytest.fail('must use guarded token transport')
    client._browser_headers = lambda accept: {'Accept': accept}
    client.headers = {}
    path = EWOExportTransport(client).download('B'*32, tmp_path)
    assert path.parent == tmp_path
    assert path.name == 'B'*32 + '.xlsx'
    assert observed[0][1]['allow_redirects'] is False
    assert observed[0][1]['params']['token'] == 'temporary-token'
    assert len(session.calls) == 2
    assert session.calls[1][1]['allow_redirects'] is False


def test_download_token_redirect_is_not_followed():
    response = Response('{"d":"do-not-use"}')
    response.status_code = 302
    session = Session([response])
    with pytest.raises(EWOExportError):
        EWOExportTransport(Client(session))._download_token('A' * 32)
    assert session.calls[0][1]['allow_redirects'] is False
