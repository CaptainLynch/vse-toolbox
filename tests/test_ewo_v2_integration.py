import pytest

from services.project_status_connectors import _snapshot
from services.project_status_records import compute_config_signature
from services.project_status_sync_runner import SyncBindingContext
from services.project_status_updates import ProjectStatusPolicyError, ProjectStatusUpdateService


def rule(mode='record_set'):
    result = {'contractVersion': '2', 'reportType': 'ewo', 'bindingMode': mode,
              'aggregate': mode == 'record_set', 'modelInfo': 'SYNTHETIC'}
    if mode == 'single_record':
        result['sourceItemId'] = 'A' * 32
    return result


def context(mode='record_set', mapping=None):
    return SyncBindingContext(
        binding_id=1, deliverable_id='VPI-T2-D3', phase_id='VPI-T2', source_type='aras',
        external_key='A' * 32 if mode == 'single_record' else None, match_rule=rule(mode),
        mapping=mapping or {'note': 'summary'}, cursor={}, expected_deliverable_updated_at='v1',
        run_id=1, credential_ref='domain')


def test_version_and_fixed_record_are_part_of_signature():
    legacy = {'reportType': 'ewo', 'aggregate': True, 'modelInfo': 'SYNTHETIC'}
    assert compute_config_signature('aras', rule()) != compute_config_signature('aras', legacy)
    first = rule('single_record')
    second = {**first, 'sourceItemId': 'B' * 32}
    assert compute_config_signature('aras', first) != compute_config_signature('aras', second)


def test_set_includes_blank_business_numbers_and_never_writes_scalar_fields():
    rows = [{'_source_item_id': 'A' * 32, '_no': '', 'summary': 'pending', 'engineer': 'owner'}]
    snapshot = _snapshot(context(), rows, [])
    assert snapshot.match_state == 'matched'
    assert snapshot.candidates[0].field_values == {'note': 'pending'}
    with pytest.raises(ValueError):
        _snapshot(context(mapping={'owner': 'engineer'}), rows, [])
    two = _snapshot(context(), rows + [{'_source_item_id': 'B' * 32, '_no': '', 'summary': 'pending'}], [])
    assert two.candidates[0].external_key != snapshot.candidates[0].external_key


def test_single_does_not_follow_new_revision_with_same_business_number():
    rows = [{'_source_item_id': 'B' * 32, '_no': 'E-1', 'summary': 'pending'}]
    assert _snapshot(context('single_record'), rows, []).match_state == 'not_found'
    rows[0]['_source_item_id'] = 'A' * 32
    assert _snapshot(context('single_record'), rows, []).candidates[0].external_key == 'A' * 32


def test_absent_or_empty_note_does_not_clear_project_note():
    for extra in ({}, {'summary': ''}, {'summary': None}):
        snapshot = _snapshot(context(), [{'_source_item_id': 'A' * 32, **extra}], [])
        assert snapshot.candidates[0].field_values == {}


def test_migration_is_explicit_disabled_and_old_client_cannot_edit(tmp_db):
    service = ProjectStatusUpdateService(tmp_db)
    payload = {'mode': 'hybrid', 'enabled': False, 'matchRule': rule(),
               'mapping': {'note': 'summary'}, 'fieldAuthority': {'note': 'automatic'}}
    with pytest.raises(ProjectStatusPolicyError):
        service.update_update_policy('VPI-T2-D3', payload)
    payload['bindingContractVersion'] = '2'
    saved = service.update_update_policy('VPI-T2-D3', payload)
    assert saved['matchRule']['contractVersion'] == '2'
    with pytest.raises(ProjectStatusPolicyError):
        service.update_update_policy('VPI-T2-D3', {'intervalMinutes': 30})
    with pytest.raises(ProjectStatusPolicyError):
        service.update_update_policy('VPI-T2-D3', {
            'bindingContractVersion': '2', 'fieldAuthority': {'owner': 'automatic'},
            'mapping': {'owner': 'engineer', 'note': 'summary'}})


