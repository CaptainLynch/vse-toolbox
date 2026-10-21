import hashlib

import pytest
import core.repos.project_status as repo
from tests.conftest import bprime_audit_case  # noqa: F401  (pytest fixture 参数注入)


def _binding(**changes):
    row = dict(mode="hybrid", enabled=1, external_key="状态",
               interval_minutes=30, credential_ref="synthetic-ref-a",
               mapping_json='{"owner":"currentApprover"}',
               match_rule_json="null", sync_config_revision=3)
    row.update(changes)
    return row


def _digest(binding, authorities=(), deliverable_id="VPI-T2-D5"):
    return repo.compute_policy_config_digest(deliverable_id, binding, authorities)


def _read(conn, did):
    binding = conn.execute(
        "SELECT * FROM project_status_update_bindings WHERE deliverable_id = ?",
        (did,)).fetchone()
    authorities = conn.execute(
        "SELECT * FROM project_status_field_authority WHERE deliverable_id = ?",
        (did,)).fetchall()
    return binding, authorities


CANONICAL = (
    rb'{"binding":{"enabled":1,"external_key":"\u72b6\u6001",'
    rb'"has_credential_ref":true,"interval_minutes":30,'
    rb'"mapping_json":"{\"owner\":\"currentApprover\"}",'
    rb'"match_rule_json":"null","mode":"hybrid","sync_config_revision":3},'
    rb'"field_authority":[{"authority":"manual","field_name":"actual_date"},'
    rb'{"authority":"automatic","field_name":"owner"},'
    rb'{"authority":"manual","field_name":"planned_date"},'
    rb'{"authority":"manual","field_name":"progress"},'
    rb'{"authority":"manual","field_name":"remark"},'
    rb'{"authority":"manual","field_name":"status"}],"v":1}'
)


def test_digest_fixed_vector():
    binding = _binding()
    rows = [{"field_name": "owner", "authority": "automatic"}]
    actual = _digest(binding, rows)
    assert actual == "cfgd1:" + hashlib.sha256(CANONICAL).hexdigest()
    assert binding == _binding()
    assert rows == [{"field_name": "owner", "authority": "automatic"}]
    for ref in ("synthetic-ref-b", " "):
        assert _digest(_binding(credential_ref=ref), rows) == actual
    assert (_digest(_binding(credential_ref=None), rows)
            == _digest(_binding(credential_ref=""), rows) != actual)
    for key, value in (("mode", "manual"), ("enabled", 0),
                       ("external_key", "K2"), ("interval_minutes", 31),
                       ("mapping_json", '{"note":"x"}'),
                       ("match_rule_json", "{}"), ("sync_config_revision", 4)):
        assert _digest(_binding(**{key: value}), rows) != actual


def test_digest_json_storage_text_distinct():
    values = (None, "", "null", "{broken", "NaN", "Infinity",
              '{"owner":"x"}', '{ "owner": "x" }')
    for key in ("mapping_json", "match_rule_json"):
        results = [_digest(_binding(**{key: value})) for value in values]
        assert len(set(results)) == len(values)


def test_digest_authority_projection_and_order():
    binding = _binding(source_type="tdc", sync_state="idle", cursor_json="old")
    rows = [{"field_name": name, "authority": authority, "locked_at": "old",
             "source_type": "tdc", "updated_at": "old"}
            for name, authority in (("owner", "automatic"), ("额外", "manual"))]
    before = [dict(row) for row in rows]
    actual = _digest(binding, rows)
    assert rows == before
    changed = [dict(row, locked_at="new", source_type="none", updated_at="new")
               for row in reversed(rows)]
    other = dict(binding, source_type="none", sync_state="failed", cursor_json="new")
    assert _digest(other, changed) == actual
    assert _digest(binding, rows[:1]) != actual
    assert _digest(binding, [dict(rows[0], authority="manual"), rows[1]]) != actual
    assert _digest(binding, [rows[0], dict(rows[1], field_name="另一字段")]) != actual


