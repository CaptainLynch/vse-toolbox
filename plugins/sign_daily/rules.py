# -*- coding: utf-8 -*-
"""3D单签署日报 v2.0 口径：解析、人员归属、长周期判定、指标与日变化（纯函数）。

规格见 Claude Docs「3D单签署进展日报插件 需求规格 v2.0」，条款编号
（P1–P9、A1–A11、L1–L6、D1–D7、G1–G8、T1–T4）在下方注释里原样引用。
本模块不碰数据库、Flask 和宿主，输入是行数据和配置，输出是判定结果。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Iterable, Mapping, Sequence

# ── 列与常量（§2 术语）──────────────────────────────────────────────

COUNTERSIGN_COLUMNS = (
    "造型", "总体工程", "CAE", "整车性能", "车身", "内外饰", "底盘", "动力", "空调电子",
    "尺寸工程", "冲压", "车身制造", "涂装", "总装", "新能源", "感知质量", "造型专家审核", "NVH",
)
INTERNAL_COLUMNS = ("车身", "内外饰")
APPROVAL_COLUMNS = ("设计工程师", "主任工程师", "专家/经理", "首席/总监")
ROLE_COLUMNS = COUNTERSIGN_COLUMNS + APPROVAL_COLUMNS
ADD_SIGN_COLUMN = "加签人员"
PHASE_COUNTERSIGN = "会签"
PHASE_APPROVAL = "审批"

#: 外部列的区域显示名（A6）；没列出的显示列名本身。
AREA_DISPLAY = {"空调电子": "空调电子/ES科"}

REQUIRED_COLUMNS = (
    "流水单号", "项目/车型", "部门", "申请人", "申请日期", "零件号", "零件名称",
    *ROLE_COLUMNS, ADD_SIGN_COLUMN, "应签人数", "已签人数", "未签人数", "签署率", "待审批人员", "状态",
)

STATUS_DONE = "已完成"
STATUS_DISCARDED = "已废弃"
#: 见过的在途状态值；其余取值也按在途处理，但记为异常（P6）。
KNOWN_IN_FLIGHT_STATUSES = frozenset({"进行中", "审批中"})

CURRENT_DEPARTMENTS = ("车身科", "车体科", "内饰科", "外饰科", "车体架构集成科")
HISTORY_DEPARTMENTS = ("结构工程科", "视觉工程科")

GROUP_ADD_UNKNOWN = "加签（区域未知）"
GROUP_CONFLICT = "同名待确认"
GROUP_HISTORY = "历史科室待拆分"
APPROVER_UNREGISTERED = "未在册"
SPECIAL_SECTION_GROUPS = ("车身（未在册）", "内外饰（未在册）", GROUP_HISTORY, GROUP_CONFLICT)

STAGE_COUNTERSIGN = "会签中"
STAGE_APPROVAL = "审批中"
STAGE_RETURNED = "退回修改"
STAGE_DRAFT = "待提交"
STAGE_LOCK = "待锁定"
_STAGE_RANK = {STAGE_COUNTERSIGN: 0, STAGE_APPROVAL: 1, STAGE_RETURNED: 2, STAGE_DRAFT: 3, STAGE_LOCK: 4}

KIND_UNSIGNED = "unsigned"  # 角色列里带未签，且在待审批人员里
KIND_RETURNED = "returned"  # 已签的设计工程师，单被退回（A13）
KIND_ADD_SIGN = "addSign"  # 不在任何角色列的待审批人（A13）

MINUS = "−"  # D5：负数写数学减号

_EMPTY_CELLS = {"", "none", "null", "nan"}
_PEOPLE_SPLIT = re.compile(r"[、,，;；\r\n]+")
_UNSIGNED_MARK = re.compile(r"\(\s*未签\s*\)")
_BRACKETS = re.compile(r"\([^()]*\)|\[[^\[\]]*\]|【[^【】]*】")
_TRAILING_DIGITS = re.compile(r"\d+$")


class MissingColumnsError(ValueError):
    """TDC 导出缺少生成日报所需的列（P1）。"""

    def __init__(self, missing: Sequence[str]):
        super().__init__("TDC 数据缺少关键列：" + "、".join(missing))
        self.missing = list(missing)


def check_columns(headers: Iterable[Any]) -> None:
    present = {str(h or "").strip() for h in headers}
    missing = [name for name in REQUIRED_COLUMNS if name not in present]
    if missing:
        raise MissingColumnsError(missing)


# ── 基础解析 ────────────────────────────────────────────────────────


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    return "" if text.lower() in _EMPTY_CELLS else text


def cell_text(value: Any) -> str:
    """单元格 -> 去首尾空白的文本；空值、None、nan 都是空串。"""
    return _text(value)


def _int(value: Any) -> int:
    text = _text(value)
    try:
        return int(float(text)) if text else 0
    except ValueError:
        return 0


def parse_rate(value: Any) -> float | None:
    text = _text(value).replace("%", "")
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if isinstance(value, (int, float)) and number <= 1:
        number *= 100  # Excel 百分比单元格是 0~1 的小数
    return number


def parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    match = re.match(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", _text(value))
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def halfwidth(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def normalize_name(raw: Any) -> tuple[str, bool]:
    """A1/P4：-> (规范化姓名, 是否带未签标记)。全角转半角、去空白，先剥未签再剥其他括号；数字保留。"""
    text = re.sub(r"\s+", "", halfwidth(_text(raw)))
    unsigned = bool(_UNSIGNED_MARK.search(text))
    text = _UNSIGNED_MARK.sub("", text)
    while True:
        stripped = _BRACKETS.sub("", text)
        if stripped == text:
            break
        text = stripped
    return text, unsigned


def parse_tokens(value: Any) -> list[tuple[str, bool]]:
    """P3/P7：单元格 -> [(姓名, 带未签标记)]，同格重名每次出现都保留（人次按出现次数计）。"""
    result = []
    for token in _PEOPLE_SPLIT.split(_text(value)):
        name, unsigned = normalize_name(token)
        if name and name.lower() not in _EMPTY_CELLS:
            result.append((name, unsigned))
    return result


def parse_people(value: Any) -> list[tuple[str, bool]]:
    """单元格 -> [(姓名, 已签)]；同格重复的人合并，任一处未签即未签。"""
    seen: dict[str, bool] = {}
    for name, unsigned in parse_tokens(value):
        seen[name] = seen.get(name, True) and not unsigned
    return list(seen.items())


# ── 归并成 3D单（§2 P2–P9）───────────────────────────────────────────


@dataclass(frozen=True)
class Placement:
    name: str
    kind: str
    #: 会签阶段的未签人是他未签的所有会签列；加签人在会签阶段为空（按出现频次归属）；审批阶段是单个节点。
    columns: tuple[str, ...]
    phase: str


_COUNTERSIGN_RANK = 2
#: 流转顺序（T3）：设计工程师、主任工程师、会签、专家/经理、首席/总监。
_FLOW_ORDER = {"设计工程师": 0, "主任工程师": 1, "专家/经理": 3, "首席/总监": 4}


def _node_rank(column: str) -> int:
    return _FLOW_ORDER.get(column, _COUNTERSIGN_RANK)


@dataclass
class Flow:
    serial: str
    project: str
    tdc_department: str
    applicant: str
    applied_on: date | None
    status: str
    required: int
    signed: int
    unsigned_count: int
    rate: float | None
    pending: list[str]
    #: (列名, 姓名) -> 已签；按人合并，任一行带未签即未签（P2）。
    roles: dict[tuple[str, str], bool] = field(default_factory=dict)
    add_sign: dict[str, bool] = field(default_factory=dict)
    #: 零件键 -> 零件名称；零件键是零件号，空零件号按行区分（P9）。
    parts: dict[str, str] = field(default_factory=dict)
    #: P7：人次按单元格里名字出现的次数计、不去重，只取该单第一行（各行的角色列相同）。
    role_count: int = 0
    role_unsigned_count: int = 0
    countersign_required: int = 0
    countersign_signed: int = 0
    add_sign_count: int = 0

    @property
    def is_done(self) -> bool:
        return self.status == STATUS_DONE

    @property
    def in_flight(self) -> bool:
        return self.status not in (STATUS_DONE, STATUS_DISCARDED)

    @property
    def is_complete(self) -> bool:
        return self.is_done or (self.rate is not None and self.rate >= 100 - 1e-9)

    def unsigned(self, phase: str | None = None) -> list[tuple[str, str]]:
        return [
            (column, name) for (column, name), signed in self.roles.items()
            if not signed and (phase is None or column_phase(column) == phase)
        ]

    def placements(self) -> list[Placement]:
        """A12、A13：待审批人员里的每个人落在哪个节点。"""
        unsigned_columns: dict[str, list[str]] = {}
        for column, name in self.unsigned():
            unsigned_columns.setdefault(name, []).append(column)
        countersign_open = bool(self.unsigned(PHASE_COUNTERSIGN))
        result = []
        for name in self.pending:
            columns = unsigned_columns.get(name)
            if columns:
                rank = min(_node_rank(column) for column in columns)
                if rank == _COUNTERSIGN_RANK:
                    result.append(Placement(name, KIND_UNSIGNED, tuple(c for c in columns if column_phase(c) == PHASE_COUNTERSIGN),
                                            PHASE_COUNTERSIGN))
                else:
                    column = next(c for c in columns if _node_rank(c) == rank)
                    result.append(Placement(name, KIND_UNSIGNED, (column,), PHASE_APPROVAL))
            elif self.roles.get(("设计工程师", name)) is True:
                result.append(Placement(name, KIND_RETURNED, ("设计工程师",), PHASE_APPROVAL))
            elif countersign_open:
                result.append(Placement(name, KIND_ADD_SIGN, (), PHASE_COUNTERSIGN))
            else:
                open_nodes = {column for column, _ in self.unsigned(PHASE_APPROVAL)}
                node = next((c for c in APPROVAL_COLUMNS[1:] if c in open_nodes), APPROVAL_COLUMNS[1])
                result.append(Placement(name, KIND_ADD_SIGN, (node,), PHASE_APPROVAL))
        return result

    @property
    def not_current(self) -> list[str]:
        """未签但非当前待办：角色列带「(未签)」、但不在待审批人员里；不计欠账。"""
        pending = set(self.pending)
        return sorted({name for _, name in self.unsigned() if name not in pending})

    @property
    def no_pending(self) -> bool:
        """T2：待审批人员为空，但还有未签（数据异常）。"""
        return not self.pending and bool(self.unsigned())

    @property
    def stage(self) -> str:
        """T1–T6，取第一条成立的。"""
        if not self.pending:
            if not self.unsigned():
                return STAGE_LOCK
            return STAGE_COUNTERSIGN if self.unsigned(PHASE_COUNTERSIGN) else STAGE_APPROVAL
        placed = self.placements()
        if any(p.phase == PHASE_COUNTERSIGN for p in placed):
            return STAGE_COUNTERSIGN
        if any(p.columns and p.columns[0] != "设计工程师" for p in placed):
            return STAGE_APPROVAL
        return STAGE_DRAFT if any(p.kind == KIND_UNSIGNED for p in placed) else STAGE_RETURNED

    def days(self, data_date: date) -> int | None:
        """P8：数据日期 − 申请日期，自然日。"""
        return (data_date - self.applied_on).days if self.applied_on else None


def column_phase(column: str) -> str:
    return PHASE_APPROVAL if column in APPROVAL_COLUMNS else PHASE_COUNTERSIGN


@dataclass
class ParseResult:
    flows: list[Flow]
    #: 数据异常（P2 行间不一致、P6 没见过的状态、P7 未签数不等），预览顶部计数。
    anomalies: list[dict[str, str]]


def build_flows(rows: Iterable[Mapping[str, Any]]) -> ParseResult:
    """零件行 -> 3D单，保持首次出现顺序；已废弃的单不返回（P6）。"""
    flows: dict[str, Flow] = {}
    anomalies: list[dict[str, str]] = []
    row_marks: dict[str, set[tuple[str, str, bool]]] = {}
    for index, row in enumerate(rows):
        serial = _text(row.get("流水单号"))
        if not serial:
            continue
        flow = flows.get(serial)
        first_row = flow is None
        if flow is None:
            flow = flows[serial] = Flow(
                serial=serial,
                project=_text(row.get("项目/车型")),
                tdc_department=_text(row.get("部门")),
                applicant=normalize_name(row.get("申请人"))[0],
                applied_on=parse_date(row.get("申请日期")),
                status=_text(row.get("状态")),
                required=_int(row.get("应签人数")),
                signed=_int(row.get("已签人数")),
                unsigned_count=_int(row.get("未签人数")),
                rate=parse_rate(row.get("签署率")),
                pending=[name for name, _ in parse_people(row.get("待审批人员"))],
            )
        elif (_int(row.get("应签人数")), _int(row.get("已签人数"))) != (flow.required, flow.signed):
            anomalies.append({"serial": serial, "kind": "rowCountsDiffer", "text": "各行签署人数不一致，取第一行"})
        marks: set[tuple[str, str, bool]] = set()
        for column in ROLE_COLUMNS:
            tokens = parse_tokens(row.get(column))
            if first_row:
                unsigned_tokens = sum(1 for _, unsigned in tokens if unsigned)
                flow.role_count += len(tokens)
                flow.role_unsigned_count += unsigned_tokens
                if column_phase(column) == PHASE_COUNTERSIGN:
                    flow.countersign_required += len(tokens)
                    flow.countersign_signed += len(tokens) - unsigned_tokens
            for name, signed in parse_people(row.get(column)):
                key = (column, name)
                flow.roles[key] = flow.roles.get(key, True) and signed
                marks.add((column, name, signed))
        if first_row:
            add_tokens = parse_tokens(row.get(ADD_SIGN_COLUMN))
            flow.add_sign_count += len(add_tokens)
            flow.role_unsigned_count += sum(1 for _, unsigned in add_tokens if unsigned)
        for name, signed in parse_people(row.get(ADD_SIGN_COLUMN)):
            flow.add_sign[name] = flow.add_sign.get(name, True) and signed
            marks.add((ADD_SIGN_COLUMN, name, signed))
        previous = row_marks.setdefault(serial, marks)
        if previous is not marks and previous != marks:
            anomalies.append({"serial": serial, "kind": "rowSignersDiffer", "text": "各行签署状态不一致，任一行未签即未签"})
        part_no = _text(row.get("零件号"))
        flow.parts.setdefault(part_no or f"#row{index}", _text(row.get("零件名称")))
    result = []
    for flow in flows.values():
        if flow.status == STATUS_DISCARDED:
            continue
        if flow.status != STATUS_DONE and flow.status not in KNOWN_IN_FLIGHT_STATUSES:
            anomalies.append({"serial": flow.serial, "kind": "unknownStatus", "text": f"没见过的状态「{flow.status}」，按在途处理"})
        if flow.in_flight and flow.no_pending:
            anomalies.append({"serial": flow.serial, "kind": "pendingEmpty",
                              "text": "有人未签但待审批人员为空，当前待办人显示「—」"})
        if flow.role_count + flow.add_sign_count != flow.required:
            anomalies.append({
                "serial": flow.serial, "kind": "requiredCountDiffer",
                "text": f"角色列人次加加签人数 {flow.role_count + flow.add_sign_count}，应签人数字段 {flow.required}，以 TDC 字段为准",
            })
        if flow.role_unsigned_count != flow.unsigned_count:
            anomalies.append({
                "serial": flow.serial, "kind": "unsignedCountDiffer",
                "text": f"未签标记 {flow.role_unsigned_count} 个，未签人数字段 {flow.unsigned_count}，以 TDC 字段为准",
            })
        result.append(flow)
    # 同一单多行不一致只报一次。
    unique: dict[tuple[str, str], dict[str, str]] = {}
    for item in anomalies:
        unique.setdefault((item["serial"], item["kind"]), item)
    return ParseResult(flows=result, anomalies=list(unique.values()))


# ── 花名册与人员归属（§3）────────────────────────────────────────────


@dataclass(frozen=True)
class RosterHit:
    #: hit（现行科室）、history（历史科室）、conflict（同名不同科室）、miss（未在册）
    status: str
    department: str = ""
    matched_name: str = ""
    digit_fallback: bool = False

    @property
    def registered(self) -> bool:
        return self.status != "miss"


class Roster:
    """生效花名册：规范化姓名 -> 科室集合（A2、A4、A5）。"""

    def __init__(self, entries: Iterable[tuple[str, str]], history_departments: Iterable[str] = HISTORY_DEPARTMENTS):
        self._departments: dict[str, set[str]] = {}
        for raw_name, department in entries:
            name, _ = normalize_name(raw_name)
            department = _text(department)
            if name and department:
                self._departments.setdefault(name, set()).add(department)
        self._history = set(history_departments)
        self._by_stem: dict[str, list[str]] = {}
        for name in self._departments:
            self._by_stem.setdefault(_TRAILING_DIGITS.sub("", name), []).append(name)

    def __contains__(self, name: str) -> bool:
        return self.lookup(name).registered

    def lookup(self, raw_name: str) -> RosterHit:
        name, _ = normalize_name(raw_name)
        if not name:
            return RosterHit("miss")
        matched, fallback = name, False
        if name not in self._departments:
            stem = _TRAILING_DIGITS.sub("", name)
            has_digits = stem != name
            # 只在一方带数字、另一方不带时兜底，且去掉数字后只对上一个人。
            candidates = [
                other for other in self._by_stem.get(stem, ())
                if (_TRAILING_DIGITS.sub("", other) != other) != has_digits
            ]
            if len(candidates) != 1:
                return RosterHit("miss")
            matched, fallback = candidates[0], True
        departments = self._departments[matched]
        if len(departments) > 1:
            return RosterHit("conflict", GROUP_CONFLICT, matched, fallback)
        department = next(iter(departments))
        status = "history" if department in self._history else "hit"
        return RosterHit(status, department, matched, fallback)


@dataclass(frozen=True)
class Attribution:
    #: 1 = 外区域会签、2 = 内部科室会签、3 = 审批；同一人按所在列分别判定。
    chart: int
    group: str
    registered: bool
    roster: RosterHit
    #: 需要提示补录（A7）
    needs_entry: bool = False


def area_display(column: str, area_names: Mapping[str, str] | None = None) -> str:
    """外部列的区域显示名；设置里可改（角色列配置），没改的用默认。"""
    names = {**AREA_DISPLAY, **(area_names or {})}
    return names.get(column) or column


def attribute(
    name: str,
    column: str,
    roster: Roster,
    person_areas: Mapping[str, str] | None = None,
    current_departments: Iterable[str] = CURRENT_DEPARTMENTS,
    area_names: Mapping[str, str] | None = None,
) -> Attribution:
    """A3–A8、A11：(姓名, 所在列) -> 责任区域与所进的图。"""
    hit = roster.lookup(name)
    phase = column_phase(column)
    if phase == PHASE_APPROVAL:
        group = column  # 图3 按审批节点分组；柱下的科室见 approver_label
        return Attribution(3, group, hit.registered, hit)
    if hit.status == "hit":
        return Attribution(2, hit.department, True, hit)
    if hit.status == "history":
        return Attribution(2, GROUP_HISTORY, True, hit)
    if hit.status == "conflict":
        return Attribution(2, GROUP_CONFLICT, True, hit)
    override = _text((person_areas or {}).get(normalize_name(name)[0]))
    if override:
        chart = 2 if override in set(current_departments) else 1
        return Attribution(chart, override, False, hit)
    if column in INTERNAL_COLUMNS:
        return Attribution(2, f"{column}（未在册）", False, hit, needs_entry=True)
    return Attribution(1, area_display(column, area_names), False, hit)


def approver_label(attribution: Attribution) -> str:
    """图3 柱下的科室：在册取科室或特殊组名，未在册写「未在册」（A8）。"""
    hit = attribution.roster
    if hit.status == "hit":
        return hit.department
    if hit.status == "history":
        return GROUP_HISTORY
    if hit.status == "conflict":
        return GROUP_CONFLICT
    return APPROVER_UNREGISTERED


def flow_department(flow: Flow, roster: Roster) -> tuple[str, bool]:
    """A9：单据归属科室 -> (科室, 是否需要提示)。申请人在册取花名册科室，否则取 TDC 部门。"""
    hit = roster.lookup(flow.applicant)
    if hit.status == "hit":
        return hit.department, False
    department = flow.tdc_department
    if hit.status == "history" or department in HISTORY_DEPARTMENTS:
        historical = hit.department if hit.status == "history" else department
        return f"{historical}（未拆分）", True
    return department, False


@dataclass
class TodoItem:
    """一项当前待办：谁、进哪张图哪个组、怎么标注。"""
    name: str
    kind: str
    attribution: Attribution

    @property
    def label_note(self) -> str:
        return {KIND_RETURNED: "退回修改", KIND_ADD_SIGN: "加签"}.get(self.kind, "")

    @property
    def area(self) -> str:
        att = self.attribution
        return approver_label(att) if att.chart == 3 else att.group


def countersign_frequency(flows: Iterable[Flow]) -> dict[str, str]:
    """A13：姓名 -> 他在本次数据里出现最多的会签列；次数相同取列顺序靠前的。"""
    counts: dict[str, dict[str, int]] = {}
    for flow in flows:
        for column, name in flow.roles:
            if column_phase(column) == PHASE_COUNTERSIGN:
                per = counts.setdefault(name, {})
                per[column] = per.get(column, 0) + 1
    order = {column: index for index, column in enumerate(COUNTERSIGN_COLUMNS)}
    return {name: min(per, key=lambda c: (-per[c], order.get(c, len(order)))) for name, per in counts.items()}


def _add_sign_attribution(
    name: str, column: str | None, roster: Roster, person_areas: Mapping[str, str] | None,
    area_names: Mapping[str, str] | None, frequency: Mapping[str, str],
) -> Attribution:
    hit = roster.lookup(name)
    if column is not None:
        return attribute(name, column, roster, person_areas, area_names=area_names)
    if hit.registered:
        return attribute(name, COUNTERSIGN_COLUMNS[0], roster, person_areas, area_names=area_names)  # 在册：列只是占位
    best = frequency.get(name)
    if best:
        return attribute(name, best, roster, person_areas, area_names=area_names)
    override = _text((person_areas or {}).get(normalize_name(name)[0]))
    if override:
        return Attribution(2 if override in set(CURRENT_DEPARTMENTS) else 1, override, False, hit)
    return Attribution(1, GROUP_ADD_UNKNOWN, False, hit)


def current_todo(
    flow: Flow,
    roster: Roster,
    person_areas: Mapping[str, str] | None = None,
    area_names: Mapping[str, str] | None = None,
    frequency: Mapping[str, str] | None = None,
) -> list[TodoItem]:
    """A10、A12、A13：待审批人员里的每一项当前待办 -> 责任区域与所进的图。"""
    frequency = frequency or {}
    items: list[TodoItem] = []
    for placement in flow.placements():
        if placement.kind == KIND_ADD_SIGN:
            column = placement.columns[0] if placement.phase == PHASE_APPROVAL else None
            items.append(TodoItem(placement.name, placement.kind,
                                  _add_sign_attribution(placement.name, column, roster, person_areas, area_names, frequency)))
            continue
        for column in placement.columns:
            items.append(TodoItem(placement.name, placement.kind,
                                  attribute(placement.name, column, roster, person_areas, area_names=area_names)))
    return items


# ── 三张欠账图（§6 G1–G8）─────────────────────────────────────────────


@dataclass
class OwedBar:
    name: str
    label: str
    serials: set[str] = field(default_factory=set)


@dataclass
class OwedGroup:
    name: str
    bars: dict[str, OwedBar] = field(default_factory=dict)
    special: bool = False

    @property
    def person_times(self) -> int:
        return sum(len(bar.serials) for bar in self.bars.values())

    @property
    def flow_count(self) -> int:
        return len({serial for bar in self.bars.values() for serial in bar.serials})

    def as_dict(self) -> dict[str, Any]:
        bars = sorted(self.bars.values(), key=lambda b: (-len(b.serials), b.name))
        return {
            "group": self.name,
            "special": self.special,
            "personTimes": self.person_times,
            "flows": self.flow_count,
            "people": len(bars),
            "bars": [{"name": b.name, "label": b.label, "count": len(b.serials), "serials": sorted(b.serials)} for b in bars],
        }


def owed_charts(
    flows: Sequence[Flow],
    roster: Roster,
    person_areas: Mapping[str, str] | None = None,
    area_names: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """在途单里「当前待办」的欠账（A10、G1）。返回三张图的分组数据和待补录名单。"""
    charts: dict[int, dict[str, OwedGroup]] = {1: {}, 2: {}, 3: {}}
    needs_entry: set[str] = set()
    frequency = countersign_frequency(flows)
    for flow in flows:
        if not flow.in_flight:
            continue  # 已完成（含签署率不到 100%）的未签人不计欠账
        for item in current_todo(flow, roster, person_areas, area_names, frequency):
            attribution = item.attribution
            if attribution.needs_entry:
                needs_entry.add(item.name)
            group = charts[attribution.chart].setdefault(
                attribution.group,
                OwedGroup(attribution.group, special=attribution.group in SPECIAL_SECTION_GROUPS),
            )
            if attribution.chart == 3:
                note = f"·{item.label_note}" if item.label_note else ""
                label = f"{item.name}（{approver_label(attribution)}{note}）"
            else:
                label = item.name
            # 在册按「人 + 单」去重，未在册按「人 + 区域 + 单」去重：两者都落在同一组的同一根柱。
            group.bars.setdefault(item.name, OwedBar(item.name, label)).serials.add(flow.serial)
    return {
        "external": _order_by_volume(charts[1]),
        "sections": _order_sections(charts[2]),
        "approval": _order_nodes(charts[3]),
        "needsEntry": sorted(needs_entry),
    }


def _order_by_volume(groups: Mapping[str, OwedGroup]) -> list[dict[str, Any]]:
    ordered = sorted(groups.values(), key=lambda g: (g.name == GROUP_ADD_UNKNOWN, -g.person_times, -g.flow_count, g.name))
    return [g.as_dict() for g in ordered]


def _order_sections(groups: Mapping[str, OwedGroup]) -> list[dict[str, Any]]:
    regular = [g for g in groups.values() if not g.special]
    special = sorted(
        (g for g in groups.values() if g.special),
        key=lambda g: SPECIAL_SECTION_GROUPS.index(g.name),
    )
    regular.sort(key=lambda g: (-g.person_times, -g.flow_count, g.name))
    return [g.as_dict() for g in regular + special]


def _order_nodes(groups: Mapping[str, OwedGroup]) -> list[dict[str, Any]]:
    return [groups[node].as_dict() for node in APPROVAL_COLUMNS if node in groups]


# ── 在途明细表（§6）──────────────────────────────────────────────────


def flow_rows(
    flows: Sequence[Flow],
    data_date: date,
    roster: Roster,
    long_serials: Iterable[str] = (),
    person_areas: Mapping[str, str] | None = None,
    area_names: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """只列在途的单；按阶段、长周期在前、已申请天数降序、流水单号排序。"""
    long_set = set(long_serials)
    frequency = countersign_frequency(flows)
    rows = []
    for flow in flows:
        if not flow.in_flight:
            continue
        todo: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for item in current_todo(flow, roster, person_areas, area_names, frequency):
            key = (item.name, item.area)
            if key in seen:
                continue
            seen.add(key)
            todo.append({
                "name": item.name, "area": item.area, "external": item.attribution.chart == 1,
                "addSign": item.kind == KIND_ADD_SIGN, "returned": item.kind == KIND_RETURNED,
            })
        todo.sort(key=lambda item: not item["external"])  # 外区域的人排在前面
        names = [name for name in flow.parts.values() if name]
        department, _ = flow_department(flow, roster)
        rows.append({
            "serial": flow.serial,
            "firstPart": names[0] if names else "",
            "partCount": len(flow.parts),
            "longCycle": flow.serial in long_set,
            "department": department,
            "applicant": flow.applicant,
            "stage": flow.stage,
            "todo": todo,
            "noPending": flow.no_pending,
            "notCurrent": len(flow.not_current),
            "countersign": (flow.countersign_signed, flow.countersign_required),
            "total": (flow.signed, flow.required),
            "days": flow.days(data_date),
        })
    rows.sort(key=lambda r: (_STAGE_RANK[r["stage"]], not r["longCycle"], -(r["days"] or 0), r["serial"]))
    return rows


def part_label(row: Mapping[str, Any]) -> str:
    text = row["firstPart"] + (f"等{row['partCount']}件" if row["partCount"] > 1 else "")
    return ("【长周期】" if row["longCycle"] else "") + text


def todo_text(row: Mapping[str, Any]) -> str:
    items = []
    for item in row["todo"]:
        if item.get("addSign"):
            items.append(f"{item['name']}（加签{'·' + item['area'] if item['area'] else ''}）")
        elif item.get("returned"):
            items.append(f"{item['name']}（退回修改）")
        else:
            items.append(f"{item['name']}（{item['area']}）")
    text = "、".join(items) or "—"
    if row.get("noPending"):
        text += "（无待审批人）"
    if row.get("notCurrent"):
        text += f"，另 {row['notCurrent']} 人未签、非当前待办"
    return text


# ── 长周期判定（§4 L1–L6）────────────────────────────────────────────

RESULT_HIT = "确定命中"
RESULT_SUSPECT = "疑似"
RESULT_EXCLUDED = "排除"
RESULT_MISS = "未命中"

ORIENTATION_CHARS = "上下前后中"
PANEL_WORDS = ("内板", "外板", "饰板")
DEFAULT_GLOBAL_EXCLUDES = ("密封条", "吸音棉", "隔音垫", "饰条", "卡扣", "堵盖", "螺栓", "支架", "导槽", "线束")
DEFAULT_SUFFIXES = (
    "总成", "分总成", "组件", "本体", "合件", "焊合件", "焊合总成", "焊接总成",
    "上部", "下部", "前部", "后部", "上段", "下段", "前段", "后段", "中段", "模块",
)
#: 同义词表初值（建议值，待确认）：规范词 -> 别名。
DEFAULT_SYNONYMS: dict[str, tuple[str, ...]] = {
    "发动机罩": ("发罩", "机盖", "机罩", "引擎盖", "前舱盖"),
    "尾门": ("背门", "后背门", "掀背门"),
    "后侧门": ("后门",),
    "前大梁": ("前纵梁",),
    "后大梁": ("后纵梁",),
    "中央通道": ("中通道",),
    "前蒙皮": ("前保险杠蒙皮", "前保蒙皮", "前保险杠"),
    "后蒙皮": ("后保险杠蒙皮", "后保蒙皮", "后保险杠"),
    "仪表板": ("仪表台",),
    "副仪表板": ("副仪表台", "中控台"),
    "饰板": ("装饰板", "内饰板", "护板"),
    "前照灯": ("前大灯", "大灯"),
    "尾灯": ("后组合灯", "后尾灯"),
}
_LIST_SUFFIXES = ("总成", "组件")
_PUNCT = re.compile(r"[\s\W_]+", re.UNICODE)


@dataclass(frozen=True)
class LongCycleRule:
    rule_id: str
    source_name: str
    #: 每组是一种叫法的有序核心词（主体 + 板件名）。
    core_groups: tuple[tuple[str, ...], ...]
    excludes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Vocabulary:
    global_excludes: tuple[str, ...] = DEFAULT_GLOBAL_EXCLUDES
    synonyms: Mapping[str, Sequence[str]] = field(default_factory=lambda: dict(DEFAULT_SYNONYMS))
    orientation: str = ORIENTATION_CHARS
    suffixes: tuple[str, ...] = DEFAULT_SUFFIXES


@dataclass(frozen=True)
class Classification:
    normalized: str
    result: str
    rule_id: str = ""
    reason: str = ""


def l1_normalize(name: Any) -> str:
    """L1：全角转半角；删括号及内容；去左/右/LH/RH；去空白和标点。"""
    text = halfwidth(_text(name)).upper()
    while True:
        stripped = _BRACKETS.sub("", text)
        if stripped == text:
            break
        text = stripped
    # 先去标点再去左右标记（「L/H」「R-H」也能去掉），反复到不再变化：
    # 结果再规范化一次不变，记忆键（conclusion_key）回传后台时才对得上。
    while True:
        stripped = re.sub(r"LH|RH|左|右", "", _PUNCT.sub("", text))
        if stripped == text:
            return text
        text = stripped


def _alias_table(vocab: Vocabulary) -> list[tuple[str, str]]:
    table: dict[str, str] = {}
    for canonical, aliases in vocab.synonyms.items():
        canonical_key = l1_normalize(canonical)
        table.setdefault(canonical_key, canonical_key)  # 规范词自身也占位
        for alias in aliases:
            table.setdefault(l1_normalize(alias), canonical_key)
    return sorted(table.items(), key=lambda item: -len(item[0]))


def l2_canonical(text: str, vocab: Vocabulary) -> str:
    """L2：最长匹配、单遍扫描地把别名换成规范词。"""
    table = _alias_table(vocab)
    out: list[str] = []
    index = 0
    while index < len(text):
        for term, canonical in table:
            if term and text.startswith(term, index):
                out.append(canonical)
                index += len(term)
                break
        else:
            out.append(text[index])
            index += 1
    return "".join(out)


def normalize_part(name: Any, vocab: Vocabulary) -> str:
    return l2_canonical(l1_normalize(name), vocab)


def split_core(name: str) -> tuple[str, ...]:
    """把规范化后的清单名切成「主体 + 板件名」，如 尾门外板 -> (尾门, 外板)。"""
    for panel in PANEL_WORDS:
        if name.endswith(panel) and len(name) > len(panel):
            return (name[: -len(panel)], panel)
    return (name,)


def parse_remark_excludes(remark: Any) -> tuple[str, ...]:
    """备注「非A、B」-> (A, B)。"""
    match = re.search(r"非(.+)", halfwidth(_text(remark)))
    if not match:
        return ()
    words = [word.strip() for word in re.split(r"[、,，;；/\s]+", match.group(1))]
    return tuple(word for word in words if word)


def build_rule(rule_id: str, source_name: str, remark: Any = "", vocab: Vocabulary | None = None,
               aliases: Iterable[str] = ()) -> LongCycleRule:
    """清单一项 -> 规则：「/」拆并列叫法，去掉「总成」「组件」后缀，核心词同样过 L1、L2。"""
    vocab = vocab or Vocabulary()
    groups: list[tuple[str, ...]] = []
    for variant in [*re.split(r"[/／]", _text(source_name)), *aliases]:
        key = normalize_part(variant, vocab)
        if key in _LIST_SUFFIXES or key in vocab.suffixes:
            continue  # 「前蒙皮总成/组件」里的「组件」是后缀的另一种写法，不是并列叫法
        for suffix in _LIST_SUFFIXES:
            if key.endswith(suffix) and len(key) > len(suffix):
                key = key[: -len(suffix)]
        core = split_core(key) if key else ()
        if core and core not in groups:
            groups.append(core)
    return LongCycleRule(rule_id, _text(source_name), tuple(groups), parse_remark_excludes(remark))


def _suffix_ok(rest: str, suffixes: Sequence[str]) -> bool:
    """余部只由白名单后缀拼成（可多个，如 上部总成）。"""
    ok = [False] * (len(rest) + 1)
    ok[0] = True
    for end in range(1, len(rest) + 1):
        ok[end] = any(ok[end - len(s)] and rest.startswith(s, end - len(s)) for s in suffixes if len(s) <= end)
    return ok[len(rest)]


def _core_pattern(core: Sequence[str], orientation: str) -> re.Pattern[str]:
    gap = f"[{re.escape(orientation)}]{{0,2}}"
    return re.compile(gap.join(re.escape(word) for word in core))


def classify_part(name: Any, rules: Sequence[LongCycleRule], vocab: Vocabulary | None = None) -> Classification:
    """L1–L6：零件名称 -> 确定命中 / 疑似 / 排除 / 未命中。"""
    vocab = vocab or Vocabulary()
    normalized = normalize_part(name, vocab)
    if not normalized:
        return Classification(normalized, RESULT_MISS)
    for word in vocab.global_excludes:
        if word and normalize_part(word, vocab) in normalized:
            return Classification(normalized, RESULT_EXCLUDED, reason=f"全局排除「{word}」")
    best: tuple[int, LongCycleRule, list[re.Match[str]]] | None = None
    for rule in rules:
        for core in rule.core_groups:
            pattern = _core_pattern(core, vocab.orientation)
            matches = [m for m in (pattern.match(normalized, i) for i in range(len(normalized))) if m]
            length = sum(len(word) for word in core)
            if matches and (best is None or length > best[0]):
                best = (length, rule, matches)
    if best is None:
        return Classification(normalized, RESULT_MISS)
    _, rule, matches = best
    for word in rule.excludes:
        if word and normalize_part(word, vocab) in normalized:
            return Classification(normalized, RESULT_EXCLUDED, rule.rule_id, f"规则排除「{word}」")
    orientation = set(vocab.orientation)
    for match in matches:
        prefix, rest = normalized[: match.start()], normalized[match.end():]
        if set(prefix) <= orientation and _suffix_ok(rest, vocab.suffixes):
            return Classification(normalized, RESULT_HIT, rule.rule_id)
    return Classification(normalized, RESULT_SUSPECT, rule.rule_id, "余部不在白名单")


def conclusion_key(name: Any) -> str:
    """长周期人工结论的记忆键：零件名称只过 L1，不随同义词表变化。"""
    return l1_normalize(name)


def long_cycle_decisions(
    part_names: Iterable[str],
    rules: Sequence[LongCycleRule],
    conclusions: Mapping[str, bool],
    vocab: Vocabulary | None = None,
) -> dict[str, Any]:
    """§7 复核时序第 1–4 步。conclusions 是本项目的「记忆键 -> 是否纳入」。

    记忆键是 ``conclusion_key``（只做 L1，不做别名归一），这样同义词表改动后
    已有的人工结论仍然认得（§4：规则或词表改动后，已有的人工结论不变）。
    返回 counted（计入长周期的记忆键）、review（待复核：确定命中默认勾选、疑似默认不勾选）
    和 excluded（折叠区）。人工结论优先于自动结果。
    """
    vocab = vocab or Vocabulary()
    by_key: dict[str, Classification] = {}
    raw_names: dict[str, list[str]] = {}
    for raw in part_names:
        if not _text(raw):
            continue  # 零件名称为空：计入 M，不参与判定
        key = conclusion_key(raw)
        if key not in by_key:
            by_key[key] = classify_part(raw, rules, vocab)
        raw_names.setdefault(key, []).append(_text(raw))
    counted: set[str] = set()
    review: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for key, result in by_key.items():
        item = {
            "normalized": key, "canonical": result.normalized, "names": sorted(set(raw_names[key])),
            "result": result.result, "rule": result.rule_id, "reason": result.reason,
        }
        if key in conclusions:
            if conclusions[key]:
                counted.add(key)
            continue
        if result.result == RESULT_HIT:
            counted.add(key)
            review.append({**item, "checked": True})
        elif result.result == RESULT_SUSPECT:
            review.append({**item, "checked": False})
        elif result.result == RESULT_EXCLUDED:
            excluded.append(item)
    review.sort(key=lambda i: (i["result"] != RESULT_HIT, i["normalized"]))
    excluded.sort(key=lambda i: i["normalized"])
    return {"counted": counted, "review": review, "excluded": excluded, "classified": by_key}


# ── 种子与 CSV 导入校验（§7）─────────────────────────────────────────

ROSTER_NAME_HEADERS = ("姓名", "责任工程师名称")
ROSTER_DEPARTMENT_HEADERS = ("科室", "责任工程师专业科室")
_NAME_WITH_ID = re.compile(r"^(.*?)\(([^()]*)\)$")


def decode_csv(data: bytes) -> str:
    """导入文件编码自动识别：UTF-8（含 BOM）优先，失败按 GBK。"""
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("gbk")


def _header_index(header: Sequence[Any], names: Sequence[str]) -> int | None:
    cells = [re.sub(r"\s+", "", halfwidth(_text(h))) for h in header]
    for name in names:
        if name in cells:
            return cells.index(name)
    return None


def _cell(row: Sequence[Any], index: int | None) -> Any:
    return row[index] if index is not None and index < len(row) else None


def parse_roster_table(
    rows: Sequence[Sequence[Any]],
    current_departments: Iterable[str] = CURRENT_DEPARTMENTS,
    history_departments: Iterable[str] = HISTORY_DEPARTMENTS,
) -> dict[str, Any]:
    """花名册表（首行表头）-> 生效条目、错误行和同名冲突。

    「姓名(工号)」拆成姓名和工号；同名同科室合并并累计工号；同名不同科室报冲突，
    该姓名不导入；科室不在现行字典里报错，历史科室提示指定现行科室。行号从 1 起，含表头。
    """
    if not rows:
        return {"entries": [], "errors": [{"line": 1, "text": "文件为空"}], "conflicts": [], "merged": 0}
    name_col = _header_index(rows[0], ROSTER_NAME_HEADERS)
    dept_col = _header_index(rows[0], ROSTER_DEPARTMENT_HEADERS)
    if name_col is None or dept_col is None:
        return {"entries": [], "errors": [{"line": 1, "text": "表头要有姓名列和科室列"}], "conflicts": [], "merged": 0}
    current, history = set(current_departments), set(history_departments)
    people: dict[str, dict[str, list[str]]] = {}
    row_counts: dict[str, int] = {}
    errors: list[dict[str, Any]] = []
    for line, row in enumerate(rows[1:], start=2):
        raw_name, department = _text(_cell(row, name_col)), _text(_cell(row, dept_col))
        if not raw_name and not department:
            continue
        text = re.sub(r"\s+", "", halfwidth(raw_name))
        match = _NAME_WITH_ID.match(text)
        name, staff_id = (match.group(1), match.group(2)) if match else (text, "")
        if not name or not department:
            errors.append({"line": line, "text": "姓名或科室为空"})
            continue
        if department in history:
            errors.append({"line": line, "text": f"{name} 的科室是历史值「{department}」，请指定现行科室"})
            continue
        if department not in current:
            errors.append({"line": line, "text": f"{name} 的科室「{department}」不在现行科室字典里"})
            continue
        ids = people.setdefault(name, {}).setdefault(department, [])
        if staff_id and staff_id not in ids:
            ids.append(staff_id)
        row_counts[name] = row_counts.get(name, 0) + 1
    entries, conflicts = [], []
    for name, by_department in people.items():
        if len(by_department) > 1:
            conflicts.append({"name": name, "departments": sorted(by_department)})
            continue
        department, ids = next(iter(by_department.items()))
        entries.append({"name": name, "department": department, "ids": ids})
    merged = sum(1 for name, count in row_counts.items() if count > 1 and len(people[name]) == 1)
    return {"entries": entries, "errors": errors, "conflicts": conflicts, "merged": merged}


def parse_long_cycle_table(rows: Sequence[Sequence[Any]], vocab: Vocabulary | None = None) -> dict[str, Any]:
    """长周期清单表（首行表头，要有「零件名称」「备注」，可选「别名」「规则编号」）-> 规则。

    重名规则（规范化后的核心词相同）合并核心词组和排除词。
    """
    vocab = vocab or Vocabulary()
    if not rows:
        return {"rules": [], "errors": [{"line": 1, "text": "文件为空"}]}
    name_col = _header_index(rows[0], ("零件名称",))
    remark_col = _header_index(rows[0], ("备注",))
    alias_col = _header_index(rows[0], ("别名",))
    id_col = _header_index(rows[0], ("规则编号",))
    if name_col is None or remark_col is None:
        return {"rules": [], "errors": [{"line": 1, "text": "表头要有「零件名称」「备注」"}]}
    rules: dict[tuple[tuple[str, ...], ...], LongCycleRule] = {}
    errors: list[dict[str, Any]] = []
    explicit_ids = [_text(_cell(row, id_col)) for row in rows[1:] if _text(_cell(row, name_col))]
    used_ids = {rule_id for rule_id in explicit_ids if rule_id}
    seen_ids: set[str] = set()
    serial = 0
    for line, row in enumerate(rows[1:], start=2):
        name = _text(_cell(row, name_col))
        if not name:
            continue
        aliases = [a for a in re.split(r"[、,，;；]+", _text(_cell(row, alias_col))) if a.strip()]
        rule_id = _text(_cell(row, id_col))
        if rule_id and rule_id in seen_ids:
            errors.append({"line": line, "text": f"规则编号「{rule_id}」重复"})
            continue
        while not rule_id:
            serial += 1
            candidate = f"LC{serial:02d}"
            rule_id = "" if candidate in used_ids else candidate
        seen_ids.add(rule_id)
        rule = build_rule(rule_id, name, _cell(row, remark_col), vocab, aliases)
        if not rule.core_groups:
            errors.append({"line": line, "text": f"「{name}」规范化后没有核心词"})
            continue
        key = tuple(sorted(rule.core_groups))
        existing = rules.get(key)
        if existing is not None:
            rule = LongCycleRule(
                existing.rule_id, existing.source_name, existing.core_groups,
                tuple(dict.fromkeys(existing.excludes + rule.excludes)),
            )
        rules[key] = rule
    return {"rules": list(rules.values()), "errors": errors}


# ── 指标（§5）─────────────────────────────────────────────────────────


def display_pct(numerator: int, denominator: int) -> Decimal | None:
    """百分比保留 1 位小数，四舍五入；分母为 0 返回 None（显示「—」）。"""
    if not denominator:
        return None
    value = Decimal(numerator) * 100 / Decimal(denominator)
    return value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


PERCENT_KEYS = ("countersignRate", "totalRate", "t2Rate")


def metrics(flows: Sequence[Flow], long_parts: Mapping[str, set[str]] | None = None) -> dict[str, Any]:
    """一套指标。long_parts 给出时算「长周期」那套：serial -> 长周期零件键集合。"""
    if long_parts is not None:
        flows = [f for f in flows if long_parts.get(f.serial)]

    def parts_of(flow: Flow) -> int:
        return len(long_parts.get(flow.serial, ())) if long_parts is not None else len(flow.parts)

    parts = sum(parts_of(f) for f in flows)
    locked = sum(parts_of(f) for f in flows if f.is_done)
    return {
        "flows": len(flows),
        "parts": parts,
        "countersignRate": display_pct(sum(f.countersign_signed for f in flows), sum(f.countersign_required for f in flows)),
        "totalRate": display_pct(sum(f.signed for f in flows), sum(f.required for f in flows)),
        "complete": sum(1 for f in flows if f.is_complete),
        "locked": locked,
        "t2Rate": display_pct(locked, parts),
        "countersignDone": sum(1 for f in flows if not f.unsigned(PHASE_COUNTERSIGN)),
    }


def long_parts_of(flows: Sequence[Flow], is_long: Any) -> dict[str, set[str]]:
    """serial -> 长周期零件键集合；is_long(零件名称) -> bool。"""
    result: dict[str, set[str]] = {}
    for flow in flows:
        keys = {key for key, name in flow.parts.items() if name and is_long(name)}
        if keys:
            result[flow.serial] = keys
    return result


def summary(flows: Sequence[Flow], long_parts: Mapping[str, set[str]]) -> dict[str, Any]:
    return {"total": metrics(flows), "longCycle": metrics(flows, long_parts)}


def deltas(today: Mapping[str, Any], base: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """D4：今天显示值 − 基线显示值；任一侧为 None（分母为 0）时该项无括号。"""
    if base is None:
        return None
    result: dict[str, Any] = {}
    for group, values in today.items():
        before = base.get(group) or {}
        result[group] = {}
        for key, value in values.items():
            old = before.get(key)
            result[group][key] = None if value is None or old is None else value - old
    return result


def fmt_pct(value: Decimal | None) -> str:
    return "—" if value is None else f"{value}%"


def fmt_delta(value: Any, *, percent: bool) -> str:
    """D5：(+1.2%) / (−0.3%) / (+0.0%)，计数 (+3) / (−1) / (+0)。"""
    if value is None:
        return ""
    sign = MINUS if value < 0 else "+"
    magnitude = abs(value)
    return f"({sign}{magnitude}%)" if percent else f"({sign}{int(magnitude)})"


def fmt_count_delta(value: Any) -> str:
    """D6：N、M 只在有变化时带括号。"""
    return "" if not value else fmt_delta(value, percent=False)


# ── 基线（§5 D2、基线缺失或不连续）──────────────────────────────────


def baseline_mode(data_date: date, base_date: date | None, max_gap_days: int = 14) -> dict[str, Any]:
    """-> {"show": 是否显示括号, "note": 汇总段后的说明行}。"""
    if base_date is None or (data_date - base_date).days > max_gap_days:
        return {"show": False, "note": "首次生成，无日变化"}
    if base_date >= data_date:
        return {"show": False, "note": ""}  # 旧数据：不写快照，不显示括号
    if (data_date - base_date).days == 1:
        return {"show": True, "note": ""}
    return {"show": True, "note": f"括号内为较 {base_date:%m-%d} 的变化"}


def snapshot_covers(snapshot_scope: Mapping[str, Any], serials: Iterable[str]) -> bool:
    """D2：全量快照覆盖任何范围；关注清单快照只在包含全部所需单号时覆盖。"""
    if snapshot_scope.get("kind") == "all":
        return True
    held = set(snapshot_scope.get("serials") or ())
    return set(serials) <= held
