# -*- coding: utf-8 -*-
"""services/project_status_updates.py 统一项目状态更新服务的行为黄金基线测试。

契约特性与覆盖要求：
1. 锁定 4 个核心公开入口的逐键值黄金契约：
   - get_update_policy() -> tests/golden/project_status_updates/get_update_policy.json
   - update_update_policy() 校验拒绝路径 (HTTP 422 形状) -> tests/golden/project_status_updates/update_update_policy_rejected.json
   - update_update_policy() 成功保存路径 -> tests/golden/project_status_updates/update_update_policy.json
   - apply_sync_update() 外部同步应用与分支归宿 -> tests/golden/project_status_updates/apply_sync_update.json
   - list_updates() 审计明细查询与敏感字段清洗 -> tests/golden/project_status_updates/list_updates.json
2. 纯合成测试数据：轻量隔离临时 SQLite 数据库，无真实网络请求与外部凭据依赖；
3. 环境变量 VSE_PSU_GOLDEN_WRITE=1 时重新生成黄金基线；默认逐键递归对比，新增、缺失、值变化三类差异分开报告；
4. 进程内多次连续重跑具有确定性与稳定性。
"""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

import pytest

from core.db_manager import DatabaseManager
from services.project_status_records import compute_config_signature
from services.project_status_updates import (
    ConnectorCandidate,
    ConnectorSnapshot,
    ProjectStatusPolicyError,
    ProjectStatusUpdateService,
    SyncResult,
)

GOLDEN_DIR = Path(__file__).resolve().parent / "golden" / "project_status_updates"

GOLDEN_PATHS = {
    "get_update_policy": GOLDEN_DIR / "get_update_policy.json",
    "update_update_policy_rejected": GOLDEN_DIR / "update_update_policy_rejected.json",
    "update_update_policy": GOLDEN_DIR / "update_update_policy.json",
    "apply_sync_update": GOLDEN_DIR / "apply_sync_update.json",
    "list_updates": GOLDEN_DIR / "list_updates.json",
}


@contextlib.contextmanager
def isolated_psu_db():
    """构建用于黄金基线收集的轻量隔离 SQLite 数据库。"""
    try:
        temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    except TypeError:
        temp_dir = tempfile.TemporaryDirectory()

    try:
        tmp_path = Path(temp_dir.name)
        db_path = tmp_path / "golden_psu.db"
        db = DatabaseManager(db_path=db_path)
        db.init_database()
        yield db
    finally:
        try:
            temp_dir.cleanup()
        except Exception:
            pass


def _record_two_observations(
    db: DatabaseManager,
    deliverable_id: str,
    source_type: str,
    external_key: str | None,
    fields: list[str] | None = None,
    match_rule: dict[str, object] | None = None,
    *,
    aggregate: bool = False,
) -> None:
    """写入满足 2/2 门禁要求的合成映射发现证据。"""
    effective_rule = match_rule or {
        "reportType": "data_model",
        "incident": external_key,
    }
    config_signature = compute_config_signature(source_type, effective_rule)
    field_list = fields if fields is not None else [
        "currentApprover", "approvalComment", "incident", "reportType",
    ]
    report = {
        "fields": field_list,
        "statusOrApprovalFields": [],
        "suggestedStatusMapping": [],
        "suggestedAutomaticFields": [],
        "requiresConfirmation": True,
    }
    candidate_fp = "agg:fp-1" if aggregate else "fp1"
    summary = [{"externalKey": external_key, "fields": {}}]
    for index in (1, 2):
        fp = candidate_fp if aggregate else f"fp{index}"
        db.record_mapping_observation(
            deliverable_id=deliverable_id,
            source_type=source_type,
            result_state="matched",
            external_key=external_key,
            candidate_fingerprint=fp,
            candidate_count=1,
            candidate_summary_json=json.dumps(summary),
            field_report_json=json.dumps(report),
            config_signature=config_signature,
        )


def _current_deliverable(db: DatabaseManager, deliverable_id: str) -> dict[str, Any]:
    """读取指定交付物的当前业务行。"""
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM project_status_deliverables WHERE id = ?",
            (deliverable_id,),
        ).fetchone()
    if row is None:
        raise KeyError(deliverable_id)
    return dict(row)


