# -*- coding: utf-8 -*-
"""3D单签署日报：从 TDC 数模设计审核流程行计算指标并渲染邮件。

纯函数模块，不碰数据库和 Flask，便于单测。口径见需求规格
「3D单签署日报一键生成 需求规格」（2026-10-02 确认）：

- 一行 = 一个零件；按 ``流水单号`` 归并为一份 3D单，人数字段只取首行。
- 角色列里人名以「、」分隔，未签的人名带「(未签)」；``加签人员`` 不计数。
- ``已废弃`` 不计入任何统计；``已完成`` = 流程关闭 = 已锁定发布。
- 3D单完成 = 签署率 100% 或 状态已完成。
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from email.message import EmailMessage
from email.utils import formataddr, getaddresses
from typing import Any, Iterable, Mapping, Sequence

logger = logging.getLogger(__name__)

COUNTERSIGN_COLUMNS = (
    "造型", "总体工程", "CAE", "整车性能", "车身", "内外饰", "底盘", "动力", "空调电子",
    "尺寸工程", "冲压", "车身制造", "涂装", "总装", "新能源", "感知质量", "造型专家审核", "NVH",
)
APPROVAL_COLUMNS = ("设计工程师", "主任工程师", "专家/经理", "首席/总监")
ROLE_COLUMNS = COUNTERSIGN_COLUMNS + APPROVAL_COLUMNS
PHASE_COUNTERSIGN = "会签"
PHASE_APPROVAL = "审批"

REQUIRED_COLUMNS = (
    "流水单号", "项目/车型", "部门", "申请人", "申请日期", "零件名称",
    *ROLE_COLUMNS, "应签人数", "已签人数", "签署率", "待审批人员", "状态",
)

STATUS_DONE = "已完成"
STATUS_DISCARDED = "已废弃"

STAGE_COUNTERSIGN = "会签中"
STAGE_ADD_SIGN = "加签中"
STAGE_APPROVAL = "审批中"
STAGE_LOCK = "待锁定"
STAGE_ORDER = (STAGE_COUNTERSIGN, STAGE_ADD_SIGN, STAGE_APPROVAL, STAGE_LOCK)

UNASSIGNED = "未分配"
#: 角色列映射成这个值时，科室取该份单的「部门」（审批人通常就在起草人科室）。
APPLICANT_DEPARTMENT = "@部门"
STALL_REASON_PLACEHOLDER = "未填写原因"
#: 「@部门」归属时，申请部门 -> 实际科室（Lynch 10-02：ES科 的审批人归运营管理部）。
DEFAULT_APPLICANT_DEPARTMENTS: dict[str, str] = {"ES科": "运营管理部"}

#: 角色列→科室初始映射（待 Lynch 确认，可在页面「设置」里改）。
DEFAULT_ROLE_DEPARTMENTS: dict[str, str] = {
    "造型": "造型",
    "总体工程": "总布置",
    "CAE": "CAE",
    "整车性能": "整车性能",
    "车身": "车身",
    "内外饰": "内外饰",
    "底盘": "底盘",
    "动力": "动力",
    "空调电子": "电子电器",
    "尺寸工程": "尺寸工程",
    "冲压": "冲压",
    "车身制造": "车身制造",
    "涂装": "涂装",
    "总装": "总装",
    "新能源": "新能源",
    "感知质量": "感知质量",
    "造型专家审核": "造型",
    "NVH": "NVH",
    "设计工程师": APPLICANT_DEPARTMENT,
    "主任工程师": APPLICANT_DEPARTMENT,
    "专家/经理": APPLICANT_DEPARTMENT,
    "首席/总监": APPLICANT_DEPARTMENT,
}

_EMPTY_CELLS = {"", "none", "null", "nan"}
_NAME_SPLIT = re.compile(r"[、,，;；\s]+")
_UNSIGNED_SUFFIX = re.compile(r"[（(]\s*未签\s*[)）]$")
_FUZZY_STRIP = re.compile(r"[\s()（）\[\]【】<>《》]|LH|RH|左|右", re.IGNORECASE)


class MissingColumnsError(ValueError):
    """TDC 导出缺少生成日报所需的列。"""

    def __init__(self, missing: Sequence[str]):
        super().__init__("TDC 数据缺少关键列：" + "、".join(missing))
        self.missing = list(missing)


# ── 解析 ────────────────────────────────────────────────────────────


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    return "" if text.lower() in _EMPTY_CELLS else text


def _int(value: Any) -> int:
    text = _text(value)
    try:
        return int(float(text)) if text else 0
    except ValueError:
        return 0


def parse_rate(value: Any) -> float | None:
    """'100.00%' / 1.0 / '85' -> 百分数；无法解析返回 None。"""
    text = _text(value).replace("%", "")
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if isinstance(value, (int, float)) and number <= 1:
        number *= 100  # Excel 百分比单元格读出来是 0~1 的小数
    return number


def parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _text(value)
    match = re.match(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", text)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def parse_people(value: Any) -> list[tuple[str, bool]]:
    """角色列 -> [(人名, 已签)]；同列重复的人只保留一次，任一处未签即未签。"""
    seen: dict[str, bool] = {}
    for token in re.split(r"[、,，;；]+", _text(value)):
        token = token.strip()
        if not token:
            continue
        signed = _UNSIGNED_SUFFIX.search(token) is None
        name = _UNSIGNED_SUFFIX.sub("", token).strip()
        if not name or name.lower() in _EMPTY_CELLS:
            continue
        seen[name] = seen.get(name, True) and signed
    return list(seen.items())


def parse_name_list(value: Any) -> list[str]:
    names: list[str] = []
    for token in _NAME_SPLIT.split(_text(value)):
        token = _UNSIGNED_SUFFIX.sub("", token).strip()
        if token and token.lower() not in _EMPTY_CELLS and token not in names:
            names.append(token)
    return names


def check_columns(headers: Iterable[str]) -> None:
    present = {str(h or "").strip() for h in headers}
    missing = [name for name in REQUIRED_COLUMNS if name not in present]
    if missing:
        raise MissingColumnsError(missing)


# ── 长周期件匹配 ─────────────────────────────────────────────────────


def fuzzy_key(name: Any) -> str:
    return _FUZZY_STRIP.sub("", _text(name)).upper()


def long_cycle_hits(part_names: Iterable[str], long_cycle_names: Iterable[str]) -> dict[str, str]:
    """零件名 -> 命中的清单名。去空格、括号、左/右/LH/RH 后互相包含即命中。"""
    keys = [(fuzzy_key(item), _text(item)) for item in long_cycle_names]
    keys = [(key, item) for key, item in keys if len(key) >= 2]
    hits: dict[str, str] = {}
    for part in part_names:
        part_key = fuzzy_key(part)
        if len(part_key) < 2:
            continue
        for key, item in keys:
            if key in part_key or part_key in key:
                hits[_text(part)] = item
                break
    return hits


# ── 归并成 3D单 ──────────────────────────────────────────────────────


@dataclass
class Signer:
    name: str
    column: str
    phase: str
    signed: bool


@dataclass
class Flow:
    serial: str
    project: str
    department: str
    applicant: str
    applied_on: date | None
    status: str
    required: int
    signed: int
    rate: float | None
    pending: list[str]
    signers: list[Signer]
    parts: list[str] = field(default_factory=list)
    long_cycle_parts: list[str] = field(default_factory=list)

    @property
    def is_closed(self) -> bool:
        return self.status == STATUS_DONE

    @property
    def is_complete(self) -> bool:
        return self.is_closed or (self.rate is not None and self.rate >= 100 - 1e-9)

    def unsigned(self, phase: str | None = None) -> list[Signer]:
        return [s for s in self.signers if not s.signed and (phase is None or s.phase == phase)]

    @property
    def countersign_required(self) -> int:
        return sum(1 for s in self.signers if s.phase == PHASE_COUNTERSIGN)

    @property
    def countersign_signed(self) -> int:
        return sum(1 for s in self.signers if s.phase == PHASE_COUNTERSIGN and s.signed)

    @property
    def add_sign_pending(self) -> list[str]:
        """待审批人员里不在任何角色列的人：正在处理的加签人。"""
        listed = {s.name for s in self.signers}
        return [name for name in self.pending if name not in listed]

    @property
    def stage(self) -> str:
        if self.is_closed:
            return STATUS_DONE
        if self.unsigned(PHASE_COUNTERSIGN):
            return STAGE_COUNTERSIGN
        if self.add_sign_pending:
            return STAGE_ADD_SIGN
        if self.unsigned(PHASE_APPROVAL):
            return STAGE_APPROVAL
        return STAGE_LOCK

    @property
    def is_long_cycle(self) -> bool:
        return bool(self.long_cycle_parts)


def _signers(row: Mapping[str, Any]) -> list[Signer]:
    signers: list[Signer] = []
    for column in ROLE_COLUMNS:
        phase = PHASE_COUNTERSIGN if column in COUNTERSIGN_COLUMNS else PHASE_APPROVAL
        for name, signed in parse_people(row.get(column)):
            signers.append(Signer(name=name, column=column, phase=phase, signed=signed))
    return signers


def build_flows(rows: Iterable[Mapping[str, Any]]) -> list[Flow]:
    """零件行 -> 3D单（按流水单号，保持首次出现顺序）。已废弃的单不返回。"""
    flows: dict[str, Flow] = {}
    for row in rows:
        serial = _text(row.get("流水单号"))
        if not serial:
            continue
        flow = flows.get(serial)
        if flow is None:
            flow = Flow(
                serial=serial,
                project=_text(row.get("项目/车型")),
                department=_text(row.get("部门")),
                applicant=_text(row.get("申请人")),
                applied_on=parse_date(row.get("申请日期")),
                status=_text(row.get("状态")),
                required=_int(row.get("应签人数")),
                signed=_int(row.get("已签人数")),
                rate=parse_rate(row.get("签署率")),
                pending=parse_name_list(row.get("待审批人员")),
                signers=_signers(row),
            )
            flows[serial] = flow
        elif (_int(row.get("应签人数")), _int(row.get("已签人数"))) != (flow.required, flow.signed):
            logger.info("3D单 %s 各行签署人数不一致，取第一行", serial)
        flow.parts.append(_text(row.get("零件名称")))
    return [flow for flow in flows.values() if flow.status != STATUS_DISCARDED]


def filter_scope(flows: Iterable[Flow], projects: Sequence[str], departments: Sequence[str]) -> list[Flow]:
    project_set, department_set = set(projects), set(departments)
    return [
        flow for flow in flows
        if (not project_set or flow.project in project_set)
        and (not department_set or flow.department in department_set)
    ]


def scope_options(flows: Iterable[Flow]) -> dict[str, list[str]]:
    flows = list(flows)
    return {
        "projects": sorted({f.project for f in flows if f.project}),
        "departments": sorted({f.department for f in flows if f.department}),
    }


def mark_long_cycle(flows: Iterable[Flow], confirmed: Mapping[str, bool]) -> None:
    """按已确认的命中结果（零件名 -> 是否长周期）标记长周期零件。"""
    for flow in flows:
        flow.long_cycle_parts = [part for part in flow.parts if confirmed.get(part)]


# ── 指标 ────────────────────────────────────────────────────────────


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator * 100.0 / denominator, 1) if denominator else None


def metrics(flows: Sequence[Flow], *, long_cycle: bool = False) -> dict[str, Any]:
    """一套汇总指标。长周期那套：份数按含长周期零件的单，零件数只数长周期零件。"""
    if long_cycle:
        flows = [f for f in flows if f.is_long_cycle]

    def parts_of(flow: Flow) -> int:
        return len(flow.long_cycle_parts) if long_cycle else len(flow.parts)

    parts = sum(parts_of(f) for f in flows)
    locked = sum(parts_of(f) for f in flows if f.is_closed)
    cs_required = sum(f.countersign_required for f in flows)
    cs_signed = sum(f.countersign_signed for f in flows)
    required = sum(f.required for f in flows)
    signed = sum(f.signed for f in flows)
    return {
        "flows": len(flows),
        "parts": parts,
        "countersignRate": _ratio(cs_signed, cs_required),
        "totalRate": _ratio(signed, required),
        "countersignDone": sum(1 for f in flows if not f.unsigned(PHASE_COUNTERSIGN)),
        "complete": sum(1 for f in flows if f.is_complete),
        "locked": locked,
        "t2Rate": _ratio(locked, parts),
    }


def summary(flows: Sequence[Flow]) -> dict[str, Any]:
    return {"total": metrics(flows), "longCycle": metrics(flows, long_cycle=True)}


def deltas(current: Mapping[str, Any], previous: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not previous:
        return None
    result: dict[str, Any] = {}
    for group, values in current.items():
        before = previous.get(group) or {}
        result[group] = {}
        for key, value in values.items():
            old = before.get(key)
            if value is None or old is None:
                result[group][key] = None
            elif isinstance(value, float) or isinstance(old, float):
                result[group][key] = round(float(value) - float(old), 1)
            else:
                result[group][key] = int(value) - int(old)
    return result


# ── 科室归属与欠账 ───────────────────────────────────────────────────


def resolve_department(
    signer: Signer,
    flow: Flow,
    role_departments: Mapping[str, str],
    person_departments: Mapping[str, str],
    applicant_departments: Mapping[str, str] | None = None,
) -> str:
    override = _text(person_departments.get(signer.name))
    if override:
        return override
    mapped = _text(role_departments.get(signer.column))
    if mapped == APPLICANT_DEPARTMENT:
        aliased = _text((applicant_departments or {}).get(flow.department))
        return aliased or flow.department or UNASSIGNED
    return mapped or UNASSIGNED


def owed_by_department(
    flows: Sequence[Flow],
    phase: str,
    role_departments: Mapping[str, str],
    person_departments: Mapping[str, str],
    applicant_departments: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """未完成单里每个未签人的欠账份数，按科室分组；科室、人都按份数从多到少。"""
    counts: dict[str, dict[str, set[str]]] = {}
    person_dept: dict[str, str] = {}
    for flow in flows:
        if flow.is_complete:
            continue  # 已完成（含签署率<100%的）不进欠账
        for signer in flow.unsigned(phase):
            dept = person_dept.setdefault(
                signer.name, resolve_department(signer, flow, role_departments, person_departments, applicant_departments)
            )
            counts.setdefault(dept, {}).setdefault(signer.name, set()).add(flow.serial)
    groups = []
    for dept, people in counts.items():
        items = sorted(
            ({"name": name, "count": len(serials), "serials": sorted(serials)} for name, serials in people.items()),
            key=lambda item: (-item["count"], item["name"]),
        )
        groups.append({"department": dept, "total": sum(i["count"] for i in items), "people": items})
    groups.sort(key=lambda g: (g["department"] == UNASSIGNED, -g["total"], g["department"]))
    return groups


def flow_table(
    flows: Sequence[Flow],
    today: date,
    role_departments: Mapping[str, str],
    person_departments: Mapping[str, str],
    applicant_departments: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """未关闭的单：按当前阶段、已申请天数从长到短排。"""
    rows = []
    for flow in flows:
        if flow.is_closed:
            continue
        unsigned = [
            {"name": s.name, "department": resolve_department(s, flow, role_departments, person_departments, applicant_departments),
             "phase": s.phase}
            for s in flow.unsigned()
        ]
        unsigned += [{"name": name, "department": "加签", "phase": "加签"} for name in flow.add_sign_pending]
        first_part = next((p for p in flow.parts if p), "")
        rows.append({
            "serial": flow.serial,
            "part": first_part + (f" 等{len(flow.parts)}件" if len(flow.parts) > 1 else ""),
            "department": flow.department,
            "applicant": flow.applicant,
            "stage": flow.stage,
            "unsigned": unsigned,
            "countersignRate": _ratio(flow.countersign_signed, flow.countersign_required),
            "totalRate": _ratio(flow.signed, flow.required),
            "days": (today - flow.applied_on).days if flow.applied_on else None,
            "stallReason": STALL_REASON_PLACEHOLDER,
            "longCycle": flow.is_long_cycle,
        })
    stage_rank = {stage: index for index, stage in enumerate(STAGE_ORDER)}
    rows.sort(key=lambda r: (stage_rank.get(r["stage"], 99), -(r["days"] or 0), r["serial"]))
    return rows


def unassigned_people(owed: Iterable[Sequence[Mapping[str, Any]]]) -> list[str]:
    names: list[str] = []
    for groups in owed:
        for group in groups:
            if group["department"] == UNASSIGNED:
                names += [p["name"] for p in group["people"] if p["name"] not in names]
    return names


# ── 收件人 ──────────────────────────────────────────────────────────


def parse_recipients(text: Any) -> list[tuple[str, str]]:
    """'"张三"<a@x.com>; 李四 <b@x.com>' -> [(姓名, 邮箱)]，按邮箱去重。"""
    raw = re.sub(r"[;；\n\r]+", ",", _text(text))
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for name, address in getaddresses([raw]):
        address = address.strip()
        if "@" not in address or address.lower() in seen:
            continue
        seen.add(address.lower())
        result.append((name.strip().strip('"'), address))
    return result


def recipients_for(
    to_text: str,
    cc_text: str,
    address_book: Sequence[tuple[str, str]],
    owed_names: Iterable[str],
) -> dict[str, list[tuple[str, str]]]:
    """收件人 = 固定名单 + 当天有未签单且在通讯录里、还不在名单中的人。"""
    to = parse_recipients(to_text)
    cc = parse_recipients(cc_text)
    listed = {address.lower() for _, address in to + cc}
    by_name: dict[str, tuple[str, str]] = {}
    for name, address in address_book:
        if name and name not in by_name:
            by_name[name] = (name, address)
    added = []
    for name in owed_names:
        entry = by_name.get(name)
        if entry and entry[1].lower() not in listed:
            listed.add(entry[1].lower())
            added.append(entry)
    return {"to": to + added, "cc": cc, "added": added}


# ── 渲染 ────────────────────────────────────────────────────────────


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f}%"


def _delta(value: Any, *, percent: bool = False) -> str:
    if value is None:
        return ""
    if percent:
        return f"({value:+.1f}%)"
    return f"({value:+d})"


def summary_lines(
    *,
    project_label: str,
    region: str,
    current: Mapping[str, Any],
    delta: Mapping[str, Any] | None,
) -> list[str]:
    total, long = current["total"], current["longCycle"]
    d_total = (delta or {}).get("total") or {}
    d_long = (delta or {}).get("longCycle") or {}

    def line(values: Mapping[str, Any], d: Mapping[str, Any], t2_label: str) -> str:
        return (
            f"会签签单率{_pct(values['countersignRate'])}{_delta(d.get('countersignRate'), percent=True)}，"
            f"总签单率{_pct(values['totalRate'])}{_delta(d.get('totalRate'), percent=True)}，"
            f"3D单完成{values['complete']}{_delta(d.get('complete'))}/{values['flows']}份，"
            f"{t2_label}{_pct(values['t2Rate'])}{_delta(d.get('t2Rate'), percent=True)}，"
            f"已锁定发布{values['locked']}{_delta(d.get('locked'))}/{values['parts']}"
        )

    return [
        f"{project_label}-{region}-3D单流程共{total['flows']}份，涉及零件{total['parts']}个，"
        f"其中长周期件流程共{long['flows']}份，涉及零件{long['parts']}个。",
        "长周期：" + line(long, d_long, "LLP T2发布率") + "；",
        "总：" + line(total, d_total, "T2发布率") + "。",
    ]


def subject_for(project_label: str, region: str, today: date) -> str:
    return f"{project_label}项目3D单签署进展-{region}-{today:%Y%m%d}"


_FONT = "font-family:'Microsoft YaHei',Arial,sans-serif;font-size:14px;color:#1f2329;"
_TH = "border:1px solid #c9cdd4;background:#f2f3f5;padding:4px 8px;text-align:left;white-space:nowrap;"
_TD = "border:1px solid #c9cdd4;padding:4px 8px;vertical-align:top;"
_BAR_COLORS = {PHASE_COUNTERSIGN: "#3370ff", PHASE_APPROVAL: "#ff8800"}


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _owed_html(title: str, groups: Sequence[Mapping[str, Any]], phase: str) -> str:
    if not groups:
        return f'<p style="{_FONT}"><b>{_e(title)}</b>：无未签</p>'
    peak = max(p["count"] for g in groups for p in g["people"]) or 1
    color = _BAR_COLORS.get(phase, "#3370ff")
    rows = []
    for group in groups:
        people = group["people"]
        for index, person in enumerate(people):
            width = max(4, round(person["count"] * 240 / peak))
            dept_cell = (
                f'<td rowspan="{len(people)}" style="{_TD}white-space:nowrap;">'
                f'<b>{_e(group["department"])}</b><br><span style="color:#646a73;">共{group["total"]}份</span></td>'
                if index == 0 else ""
            )
            rows.append(
                f"<tr>{dept_cell}"
                f'<td style="{_TD}white-space:nowrap;">{_e(person["name"])}</td>'
                f'<td style="{_TD}"><table cellpadding="0" cellspacing="0" style="border-collapse:collapse;"><tr>'
                f'<td style="background:{color};width:{width}px;height:14px;font-size:1px;line-height:1px;">&nbsp;</td>'
                f'<td style="padding-left:6px;{_FONT}">{person["count"]}</td></tr></table></td></tr>'
            )
    return (
        f'<p style="{_FONT}"><b>{_e(title)}</b></p>'
        f'<table cellpadding="0" cellspacing="0" style="border-collapse:collapse;{_FONT}">'
        f'<tr><th style="{_TH}">科室</th><th style="{_TH}">未签人</th><th style="{_TH}">未签3D单份数</th></tr>'
        + "".join(rows) + "</table>"
    )


def _unsigned_text(items: Sequence[Mapping[str, Any]]) -> str:
    return "、".join(f"{i['name']}({i['department']})" for i in items) or "—"


def _flows_html(rows: Sequence[Mapping[str, Any]]) -> str:
    if not rows:
        return f'<p style="{_FONT}">无未签</p>'
    headers = ("流水单号", "零件名称", "部门", "申请人", "当前阶段", "未签人(科室)", "会签/总签单率", "已申请天数", "停滞原因")
    body = []
    for row in rows:
        reason_style = "color:#f54a45;" if row["stallReason"] == STALL_REASON_PLACEHOLDER else ""
        cells = (
            _e(row["serial"]) + (' <span style="color:#f54a45;">[长周期]</span>' if row["longCycle"] else ""),
            _e(row["part"]),
            _e(row["department"]),
            _e(row["applicant"]),
            _e(row["stage"]),
            _e(_unsigned_text(row["unsigned"])),
            _e(f"{_pct(row['countersignRate'])}/{_pct(row['totalRate'])}"),
            _e("—" if row["days"] is None else row["days"]),
            f'<span style="{reason_style}">{_e(row["stallReason"])}</span>',
        )
        body.append("<tr>" + "".join(f'<td style="{_TD}">{cell}</td>' for cell in cells) + "</tr>")
    head = "".join(f'<th style="{_TH}">{_e(h)}</th>' for h in headers)
    return (
        f'<table cellpadding="0" cellspacing="0" style="border-collapse:collapse;{_FONT}">'
        f"<tr>{head}</tr>" + "".join(body) + "</table>"
    )


def _paragraphs(text: str) -> list[str]:
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def _link_html(text: str) -> str:
    escaped = _e(text)
    return re.sub(r"(https?://[^\s<]+)", r'<a href="\1">\1</a>', escaped)


def render_html(report: Mapping[str, Any]) -> str:
    lines = report["summaryLines"]
    parts = [f'<div style="{_FONT}line-height:1.7;">', "<p>各位领导、同事：</p>"]
    parts.append(f"<p>{_e(lines[0])}<br>{_e(lines[1])}<br>{_e(lines[2])}</p>")
    if report.get("deltaNote"):
        parts.append(f'<p style="color:#646a73;">{_e(report["deltaNote"])}</p>')
    for line in _paragraphs(report.get("planText", "")):
        parts.append(f"<p>{_e(line)}</p>")
    for line in _paragraphs(report.get("feishuLink", "")):
        parts.append(f"<p>{_link_html(line)}</p>")
    parts.append("<p><b>一、各科室未签人员欠账：</b></p>")
    parts.append(_owed_html("会签阶段", report["owed"][PHASE_COUNTERSIGN], PHASE_COUNTERSIGN))
    parts.append(_owed_html("审批阶段", report["owed"][PHASE_APPROVAL], PHASE_APPROVAL))
    parts.append("<p><b>二、各流程签署情况：</b></p>")
    parts.append(_flows_html(report["flows"]))
    parts.append("</div>")
    return "".join(parts)


def render_text(report: Mapping[str, Any]) -> str:
    out = ["各位领导、同事：", *report["summaryLines"]]
    if report.get("deltaNote"):
        out.append(report["deltaNote"])
    out += [""] + _paragraphs(report.get("planText", "")) + _paragraphs(report.get("feishuLink", ""))
    out += ["", "一、各科室未签人员欠账："]
    for phase, title in ((PHASE_COUNTERSIGN, "会签阶段"), (PHASE_APPROVAL, "审批阶段")):
        groups = report["owed"][phase]
        if not groups:
            out.append(f"{title}：无未签")
            continue
        out.append(f"{title}：")
        for group in groups:
            people = "、".join(f"{p['name']}{p['count']}" for p in group["people"])
            out.append(f"  {group['department']}（共{group['total']}份）：{people}")
    out += ["", "二、各流程签署情况："]
    if not report["flows"]:
        out.append("无未签")
    for row in report["flows"]:
        days = "—" if row["days"] is None else f"{row['days']}天"
        out.append(
            f"  {row['serial']} | {row['part']} | {row['department']} | {row['applicant']} | {row['stage']} | "
            f"{_unsigned_text(row['unsigned'])} | {_pct(row['countersignRate'])}/{_pct(row['totalRate'])} | "
            f"{days} | {row['stallReason']}"
        )
    return "\n".join(out) + "\n"


def build_eml(
    *,
    subject: str,
    to: Sequence[tuple[str, str]],
    cc: Sequence[tuple[str, str]],
    text_body: str,
    html_body: str,
) -> bytes:
    """未发送的 .eml 草稿：Outlook / 飞书邮件打开后可直接编辑发送。"""
    message = EmailMessage()
    message["Subject"] = subject
    if to:
        message["To"] = ", ".join(formataddr(item) for item in to)
    if cc:
        message["Cc"] = ", ".join(formataddr(item) for item in cc)
    message["X-Unsent"] = "1"
    message.set_content(text_body)
    message.add_alternative(f"<html><body>{html_body}</body></html>", subtype="html")
    return message.as_bytes()


# ── 组装 ────────────────────────────────────────────────────────────


def project_label(projects: Sequence[str], flows: Sequence[Flow]) -> str:
    chosen = list(projects) or sorted({f.project for f in flows if f.project})
    return "&".join(chosen) or "全部项目"


def build_report(
    flows: Sequence[Flow],
    *,
    projects: Sequence[str],
    today: date,
    region: str,
    plan_text: str,
    feishu_link: str,
    role_departments: Mapping[str, str],
    person_departments: Mapping[str, str],
    previous: Mapping[str, Any] | None,
    applicant_departments: Mapping[str, str] | None = None,
    previous_date: date | None,
) -> dict[str, Any]:
    label = project_label(projects, flows)
    current = summary(flows)
    delta = deltas(current, previous)
    delta_note = ""
    if delta is not None and previous_date is not None and (today - previous_date).days != 1:
        delta_note = f"注：括号内为较{previous_date:%m-%d}的变化。"
    owed = {
        phase: owed_by_department(flows, phase, role_departments, person_departments, applicant_departments)
        for phase in (PHASE_COUNTERSIGN, PHASE_APPROVAL)
    }
    report: dict[str, Any] = {
        "subject": subject_for(label, region, today),
        "projectLabel": label,
        "summary": current,
        "delta": delta,
        "deltaNote": delta_note,
        "summaryLines": summary_lines(project_label=label, region=region, current=current, delta=delta),
        "planText": plan_text,
        "feishuLink": feishu_link,
        "owed": owed,
        "flows": flow_table(flows, today, role_departments, person_departments, applicant_departments),
        "unassigned": unassigned_people(owed.values()),
    }
    report["html"] = render_html(report)
    report["text"] = render_text(report)
    return report
