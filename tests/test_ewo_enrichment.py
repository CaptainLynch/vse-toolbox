from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core.ewo_export_jobs import EWOExportJobs, ExportJobConflict
from services.aras_crawler import EWOReportFilters
from services.ewo_enrichment import EWOEnrichment


def setup_service(tmp_path):
    jobs = EWOExportJobs(tmp_path / 'jobs.db')
    transport = Mock()
    transport.generate.return_value = 'B' * 32
    reader = Mock(return_value={'headers': ['EWO编号'], 'rows': [['E-1']]})
    service = EWOEnrichment(jobs, tmp_path / 'files', transport_factory=lambda c: transport, reader=reader)
    crawler = Mock()
    crawler.crawl_ewo_report_all.return_value = SimpleNamespace(
        rows=[{'id': 'A' * 32, '_no': 'E-1', 'state': 'OPEN'}],
        item_ids=['A' * 32], complete=True, truncated=False)
    return service, crawler, transport, reader


def test_prepare_only_queries_and_persists_context(tmp_path):
    service, crawler, transport, _ = setup_service(tmp_path)
    job = service.prepare('scope-a', crawler, EWOReportFilters(ewo_no='E-1'))
    assert job['state'] == 'queued'
    assert job['baseRecords'][0]['sourceItemId'] == 'A' * 32
    assert job['counts']['base_count'] == 1
    transport.generate.assert_not_called()
    context, snapshot = service.jobs.data(job['id'], 'scope-a')
    assert context['base_rows'][0]['id'] == 'A' * 32
    assert context['query_signature']
    assert snapshot is None
    with pytest.raises(ExportJobConflict):
        service.status(job['id'], 'scope-b')


def test_run_and_restart_download_do_not_regenerate(tmp_path):
    service, crawler, transport, reader = setup_service(tmp_path)
    job = service.prepare('scope-a', crawler, EWOReportFilters())
    transport.download.side_effect = ValueError('secret must not escape')
    state = service.run(job['id'], 'scope-a', crawler)
    assert state['state'] == 'generated'
    assert state['errorStage'] == 'download-or-parse'
    transport.download.side_effect = None
    service.jobs = EWOExportJobs(tmp_path / 'jobs.db')
    assert service.status(job['id'], 'scope-a')['errorStage'] == 'download-or-parse'
    state = service.run(job['id'], 'scope-a', crawler)
    assert state['state'] == 'parsed'
    assert state['counts']['matched_count'] == 1
    assert state['errorStage'] is None
    assert state['enhancementTime'] is not None
    assert transport.generate.call_count == 1
    service.run(job['id'], 'scope-a', crawler)
    assert transport.generate.call_count == 1
    assert reader.call_count == 1


def test_unknown_generation_never_reissued(tmp_path):
    service, crawler, transport, _ = setup_service(tmp_path)
    job = service.prepare('scope-a', crawler, EWOReportFilters())
    transport.generate.side_effect = TimeoutError('secret')
    result = service.run(job['id'], 'scope-a', crawler)
    assert result['state'] == 'generation_unknown'
    assert 'secret' not in str(result)
    assert service.prepare('scope-a', crawler, EWOReportFilters())['id'] == job['id']
    service.run(job['id'], 'scope-a', crawler)
    assert transport.generate.call_count == 1


def test_restore_after_restart_is_account_and_query_scoped_without_network(tmp_path):
    service, crawler, transport, _ = setup_service(tmp_path)
    filters = EWOReportFilters(ewo_no='E-1')
    job = service.prepare('scope-a', crawler, filters)
    service.run(job['id'], 'scope-a', crawler)
    service.jobs = EWOExportJobs(tmp_path / 'jobs.db')
    crawler.reset_mock()
    assert service.restore('scope-a', filters)['state'] == 'parsed'
    crawler.crawl_ewo_report_all.assert_not_called()
    with pytest.raises(ExportJobConflict):
        service.restore('scope-b', filters)
    with pytest.raises(ExportJobConflict):
        service.restore('scope-a', EWOReportFilters(ewo_no='different'))
    assert transport.generate.call_count == 1


def test_fixed_record_export_never_includes_other_matching_rows(tmp_path):
    service, crawler, transport, _ = setup_service(tmp_path)
    result = crawler.crawl_ewo_report_all.return_value
    result.rows.append({'id': 'C' * 32, '_no': 'E-2'})
    result.item_ids.append('C' * 32)
    filters = EWOReportFilters(model_info='SYNTHETIC')
    job = service.prepare('scope-a', crawler, filters, source_item_id='A' * 32)
    service.run(job['id'], 'scope-a', crawler)
    transport.generate.assert_called_once_with(['A' * 32])
    assert service.restore('scope-a', filters, source_item_id='A' * 32)['id'] == job['id']
    with pytest.raises(ExportJobConflict):
        service.restore('scope-a', filters, source_item_id='C' * 32)
    with pytest.raises(ValueError):
        service.prepare('scope-a', crawler, filters, source_item_id='D' * 32)


@pytest.mark.parametrize('change', [{'complete': False}, {'truncated': True}, {'item_ids': []},
                                  {'rows': []}, {'item_ids': ['not-an-id']}])
def test_invalid_selection_never_creates_export(tmp_path, change):
    service, crawler, transport, _ = setup_service(tmp_path)
    for key, value in change.items():
        setattr(crawler.crawl_ewo_report_all.return_value, key, value)
    with pytest.raises(ValueError):
        service.prepare('scope-a', crawler, EWOReportFilters())
    transport.generate.assert_not_called()