def _normalize_dynamic_values(data: Any) -> Any:
    """递归归一化运行时易变时间戳与易变标识，保证黄金基线跨环境稳定重现。"""
    if isinstance(data, dict):
        result: dict[str, Any] = {}
        for k, v in data.items():
            if k in ("createdAt", "updatedAt", "lastAttemptAt", "lastSuccessAt", "updated_at", "locked_at") and v is not None:
                result[k] = "<TIMESTAMP>"
            else:
                result[k] = _normalize_dynamic_values(v)
        return result
    elif isinstance(data, list):
        return [_normalize_dynamic_values(item) for item in data]
    return data


def _sync_result_to_dict(res: SyncResult) -> dict[str, Any]:
    """将 SyncResult 领域对象规整为可 JSON 序列化的字典。"""
    return {
        "run_id": res.run_id,
        "final_state": res.final_state,
        "applied_fields": sorted(res.applied_fields),
        "skipped_fields": dict(sorted(res.skipped_fields.items())),
        "external_version": res.external_version,
        "updated_at": "<TIMESTAMP>" if res.updated_at is not None else None,
        "message": res.message,
    }


def collect_get_update_policy(db: DatabaseManager) -> dict[str, Any]:
    """入口 1：收集交付物更新策略查询契约（锁定默认字段归属与配置摘要）。"""
    service = ProjectStatusUpdateService(db)
    raw = {
        "VPI-T2-D5": service.get_update_policy("VPI-T2-D5"),
        "VPI-T2-D3": service.get_update_policy("VPI-T2-D3"),
        "VPI-T2-D1": service.get_update_policy("VPI-T2-D1"),
        "non_existent": service.get_update_policy("UNKNOWN_DELIVERABLE_ID"),
    }
    return _normalize_dynamic_values(raw)


def collect_update_update_policy_rejected(db: DatabaseManager) -> dict[str, Any]:
    """入口 2：收集更新策略校验拒绝路径（锁定 HTTP 422 形状的各字段错误说明）。"""
    service = ProjectStatusUpdateService(db)
    rejections: dict[str, Any] = {}

    cases: dict[str, tuple[str, dict[str, Any]]] = {
        "unknown_request_keys": (
            "VPI-T2-D5",
            {"unknownParam": "value"},
        ),
        "invalid_mode": (
            "VPI-T2-D5",
            {"mode": "not_a_valid_mode"},
        ),
        "manual_mode_with_auto_fields": (
            "VPI-T2-D5",
            {"mode": "manual", "fieldAuthority": {"owner": "automatic"}},
        ),
        "invalid_interval_and_credential": (
            "VPI-T2-D5",
            {"intervalMinutes": -5, "credentialRef": "   "},
        ),
        "unknown_match_keys": (
            "VPI-T2-D5",
            {"matchRule": {"unapprovedKey": "test"}},
        ),
        "data_model_document_no_and_incident_conflict": (
            "VPI-T2-D5",
            {
                "matchRule": {
                    "reportType": "data_model",
                    "incident": "INC-12345",
                    "documentNo": "3D-00001018",
                }
            },
        ),
        "data_model_section_scope_conflict": (
            "VPI-T2-D5",
            {
                "matchRule": {
                    "reportType": "data_model",
                    "incident": "INC-12345",
                    "section": "车身科",
                    "sectionScope": ["车身科", "底盘科"],
                }
            },
        ),
        "enable_without_evidence": (
            "VPI-T2-D5",
            {
                "mode": "hybrid",
                "enabled": True,
                "externalKey": "FM-SYNTH-1",
                "credentialRef": "alias",
                "matchRule": {"reportType": "data_model", "incident": "FM-SYNTH-1"},
                "mapping": {"owner": "currentApprover"},
                "fieldAuthority": {"owner": "automatic"},
            },
        ),
        "non_sync_target_auto_forbidden": (
            "VPI-T2-D1",
            {"mode": "hybrid", "fieldAuthority": {"owner": "automatic"}},
        ),
    }

    for case_name, (deliverable_id, payload) in cases.items():
        try:
            service.update_update_policy(deliverable_id, payload)
            raise AssertionError(f"未按预期抛出 ProjectStatusPolicyError：{case_name}")
        except ProjectStatusPolicyError as exc:
            rejections[case_name] = {
                "fields": exc.fields,
                "error_str": str(exc),
            }

    return _normalize_dynamic_values(rejections)