def test_digest_missing_rows_equal_ensured_rows(bprime_audit_case):  # noqa: F811
    case = bprime_audit_case
    db = case["db"]
    cases = (("VPI-T2-D1", "manual"), (case["deliverable_id"], "automatic"))
    with db.get_connection() as conn:
        for did, mode in cases:
            cap = repo.PROJECT_STATUS_SOURCE_CAPABILITIES[did]
            assert bool(cap["syncCapable"]) == (mode == "automatic")
            assert conn.execute(
                "SELECT 1 FROM project_status_deliverables WHERE id = ?",
                (did,)).fetchone() is not None
            for table in ("project_status_field_authority",
                          "project_status_update_bindings"):
                conn.execute(f"DELETE FROM {table} WHERE deliverable_id = ?", (did,))
            assert _read(conn, did) == (None, [])
            statements = []
            conn.set_trace_callback(statements.append)
            expected = _digest(None, (), did)
            conn.set_trace_callback(None)
            assert statements == []
            repo.ProjectStatusRepo._ensure_project_status_policy(conn, did)
            binding, rows = _read(conn, did)
            keys = ("mode", "enabled", "external_key", "interval_minutes",
                    "credential_ref", "mapping_json", "match_rule_json",
                    "sync_config_revision")
            assert tuple(binding[k] for k in keys) == (
                mode, 0, None, None, None, "{}", "{}", 0)
            assert type(binding["enabled"]) is int
            assert type(binding["sync_config_revision"]) is int
            assert {r["field_name"] for r in rows} == set(repo.PROJECT_STATUS_EDITABLE_FIELDS)
            assert all(r["authority"] == "manual" for r in rows)
            assert _digest(binding, rows, did) == expected
            conn.execute(
                "UPDATE project_status_field_authority SET authority = 'automatic' "
                "WHERE deliverable_id = ? AND field_name = 'owner'", (did,))
            conn.execute(
                "DELETE FROM project_status_field_authority "
                "WHERE deliverable_id = ? AND field_name = 'remark'", (did,))
            partial = _digest(*_read(conn, did), deliverable_id=did)
            repo.ProjectStatusRepo._ensure_project_status_policy(conn, did)
            assert _digest(*_read(conn, did), deliverable_id=did) == partial


def test_digest_rejects_nonfinite_numbers():
    for value in (float("nan"), float("inf"), float("-inf")):
        for key in ("mode", "enabled", "external_key", "interval_minutes",
                    "mapping_json", "match_rule_json", "sync_config_revision"):
            with pytest.raises(ValueError, match="Out of range float values"):
                _digest(_binding(**{key: value}))
        with pytest.raises(ValueError, match="Out of range float values"):
            _digest(_binding(), [{"field_name": "owner", "authority": value}])


# --- 配置签名对多值键 documentNos 的规范化（存量签名逐字节不变） -------------

def test_signature_canonicalizes_document_nos():
    """多单号列表/字符串统一规范化为「去重排序 + 空格连接」的同一签名。"""
    from services.project_status_records import compute_config_signature
    base = {"reportType": "data_model", "aggregate": True}
    a = compute_config_signature("tdc", {**base, "documentNos": ["3D-2", "3D-1"]})
    b = compute_config_signature(
        "tdc", {**base, "documentNos": [" 3D-1 ", "3D-2", "3D-1"]})
    c = compute_config_signature("tdc", {**base, "documentNos": "3D-1 3D-2"})
    assert a == b == c
    # 关键：多单号必须真的进入签名。若该键被当成未知键丢弃，上面三值也会
    # 相等（假通过），所以必须与「不含该键 / 不同集合 / 单值键」三者区分。
    assert a != compute_config_signature("tdc", base)
    assert a != compute_config_signature("tdc", {**base, "documentNos": ["3D-1"]})
    assert a != compute_config_signature("tdc", {**base, "documentNo": "3D-1"})


def test_signature_rejects_malformed_document_nos():
    """多值键同样 fail-closed：不接受空集合、空白串与非法类型。"""
    from services.project_status_records import compute_config_signature
    base = {"reportType": "data_model", "aggregate": True}
    for bad in ([], "   ", " ,; ", {"a": 1}, 5, True):
        with pytest.raises(ValueError):
            compute_config_signature("tdc", {**base, "documentNos": bad})


def test_signature_of_legacy_single_serial_rule_is_unchanged():
    """golden：契约新增键不得改变存量规则的签名（逐字节不变）。"""
    from services.project_status_records import compute_config_signature
    sig = compute_config_signature(
        "tdc",
        {"reportType": "data_model", "aggregate": False,
         "documentNo": "3D-00001018"})
    assert sig == "sig:28bf6d069facde729ee1fe06bf56"
    agg = compute_config_signature(
        "tdc", {"reportType": "data_model", "aggregate": True,
                "projectModel": "F610S"})
    assert agg == "sig:5da94c0257977e70332cc3eaf9eb"
