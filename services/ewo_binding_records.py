"""Versioned EWO records; legacy business-number identity remains untouched."""
from core.ewo_binding_v2 import identified_ewo_v2_rows, normalize_ewo_v2_rule
from services.project_status_records import build_aggregate_candidate_values


def attach_ewo_source_ids(result):
    if len(result.rows) != len(result.item_ids):
        raise ValueError('EWO source identity is incomplete')
    rows = [{**row, '_source_item_id': item_id} for row, item_id in zip(result.rows, result.item_ids)]
    return [row for _, row in identified_ewo_v2_rows(rows)]


def ewo_v2_candidate_values(records, mapping, rule):
    normalized = normalize_ewo_v2_rule(dict(rule))
    if normalized['bindingMode'] == 'record_set' and set(mapping) - {'note'}:
        raise ValueError('EWO record sets cannot map scalar owner or planned date')
    values = build_aggregate_candidate_values(records, mapping)
    # Missing/empty source content is not authority to clear local fields.
    return {key: value for key, value in values.items() if value is not None and value != ''}