def collect_update_update_policy(db: DatabaseManager) -> dict[str, Any]:
    """入口 3：收集策略更新成功路径（包含 TDC 与 ARAS EWO 合同变更及局部调优）。"""
    service = ProjectStatusUpdateService(db)

    # 1. 启用 TDC VPI-T2-D5 混合模式
    _record_two_observations(
        db,
        deliverable_id="VPI-T2-D5",
        source_type="tdc",
        external_key="FM-SYNTH-1",
        fields=["currentApprover", "approvalComment", "incident", "reportType"],
        match_rule={"reportType": "data_model", "incident": "FM-SYNTH-1"},
    )
    res_a = service.update_update_policy(
        "VPI-T2-D5",
        {
            "mode": "hybrid",
            "enabled": True,
            "externalKey": "FM-SYNTH-1",
            "credentialRef": "tdc_cred_alias",
            "matchRule": {"reportType": "data_model", "incident": "FM-SYNTH-1"},
            "mapping": {"owner": "currentApprover", "note": "approvalComment"},
            "fieldAuthority": {"owner": "automatic", "note": "automatic"},
            "intervalMinutes": 30,
        },
    )

    # 2. 局部调整已启用策略的同步周期与权限
    res_b = service.update_update_policy(
        "VPI-T2-D5",
        {
            "intervalMinutes": 15,
            "mapping": {"owner": "currentApprover"},
            "fieldAuthority": {"owner": "automatic", "note": "manual"},
        },
    )

    # 3. 启用 ARAS EWO VPI-T2-D3 v2 集合契约
    v2_rule = {
        "reportType": "ewo",
        "contractVersion": "2",
        "bindingMode": "record_set",
        "aggregate": True,
        "projectCode": "F610S",
    }
    _record_two_observations(
        db,
        deliverable_id="VPI-T2-D3",
        source_type="aras",
        external_key=None,
        fields=["_subject", "_rsp_name", "_required_date"],
        match_rule=v2_rule,
        aggregate=True,
    )
    res_c = service.update_update_policy(
        "VPI-T2-D3",
        {
            "mode": "automatic",
            "enabled": True,
            "credentialRef": "aras_cred_alias",
            "bindingContractVersion": "2",
            "matchRule": v2_rule,
            "mapping": {"note": "_subject"},
            "fieldAuthority": {"note": "automatic"},
            "intervalMinutes": 60,
        },
    )

    results = {
        "enable_tdc_d5": res_a,
        "modify_settings_d5": res_b,
        "enable_aras_d3_v2": res_c,
    }
    return _normalize_dynamic_values(results)


