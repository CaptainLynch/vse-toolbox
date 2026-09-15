"""Behavioral contract for durable EWO generation ownership."""
import sqlite3

import pytest

from core.ewo_export_jobs import EWOExportJobs, ExportJobConflict


def test_generation_claim_is_exclusive_and_unknown_is_not_retryable(tmp_path):
    path = tmp_path / 'jobs.db'
    a, b = EWOExportJobs(path), EWOExportJobs(path)
    job = a.create('scope-a', ['A' * 32], now=10)
    claimed = a.claim(job['id'], 'scope-a', now=11, lease_seconds=10)
    with pytest.raises(ExportJobConflict):
        b.claim(job['id'], 'scope-a', now=12)
    assert b.recover(now=22) == 1
    assert a.get(job['id'], 'scope-a')['state'] == 'generation_unknown'
    with pytest.raises(ExportJobConflict):
        a.claim(job['id'], 'scope-a', now=23)
    with pytest.raises(ExportJobConflict):
        a.generated(job['id'], 'scope-a', claimed['lease_token'], 'B' * 32, now=23)


def test_file_reference_recovery_never_regenerates(tmp_path):
    a = EWOExportJobs(tmp_path / 'jobs.db')
    job = a.create('scope-a', ['A' * 32], now=10)
    run = a.claim(job['id'], 'scope-a', now=11)
    a.generated(job['id'], 'scope-a', run['lease_token'], 'B' * 32, now=12)
    download = a.claim(job['id'], 'scope-a', now=13, lease_seconds=10)
    assert download['state'] == 'downloading'
    assert download['file_id'] == 'B' * 32
    a.recover(now=24)
    assert a.get(job['id'], 'scope-a')['state'] == 'generated'
    assert a.claim(job['id'], 'scope-a', now=25)['state'] == 'downloading'


def test_scope_and_lease_are_required_for_completion(tmp_path):
    a = EWOExportJobs(tmp_path / 'jobs.db')
    job = a.create('scope-a', ['A' * 32], now=10)
    with pytest.raises(ExportJobConflict):
        a.get(job['id'], 'scope-b')
    run = a.claim(job['id'], 'scope-a', now=11)
    with pytest.raises(ExportJobConflict):
        a.generated(job['id'], 'scope-a', 'wrong', 'B' * 32, now=12)
    a.generated(job['id'], 'scope-a', run['lease_token'], 'B' * 32, now=12)
    download = a.claim(job['id'], 'scope-a', now=13)
    a.parsed(job['id'], 'scope-a', download['lease_token'], 'snapshot-1', now=14)
    assert a.get(job['id'], 'scope-a')['snapshot_ref'] == 'snapshot-1'
    with pytest.raises(ExportJobConflict):
        a.claim(job['id'], 'scope-a', now=15)


def test_active_input_deduplicates_and_records_no_auth_material(tmp_path):
    path = tmp_path / 'jobs.db'
    a = EWOExportJobs(path)
    first = a.create('scope-a', ['A' * 32, 'B' * 32], now=10)
    second = a.create('scope-a', ['B' * 32, 'A' * 32], now=11)
    assert first['id'] == second['id']
    assert a.create('scope-b', ['A' * 32, 'B' * 32], now=12)['id'] != first['id']
    with sqlite3.connect(path) as c:
        columns = [row[1] for row in c.execute('PRAGMA table_info(ewo_export_jobs)')]
    assert not {'password', 'cookie', 'download_token', 'headers'} & set(columns)


@pytest.mark.parametrize('ids', [[], ['bad'], ['A' * 32, 'A' * 32], ['A' * 32] * 5001])
def test_rejects_invalid_selection(tmp_path, ids):
    a = EWOExportJobs(tmp_path / 'jobs.db')
    with pytest.raises(ValueError):
        a.create('scope-a', ids)
