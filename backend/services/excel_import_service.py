"""交付物 Excel 导入引擎。

支持列名模糊匹配 + 字段标准化 + 错误行收集。
R-02: 所有 SQL 参数化
R-03: 文件操作使用 with 语句
"""

import logging
from pathlib import Path

import openpyxl

from services.db import DBManager

logger = logging.getLogger("VSE_TOOLBOX.excel_import")

# ---------------------------------------------------------------------------
# 列名模糊匹配映射
# ---------------------------------------------------------------------------

# 造车问题列名映射（支持多种中文/英文列名）
ISSUE_COLUMN_MAP = {
    # 标准字段名 -> 匹配的列名列表（小写）
    "priority": ["优先级", "priority", "等级"],
    "component": ["零部件", "零部件名称", "component", "零件", "部件"],
    "description": ["问题描述", "描述", "description", "问题"],
    "department": ["责任科室", "科室", "department", "部门"],
    "assignee": ["责任工程师", "工程师", "assignee", "负责人"],
    "status": ["状态", "status"],
    "part_system": ["零件总成", "总成", "part_system"],
    "sub_system": ["子系统", "sub_system"],
    "root_cause": ["问题原因", "原因分析", "root_cause", "原因"],
    "short_term_action": ["短期措施", "短期", "short_term"],
    "long_term_action": ["长期措施", "长期", "long_term"],
    "cutoff_point": ["断点时间", "断点", "cutoff"],
    "action_plan": ["行动计划", "行动", "action_plan"],
}

# EWO/NCR 列名映射
EWO_COLUMN_MAP = {
    "type": ["类型", "type", "EWO/NCR"],
    "title": ["标题", "title", "名称", "问题标题"],
    "description": ["描述", "description", "问题描述"],
    "severity": ["严重程度", "severity", "等级", "严重度"],
    "status": ["状态", "status"],
    "department": ["责任科室", "科室", "department", "部门"],
    "assignee": ["责任工程师", "工程师", "assignee", "负责人"],
    "raised_date": ["提出日期", "raised_date", "日期"],
    "target_date": ["目标日期", "target_date", "计划完成"],
}

# TIR 列名映射
TIR_COLUMN_MAP = {
    "title": ["标题", "title", "名称", "试验标题"],
    "description": ["描述", "description", "试验描述"],
    "category": ["试验类型", "category", "类型"],
    "status": ["状态", "status"],
    "department": ["责任科室", "科室", "department", "部门"],
    "assignee": ["责任工程师", "工程师", "assignee", "负责人"],
    "test_date": ["试验日期", "test_date", "日期"],
    "result": ["试验结果", "result", "结果"],
}


def _match_column(header: str, column_map: dict[str, list[str]]) -> str | None:
    """将 Excel 列头匹配到标准字段名。优先精确匹配，其次子串匹配。"""
    header_clean = header.strip()
    header_lower = header_clean.lower()

    # 第一轮：精确匹配（最高优先级）
    for field_name, aliases in column_map.items():
        for alias in aliases:
            if header_lower == alias.lower():
                return field_name

    # 第二轮：别名是表头的子串（表头更长，如 "责任科室(必填)" 匹配 "责任科室"）
    for field_name, aliases in column_map.items():
        for alias in aliases:
            if alias.lower() in header_lower:
                return field_name

    return None


def _read_excel(file_path: Path) -> tuple[list[str], list[list[str]]]:
    """读取 Excel 文件，返回 (headers, rows)。仅读取第一个 sheet。"""
    allowed_suffixes = {".xlsx", ".xls", ".xlsm"}
    if file_path.suffix.lower() not in allowed_suffixes:
        raise ValueError(f"不支持的文件格式: {file_path.suffix}，请使用 .xlsx 或 .xls 文件")
    wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    ws = wb.active
    rows_iter = ws.iter_rows(values_only=True)

    # 读取表头
    headers = []
    first_row = next(rows_iter, None)
    if first_row:
        headers = [str(c).strip() if c is not None else "" for c in first_row]

    # 读取数据行
    rows = []
    for row in rows_iter:
        cells = [str(c).strip() if c is not None else "" for c in row]
        if any(cells):  # 跳过全空行
            rows.append(cells)

    wb.close()
    return headers, rows


