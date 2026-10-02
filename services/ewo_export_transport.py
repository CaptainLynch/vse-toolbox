"""EWO official export generation without automatic retries or redirects."""
import re
import json
from xml.etree import ElementTree as ET

from services.aras_crawler import SOAP_ROUTE, TOKEN_ROUTE, _soap_envelope, ArasCrawlerClient


class EWOExportError(ValueError):
    """A credential-safe export failure; generation outcome may be unknown."""


def _item_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-fA-F]{32}', value):
        raise EWOExportError('Invalid source reference')
    return value.upper()


class EWOExportTransport:
    def __init__(self, client):
        self.client = client

    def _post(self, action, payload):
        try:
            response = self.client.session.post(
                self.client._url(SOAP_ROUTE), data=payload,
                headers=self.client._headers(action, 'text/xml; charset=UTF-8'),
                timeout=(self.client.timeout, max(self.client.timeout, 240)),
                allow_redirects=False,
            )
            if response.status_code != 200:
                raise EWOExportError('EWO export HTTP response rejected')
            text = response.text
            if len(text) > 4 * 1024 * 1024 or '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
                raise EWOExportError('EWO export XML rejected')
            return text
        except Exception:
            raise EWOExportError('EWO export request failed; outcome requires inspection') from None

    def generate(self, item_ids):
        if not isinstance(item_ids, (list, tuple)) or not 1 <= len(item_ids) <= 5000:
            raise EWOExportError('Invalid selection size')
        ids = [_item_id(value) for value in item_ids]
        if len(set(ids)) != len(ids):
            raise EWOExportError('Duplicate source reference')
        selected = ','.join("'" + value + "'" for value in ids)
        payload = _soap_envelope(
            '<ApplyMethod><Item type="Method" action="sgmw_mwt_downloadEworeportCall">'
            f'<ewoids>{selected}</ewoids></Item></ApplyMethod>'
        )
        text = self._post('ApplyMethod', payload)
        try:
            root = ET.fromstring(text)
            refs = []
            for record in root.iter():
                if record.tag.split('}')[-1] != 'Item' or record.get('type') != 'sgmw_outputFileRecord':
                    continue
                for child in record:
                    if child.tag.split('}')[-1] != '_file':
                        continue
                    value = (child.text or '').strip()
                    if not value:
                        nested = next((n for n in child if n.get('type') == 'File'), None)
                        value = nested.get('id', '') if nested is not None else ''
                    refs.append(_item_id(value))
            if len(refs) != 1:
                raise EWOExportError('EWO export file reference unavailable')
            return refs[0]
        except (ValueError, ET.ParseError):
            raise EWOExportError('EWO export response rejected') from None

    def download(self, file_id, destination):
        from pathlib import Path
        from urllib.parse import urlsplit
        from zipfile import ZipFile
        from io import BytesIO
        from services.aras_crawler import _atomic_write_download

        file_id = _item_id(file_id)
        params = {}
        try:
            text = self._post('ApplyItem', self.client._build_ncr_vault_metadata_payload(file_id))
            location = self.client.parse_ncr_vault_metadata_response(text, file_id)
            base, vault = urlsplit(self.client.base_url), urlsplit(location.vault_url)

            def origin(url):
                return url.scheme, url.hostname, url.port or (443 if url.scheme == 'https' else 80)
            if (origin(base) != origin(vault) or vault.scheme not in ('http', 'https')
                    or vault.username or vault.password or vault.query or vault.fragment
                    or not vault.path.lower().endswith('/vault/vaultserver.aspx')):
                raise EWOExportError('Export file origin rejected')
            params = {
                'dbName': 'InnovatorSolutions', 'fileId': file_id,
                'fileName': location.file_name, 'vaultId': _item_id(location.vault_id),
                'token': self._download_token(file_id),
                'contentDispositionAttachment': '1',
            }
            response = self.client.session.get(
                location.vault_url, params=params,
                headers={**self.client._browser_headers('*/*'), **self.client.headers},
                timeout=(self.client.timeout, 240), allow_redirects=False,
            )
            content = response.content
            mime = response.headers.get('Content-Type', '').split(';')[0].lower()
            if (response.status_code != 200 or mime not in (
                    'application/octet-stream',
                    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
                    or not content or len(content) > 64 * 1024 * 1024):
                raise EWOExportError('Export download rejected')
            with ZipFile(BytesIO(content)) as archive:
                if ('[Content_Types].xml' not in archive.namelist()
                        or sum(info.file_size for info in archive.infolist()) > 96 * 1024 * 1024):
                    raise EWOExportError('Export workbook rejected')
            return _atomic_write_download(Path(destination) / (file_id + '.xlsx'), content)
        except Exception:
            raise EWOExportError('EWO export download failed') from None
        finally:
            # Do not retain the token on the transport object or in persistent state.
            params = {}

    def _download_token(self, file_id):
        response = self.client.session.post(
            self.client._url(TOKEN_ROUTE),
            data=json.dumps({'param': {'fileId': file_id}}, separators=(',', ':')),
            headers=self.client._headers('GetFileDownloadToken', 'application/json; charset=UTF-8'),
            timeout=(self.client.timeout, 240), allow_redirects=False,
        )
        if response.status_code != 200 or len(response.text) > 65536:
            raise EWOExportError('Export download token rejected')
        return ArasCrawlerClient.parse_download_token_response(response.text)
