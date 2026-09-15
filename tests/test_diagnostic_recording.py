import io
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pytest

from core import diagnostic_recording as dr


def test_recording_export_is_safe_and_shared(tmp_path):
    first = dr.Recorder(tmp_path)
    second = dr.Recorder(tmp_path)
    recording = first.start()
    with dr.recording_scope(second):
        with dr.operation('test.query'):
            dr.record_http('tdc', {'stage': 'request', 'status_code': 200,
                                 'request_headers': {'Cookie': 'SYNTHETIC_SECRET'},
                                 'response_body': 'SYNTHETIC_SECRET',
                                 'query': {'password': 'SYNTHETIC_SECRET', 'project': 'Project A'}})
    first.stop()
    with zipfile.ZipFile(io.BytesIO(first.export(recording['id']))) as bundle:
        joined = b''.join(bundle.read(n) for n in bundle.namelist())
        assert b'SYNTHETIC_SECRET' not in joined
        assert b'Project A' not in joined
        events = [json.loads(s) for s in bundle.read('events.jsonl').splitlines()]
        assert any(e['kind'] == 'http' for e in events)
        assert len({e['trace_id'] for e in events}) == 1
        assert {'summary.md', 'manifest.json', 'environment.json', 'events.jsonl', 'exceptions.json'} <= set(bundle.namelist())


def test_exception_frames_without_values_and_original_error(tmp_path):
    recorder = dr.Recorder(tmp_path)
    info = recorder.start()
    with dr.recording_scope(recorder), pytest.raises(ValueError, match='SYNTHETIC_SECRET'):
        with dr.operation('test.failure'):
            raise ValueError('SYNTHETIC_SECRET')
    recorder.stop()
    with zipfile.ZipFile(io.BytesIO(recorder.export(info['id']))) as archive:
        errors = json.loads(archive.read('exceptions.json'))
        assert errors and errors[0]['data']['exception_type'] == 'ValueError'
        assert errors[0]['data']['frames']
        assert b'SYNTHETIC_SECRET' not in archive.read('exceptions.json')


def test_expiry_capacity_and_invalid_download(tmp_path):
    now = [1000.0]
    recorder = dr.Recorder(tmp_path, clock=lambda: now[0], max_bytes=600)
    recorder.start(duration=1)
    now[0] += 2
    assert recorder.status()['active'] is False
    recorder.start()
    with dr.recording_scope(recorder):
        for _ in range(30):
            with dr.operation('test.capacity'):
                pass
    assert recorder.status()['active'] is False
    assert recorder.status()['latest']['reason'] == 'capacity'
    with pytest.raises(ValueError):
        recorder.export('../../secret')


def test_concurrent_traces_do_not_mix(tmp_path):
    recorder = dr.Recorder(tmp_path)
    info = recorder.start()
    def run(_):
        with dr.recording_scope(recorder), dr.operation('test.concurrent'):
            dr.record_http('tdc', {'status_code': 200})
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(run, range(12)))
    recorder.stop()
    with zipfile.ZipFile(io.BytesIO(recorder.export(info['id']))) as archive:
        events = [json.loads(s) for s in archive.read('events.jsonl').splitlines()]
    assert len({e['trace_id'] for e in events}) == 12
    assert len(events) == 36


def test_database_cache_archive_chain(tmp_path):
    from core.db_manager import DatabaseManager
    from core.archive_store import ArchiveStore
    from services.tdc_export_cache import TDCExportCache
    recorder = dr.Recorder(tmp_path / 'diagnostics')
    info = recorder.start()
    with dr.recording_scope(recorder), dr.operation('test.chain'):
        db = DatabaseManager(tmp_path / 'business.sqlite')
        with db.get_connection() as conn:
            conn.execute('CREATE TABLE synthetic (value TEXT)')
            conn.execute('INSERT INTO synthetic VALUES (?)', ('SYNTHETIC_SECRET',))
        cache = TDCExportCache()
        cache.get_or_create('synthetic', lambda: b'SYNTHETIC_SECRET')
        cache.get_or_create('synthetic', lambda: b'not-called')
        archive = ArchiveStore({'default': tmp_path / 'archive'})
        archive.write_bytes(b'SYNTHETIC_SECRET', source='tdc', report='sor', run_id=1, file_name='test.bin', artifact_type='raw')
    recorder.stop()
    with zipfile.ZipFile(io.BytesIO(recorder.export(info['id']))) as bundle:
        raw = bundle.read('events.jsonl')
        events = [json.loads(s) for s in raw.splitlines()]
    assert b'SYNTHETIC_SECRET' not in raw
    names = {e['name'] for e in events}
    assert 'db.transaction' in names
    assert 'cache.TDCExportCache.get_or_create' in names
    assert 'archive.ArchiveStore._write_chunks' in names
    assert len({e['trace_id'] for e in events}) == 1