def collect_apply_sync_update(db: DatabaseManager) -> dict[str, Any]:
    """入口 4：收集连接器快照单事务应用入口（覆盖匹配、部分锁定、未找到、歧义等分支）。"""
    service = ProjectStatusUpdateService(db)
    _record_two_observations(
        db,
        deliverable_id="VPI-T2-D5",
        source_type="tdc",
        external_key="FM-SYNTH-1",
        fields=["currentApprover", "approvalComment", "incident", "reportType"],
        match_rule={"reportType": "data_model", "incident": "FM-SYNTH-1"},
    )
    service.update_update_policy(
        "VPI-T2-D5",
        {
            "mode": "hybrid",
            "enabled": True,
            "externalKey": "FM-SYNTH-1",
            "credentialRef": "tdc_cred_alias",
            "matchRule": {"reportType": "data_model", "incident": "FM-SYNTH-1"},
            "mapping": {"owner": "currentApprover", "note": "approvalComment"},
            "fieldAuthority": {"owner": "automatic", "note": "automatic"},
            "intervalMinutes": 30,
        },
    )

    results: dict[str, Any] = {}

    # 1. 成功全字段匹配同步
    lease1 = service.acquire_sync_lease("VPI-T2-D5", "scheduled")
    row1 = _current_deliverable(db, "VPI-T2-D5")
    snapshot1 = ConnectorSnapshot(
        match_state="matched",
        candidates=[
            ConnectorCandidate(
                external_key="FM-SYNTH-1",
                external_version="ver-001",
                field_values={"owner": "张三", "note": "已审核"},
                fetched_at="2026-09-01T10:00:00.000Z",
            )
        ],
        external_version="ver-001",
        fetched_at="2026-09-01T10:00:00.000Z",
        expected_deliverable_updated_at=str(row1["updated_at"]),
    )
    res1 = service.apply_sync_update(
        int(lease1["binding_id"]),
        int(lease1["run_id"]),
        lease1["lease_token"],
        snapshot1,
        "scheduled",
    )
    results["matched_success"] = _sync_result_to_dict(res1)

    # 2. 未找到候选 (not_found -> needs_attention)
    lease2 = service.acquire_sync_lease("VPI-T2-D5", "scheduled")
    row2 = _current_deliverable(db, "VPI-T2-D5")
    snapshot2 = ConnectorSnapshot(
        match_state="not_found",
        candidates=[],
        external_version="ver-002",
        fetched_at="2026-09-01T10:00:00.000Z",
        expected_deliverable_updated_at=str(row2["updated_at"]),
    )
    res2 = service.apply_sync_update(
        int(lease2["binding_id"]),
        int(lease2["run_id"]),
        lease2["lease_token"],
        snapshot2,
        "scheduled",
    )
    results["not_found"] = _sync_result_to_dict(res2)

    # 3. 歧义多候选 (ambiguous -> needs_attention)
    lease3 = service.acquire_sync_lease("VPI-T2-D5", "scheduled")
    row3 = _current_deliverable(db, "VPI-T2-D5")
    snapshot3 = ConnectorSnapshot(
        match_state="ambiguous",
        candidates=[],
        external_version="ver-003",
        fetched_at="2026-09-01T10:00:00.000Z",
        expected_deliverable_updated_at=str(row3["updated_at"]),
    )
    res3 = service.apply_sync_update(
        int(lease3["binding_id"]),
        int(lease3["run_id"]),
        lease3["lease_token"],
        snapshot3,
        "scheduled",
    )
    results["ambiguous"] = _sync_result_to_dict(res3)

    # 4. 外部键不匹配 (external_key mismatch -> needs_attention)
    lease4 = service.acquire_sync_lease("VPI-T2-D5", "scheduled")
    row4 = _current_deliverable(db, "VPI-T2-D5")
    snapshot4 = ConnectorSnapshot(
        match_state="matched",
        candidates=[
            ConnectorCandidate(
                external_key="OTHER-KEY",
                external_version="ver-004",
                field_values={"owner": "李四"},
                fetched_at="2026-09-01T10:00:00.000Z",
            )
        ],
        external_version="ver-004",
        fetched_at="2026-09-01T10:00:00.000Z",
        expected_deliverable_updated_at=str(row4["updated_at"]),
    )
    res4 = service.apply_sync_update(
        int(lease4["binding_id"]),
        int(lease4["run_id"]),
        lease4["lease_token"],
        snapshot4,
        "scheduled",
    )
    results["external_key_mismatch"] = _sync_result_to_dict(res4)

    # 5. 人工锁定字段跳过 (partial)
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE project_status_field_authority SET locked_at = '2026-08-15 10:00:00' "
            "WHERE deliverable_id = 'VPI-T2-D5' AND field_name = 'owner'"
        )
    lease5 = service.acquire_sync_lease("VPI-T2-D5", "scheduled")
    row5 = _current_deliverable(db, "VPI-T2-D5")
    snapshot5 = ConnectorSnapshot(
        match_state="matched",
        candidates=[
            ConnectorCandidate(
                external_key="FM-SYNTH-1",
                external_version="ver-005",
                field_values={"owner": "王五", "note": "部分同步备注更新"},
                fetched_at="2026-09-01T10:00:00.000Z",
            )
        ],
        external_version="ver-005",
        fetched_at="2026-09-01T10:00:00.000Z",
        expected_deliverable_updated_at=str(row5["updated_at"]),
    )
    res5 = service.apply_sync_update(
        int(lease5["binding_id"]),
        int(lease5["run_id"]),
        lease5["lease_token"],
        snapshot5,
        "scheduled",
    )
    results["partial_locked_field"] = _sync_result_to_dict(res5)

    return _normalize_dynamic_values(results)