def _standardize_status(value: str, valid_values: list[str]) -> str | None:
    """标准化状态字段。无法识别时返回 None 而非静默回退。"""
    if not value:
        return None
    v = value.strip().lower()
    # 中文→英文映射
    status_map = {
        "待处理": "open", "未处理": "open", "新建": "open", "open": "open",
        "处理中": "in_progress", "进行中": "in_progress", "调查中": "investigating",
        "in_progress": "in_progress", "investigating": "investigating",
        "已解决": "resolved", "已关闭": "closed", "closed": "closed",
        "草稿": "draft", "已提交": "submitted", "已批准": "approved", "已拒绝": "rejected",
        "draft": "draft", "submitted": "submitted", "approved": "approved", "rejected": "rejected",
    }
    mapped = status_map.get(v, v)
    if mapped in valid_values:
        return mapped
    logger.warning("无法识别的状态值: '%s'，有效值: %s", value, valid_values)
    return None


def _standardize_priority(value: str) -> str:
    """标准化优先级字段。"""
    if not value:
        return "P1"
    v = value.strip()
    # 精确匹配 P0-P3（必须先于中文匹配，避免 "P3" 中的 "中" 被误识别）
    if v.upper() in ("P0", "P1", "P2", "P3"):
        return v.upper()
    # 中文映射（仅当非 P0-P3 格式时）
    vl = v.lower()
    if "紧急" in v or "critical" in vl:
        return "P0"
    if "高" in v or "high" in vl:
        return "P1"
    if "中" in v or "medium" in vl:
        return "P2"
    return "P3"


def _standardize_severity(value: str) -> str:
    """标准化严重程度字段。"""
    if not value:
        return "minor"
    v = value.strip()
    # 精确匹配英文
    vl = v.lower()
    if vl in ("critical", "major", "minor"):
        return vl
    # 中文精确匹配（避免 "非严重" 误匹配 "严重"）
    severity_cn = {"严重": "critical", "重要": "major", "主要": "major", "一般": "minor", "轻微": "minor"}
    for cn, en in severity_cn.items():
        if v == cn:
            return en
    # 英文子串匹配
    if "critical" in vl:
        return "critical"
    if "major" in vl:
        return "major"
    return "minor"


def _standardize_ewo_type(value: str) -> str:
    """标准化 EWO/NCR 类型。"""
    if not value:
        return "EWO"
    v = value.strip().upper()
    if v in ("EWO", "NCR"):
        return v
    if "NCR" in v:
        return "NCR"
    return "EWO"


def _row_to_issue(headers: list[str], row: list[str], column_map: dict) -> dict | None:
    """将一行数据转换为 issue 字典。返回 None 表示跳过。"""
    mapped = {}
    for i, header in enumerate(headers):
        if i < len(row):
            field = _match_column(header, column_map)
            if field:
                mapped[field] = row[i]

    # 必填字段检查
    if not mapped.get("component") or not mapped.get("description") or not mapped.get("department"):
        return None

    return {
        "priority": _standardize_priority(mapped.get("priority", "")),
        "component": mapped["component"],
        "description": mapped["description"],
        "department": mapped["department"],
        "assignee": mapped.get("assignee") or None,
        "status": _standardize_status(mapped.get("status", ""), ["open", "in_progress", "resolved", "closed"]) or "open",
        "part_system": mapped.get("part_system") or None,
        "sub_system": mapped.get("sub_system") or None,
        "root_cause": mapped.get("root_cause") or None,
        "short_term_action": mapped.get("short_term_action") or None,
        "long_term_action": mapped.get("long_term_action") or None,
        "cutoff_point": mapped.get("cutoff_point") or None,
        "action_plan": mapped.get("action_plan") or None,
        "source": "excel_import",
    }


