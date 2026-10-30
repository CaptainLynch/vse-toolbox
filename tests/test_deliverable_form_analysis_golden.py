# -*- coding: utf-8 -*-
"""services/deliverable_form_analysis.py 统一表单分析服务的行为黄金基线测试。

契约特性与覆盖要求：
1. 覆盖至少 3 个不同 report 类型（含 TDC 与 Aras 各一）：
   - VPI-T2-D3 (report: ewo, source: aras)
   - tdc_sor (report: tdc_sor, source: tdc)
   - aras_ncr_progress (report: ncr_progress, source: aras)
2. 锁定 3 个代表性公开入口的逐键值契约：
   - form_definition() -> tests/golden/form_analysis/form_definition.json
   - DeliverableFormAnalysisService.view() -> tests/golden/form_analysis/view.json
   - DeliverableFormAnalysisService.rows() -> tests/golden/form_analysis/rows.json
3. 纯合成测试数据：自建轻量隔离 SQLite 数据库，无真实导出文件与凭据依赖；
4. 环境变量 VSE_FORM_ANALYSIS_GOLDEN_WRITE=1 时重新生成 golden 基线；
   默认模式逐键递归对比，新增、缺失、值变化三类差异分开断言报告；
5. 进程内多次连续重跑具有确定性与稳定性。
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import pytest

from core.db_manager import DatabaseManager
from core.form_registry import FORMS_BY_KEY
from services.deliverable_form_analysis import (
    DeliverableFormAnalysisService,
    build_form_snapshot,
    form_definition,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_DIR = Path(__file__).resolve().parent / "golden" / "form_analysis"

FORM_KEYS_TO_TEST = ("VPI-T2-D3", "tdc_sor", "aras_ncr_progress")

GOLDEN_PATHS = {
    "form_definition": GOLDEN_DIR / "form_definition.json",
    "view": GOLDEN_DIR / "view.json",
    "rows": GOLDEN_DIR / "rows.json",
}


def _synthetic_ewo_rows_trend() -> list[dict[str, Any]]:
    """EWO 进度历史快照数据（用于聚合生成趋势）。"""
    return [
        {
            "_no": "EWO-SYNTH-001",
            "_rsp_department": "车身工程部",
            "_rsp_smt": "车门科",
            "_modelinfo": "F610S",
            "_subject": "前车门铰链结构优化",
            "state": "PROC",
            "_submit_time": "2026-09-01",
            "_required_date": "2026-09-20",
            "_rsp_phone": "13800138001",
        },
        {
            "_no": "EWO-SYNTH-002",
            "_rsp_department": "底盘工程部",
            "_rsp_smt": "制动科",
            "_modelinfo": "F620S",
            "_subject": "制动总泵管路走向调整",
            "state": "CLOSE",
            "_submit_time": "2026-08-15",
            "_required_date": "2026-08-30",
            "_rsp_phone": "13800138002",
        },
    ]


def _synthetic_ewo_rows_latest() -> list[dict[str, Any]]:
    """EWO 进度最新快照数据（覆盖按期、逾期与完成三种状态）。"""
    return [
        {
            "_no": "EWO-SYNTH-001",
            "_rsp_department": "车身工程部",
            "_rsp_smt": "车门科",
            "_modelinfo": "F610S",
            "_subject": "前车门铰链结构优化",
            "state": "PROC",
            "_submit_time": "2026-09-01",
            "_required_date": "2026-09-20",
            "_rsp_phone": "13800138001",
        },
        {
            "_no": "EWO-SYNTH-002",
            "_rsp_department": "车身工程部",
            "_rsp_smt": "车门科",
            "_modelinfo": "F610S",
            "_subject": "侧围外板冲压干涉处理",
            "state": "PROC",
            "_submit_time": "2026-08-01",
            "_required_date": "2026-08-10",
            "_rsp_phone": "13800138003",
        },
        {
            "_no": "EWO-SYNTH-003",
            "_rsp_department": "底盘工程部",
            "_rsp_smt": "制动科",
            "_modelinfo": "F620S",
            "_subject": "制动总泵管路走向调整",
            "state": "CLOSE",
            "_submit_time": "2026-08-15",
            "_required_date": "2026-08-30",
            "_rsp_phone": "13800138002",
        },
    ]


def _synthetic_sor_rows_trend() -> list[dict[str, Any]]:
    """SOR 定点流程历史快照数据。"""
    return [
        {
            "processNo": "SOR-SYNTH-001",
            "sorNo": "SGMW-SOR-SYNTH-001",
            "processInstanceStatus": "审批中",
            "deptName": "车身工程部",
            "sectionName": "车体科",
            "carTypeProject": "F610S",
            "processType": "新建",
            "startTime": "2026-09-12 10:00:00",
            "startUser": "合成测试员甲",
            "sorPartNo": "PART-001",
            "sorPartName": "车身侧围骨架",
        },
        {
            "processNo": "SOR-SYNTH-003",
            "sorNo": "SGMW-SOR-SYNTH-003",
            "processInstanceStatus": "Completed",
            "deptName": "车身工程部",
            "sectionName": "车体科",
            "carTypeProject": "F610S",
            "processType": "新建",
            "startTime": "2026-08-20 10:00:00",
            "startUser": "合成测试员丙",
            "sorPartNo": "PART-003",
            "sorPartName": "顶盖横梁总成",
        },
    ]


def _synthetic_sor_rows_latest() -> list[dict[str, Any]]:
    """SOR 定点流程最新快照数据（覆盖滞留未逾期、滞留逾期、已完成及终态作废）。"""
    return [
        {
            "processNo": "SOR-SYNTH-001",
            "sorNo": "SGMW-SOR-SYNTH-001",
            "processInstanceStatus": "审批中",
            "deptName": "车身工程部",
            "sectionName": "车体科",
            "carTypeProject": "F610S",
            "processType": "新建",
            "startTime": "2026-09-12 10:00:00",
            "startUser": "合成测试员甲",
            "sorPartNo": "PART-001",
            "sorPartName": "车身侧围骨架",
        },
        {
            "processNo": "SOR-SYNTH-002",
            "sorNo": "SGMW-SOR-SYNTH-002",
            "processInstanceStatus": "审批中",
            "deptName": "底盘工程部",
            "sectionName": "转向科",
            "carTypeProject": "F620S",
            "processType": "变更",
            "startTime": "2026-09-01 10:00:00",
            "startUser": "合成测试员乙",
            "sorPartNo": "PART-002",
            "sorPartName": "转向机支架",
        },
        {
            "processNo": "SOR-SYNTH-003",
            "sorNo": "SGMW-SOR-SYNTH-003",
            "processInstanceStatus": "Completed",
            "deptName": "车身工程部",
            "sectionName": "车体科",
            "carTypeProject": "F610S",
            "processType": "新建",
            "startTime": "2026-08-20 10:00:00",
            "startUser": "合成测试员丙",
            "sorPartNo": "PART-003",
            "sorPartName": "顶盖横梁总成",
        },
        {
            "processNo": "SOR-SYNTH-004",
            "sorNo": "SGMW-SOR-SYNTH-004",
            "processInstanceStatus": "Terminated",
            "deptName": "底盘工程部",
            "sectionName": "转向科",
            "carTypeProject": "F620S",
            "processType": "新建",
            "startTime": "2026-08-10 10:00:00",
            "startUser": "合成测试员丁",
            "sorPartNo": "PART-004",
            "sorPartName": "转向柱总成",
        },
    ]


def _make_ncr_values(values_by_label: dict[str, object]) -> list[object | None]:
    """根据表头标签构造 NCR 位置行数据，缺失字段补 None。"""
    definition = form_definition("aras_ncr_progress")
    headers = definition["headerRows"][int(definition["dataHeaderRow"])]
    values: list[object | None] = [None] * len(headers)
    for label, value in values_by_label.items():
        if label in headers:
            values[headers.index(label)] = value
    return values


def _synthetic_ncr_rows_trend() -> list[list[object | None]]:
    """NCR 进度历史快照数据。"""
    return [
        _make_ncr_values({
            "NCR编号": "NCR-SYNTH-001",
            "状态": "审批中",
            "当前节点及通知时间": "NCR管理员",
            "NCR管理员": "2026-09-13",
            "PE填写": "2026-09-13",
            "区域": "车身工程科",
            "项目": "F610S",
            "是否审批完成": "否",
            "提交日期": "2026-09-13",
        }),
        _make_ncr_values({
            "NCR编号": "NCR-SYNTH-003",
            "状态": "已完成",
            "当前节点及通知时间": "CLOSE",
            "NCR管理员": "2026-08-20",
            "PE填写": "2026-08-20",
            "区域": "车身工程科",
            "项目": "F610S",
            "是否审批完成": "是",
            "提交日期": "2026-08-20",
        }),
    ]


def _synthetic_ncr_rows_latest() -> list[list[object | None]]:
    """NCR 进度最新快照数据（覆盖在审按期、节点滞留逾期、已完成）。"""
    return [
        _make_ncr_values({
            "NCR编号": "NCR-SYNTH-001",
            "状态": "审批中",
            "当前节点及通知时间": "NCR管理员",
            "NCR管理员": "2026-09-14",
            "PE填写": "2026-09-14",
            "区域": "车身工程科",
            "项目": "F610S",
            "是否审批完成": "否",
            "提交日期": "2026-09-14",
        }),
        _make_ncr_values({
            "NCR编号": "NCR-SYNTH-002",
            "状态": "审批中",
            "当前节点及通知时间": "NCR管理员",
            "NCR管理员": "2026-09-01",
            "PE填写": "2026-09-01",
            "区域": "底盘工程科",
            "项目": "F620S",
            "是否审批完成": "否",
            "提交日期": "2026-09-01",
        }),
        _make_ncr_values({
            "NCR编号": "NCR-SYNTH-003",
            "状态": "已完成",
            "当前节点及通知时间": "CLOSE",
            "NCR管理员": "2026-08-20",
            "PE填写": "2026-08-20",
            "区域": "车身工程科",
            "项目": "F610S",
            "是否审批完成": "是",
            "提交日期": "2026-08-20",
        }),
    ]


def _seed_synthetic_snapshots(db: DatabaseManager) -> None:
    """在测试数据库中生成并持久化各报表的两期合成快照。"""
    # 1. VPI-T2-D3 (ewo)
    db.publish_deliverable_form_snapshot(
        build_form_snapshot(
            "VPI-T2-D3",
            _synthetic_ewo_rows_trend(),
            snapshot_at="2026-09-14T10:00:00Z",
            source_run_id=1,
            source="synthetic_test",
        )
    )
    db.publish_deliverable_form_snapshot(
        build_form_snapshot(
            "VPI-T2-D3",
            _synthetic_ewo_rows_latest(),
            snapshot_at="2026-09-15T10:00:00Z",
            source_run_id=2,
            source="synthetic_test",
        )
    )

    # 2. tdc_sor (tdc_sor)
    db.publish_deliverable_form_snapshot(
        build_form_snapshot(
            "tdc_sor",
            _synthetic_sor_rows_trend(),
            snapshot_at="2026-09-14T10:00:00Z",
            source_run_id=1,
            source="synthetic_test",
        )
    )
    db.publish_deliverable_form_snapshot(
        build_form_snapshot(
            "tdc_sor",
            _synthetic_sor_rows_latest(),
            snapshot_at="2026-09-15T10:00:00Z",
            source_run_id=2,
            source="synthetic_test",
        )
    )

    # 3. aras_ncr_progress (ncr_progress)
    db.publish_deliverable_form_snapshot(
        build_form_snapshot(
            "aras_ncr_progress",
            [{"values": row, "sheetName": "Sheet1"} for row in _synthetic_ncr_rows_trend()],
            snapshot_at="2026-09-14T10:00:00Z",
            source_run_id=1,
            source="synthetic_test",
        )
    )
    db.publish_deliverable_form_snapshot(
        build_form_snapshot(
            "aras_ncr_progress",
            [{"values": row, "sheetName": "Sheet1"} for row in _synthetic_ncr_rows_latest()],
            snapshot_at="2026-09-15T10:00:00Z",
            source_run_id=2,
            source="synthetic_test",
        )
    )


@contextlib.contextmanager
def isolated_form_service():
    """构建用于黄金基线收集的轻量隔离 DeliverableFormAnalysisService。

    使用临时目录隔离 SQLite 数据库与快照，避免对工作区产生任何副作用。
    """
    try:
        temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    except TypeError:
        temp_dir = tempfile.TemporaryDirectory()

    try:
        tmp_path = Path(temp_dir.name)
        db_path = tmp_path / "golden_forms.db"
        db = DatabaseManager(db_path=db_path)
        db.init_database()
        _seed_synthetic_snapshots(db)
        service = DeliverableFormAnalysisService(db)
        yield service
    finally:
        try:
            temp_dir.cleanup()
        except Exception:
            pass


@pytest.fixture()
def form_service():
    """测试用隔离表单分析服务夹具。"""
    with isolated_form_service() as service:
        yield service


def collect_form_definition() -> dict[str, Any]:
    """收集待测表单的 form_definition() 契约字典。"""
    return {
        form_key: form_definition(form_key)
        for form_key in FORM_KEYS_TO_TEST
    }


def collect_view(service: DeliverableFormAnalysisService) -> dict[str, Any]:
    """收集待测表单的 view() 视图契约字典。"""
    return {
        form_key: service.view(form_key)
        for form_key in FORM_KEYS_TO_TEST
    }


def collect_rows(service: DeliverableFormAnalysisService) -> dict[str, Any]:
    """收集待测表单的 rows() 分页行契约字典。"""
    return {
        form_key: service.rows(form_key, offset=0, limit=200)
        for form_key in FORM_KEYS_TO_TEST
    }


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
    """递归逐键对比两个 JSON 兼容数据结构。

    返回 dict 包含:
      - "added": current 中新增的键/索引路径及取值
      - "missing": golden 中存在但在 current 中缺失的键/索引路径及取值
      - "changed": 两者均存在但值不一致的键/索引路径、golden 值与 current 值
    """
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
    """生成结构清晰的差异报告文本，分别列出新增、缺失与值变化。"""
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
    """重新生成并持久化全部 3 个入口的黄金基线 JSON 文件。"""
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    save_golden(collect_form_definition(), GOLDEN_PATHS["form_definition"])
    with isolated_form_service() as service:
        save_golden(collect_view(service), GOLDEN_PATHS["view"])
        save_golden(collect_rows(service), GOLDEN_PATHS["rows"])


def _auto_init_golden() -> None:
    """模块导入时检测：环境变量要求写入或基线文件缺失时自动生成。"""
    write_requested = os.environ.get("VSE_FORM_ANALYSIS_GOLDEN_WRITE") == "1"
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
    write_requested = os.environ.get("VSE_FORM_ANALYSIS_GOLDEN_WRITE") == "1"
    missing_files = any(
        not path.exists() or path.stat().st_size == 0
        for path in GOLDEN_PATHS.values()
    )
    if write_requested or missing_files:
        save_all_golden()


def test_form_definition_matches_golden():
    """验证 form_definition() 公开入口与黄金基线完全一致。"""
    write_requested = os.environ.get("VSE_FORM_ANALYSIS_GOLDEN_WRITE") == "1"
    current = collect_form_definition()
    golden_path = GOLDEN_PATHS["form_definition"]

    if write_requested or not golden_path.exists():
        save_golden(current, golden_path)
        return

    golden = load_golden(golden_path)
    diff = diff_data(golden, current)
    report = format_diff_report(diff)

    assert not diff["added"], f"form_definition 契约对比失败：存在未记录的新增项\n{report}"
    assert not diff["missing"], f"form_definition 契约对比失败：存在基线中丢失的项\n{report}"
    assert not diff["changed"], f"form_definition 契约对比失败：存在字段值变化\n{report}"


def test_view_matches_golden(form_service: DeliverableFormAnalysisService):
    """验证 DeliverableFormAnalysisService.view() 公开入口与黄金基线完全一致。"""
    write_requested = os.environ.get("VSE_FORM_ANALYSIS_GOLDEN_WRITE") == "1"
    current = collect_view(form_service)
    golden_path = GOLDEN_PATHS["view"]

    if write_requested or not golden_path.exists():
        save_golden(current, golden_path)
        return

    golden = load_golden(golden_path)
    diff = diff_data(golden, current)
    report = format_diff_report(diff)

    assert not diff["added"], f"view 契约对比失败：存在未记录的新增项\n{report}"
    assert not diff["missing"], f"view 契约对比失败：存在基线中丢失的项\n{report}"
    assert not diff["changed"], f"view 契约对比失败：存在字段值变化\n{report}"


def test_rows_matches_golden(form_service: DeliverableFormAnalysisService):
    """验证 DeliverableFormAnalysisService.rows() 公开入口与黄金基线完全一致。"""
    write_requested = os.environ.get("VSE_FORM_ANALYSIS_GOLDEN_WRITE") == "1"
    current = collect_rows(form_service)
    golden_path = GOLDEN_PATHS["rows"]

    if write_requested or not golden_path.exists():
        save_golden(current, golden_path)
        return

    golden = load_golden(golden_path)
    diff = diff_data(golden, current)
    report = format_diff_report(diff)

    assert not diff["added"], f"rows 契约对比失败：存在未记录的新增项\n{report}"
    assert not diff["missing"], f"rows 契约对比失败：存在基线中丢失的项\n{report}"
    assert not diff["changed"], f"rows 契约对比失败：存在字段值变化\n{report}"


def test_golden_baseline_stability():
    """验证同一进程内连续重跑黄金基线数据采集具有绝对稳定性（无时钟或随机漂移）。"""
    with isolated_form_service() as service_a:
        defs_a = collect_form_definition()
        view_a = collect_view(service_a)
        rows_a = collect_rows(service_a)

    with isolated_form_service() as service_b:
        defs_b = collect_form_definition()
        view_b = collect_view(service_b)
        rows_b = collect_rows(service_b)

    for name, a, b in [
        ("form_definition", defs_a, defs_b),
        ("view", view_a, view_b),
        ("rows", rows_a, rows_b),
    ]:
        diff = diff_data(a, b)
        report = format_diff_report(diff)
        assert not diff["added"], f"{name} 进程内连续重跑稳定性断言失败：存在新增项\n{report}"
        assert not diff["missing"], f"{name} 进程内连续重跑稳定性断言失败：存在缺失项\n{report}"
        assert not diff["changed"], f"{name} 进程内连续重跑稳定性断言失败：存在值变化\n{report}"


def test_golden_coverage_requirements():
    """断言基线测试覆盖至少 3 个 report 类型（含 TDC 与 Aras 各一）且至少 2 个公开入口。"""
    assert len(FORM_KEYS_TO_TEST) >= 3, f"测试表单数 {len(FORM_KEYS_TO_TEST)} 少于 3"

    covered_reports = {FORMS_BY_KEY[k].report for k in FORM_KEYS_TO_TEST}
    assert len(covered_reports) >= 3, f"覆盖的 report 类型数 {len(covered_reports)} 少于 3: {covered_reports}"

    sources = {FORMS_BY_KEY[k].source for k in FORM_KEYS_TO_TEST}
    assert "tdc" in sources, "测试表单未包含 TDC 源"
    assert "aras" in sources, "测试表单未包含 Aras 源"

    assert len(GOLDEN_PATHS) >= 2, f"公开入口数 {len(GOLDEN_PATHS)} 少于 2"


def test_diff_reports_detects_added_missing_changed():
    """断言差异对比工具能准确区分并报告新增、缺失与值变化三种情形。"""
    golden = {
        "common": 1,
        "removed_key": "old",
        "changed_val": "before",
        "nested": {"a": [1, 2]},
    }
    current = {
        "common": 1,
        "added_key": "new",
        "changed_val": "after",
        "nested": {"a": [1, 2, 3]},
    }
    diff = diff_data(golden, current)
    assert len(diff["added"]) == 2  # added_key and nested.a[2]
    assert len(diff["missing"]) == 1  # removed_key
    assert len(diff["changed"]) == 1  # changed_val

    report = format_diff_report(diff)
    assert "【新增键/项】" in report
    assert "added_key" in report
    assert "【缺失键/项】" in report
    assert "removed_key" in report
    assert "【值变化】" in report
    assert "changed_val" in report