def collect_list_updates(db: DatabaseManager) -> dict[str, Any]:
    """入口 5：收集更新审计明细（验证人工更新与同步更新的记录结构及凭据脱敏）。"""
    service = ProjectStatusUpdateService(db)

    # 1. 触发一次人工修改（包含测试用敏感密码与 token，验证是否被脱敏为 [redacted]）
    curr = _current_deliverable(db, "VPI-T2-D5")
    manual_values = {
        "status": curr["status"],
        "owner": curr["owner"],
        "planned_date": curr["planned_date"],
        "actual_date": curr["actual_date"],
        "progress": 75,
        "remark": "进展正常 password=hunter2 token=secret123",
    }
    service.apply_manual_update("VPI-T2-D5", "VPI-T2", manual_values, str(curr["updated_at"]))

    # 2. 配置并触发一次同步更新
    _record_two_observations(
        db,
        deliverable_id="VPI-T2-D5",
        source_type="tdc",
        external_key="FM-SYNTH-1",
        fields=["currentApprover", "approvalComment", "incident", "reportType"],
        match_rule={"reportType": "data_model", "incident": "FM-SYNTH-1"},
    )
    service.update_update_policy(
        "VPI-T2-D5",
        {
            "mode": "hybrid",
            "enabled": True,
            "externalKey": "FM-SYNTH-1",
            "credentialRef": "tdc_cred",
            "matchRule": {"reportType": "data_model", "incident": "FM-SYNTH-1"},
            "mapping": {"owner": "currentApprover", "note": "approvalComment"},
            "fieldAuthority": {"owner": "automatic", "note": "automatic"},
            "intervalMinutes": 30,
        },
    )
    curr = _current_deliverable(db, "VPI-T2-D5")
    lease = service.acquire_sync_lease("VPI-T2-D5", "scheduled")
    snapshot = ConnectorSnapshot(
        match_state="matched",
        candidates=[
            ConnectorCandidate(
                external_key="FM-SYNTH-1",
                external_version="v-sync-01",
                field_values={"owner": "同步负责人", "note": "自动同步备注"},
                fetched_at="2026-09-01T10:00:00.000Z",
            )
        ],
        external_version="v-sync-01",
        fetched_at="2026-09-01T10:00:00.000Z",
        expected_deliverable_updated_at=str(curr["updated_at"]),
    )
    service.apply_sync_update(
        int(lease["binding_id"]),
        int(lease["run_id"]),
        lease["lease_token"],
        snapshot,
        "scheduled",
    )

    results = {
        "deliverable_with_audits": service.list_updates("VPI-T2-D5"),
        "deliverable_empty_audits": service.list_updates("VPI-T2-D1"),
        "deliverable_non_existent": service.list_updates("UNKNOWN_DELIVERABLE_ID"),
    }
    return _normalize_dynamic_values(results)


def save_golden(data: Any, target_path: Path) -> None:
    """以 UTF-8 缩进 2、排序键且结尾换行的规范格式持久化黄金快照。"""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    target_path.write_text(serialized, encoding="utf-8")


def load_golden(source_path: Path) -> Any:
    """读取已持久化的黄金快照 JSON 文件。"""
    if not source_path.exists():
        raise FileNotFoundError(f"未找到黄金快照文件：{source_path}")
    content = source_path.read_text(encoding="utf-8")
    return json.loads(content)


def diff_data(golden: Any, current: Any, path: str = "") -> dict[str, list[dict[str, Any]]]:
    """递归逐键对比两个 JSON 兼容数据结构，分别记录新增、缺失与值变化。"""
    added: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []

    if isinstance(golden, dict) and isinstance(current, dict):
        golden_keys = set(golden.keys())
        current_keys = set(current.keys())

        for k in sorted(current_keys - golden_keys):
            child_path = f"{path}.{k}" if path else str(k)
            added.append({"path": child_path, "value": current[k]})

        for k in sorted(golden_keys - current_keys):
            child_path = f"{path}.{k}" if path else str(k)
            missing.append({"path": child_path, "value": golden[k]})

        for k in sorted(golden_keys & current_keys):
            child_path = f"{path}.{k}" if path else str(k)
            sub = diff_data(golden[k], current[k], path=child_path)
            added.extend(sub["added"])
            missing.extend(sub["missing"])
            changed.extend(sub["changed"])

    elif isinstance(golden, list) and isinstance(current, list):
        common_len = min(len(golden), len(current))
        for i in range(common_len):
            sub = diff_data(golden[i], current[i], path=f"{path}[{i}]")
            added.extend(sub["added"])
            missing.extend(sub["missing"])
            changed.extend(sub["changed"])

        if len(current) > len(golden):
            for i in range(len(golden), len(current)):
                added.append({"path": f"{path}[{i}]", "value": current[i]})
        elif len(golden) > len(current):
            for i in range(len(current), len(golden)):
                missing.append({"path": f"{path}[{i}]", "value": golden[i]})

    else:
        if golden != current:
            changed.append({"path": path, "golden": golden, "current": current})

    return {
        "added": added,
        "missing": missing,
        "changed": changed,
    }