def _row_to_ewo(headers: list[str], row: list[str], column_map: dict) -> dict | None:
    """将一行数据转换为 EWO 字典。返回 None 表示跳过。"""
    mapped = {}
    for i, header in enumerate(headers):
        if i < len(row):
            field = _match_column(header, column_map)
            if field:
                mapped[field] = row[i]

    if not mapped.get("title"):
        return None

    return {
        "type": _standardize_ewo_type(mapped.get("type", "")),
        "title": mapped["title"],
        "description": mapped.get("description") or None,
        "severity": _standardize_severity(mapped.get("severity", "")),
        "status": _standardize_status(mapped.get("status", ""), ["open", "investigating", "resolved", "closed"]) or "open",
        "department": mapped.get("department") or None,
        "assignee": mapped.get("assignee") or None,
        "raised_date": mapped.get("raised_date") or None,
        "target_date": mapped.get("target_date") or None,
        "source": "excel_import",
    }


def _row_to_tir(headers: list[str], row: list[str], column_map: dict) -> dict | None:
    """将一行数据转换为 TIR 字典。返回 None 表示跳过。"""
    mapped = {}
    for i, header in enumerate(headers):
        if i < len(row):
            field = _match_column(header, column_map)
            if field:
                mapped[field] = row[i]

    if not mapped.get("title"):
        return None

    return {
        "title": mapped["title"],
        "description": mapped.get("description") or None,
        "category": mapped.get("category") or None,
        "status": _standardize_status(mapped.get("status", ""), ["draft", "submitted", "approved", "rejected"]) or "draft",
        "department": mapped.get("department") or None,
        "assignee": mapped.get("assignee") or None,
        "test_date": mapped.get("test_date") or None,
        "result": mapped.get("result") or None,
        "source": "excel_import",
    }


# ---------------------------------------------------------------------------
# 公开导入函数
# ---------------------------------------------------------------------------

def import_issues_from_excel(file_path: Path, source_file: str | None = None) -> dict:
    """从 Excel 导入造车问题。返回 {created, skipped, errors}。"""
    headers, rows = _read_excel(file_path)
    if not headers:
        return {"created": 0, "skipped": 0, "errors": ["Excel 文件为空或无法读取表头"]}

    created, skipped, errors = 0, 0, []
    for idx, row in enumerate(rows, start=2):  # 从第2行开始（第1行是表头）
        try:
            data = _row_to_issue(headers, row, ISSUE_COLUMN_MAP)
            if data is None:
                skipped += 1
                errors.append(f"第{idx}行：缺少必填字段（零部件/问题描述/责任科室），已跳过")
                continue
            data["source_file"] = source_file
            DBManager.create_issue(data)
            created += 1
        except Exception as e:
            errors.append(f"第{idx}行：导入失败")

    return {"created": created, "skipped": skipped, "errors": errors}


def import_ewo_from_excel(file_path: Path, source_file: str | None = None) -> dict:
    """从 Excel 导入 EWO/NCR。返回 {created, skipped, errors}。"""
    headers, rows = _read_excel(file_path)
    if not headers:
        return {"created": 0, "skipped": 0, "errors": ["Excel 文件为空或无法读取表头"]}

    created, skipped, errors = 0, 0, []
    for idx, row in enumerate(rows, start=2):
        try:
            data = _row_to_ewo(headers, row, EWO_COLUMN_MAP)
            if data is None:
                skipped += 1
                errors.append(f"第{idx}行：缺少必填字段（标题），已跳过")
                continue
            data["source_file"] = source_file
            DBManager.create_ewo(data)
            created += 1
        except Exception as e:
            errors.append(f"第{idx}行：导入失败")

    return {"created": created, "skipped": skipped, "errors": errors}


def import_tir_from_excel(file_path: Path, source_file: str | None = None) -> dict:
    """从 Excel 导入 TIR。返回 {created, skipped, errors}。"""
    headers, rows = _read_excel(file_path)
    if not headers:
        return {"created": 0, "skipped": 0, "errors": ["Excel 文件为空或无法读取表头"]}

    created, skipped, errors = 0, 0, []
    for idx, row in enumerate(rows, start=2):
        try:
            data = _row_to_tir(headers, row, TIR_COLUMN_MAP)
            if data is None:
                skipped += 1
                errors.append(f"第{idx}行：缺少必填字段（标题），已跳过")
                continue
            data["source_file"] = source_file
            DBManager.create_tir(data)
            created += 1
        except Exception as e:
            errors.append(f"第{idx}行：导入失败")

    return {"created": created, "skipped": skipped, "errors": errors}