def test_discovery_and_execution_use_same_id_set_and_new_evidence(tmp_db):
    from services.project_status_discovery import MappingDiscoveryService
    service = ProjectStatusUpdateService(tmp_db)
    payload = {'bindingContractVersion': '2', 'mode': 'hybrid', 'enabled': False,
               'matchRule': rule(), 'mapping': {'note': 'summary'},
               'fieldAuthority': {'note': 'automatic'}, 'credentialRef': 'domain'}
    service.update_update_policy('VPI-T2-D3', payload)
    with pytest.raises(ProjectStatusPolicyError):
        service.update_update_policy('VPI-T2-D3', {'bindingContractVersion': '2', 'enabled': True})
    rows = [{'_source_item_id': 'A' * 32, '_no': '', 'summary': 'pending'}]
    discovery = MappingDiscoveryService(tmp_db)
    for _ in range(2):
        result = discovery.observe('VPI-T2-D3', 'aras', rows, aggregate=True, match_rule=rule())
    assert result['candidateCount'] == 1
    assert result['stability']['ready'] is True
    assert result['candidates'][0]['externalKey'] == 'A' * 32
    assert service.update_update_policy('VPI-T2-D3', {
        'bindingContractVersion': '2', 'enabled': True})['enabled'] is True


def test_stale_legacy_validation_cannot_overwrite_migrated_rule(tmp_db, monkeypatch):
    service = ProjectStatusUpdateService(tmp_db)
    legacy = tmp_db.get_project_status_update_policy('VPI-T2-D3')
    payload = {'bindingContractVersion': '2', 'mode': 'hybrid', 'enabled': False,
               'matchRule': rule(), 'mapping': {'note': 'summary'},
               'fieldAuthority': {'note': 'automatic'}}
    service.update_update_policy('VPI-T2-D3', payload)
    original = tmp_db.get_project_status_update_policy
    monkeypatch.setattr(tmp_db, 'get_project_status_update_policy', lambda _: legacy)
    with pytest.raises(ProjectStatusPolicyError, match='validation failed'):
        service.update_update_policy('VPI-T2-D3', {'intervalMinutes': 30})
    monkeypatch.setattr(tmp_db, 'get_project_status_update_policy', original)
    assert service.get_update_policy('VPI-T2-D3')['matchRule']['contractVersion'] == '2'


def test_empty_v2_note_preview_matches_no_clear_execution(tmp_db):
    from services.project_status_discovery import MappingDiscoveryService
    service = ProjectStatusUpdateService(tmp_db)
    service.update_update_policy('VPI-T2-D3', {
        'bindingContractVersion': '2', 'mode': 'hybrid', 'enabled': False,
        'matchRule': rule(), 'mapping': {'note': 'summary'},
        'fieldAuthority': {'note': 'automatic'}, 'credentialRef': 'domain'})
    with tmp_db.get_connection() as conn:
        conn.execute("UPDATE project_status_deliverables SET remark='keep-note' WHERE id='VPI-T2-D3'")
    discovery = MappingDiscoveryService(tmp_db)
    rows = [{'_source_item_id': 'A' * 32, '_no': '', 'summary': ''}]
    for _ in range(2):
        discovery.observe('VPI-T2-D3', 'aras', rows, aggregate=True, match_rule=rule())
    service.update_update_policy('VPI-T2-D3', {'bindingContractVersion': '2', 'enabled': True})
    preview = discovery.candidate_preview('VPI-T2-D3')
    assert preview['stability']['ready'] is True
    assert preview['differences'][0]['changed'] is False
    assert _snapshot(context(), rows, []).candidates[0].field_values == {}


def test_base_analysis_keeps_distinct_internal_ids_with_same_or_blank_number():
    from services.project_status_deliverable_analysis import normalize_analysis_rows
    for number in ('', 'E-1'):
        rows = [{'_source_item_id': 'A' * 32, '_no': number},
                {'_source_item_id': 'B' * 32, '_no': number}]
        first = normalize_analysis_rows(rows, source_type='aras')
        assert len(first) == 2
        rows[0]['_subject'] = 'Changed title'
        second = normalize_analysis_rows(rows, source_type='aras')
        assert first[0]['item_key'] == second[0]['item_key']


def test_schema_upgrade_preserves_legacy_policy_and_blocks_old_runtime(tmp_db, monkeypatch):
    import sqlite3
    import core.db_manager as database_module
    service = ProjectStatusUpdateService(tmp_db)
    old_rule = {'reportType': 'ewo', 'aggregate': True, 'modelInfo': 'SYNTHETIC'}
    service.update_update_policy('VPI-T2-D3', {'matchRule': old_rule})
    before = service.get_update_policy('VPI-T2-D3')
    with tmp_db.get_connection() as conn:
        conn.execute('PRAGMA user_version=13')
    tmp_db.init_database()
    after = service.get_update_policy('VPI-T2-D3')
    assert after['matchRule'] == old_rule
    assert after['fieldAuthority'] == before['fieldAuthority']
    monkeypatch.setattr(database_module, 'CURRENT_SCHEMA_VERSION', 13)
    with pytest.raises(sqlite3.DatabaseError, match='unsupported schema version 14'):
        tmp_db.init_database()