def format_diff_report(diff: dict[str, list[dict[str, Any]]]) -> str:
    """生成结构清晰的差异报告文本，分别展示新增项、缺失项与值差异。"""
    sections: list[str] = []
    if diff["added"]:
        lines = [f"+ {item['path']}: {item['value']!r}" for item in diff["added"]]
        sections.append(f"【新增键/项】共 {len(diff['added'])} 处:\n  " + "\n  ".join(lines))
    if diff["missing"]:
        lines = [f"- {item['path']}: {item['value']!r}" for item in diff["missing"]]
        sections.append(f"【缺失键/项】共 {len(diff['missing'])} 处:\n  " + "\n  ".join(lines))
    if diff["changed"]:
        lines = [
            f"* {item['path']}: golden={item['golden']!r} -> current={item['current']!r}"
            for item in diff["changed"]
        ]
        sections.append(f"【值变化】共 {len(diff['changed'])} 处:\n  " + "\n  ".join(lines))
    return "\n\n".join(sections)


def save_all_golden() -> None:
    """重新生成并持久化全部 5 个入口的黄金基线 JSON 文件。"""
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    with isolated_psu_db() as db:
        save_golden(collect_get_update_policy(db), GOLDEN_PATHS["get_update_policy"])
    with isolated_psu_db() as db:
        save_golden(collect_update_update_policy_rejected(db), GOLDEN_PATHS["update_update_policy_rejected"])
    with isolated_psu_db() as db:
        save_golden(collect_update_update_policy(db), GOLDEN_PATHS["update_update_policy"])
    with isolated_psu_db() as db:
        save_golden(collect_apply_sync_update(db), GOLDEN_PATHS["apply_sync_update"])
    with isolated_psu_db() as db:
        save_golden(collect_list_updates(db), GOLDEN_PATHS["list_updates"])


def _auto_init_golden() -> None:
    """模块导入时检测：环境变量要求写入或基线文件缺失时自动生成。"""
    write_requested = os.environ.get("VSE_PSU_GOLDEN_WRITE") == "1"
    missing_files = any(
        not path.exists() or path.stat().st_size == 0
        for path in GOLDEN_PATHS.values()
    )
    if write_requested or missing_files:
        try:
            save_all_golden()
        except Exception:
            pass


_auto_init_golden()


@pytest.fixture(scope="session", autouse=True)
def _ensure_golden_ready():
    """确保 pytest 会话执行期间基线文件就绪。"""
    write_requested = os.environ.get("VSE_PSU_GOLDEN_WRITE") == "1"
    missing_files = any(
        not path.exists() or path.stat().st_size == 0
        for path in GOLDEN_PATHS.values()
    )
    if write_requested or missing_files:
        save_all_golden()


def test_get_update_policy_matches_golden(tmp_path: Path):
    """验证 get_update_policy() 公开入口返回结构与黄金基线完全一致。"""
    db = DatabaseManager(db_path=tmp_path / "psu_get.db")
    db.init_database()
    current = collect_get_update_policy(db)
    golden_path = GOLDEN_PATHS["get_update_policy"]
    write_requested = os.environ.get("VSE_PSU_GOLDEN_WRITE") == "1"

    if write_requested or not golden_path.exists():
        save_golden(current, golden_path)
        return

    golden = load_golden(golden_path)
    diff = diff_data(golden, current)
    report = format_diff_report(diff)

    assert not diff["added"], f"get_update_policy 契约对比失败：存在未记录的新增项\n{report}"
    assert not diff["missing"], f"get_update_policy 契约对比失败：存在基线中丢失的项\n{report}"
    assert not diff["changed"], f"get_update_policy 契约对比失败：存在字段值变化\n{report}"


def test_update_update_policy_rejected_matches_golden(tmp_path: Path):
    """验证 update_update_policy() 校验拒绝路径 (422 形状) 与黄金基线完全一致。"""
    db = DatabaseManager(db_path=tmp_path / "psu_rej.db")
    db.init_database()
    current = collect_update_update_policy_rejected(db)
    golden_path = GOLDEN_PATHS["update_update_policy_rejected"]
    write_requested = os.environ.get("VSE_PSU_GOLDEN_WRITE") == "1"

    if write_requested or not golden_path.exists():
        save_golden(current, golden_path)
        return

    golden = load_golden(golden_path)
    diff = diff_data(golden, current)
    report = format_diff_report(diff)

    assert not diff["added"], f"update_update_policy_rejected 契约对比失败：存在未记录的新增项\n{report}"
    assert not diff["missing"], f"update_update_policy_rejected 契约对比失败：存在基线中丢失的项\n{report}"
    assert not diff["changed"], f"update_update_policy_rejected 契约对比失败：存在字段值变化\n{report}"


