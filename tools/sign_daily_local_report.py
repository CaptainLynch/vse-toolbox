# -*- coding: utf-8 -*-
"""从本地导出的 TDC 数模表单生成「3D单签署进展日报」（离线、只读、零写库）。

    python tools/sign_daily_local_report.py --file <TDC数模导出.xlsx> --date 2026-11-06
    python tools/sign_daily_local_report.py --file <Excel另存的文本.txt> --date 2026-11-06
    python tools/sign_daily_local_report.py --file x.xlsx --date 2026-11-06 --project CX01 --md out.md
    python tools/sign_daily_local_report.py --file x.xlsx --date 2026-11-06 --json

设计边界（与签署日报插件「手工导入」口径一致，见 .runtime/sign-daily-import-plan-20261110.md）：

- 只读：不写数据库、不建快照、不写日变化基线、不改任何配置；NullStore 的写方法一律抛错。
- 不计算日变化：不读基线（不是靠 stale），delta 恒为 None。
- 数据日期必须由人确认（``--date``），不接受从文件修改时间或行内日期推导。
- 口径单一来源：解析与指标全部复用 ``plugins/sign_daily/rules.py`` 的纯函数与
  ``service.compose``，本工具只做「文件 → records → compose」的接线。
- 表头按官方 47 列契约 fail-closed 校验（``services/tdc_official_rows.py``，逐字、逐序），
  再校验日报必需的 36 列（``rules.REQUIRED_COLUMNS``）。
- 输入可以是官方 .xlsx，或 Excel「另存为文本」得到的 .txt（TAB 分隔；UTF-16/UTF-8 带 BOM
  或无 BOM 的 GBK）。两种都整份读进内存解析，与插件导入同一套校验。

退出码：0 成功；1 表单不合格（表头/列/行数）；2 参数或读取错误。
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import importlib.util
import json
import re
import sys
import types
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


def _base_dir() -> Path:
    """PyInstaller onefile 下资源在 sys._MEIPASS，源码运行时在仓库根。"""
    frozen = getattr(sys, "_MEIPASS", None)
    if frozen:
        return Path(frozen)
    return Path(__file__).resolve().parent.parent


REPO = _base_dir()
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from services.tdc_official_rows import (  # noqa: E402
    OfficialWorkbookError,
    OfficialWorkbookTruncated,
    OfficialWorkbookUnreadable,
    read_official_tdc_rows_from_bytes,
)

PLUGIN_DIR = REPO / "plugins" / "sign_daily"
MAX_ROWS = 5001
#: 单份输入文件的字节上限（同插件导入）。
MAX_FILE_BYTES = 15 * 1024 * 1024
#: 允许的输入扩展名：官方 xlsx，或 Excel「另存为文本」的 TAB 文本。
SUFFIXES = (".xlsx", ".txt")

# ── 导入失败文案（逐字同插件 /import-form，取自契约 2026-11-11 §3/§4）──
# 本工具自带一份：离线单文件可跑，不从插件或宿主取常量（业务模块仍复用 _load_plugin）。
_IMPORT_TEXT = {
    "encrypted": "文件受公司终端加密保护，本功能读不到内容，文件本身没有损坏。请改用「一键生成」。",
    "damaged": "文件无法按 xlsx 打开，可能下载不完整、已损坏或受加密。请重新导出，或改用「一键生成」。",
    "schema": "文件可读，但表头与官方 47 列模板不一致。请确认导出的是官方签署明细且未增删改列。",
    "text_encoding": "文本文件的编码无法识别。请在 Excel 中另存为「Unicode 文本(*.txt)」后重试。",
    "text_malformed": "文本文件的行列结构不完整。请在 Excel 中重新另存为文本，不要手工编辑。",
}
#: reason → (code, 文案)：闭集词与 services.xlsx_preview.REASONS 一致。
_IMPORT_ERRORS = {
    "encrypted_container": ("E_ENCRYPTED_WORKBOOK", _IMPORT_TEXT["encrypted"]),
    "ole_container": ("E_WORKBOOK_INVALID", _IMPORT_TEXT["damaged"]),
    "empty_or_truncated": ("E_WORKBOOK_INVALID", _IMPORT_TEXT["damaged"]),
    "unknown_binary": ("E_WORKBOOK_INVALID", _IMPORT_TEXT["damaged"]),
    "corrupt_zip": ("E_WORKBOOK_INVALID", _IMPORT_TEXT["damaged"]),
    "unreadable": ("E_WORKBOOK_INVALID", _IMPORT_TEXT["damaged"]),
    "schema_mismatch": ("E_HEADER_MISMATCH", _IMPORT_TEXT["schema"]),
    "text_encoding": ("E_TEXT_INVALID", _IMPORT_TEXT["text_encoding"]),
    "text_malformed": ("E_TEXT_INVALID", _IMPORT_TEXT["text_malformed"]),
}
#: .txt 输入读不出来时（空文件、读盘失败等非文本专用 reason）统一用这条：同插件 _translate。
_TEXT_FALLBACK = ("E_TEXT_INVALID", _IMPORT_TEXT["text_encoding"])
#: 行数超限：码与文案同插件（契约 §4 保持既有码与既有文案）。
_TOO_MANY_ROWS = (
    "E_TOO_MANY_ROWS",
    f"表单行数超过上限（{MAX_ROWS - 1} 行数据）：请缩小范围后再导出",
)


def _load_plugin() -> types.SimpleNamespace:
    """把 plugins/sign_daily 当合成包导入（插件无 __init__.py，相对导入需要包上下文）。"""
    package_name = "_sign_daily_local"
    package = types.ModuleType(package_name)
    package.__path__ = [str(PLUGIN_DIR)]  # type: ignore[attr-defined]
    sys.modules[package_name] = package

    def load(name: str):
        spec = importlib.util.spec_from_file_location(
            f"{package_name}.{name}", PLUGIN_DIR / f"{name}.py"
        )
        if spec is None or spec.loader is None:  # pragma: no cover - 打包缺失时才会走到
            raise ImportError(f"cannot load plugin module: {name}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    rules = load("rules")
    settings = load("settings")
    service = load("service")
    scheduled = load("scheduled")
    importer = load("importer")
    return types.SimpleNamespace(
        rules=rules, settings=settings, service=service, scheduled=scheduled, importer=importer
    )


class NullStore:
    """一个什么也没有的快照库：读全是空，写一律报错（证明本工具零写库）。"""

    def conclusions(self, projects: Iterable[str]) -> dict[str, dict[str, Any]]:
        return {}

    def snapshot_dates(self, project: str) -> list[date]:
        return []

    def snapshot_scope(self, project: str, day: date) -> dict[str, Any] | None:
        return None

    def snapshot_rows(self, projects: Iterable[str], day: date) -> list[dict[str, Any]]:
        return []

    def save_snapshot(self, *args: Any, **kwargs: Any) -> None:  # pragma: no cover
        raise RuntimeError("本地表单模式不允许写快照")


def _split(values: Sequence[str] | None) -> list[str]:
    out: list[str] = []
    for raw in values or ():
        for item in str(raw).replace("，", ",").split(","):
            item = item.strip()
            if item and item not in out:
                out.append(item)
    return out


def _records(rows: Sequence[Mapping[str, Any]], rules) -> list[dict[str, Any]]:
    keep = set(rules.REQUIRED_COLUMNS)
    return [{key: value for key, value in row.items() if key in keep} for row in rows]


def _json_default(value: object) -> object:
    if dataclasses.is_dataclass(value):
        return dataclasses.asdict(value)  # type: ignore[arg-type]
    return str(value)


def _bars(item: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    for bar in item.get("bars") or ():
        out.append(f"{bar.get('label') or bar.get('name')}：{bar.get('count')}")
    return out


def _chart_block(title: str, items: Sequence[Mapping[str, Any]]) -> list[str]:
    lines = [f"### {title}"]
    if not items:
        lines.append("  - （无）")
        return lines
    for item in items:
        people = "、".join(_bars(item))
        special = "（未在册专列）" if item.get("special") else ""
        lines.append(
            f"  - {item.get('group')}{special}：{item.get('flows')} 份 / "
            f"{item.get('people')} 人 / {item.get('personTimes')} 人次 —— {people}"
        )
    return lines


def _metrics_line(title: str, metrics: Mapping[str, Any]) -> str:
    return (
        f"{title}：会签签单率 {metrics.get('countersignRate')}%，"
        f"总签单率 {metrics.get('totalRate')}%，"
        f"3D单完成 {metrics.get('complete')}/{metrics.get('flows')} 份，"
        f"已锁定发布 {metrics.get('locked')}/{metrics.get('flows')}，"
        f"T2 发布率 {metrics.get('t2Rate')}%"
    )


def _csv_rows(path: Path) -> list[list[str]]:
    "\"\"\"读 CSV（UTF-8 BOM 容忍），返回行列表；与设置页导出格式一致。\"\"\""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [row for row in csv.reader(handle) if any(str(cell).strip() for cell in row)]


def _effective(plugin, roster_csv: Path | None, rules_csv: Path | None):
    "\"\"\"生效配置：默认内置种子；给了 CSV 就用 CSV 覆盖（格式 = 设置页导出）。\"\"\""
    rules_mod = plugin.rules
    settings_mod = plugin.settings
    seeds = plugin.service.Effective.seeds()
    if roster_csv is None and rules_csv is None:
        return seeds

    vocab = settings_mod.to_vocabulary(settings_mod.default_vocabulary())
    roster = seeds.roster
    if roster_csv is not None:
        parsed = rules_mod.parse_roster_table(_csv_rows(roster_csv))
        if parsed["errors"]:
            first = parsed["errors"][0]
            raise ValueError(f"花名册第 {first.get('line')} 行有问题：{first.get('text')}")
        roster = rules_mod.Roster([(e["name"], e["department"]) for e in parsed["entries"]])

    rules = seeds.rules
    if rules_csv is not None:
        table = settings_mod.parse_rule_table(_csv_rows(rules_csv), vocab)
        if table["errors"]:
            first = table["errors"][0]
            raise ValueError(f"规则第 {first.get('line')} 行有问题：{first.get('text')}")
        built = []
        for row in table["rows"]:
            if not row["enabled"]:
                continue
            aliases = [a for a in re.split(r"[、,，;；]+", str(row.get("aliases") or "")) if a.strip()]
            rule = rules_mod.build_rule(row["id"], row["name"], row.get("remark") or "", vocab, aliases)
            if rule.core_groups:
                built.append(rule)
        rules = built

    return plugin.service.Effective(roster, rules, vocab)


def build_report(
    *,
    path: Path,
    data_date: date,
    projects: Sequence[str],
    departments: Sequence[str],
    region: str,
    effective: Any | None = None,
) -> dict[str, Any]:
    """解析文件并组装日报；返回 compose 的结果加上本工具的元数据。"""
    plugin = _load_plugin()
    rules = plugin.rules
    service = plugin.service

    is_text = path.suffix.lower() == ".txt"
    try:
        with path.open("rb") as handle:
            data = handle.read(MAX_FILE_BYTES + 1)
    except OSError:
        error = OfficialWorkbookUnreadable("input file cannot be read", reason="unreadable")
        error.is_text = is_text  # type: ignore[attr-defined]
        raise error from None
    if len(data) > MAX_FILE_BYTES:
        raise ValueError(f"文件超过 {MAX_FILE_BYTES // (1024 * 1024)} MB 上限")
    try:
        # 与插件导入同一入口：xlsx / TXT 都在内存里解析，表头逐字校验。
        rows = read_official_tdc_rows_from_bytes(
            data, "data_model", max_rows=MAX_ROWS, text=is_text, strict=True
        )
    except OfficialWorkbookError as exc:
        exc.is_text = is_text  # type: ignore[attr-defined]
        raise
    if not rows:
        raise ValueError("表单里没有任何数据行")
    present = set(rows[0])
    missing = [name for name in rules.REQUIRED_COLUMNS if name not in present]
    if missing:
        raise rules.MissingColumnsError(missing)
    records = _records(rows, rules)

    source = service.SourceData(
        records=records,
        snapshot_at=f"{data_date.isoformat()}T00:00:00+08:00",
        data_date=data_date,
        coverage={"kind": service.W.SCOPE_ALL},
    )
    result = service.compose(
        NullStore(),
        source,
        service.Scope(list(projects), list(departments)),
        region=region,
        effective=effective if effective is not None else service.Effective.seeds(),
        save_snapshot=False,
        today=data_date,
    )
    return {
        "source": {
            "file": path.name,
            "rows": len(records),
            "dataDate": data_date.isoformat(),
            "dataDateConfirmedBy": "user",
            "region": region,
            "projects": list(projects),
            "departments": list(departments),
        },
        "report": result,
    }


def render_markdown(payload: Mapping[str, Any], *, max_rows: int = 30) -> str:
    report = payload["report"]
    source = payload["source"]
    charts = report.get("charts") or {}
    summary = report.get("summary") or {}
    flows = report.get("flows") or []

    lines: list[str] = []
    lines.append("# 3D单签署进展日报（手工导入）")
    lines.append("")
    lines.append(
        f"数据截至日期：{source['dataDate']}（用户确认，未经系统核验）｜"
        f"文件：{source['file']}｜参与计算：{source['rows']} 行"
    )
    lines.append("")
    lines.append(f"**{report['subject']}**")
    lines.append("")
    lines.append("仅供核对｜手工导入｜不计算日变化")
    lines.append("")

    lines.append("## 一、摘要")
    if summary.get("total"):
        lines.append(f"- {_metrics_line('总签单', summary['total'])}")
    if summary.get("longCycle"):
        lines.append(f"- {_metrics_line('长周期', summary['longCycle'])}")
    for line in report.get("summaryLines") or ():
        lines.append(f"- {line}")
    lines.append("")

    lines.append("## 二、三图数据")
    lines.extend(_chart_block("图1 待办欠账（按区域/会签列）", charts.get("external") or ()))
    lines.extend(_chart_block("图2 待办欠账（按科室）", charts.get("sections") or ()))
    lines.extend(_chart_block("图3 待办欠账（审批人）", charts.get("approval") or ()))
    needs_entry = charts.get("needsEntry") or ()
    lines.append("### 待补录人员（花名册里没有）")
    lines.append("  - " + ("、".join(needs_entry) if needs_entry else "（无）"))
    lines.append("")

    lines.append(f"## 三、数据表（前 {min(max_rows, len(flows))} / {len(flows)} 行）")
    lines.append("")
    lines.append("| 流水单号 | 科室 | 阶段 | 会签 已/应 | 总 已/应 | 停留天数 | 零件 | 待办 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for row in flows[:max_rows]:
        countersign = row.get("countersign") or [0, 0]
        total = row.get("total") or [0, 0]
        cells = [
            str(row.get("serial") or ""),
            str(row.get("department") or ""),
            str(row.get("stage") or ""),
            f"{countersign[0]}/{countersign[1]}",
            f"{total[0]}/{total[1]}",
            str(row.get("days") if row.get("days") is not None else ""),
            str(row.get("partLabel") or ""),
            str(row.get("todoText") or "").replace("|", "/"),
        ]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")

    review = (report.get("longCycle") or {}).get("review") or ()
    if review:
        lines.append(f"## 四、长周期初筛待确认（{len(review)} 项）")
        lines.append("")
        lines.append("| 项目 | 零件 | 判定 | 规则 | 涉及流程 |")
        lines.append("| --- | --- | --- | --- | --- |")
        for item in review[:20]:
            lines.append(
                "| "
                + " | ".join([
                    str(item.get("project") or ""),
                    str(item.get("canonical") or item.get("normalized") or ""),
                    str(item.get("result") or ""),
                    str(item.get("rule") or ""),
                    str(item.get("flows") or 0),
                ])
                + " |"
            )
        lines.append("")

    notices = report.get("notices") or ()
    anomalies = report.get("anomalies") or ()
    if notices or anomalies:
        lines.append("## 五、提示")
        for notice in notices:
            lines.append(f"- {notice.get('text', '')}")
        for anomaly in anomalies:
            text = anomaly.get("text") or anomaly.get("kind")
            lines.append(f"- 数据异常：{text}")
        lines.append("")

    gate = report.get("statusGate") or {}
    if gate.get("blocked"):
        lines.append(f"**状态列数字码门禁已触发，禁止对外发送**：{gate.get('text', '')}")
        lines.append("")

    lines.append(
        "> 本地表单模式：不写快照、不写日变化基线、不计算日变化；"
        "生成日期不影响本报告口径（数据截至日期以上方为准）。"
    )
    return "\n".join(lines) + "\n"


_REASONS = {
    "E_NO_FILE": "目录里没有 .xlsx 或 .txt",
    "E_MTIME_TIE": "有两个文件修改时间完全相同，请用 --file 手动指定",
    "E_FILE_WRITING": "最新那份还在写入（大小或时间在变），请稍后再试",
    "E_NEWEST_HIDDEN": "最新的是隐藏文件，已跳过；请改成普通文件或用 --file 指定",
    "E_HEADER_MISMATCH": "最新那份表头与官方 47 列不一致",
    "E_ENCRYPTED_WORKBOOK": "最新那份受公司终端加密保护，本功能读不到内容",
    "E_WORKBOOK_INVALID": "最新那份读不了（不是有效的 .xlsx）",
    "E_TEXT_INVALID": "最新那份文本读不了（请在 Excel 中重新另存为「Unicode 文本」）",
    "E_FILE_TOO_LARGE": "最新那份超过大小上限",
    "E_EMPTY_WORKBOOK": "最新那份没有数据行",
    "E_REQUIRED_COLUMNS": "最新那份缺少日报必需的列",
    "E_DIR_TOO_MANY": "目录项太多，请先清理",
    "E_DIR_UNREADABLE": "目录读不了",
}


def _align_console_encoding() -> None:
    """控制台是 UTF-8 代码页时把输出也切成 UTF-8，避免中文乱码；GBK 终端保持默认。"""
    try:
        import ctypes

        if ctypes.windll.kernel32.GetConsoleOutputCP() != 65001:
            return
    except Exception:  # noqa: BLE001 - 非 Windows / 无控制台时沿用默认编码
        return
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


def _reason_text(code: str | None) -> str:
    return _REASONS.get(str(code or ""), str(code or "E_NO_FILE"))


def _import_failure(exc: OfficialWorkbookError) -> tuple[str, str]:
    """官方工作簿异常 → (code, 文案)：只按 reason 白名单，不回显底层异常原文。"""
    reason = str(getattr(exc, "reason", "") or "").strip()
    if (
        getattr(exc, "is_text", False)
        and isinstance(exc, OfficialWorkbookUnreadable)
        and reason not in ("encrypted_container", "text_encoding", "text_malformed")
    ):
        return _TEXT_FALLBACK
    mapped = _IMPORT_ERRORS.get(reason)
    if mapped is not None:
        return mapped
    if isinstance(exc, OfficialWorkbookTruncated):
        return _TOO_MANY_ROWS
    # 兜底不回显底层异常原文。
    return "E_IMPORT_FAILED", "报表无法导入，请确认是官方导出的签署明细"


def _import_diagnostic(exc: OfficialWorkbookError) -> str:
    """第二行只放枚举诊断（reason，可含 colIndex）；不含十六进制、路径或单元格值。"""
    parts: list[str] = []
    reason = str(getattr(exc, "reason", "") or "").strip()
    if reason:
        parts.append(f"reason={reason}")
    col_index = getattr(exc, "col_index", None)
    if isinstance(col_index, int) and col_index >= 0:
        parts.append(f"colIndex={col_index}")
    return " ".join(parts)


def main(argv: list[str] | None = None) -> int:
    _align_console_encoding()
    parser = argparse.ArgumentParser(
        prog="sign_daily_local_report",
        description="从本地 TDC 数模导出表单生成签署日报（离线只读）",
    )
    parser.add_argument(
        "--file", help="TDC 数模官方导出 .xlsx，或 Excel「另存为文本」得到的 .txt（47 列契约）"
    )
    parser.add_argument(
        "--dir",
        metavar="DIR",
        help="监控目录：取最后修改时间最晚的 .xlsx / .txt 作为最新报表（不合格则报错，不退回更旧的文件）",
    )
    parser.add_argument("--date", required=True, help="数据截至日期 YYYY-MM-DD（必须由人确认）")
    parser.add_argument("--project", action="append", help="项目/车型，可多次或用逗号分隔；缺省=全部")
    parser.add_argument("--department", action="append", help="科室，可多次或用逗号分隔；缺省=全部")
    parser.add_argument("--region", default="", help="正文称呼里的区域，缺省读取插件默认值")
    parser.add_argument("--roster", metavar="CSV", help="花名册 CSV（设置页导出的 姓名,科室 格式）")
    parser.add_argument("--rules", metavar="CSV", help="长周期规则 CSV（设置页导出格式）")
    parser.add_argument("--md", metavar="PATH", help="同时写出 Markdown 报告")
    parser.add_argument("--json", action="store_true", help="打印完整 JSON（含三图与数据表）")
    parser.add_argument("--max-rows", type=int, default=30, help="Markdown 数据表最多打印行数（默认 30）")
    args = parser.parse_args(argv)

    if bool(args.file) == bool(args.dir):
        print("请用 --file 指定一份报表，或用 --dir 指定监控目录（二选一）", file=sys.stderr)
        return 2
    plugin = _load_plugin()
    if args.dir:
        directory = Path(args.dir).expanduser()
        if not directory.is_dir():
            print(f"目录不存在：{directory}", file=sys.stderr)
            return 2
        result = plugin.importer.scan_directory(directory)
        if not result.selected:
            print(
                f"没有自动选中：{_reason_text(result.reason)}"
                "（口径：只认最后修改时间最晚的那份，不合格或时间并列就转人工，不退回更旧的文件）",
                file=sys.stderr,
            )
            return 1
        path = directory / result.selected
        print(f"已选中（最后修改时间最晚）：{result.selected}", file=sys.stderr)
    else:
        path = Path(args.file).expanduser()
    if not path.is_file():
        print(f"文件不存在：{path}", file=sys.stderr)
        return 2
    if path.suffix.lower() not in SUFFIXES:
        print("只接受 .xlsx 或 Excel 另存的 .txt 文件", file=sys.stderr)
        return 2
    try:
        data_date = date.fromisoformat(args.date)
    except ValueError:
        print(f"日期格式不对（要 YYYY-MM-DD）：{args.date}", file=sys.stderr)
        return 2

    region = args.region or plugin.scheduled.DEFAULT_REGION
    roster_csv = Path(args.roster).expanduser() if args.roster else None
    rules_csv = Path(args.rules).expanduser() if args.rules else None
    for label, candidate in (("花名册", roster_csv), ("规则", rules_csv)):
        if candidate is not None and not candidate.is_file():
            print(f"{label}文件不存在：{candidate}", file=sys.stderr)
            return 2
    try:
        payload = build_report(
            path=path,
            data_date=data_date,
            projects=_split(args.project),
            departments=_split(args.department),
            region=region,
            effective=_effective(plugin, roster_csv, rules_csv),
        )
    except OfficialWorkbookError as exc:
        code, text = _import_failure(exc)
        print(f"表单不合格：{code}：{text}", file=sys.stderr)
        diagnostic = _import_diagnostic(exc)
        if diagnostic:
            print(diagnostic, file=sys.stderr)
        return 1
    except plugin.rules.MissingColumnsError as exc:
        print(f"表单缺列：{exc}", file=sys.stderr)
        return 1
    except (LookupError, ValueError) as exc:
        print(f"无法生成：{exc}", file=sys.stderr)
        return 1

    markdown = render_markdown(payload, max_rows=max(0, args.max_rows))
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    else:
        print(markdown, end="")
    if args.md:
        target = Path(args.md).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(markdown, encoding="utf-8")
        print(f"已写出：{target}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