def test_background_process_shares_recording(tmp_path):
    import subprocess
    import sys
    recorder = dr.Recorder(tmp_path)
    info = recorder.start()
    code = """
import sys
from core import diagnostic_recording as dr
dr._default = dr.Recorder(sys.argv[1])
@dr.observed('scheduler.synthetic', background=True)
def task():
    dr.record_http('tdc', {'status_code': 200})
task()
"""
    subprocess.run([sys.executable, '-c', code, str(tmp_path)], check=True)
    recorder.stop()
    with zipfile.ZipFile(io.BytesIO(recorder.export(info['id']))) as bundle:
        assert b'scheduler.synthetic' in bundle.read('events.jsonl')


def test_diagnostic_write_failure_never_changes_business_result(tmp_path, monkeypatch):
    recorder = dr.Recorder(tmp_path)
    recorder.start()
    with dr.recording_scope(recorder):
        def unavailable(*args, **kwargs):
            raise OSError('synthetic disk unavailable')
        monkeypatch.setattr(recorder, '_connect', unavailable)
        @dr.observed('test.business')
        def business():
            return 42
        assert business() == 42
        with pytest.raises(RuntimeError, match='original business failure'):
            with dr.operation('test.failure'):
                raise RuntimeError('original business failure')
    assert recorder.dropped >= 3


def test_old_context_cannot_write_into_new_recording(tmp_path):
    recorder = dr.Recorder(tmp_path)
    recorder.start()
    with dr.recording_scope(recorder):
        recorder.stop()
        new = recorder.start()
        dr.emit('mark', name='old.context')
    with zipfile.ZipFile(io.BytesIO(recorder.export(new['id']))) as bundle:
        assert b'old.context' not in bundle.read('events.jsonl')


def test_upstream_failure_keeps_code_and_safe_path(tmp_path):
    from services.tdc_crawler import TDCCrawlerError
    recorder = dr.Recorder(tmp_path)
    info = recorder.start()
    with dr.recording_scope(recorder), pytest.raises(TDCCrawlerError):
        with dr.operation('test.export'):
            dr.record_http('tdc', {'path': '/sp/sor/export', 'validation': 'rejected-json-response'})
            raise TDCCrawlerError('SYNTHETIC_SECRET', stage='api-validation', api_code=1, status_code=200)
    with zipfile.ZipFile(io.BytesIO(recorder.export(info['id']))) as bundle:
        events = [json.loads(s) for s in bundle.read('events.jsonl').splitlines()]
        assert any(e['data'].get('api_code') == 1 for e in events)
        assert any(e['data'].get('path') == '/sp/sor/export' for e in events)
        assert b'SYNTHETIC_SECRET' not in bundle.read('events.jsonl')


def test_retention_discards_only_old_recordings(tmp_path):
    now = [1000.0]
    recorder = dr.Recorder(tmp_path, clock=lambda: now[0])
    old = recorder.start()
    recorder.stop()
    now[0] += 8 * 86400
    new = recorder.start()
    assert recorder.status()['latest']['id'] == new['id']
    with pytest.raises(KeyError):
        recorder.export(old['id'])


def test_expired_export_and_process_build_identity(tmp_path, monkeypatch):
    now = [1000.0]
    recorder = dr.Recorder(tmp_path, clock=lambda: now[0])
    monkeypatch.setattr(dr, 'build_identity', lambda: 'synthetic-build')
    identity = recorder.start(duration=1)['id']
    with dr.recording_scope(recorder):
        dr.emit('mark', name='test.mark')
    now[0] += 2
    with zipfile.ZipFile(io.BytesIO(recorder.export(identity))) as bundle:
        assert json.loads(bundle.read('manifest.json'))['reason'] == 'expired'
        assert json.loads(bundle.read('events.jsonl'))['build'] == 'synthetic-build'


def test_native_error_code_survives_without_native_error_message(tmp_path):
    recorder = dr.Recorder(tmp_path)
    identity = recorder.start()['id']
    with dr.recording_scope(recorder), pytest.raises(RuntimeError):
        with dr.operation('native.synthetic'):
            try:
                raise OSError(5, 'SYNTHETIC_SECRET')
            except OSError as cause:
                raise RuntimeError('SYNTHETIC_SECRET') from cause
    with zipfile.ZipFile(io.BytesIO(recorder.export(identity))) as bundle:
        data = json.loads(bundle.read('exceptions.json'))[0]['data']
        assert data['causes'][1]['errno'] == 5
        assert b'SYNTHETIC_SECRET' not in bundle.read('exceptions.json')