def test_update_update_policy_matches_golden(tmp_path: Path):
    """验证 update_update_policy() 正常保存路径与黄金基线完全一致。"""
    db = DatabaseManager(db_path=tmp_path / "psu_update.db")
    db.init_database()
    current = collect_update_update_policy(db)
    golden_path = GOLDEN_PATHS["update_update_policy"]
    write_requested = os.environ.get("VSE_PSU_GOLDEN_WRITE") == "1"

    if write_requested or not golden_path.exists():
        save_golden(current, golden_path)
        return

    golden = load_golden(golden_path)
    diff = diff_data(golden, current)
    report = format_diff_report(diff)

    assert not diff["added"], f"update_update_policy 契约对比失败：存在未记录的新增项\n{report}"
    assert not diff["missing"], f"update_update_policy 契约对比失败：存在基线中丢失的项\n{report}"
    assert not diff["changed"], f"update_update_policy 契约对比失败：存在字段值变化\n{report}"


def test_apply_sync_update_matches_golden(tmp_path: Path):
    """验证 apply_sync_update() 事务应用入口各分支与黄金基线完全一致。"""
    db = DatabaseManager(db_path=tmp_path / "psu_sync.db")
    db.init_database()
    current = collect_apply_sync_update(db)
    golden_path = GOLDEN_PATHS["apply_sync_update"]
    write_requested = os.environ.get("VSE_PSU_GOLDEN_WRITE") == "1"

    if write_requested or not golden_path.exists():
        save_golden(current, golden_path)
        return

    golden = load_golden(golden_path)
    diff = diff_data(golden, current)
    report = format_diff_report(diff)

    assert not diff["added"], f"apply_sync_update 契约对比失败：存在未记录的新增项\n{report}"
    assert not diff["missing"], f"apply_sync_update 契约对比失败：存在基线中丢失的项\n{report}"
    assert not diff["changed"], f"apply_sync_update 契约对比失败：存在字段值变化\n{report}"


def test_list_updates_matches_golden(tmp_path: Path):
    """验证 list_updates() 审计明细查询入口与黄金基线完全一致。"""
    db = DatabaseManager(db_path=tmp_path / "psu_audit.db")
    db.init_database()
    current = collect_list_updates(db)
    golden_path = GOLDEN_PATHS["list_updates"]
    write_requested = os.environ.get("VSE_PSU_GOLDEN_WRITE") == "1"

    if write_requested or not golden_path.exists():
        save_golden(current, golden_path)
        return

    golden = load_golden(golden_path)
    diff = diff_data(golden, current)
    report = format_diff_report(diff)

    assert not diff["added"], f"list_updates 契约对比失败：存在未记录的新增项\n{report}"
    assert not diff["missing"], f"list_updates 契约对比失败：存在基线中丢失的项\n{report}"
    assert not diff["changed"], f"list_updates 契约对比失败：存在字段值变化\n{report}"


def test_golden_baselines_reproducible_across_runs(tmp_path: Path):
    """验证各收集器在两个全新隔离库上产生 100% 一致的黄金数据。

    每个收集器有独立的有状态序列（如 apply_sync_update 会写入外部映射，
    之后同库再跑 update_policy 会撞「已映射只读」守卫），所以每步都用
    全新的数据库成对收集——稳定性比较的是「同起点同序列」，不是跨序列。
    """
    collectors = (
        ("get_update_policy", collect_get_update_policy),
        ("update_update_policy_rejected", collect_update_update_policy_rejected),
        ("update_update_policy", collect_update_update_policy),
        ("apply_sync_update", collect_apply_sync_update),
        ("list_updates", collect_list_updates),
    )

    def fresh_db(tag: str) -> DatabaseManager:
        db = DatabaseManager(db_path=tmp_path / f"{tag}.db")
        db.init_database()
        return db

    for name, collect in collectors:
        data1 = collect(fresh_db(f"{name}-run1"))
        data2 = collect(fresh_db(f"{name}-run2"))
        diff = diff_data(data1, data2)
        assert not diff["added"] and not diff["missing"] and not diff["changed"], f"{name} 重跑不稳定"
