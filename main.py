# -*- coding: utf-8 -*-
"""
VSE TOOLBOX (CLI Edition) — 主入口模块

功能概述:
    基于 rich 终端渲染的交互式主菜单循环，
    通过数字选项路由到各 service 模块的独立功能。

架构约束:
    - main.py 仅做路由，不包含任何业务逻辑
    - 所有功能调用均通过 services/ 下的模块完成
    - 数据库操作通过 core/db_manager 统一管理
    - 本文件是 CLI 适配层，可使用 rich；service/core 层禁止引入 rich
"""

import logging
import re
import sys
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlsplit

from rich.console import Console
from rich import box
from rich.panel import Panel
from rich.text import Text
from rich.prompt import Prompt, Confirm
from rich.table import Table
from rich.theme import Theme

# ── 项目路径初始化 ──────────────────────────────────────────────
BOOTSTRAP_ROOT = Path(__file__).resolve().parent
if str(BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(BOOTSTRAP_ROOT))

from core.db_manager import DatabaseManager
from core.diagnostics import DiagnosticOptions, MarkdownDiagnosticReport
from core.redaction import redact_sensitive_text, safe_display_value
from core.runtime_paths import app_root
from services.excel_toolbox import ExcelToolbox
from services.feishu_imap import FeishuImapParser
from services.office_toolbox import OfficeToolbox
from services.aras_crawler import (
    ArasCrawlerClient,
    ArasCrawlerError,
    DEFAULT_BROWSER_USER_AGENT,
    EWOReportFilters,
    NCRApprovalFilters,
    PAAReportFilters,
)

PROJECT_ROOT = app_root()

# ── 日志配置 ────────────────────────────────────────────────────
LOG_DIR = PROJECT_ROOT / "data"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    filename=str(LOG_DIR / "vse_toolbox.log"),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    encoding="utf-8",
)
logger = logging.getLogger("vse_toolbox")

DEFAULT_ARAS_BASE_URL = ""

# ── 全局 rich 控制台 ────────────────────────────────────────────
console = Console(
    theme=Theme(
        {
            "vse.title": "bold #9fc7c2",
            "vse.subtitle": "#a7a49a",
            "vse.accent": "#88a6a4",
            "vse.sage": "#9caf88",
            "vse.amber": "#c7ad7a",
            "vse.rose": "#c19191",
            "vse.plum": "#a899b8",
            "vse.muted": "#747a83",
            "vse.error": "bold #c19191",
        }
    )
)

# ── 暂缓（置灰）模块键集合（D1：P1/P3/P4 短路占位）──────────────
DEFERRED: set[str] = {"2", "3"}



def handle_update_deliverables(db: DatabaseManager) -> None:
    """【菜单 1】交互式更新交付物状态"""
    console.print("\n[bold cyan]═══ 更新交付物状态 ═══[/]\n")
    try:
        with db.get_connection() as conn:
            rows = conn.execute(
                "SELECT id, name, owner, status, due_date FROM deliverables ORDER BY due_date"
            ).fetchall()

        if not rows:
            console.print("[yellow]当前无交付物记录，请先通过其他方式导入数据。[/]")
            return

        from rich.table import Table

        table = Table(title="当前交付物列表", show_lines=True)
        table.add_column("ID", justify="center", style="cyan")
        table.add_column("名称", style="white")
        table.add_column("负责人", style="green")
        table.add_column("状态", style="yellow")
        table.add_column("截止日期", style="magenta")

        status_styles = {
            "pending": "[yellow]待开始[/]",
            "in_progress": "[blue]进行中[/]",
            "done": "[green]已完成[/]",
            "blocked": "[red]阻塞[/]",
        }
        for row in rows:
            sid, name, owner, status, due = row
            styled_status = status_styles.get(status, status)
            table.add_row(str(sid), name, owner or "-", styled_status, due or "-")

        console.print(table)

        deliverable_id = Prompt.ask("\n请输入要更新的交付物 ID（输入 q 返回主菜单）")
        if deliverable_id.lower() == "q":
            return

        new_status = Prompt.ask(
            "选择新状态",
            choices=["pending", "in_progress", "done", "blocked"],
            default="pending",
        )
        remark = Prompt.ask("备注（可选，直接回车跳过）", default="")

        with db.get_connection() as conn:
            conn.execute(
                "UPDATE deliverables SET status=?, remark=?, updated_at=datetime('now','localtime') WHERE id=?",
                (new_status, remark, int(deliverable_id)),
            )
            conn.commit()

        console.print(f"[green]✓ 交付物 #{deliverable_id} 状态已更新为 {new_status}[/]")
        logger.info("交付物 #%s 状态更新为 %s", deliverable_id, new_status)

    except (ValueError, TypeError) as e:
        console.print(f"[red]错误: 输入无效 — {e}[/]")
        logger.error("更新交付物状态时输入无效: %s", e)
    except Exception as e:
        console.print(f"[red]错误: 更新失败 — {e}[/]")
        logger.exception("更新交付物状态时发生异常")


def handle_generate_ppt(db: DatabaseManager) -> None:
    """【菜单 2 · P3 暂缓】生成周报 PPT"""
    # D1 短路：P3 暂缓，仅提示后返回，保留原业务代码供后续 Sprint 解除暂缓
    console.print("\n[dim]该模块（P3 周报 PPT）暂缓开放，敬请期待。[/]")
    return  # noqa: 以下为保留的原业务代码，暂不执行
    console.print("\n[bold cyan]═══ 生成周报 PPT ═══[/]\n")
    try:
        toolbox = OfficeToolbox(db)
        output_path = toolbox.refresh_weekly_ppt()
        console.print(f"[green]✓ 周报 PPT 已生成: {output_path}[/]")
    except FileNotFoundError as e:
        console.print(f"[red]错误: 模板文件未找到 — {e}[/]")
        logger.error("PPT 模板文件未找到: %s", e)
    except PermissionError as e:
        console.print(f"[red]错误: 文件被占用或无写入权限 — {e}[/]")
        logger.error("PPT 写入权限错误: %s", e)
    except Exception as e:
        console.print(f"[red]错误: PPT 生成失败 — {e}[/]")
        logger.exception("生成周报 PPT 时发生异常")


def handle_scan_feishu(db: DatabaseManager) -> None:
    """【菜单 3 · P4 暂缓】扫描飞书待办"""
    # D1 短路：P4 暂缓，仅提示后返回，保留原业务代码供后续 Sprint 解除暂缓
    console.print("\n[dim]该模块（P4 飞书助手）暂缓开放，敬请期待。[/]")
    return  # noqa: 以下为保留的原业务代码，暂不执行
    console.print("\n[bold cyan]═══ 扫描飞书待办 ═══[/]\n")
    try:
        parser = FeishuImapParser(db)
        count = parser.scan_and_parse()
        console.print(f"[green]✓ 本次解析并入库 {count} 条飞书待办任务[/]")
    except ConnectionError as e:
        console.print(f"[red]错误: IMAP 连接失败 — {e}[/]")
        logger.error("IMAP 连接失败: %s", e)
    except Exception as e:
        console.print(f"[red]错误: 飞书邮件解析失败 — {e}[/]")
        logger.exception("扫描飞书待办时发生异常")



def _blank_to_none(value: str) -> str | None:
    value = value.strip()
    return value or None


def _parse_header_lines(raw: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    for part in re.split(r"\r?\n|,\s*(?=[A-Za-z0-9_-]+\s*:)", raw):
        item = part.strip()
        if not item or ":" not in item:
            continue
        key, value = item.split(":", 1)
        key = key.strip()
        value = value.strip()
        if key and value:
            headers[key] = value
    return headers


def _contains_control_char(value: str) -> bool:
    return any(ord(char) < 32 or ord(char) == 127 for char in value)


def _normalize_cookie_header(raw: str) -> str:
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    cookie_line = next((line for line in lines if line.lower().startswith("cookie:")), "")
    cookie = cookie_line or " ".join(lines) or raw.strip()
    if cookie.lower().startswith("cookie:"):
        cookie = cookie.split(":", 1)[1].strip()
    return cookie


def _ask_cookie_header() -> str:
    console.print("Cookie header（可粘贴多行，空行结束；直接回车跳过）:")
    lines: list[str] = []
    while True:
        line = console.input("Cookie> " if not lines else "      > ")
        if line == "":
            break
        lines.append(line)
    return _normalize_cookie_header("\n".join(lines))


def _ask_extra_headers(default_headers: str) -> str:
    console.print(
        "Extra headers（建议从浏览器 DevTools 复制成功的 InnovatorServer.aspx 请求头；"
        "可粘贴多行，空行结束；直接回车使用默认 headers）:"
    )
    lines: list[str] = []
    while True:
        line = console.input("Header> " if not lines else "      > ")
        if line == "":
            break
        lines.append(line)
    return "\n".join(lines) if lines else default_headers


def _has_header(headers: dict[str, str], name: str) -> bool:
    return any(key.lower() == name.lower() for key in headers)


def _default_aras_headers_text(base_url: str) -> str:
    parsed = urlsplit(base_url.rstrip("/") + "/")
    origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else base_url.rstrip("/")
    headers = {
        "Origin": origin,
        "Referer": urljoin(origin + "/", "innovatorserver/Client/default.aspx"),
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Connection": "keep-alive",
        "TIMEZONE_NAME": "China Standard Time",
        "User-Agent": DEFAULT_BROWSER_USER_AGENT,
    }
    return ", ".join(f"{key}: {value}" for key, value in headers.items())



def _ask_positive_int(label: str, default: int) -> int:
    raw = Prompt.ask(label, default=str(default))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        console.print(f"[vse.amber]{label} invalid, using {default}[/]")
        return default
    if value <= 0:
        console.print(f"[vse.amber]{label} must be positive, using {default}[/]")
        return default
    return value


def _ask_aras_connection() -> tuple[str, dict[str, str], dict[str, str] | None]:
    base_url = Prompt.ask("Aras base_url", default=DEFAULT_ARAS_BASE_URL).strip()
    if not base_url:
        return "", {}, None
    default_headers = _default_aras_headers_text(base_url) if base_url else ""
    raw_headers = _ask_extra_headers(default_headers)
    headers = _parse_header_lines(raw_headers)
    cookie = _ask_cookie_header()
    if cookie:
        if _contains_control_char(cookie):
            console.print("[vse.amber]Cookie header contains control characters and was ignored. Please paste plain text.[/]")
        else:
            headers["Cookie"] = cookie
    if not _has_header(headers, "Authorization"):
        console.print(
            "[vse.amber]当前 Aras 可能需要 Authorization: Bearer token；"
            "若遇到 401，请从浏览器成功的 InnovatorServer.aspx 请求复制 Authorization header。[/]"
        )
    return base_url, headers, None


def _ask_aras_diagnostic_options() -> DiagnosticOptions:
    enabled = Confirm.ask("生成 Aras 调试诊断 MD 报告？", default=False)
    if not enabled:
        return DiagnosticOptions()
    unsafe_raw = Confirm.ask("报告中包含原始 Cookie/token/Authorization？仅排障使用", default=False)
    return DiagnosticOptions(enabled=True, unsafe_raw=unsafe_raw)


def _ask_ewo_filters() -> tuple[EWOReportFilters, int, int, int]:
    filters = EWOReportFilters(
        ewo_no=_blank_to_none(Prompt.ask("EWO no", default="")),
        project_code=_blank_to_none(Prompt.ask("Project code", default="")),
        subject_keyword=_blank_to_none(Prompt.ask("Subject keyword", default="")),
        change_type=_blank_to_none(Prompt.ask("Change type", default="")),
        change_sub_type=_blank_to_none(Prompt.ask("Change sub type", default="")),
        area=_blank_to_none(Prompt.ask("Area", default="")),
        state=_blank_to_none(Prompt.ask("State", default="")),
        rsp_department=_blank_to_none(Prompt.ask("Response department", default="")),
        submit_start=_blank_to_none(Prompt.ask("Submit start", default="")),
        submit_end=_blank_to_none(Prompt.ask("Submit end", default="")),
    )
    return (
        filters,
        _ask_positive_int("Page", 1),
        _ask_positive_int("Page size", 50),
        _ask_positive_int("Max records", 2000),
    )


def _ask_paa_filters() -> tuple[PAAReportFilters, int, int, int, int]:
    filters = PAAReportFilters(
        paa_no=_blank_to_none(Prompt.ask("PAA no", default="")),
        ewo_no=_blank_to_none(Prompt.ask("EWO no", default="")),
        state=_blank_to_none(Prompt.ask("State", default="")),
        area=_blank_to_none(Prompt.ask("Area", default="")),
        base=_blank_to_none(Prompt.ask("Base", default="")),
        vehicle_keyword=_blank_to_none(Prompt.ask("Vehicle keyword", default="")),
        submit_start=_blank_to_none(Prompt.ask("Submit start", default="")),
        submit_end=_blank_to_none(Prompt.ask("Submit end", default="")),
        mtl_rq_start=_blank_to_none(Prompt.ask("Material request start", default="")),
        mtl_rq_end=_blank_to_none(Prompt.ask("Material request end", default="")),
    )
    return (
        filters,
        _ask_positive_int("Page", 1),
        _ask_positive_int("Page size", 50),
        _ask_positive_int("Max records", 2000),
        _ask_positive_int("Max pages", 20),
    )


def _ask_ncr_filters() -> NCRApprovalFilters:
    projects = [
        item.strip()
        for item in Prompt.ask("项目名称（多个用逗号分隔）", default="").split(",")
        if item.strip()
    ]
    return NCRApprovalFilters(
        buy_start=_blank_to_none(Prompt.ask("采购开始日期", default="")),
        buy_end=_blank_to_none(Prompt.ask("采购结束日期", default="")),
        pe_start=_blank_to_none(Prompt.ask("PE 开始日期", default="")),
        pe_end=_blank_to_none(Prompt.ask("PE 结束日期", default="")),
        ncr_no=_blank_to_none(Prompt.ask("NCR 编号", default="")),
        project_names=tuple(projects),
        section_code=_blank_to_none(Prompt.ask("科室代码", default="")),
        change_type=_blank_to_none(Prompt.ask("变更类型", default="")),
        othercondition=Prompt.ask("othercondition", default="0").strip() or "0",
    )



_SENSITIVE_DISPLAY_KEYS = {
    "raw_xml",
    "authorization",
    "cookie",
    "token",
    "api_key",
    "sid",
    "sessionid",
    "csrf",
    "secret",
    "password",
}

_EWO_COLUMNS = [
    "_no",
    "_eplmwriteneplcode",
    "_subject",
    "_area",
    "_sort_type",
    "_rsp_department",
    "_submit_time",
    "state",
]

_PAA_COLUMNS = [
    "_no",
    "_ewo_no",
    "state",
    "_area",
    "_base",
    "_vehicles",
    "_submit_date",
    "_mtl_rq_date",
]


def _safe_error_message(exc: Exception) -> str:
    return redact_sensitive_text(exc)


def _select_display_columns(rows, preferred, max_columns=12) -> list[str]:
    columns: list[str] = []
    available = {key for row in rows for key in row if str(key).lower() not in _SENSITIVE_DISPLAY_KEYS}
    for key in preferred:
        if key in available and key not in columns:
            columns.append(key)
    extra = sorted(key for key in available if key not in columns)
    columns.extend(extra)
    return columns[:max_columns]


def _render_report_rows(title, page, rows, item_ids, preferred_columns) -> Table:
    table = Table(
        title=f"{title} | page={page or '-'} rows={len(rows)} items={len(item_ids)}",
        show_lines=True,
        box=box.SIMPLE_HEAVY,
    )
    keys = _select_display_columns(rows, preferred_columns)
    for key in keys or ["message"]:
        table.add_column(key, overflow="fold")
    if rows:
        for row in rows:
            table.add_row(*(safe_display_value(row.get(key)) for key in keys))
    else:
        table.add_row("No results")
    return table


def _render_ewo_result(page) -> Table:
    return _render_report_rows("EWO report result", page.page, page.rows, page.item_ids, _EWO_COLUMNS)


def _render_paa_result(page) -> Table:
    return _render_report_rows("PAA report result", page.page, page.rows, page.item_ids, _PAA_COLUMNS)


def _render_ncr_progress_result(result) -> Table:
    table = Table(title="NCR approval progress result", show_lines=True, box=box.SIMPLE_HEAVY)
    table.add_column("field", style="#88a6a4", no_wrap=True)
    table.add_column("value", overflow="fold")
    table.add_row("file_name", safe_display_value(getattr(result, "file_name", None)))
    table.add_row("record_id", safe_display_value(getattr(result, "record_id", None)))
    return table


def _render_ncr_detail_result(result) -> Table:
    table = Table(title="NCR approval detail result", show_lines=True, box=box.SIMPLE_HEAVY)
    table.add_column("field", style="#88a6a4", no_wrap=True)
    table.add_column("value", overflow="fold")
    table.add_row("file_name", safe_display_value(getattr(result, "file_name", None)))
    return table



def handle_intranet_scrape(db: DatabaseManager) -> None:
    """Menu 4: Aras CLI adapter."""
    menu = Table(box=box.SIMPLE_HEAVY, show_header=False)
    menu.add_column("Key", style="#88a6a4", no_wrap=True)
    menu.add_column("Mode")
    menu.add_row("1", "EWO report query")
    menu.add_row("2", "NCR approval progress")
    menu.add_row("3", "NCR approval detail")
    menu.add_row("4", "PAA paged query")
    menu.add_row("5", "PAA full crawl")
    menu.add_row("0", "Return")
    console.print(Panel(menu, title="Aras Cockpit", border_style="#88a6a4", box=box.ROUNDED))
    sub = Prompt.ask("Select Aras mode", choices=["0", "1", "2", "3", "4", "5"], default="0")
    if sub == "0":
        return

    report: MarkdownDiagnosticReport | None = None
    try:
        diagnostic_options = _ask_aras_diagnostic_options()
        base_url, headers, cookies = _ask_aras_connection()
        if not base_url:
            console.print("[bold #c19191]base_url is required[/]")
            return
        parsed = urlsplit(base_url.rstrip("/") + "/")
        origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else base_url
        report = MarkdownDiagnosticReport(
            options=diagnostic_options,
            base_url=base_url,
            mode=sub,
            inputs={
                "sub_menu": sub,
                "origin": origin,
                "headers": headers,
                "cookies": cookies,
                "timeout": 30.0,
            },
        )
        client = ArasCrawlerClient(
            base_url,
            headers=headers,
            cookies=cookies,
            timeout=30.0,
            diagnostic_hook=report.record_http_event if diagnostic_options.enabled else None,
        )

        if sub == "1":
            filters, page, page_size, max_records = _ask_ewo_filters()
            console.print(
                f"[#747a83]mode=EWO origin={origin} page={page} page_size={page_size} max_records={max_records}[/]"
            )
            with console.status("Querying Aras", spinner="dots"):
                result = client.query_ewo_report(filters, page=page, page_size=page_size, max_records=max_records)
            console.print(_render_ewo_result(result))
            if report_path := report.save("success"):
                console.print(f"[#747a83]诊断报告已保存: {report_path}[/]")
        elif sub == "2":
            console.print(f"[#747a83]mode=NCR progress origin={origin}[/]")
            filters = _ask_ncr_filters()
            with console.status("Querying Aras", spinner="dots"):
                result = client.query_ncr_approval_progress(filters)
            console.print(_render_ncr_progress_result(result))
            if report_path := report.save("success"):
                console.print(f"[#747a83]诊断报告已保存: {report_path}[/]")
        elif sub == "3":
            console.print(f"[#747a83]mode=NCR detail origin={origin}[/]")
            filters = _ask_ncr_filters()
            with console.status("Querying Aras", spinner="dots"):
                result = client.extract_ncr_approval_detail(filters)
            console.print(_render_ncr_detail_result(result))
            if report_path := report.save("success"):
                console.print(f"[#747a83]诊断报告已保存: {report_path}[/]")
        elif sub == "4":
            filters, page, page_size, max_records, _max_pages = _ask_paa_filters()
            console.print(
                f"[#747a83]mode=PAA origin={origin} page={page} page_size={page_size} max_records={max_records}[/]"
            )
            with console.status("Querying Aras", spinner="dots"):
                result = client.query_paa_report(filters, page=page, page_size=page_size, max_records=max_records)
            console.print(_render_paa_result(result))
            if report_path := report.save("success"):
                console.print(f"[#747a83]诊断报告已保存: {report_path}[/]")
        elif sub == "5":
            filters, _page, page_size, max_records, max_pages = _ask_paa_filters()
            if not Confirm.ask("PAA full crawl may be slow. Continue?", default=False):
                console.print("[#747a83]PAA full crawl cancelled[/]")
                return
            console.print(
                f"[#747a83]mode=PAA all origin={origin} page_size={page_size} max_pages={max_pages} max_records={max_records}[/]"
            )
            with console.status("Querying Aras", spinner="dots"):
                result = client.crawl_paa_report_all(
                    filters,
                    page_size=page_size,
                    max_pages=max_pages,
                    max_records=max_records,
                )
            console.print(_render_paa_result(result))
            if report_path := report.save("success"):
                console.print(f"[#747a83]诊断报告已保存: {report_path}[/]")
        logger.info("Aras CLI query finished: type=%s", sub)
    except ArasCrawlerError as e:
        console.print(Panel(_safe_error_message(e), title="ArasCrawlerError", border_style="#c19191"))
        if report:
            report.record_exception(e)
            if report_path := report.save("failed"):
                console.print(f"[#c19191]诊断报告已保存: {report_path}[/]")
        logger.warning("Aras CLI query failed with ArasCrawlerError")
    except Exception as e:
        console.print(Panel(_safe_error_message(e), title=type(e).__name__, border_style="#c19191"))
        if report:
            report.record_exception(e)
            if report_path := report.save("failed"):
                console.print(f"[#c19191]诊断报告已保存: {report_path}[/]")
        logger.warning("Aras CLI query failed: %s", type(e).__name__)


def handle_project_overview(db: DatabaseManager) -> None:
    """【菜单 5】查看项目概览统计"""
    console.print("\n[bold cyan]═══ 项目概览 ═══[/]\n")
    try:
        with db.get_connection() as conn:
            projects = conn.execute(
                "SELECT status, COUNT(*) FROM projects GROUP BY status"
            ).fetchall()
            deliverables = conn.execute(
                "SELECT status, COUNT(*) FROM deliverables GROUP BY status"
            ).fetchall()
            feishu_total = conn.execute("SELECT COUNT(*) FROM feishu_tasks").fetchone()[0]
            feishu_synced = conn.execute(
                "SELECT COUNT(*) FROM feishu_tasks WHERE synced=1"
            ).fetchone()[0]

        from rich.table import Table

        table = Table(title="项目统计概览", show_lines=True)
        table.add_column("类别", style="cyan")
        table.add_column("状态", style="white")
        table.add_column("数量", justify="right", style="green")

        for status, count in projects:
            table.add_row("项目", status, str(count))
        for status, count in deliverables:
            table.add_row("交付物", status, str(count))
        table.add_row("飞书待办", "总计", str(feishu_total))
        table.add_row("飞书待办", "已同步", str(feishu_synced))

        console.print(table)

    except Exception as e:
        console.print(f"[red]错误: 查询概览失败 — {e}[/]")
        logger.exception("查看项目概览时发生异常")


def handle_excel_toolbox(db: DatabaseManager) -> None:
    """【菜单 6 · P0】Excel 工具箱二级菜单（CLI 适配层）"""
    console.print("\n[bold cyan]═══ Excel 工具箱 ═══[/]\n")
    console.print("  [bold white]1[/] ── 纵向追加合并")
    console.print("  [bold white]2[/] ── 坐标重合合并")
    console.print("  [bold white]3[/] ── 差异比对")
    console.print("  [dim]0[/] ── 返回主菜单")
    console.print()

    sub = Prompt.ask("[bold]请选择操作[/]", choices=["0", "1", "2", "3"], default="0")
    if sub == "0":
        return

    toolbox = ExcelToolbox()

    def _ask_paths(prompt_text: str) -> list[Path]:
        raw = Prompt.ask(prompt_text)
        return [Path(p.strip()) for p in raw.split(",") if p.strip()]

    def _ask_path_optional(prompt_text: str) -> Path | None:
        raw = Prompt.ask(f"{prompt_text}（直接回车跳过）", default="")
        return Path(raw.strip()) if raw.strip() else None

    try:
        if sub == "1":
            sources = _ask_paths("源文件路径（多个以逗号分隔）")
            baseline = _ask_path_optional("基线文件路径")
            output = _ask_path_optional("输出路径")
            result = toolbox.merge_append(sources, output_path=output, baseline=baseline)
            console.print(f"[green]✓ 纵向追加合并完成: {result}[/]")

        elif sub == "2":
            sources = _ask_paths("来源文件路径（多个以逗号分隔）")
            target = Path(Prompt.ask("底层目标文件路径"))
            baseline = _ask_path_optional("基线文件路径")
            output = _ask_path_optional("输出路径")
            result = toolbox.merge_overlay(sources, target, output_path=output, baseline=baseline)
            console.print(f"[green]✓ 坐标重合合并完成: {result}[/]")

        elif sub == "3":
            target = Path(Prompt.ask("待比对文件路径"))
            baseline = Path(Prompt.ask("基线文件路径"))
            output = _ask_path_optional("输出路径")
            result = toolbox.diff_against_baseline(target, baseline, output_path=output)
            console.print(f"[green]✓ 差异比对完成: {result}[/]")

    except PermissionError as e:
        console.print(f"[red]错误: 文件被占用 — {e}[/]")
        logger.error("Excel 工具箱权限错误: %s", e)
    except FileNotFoundError as e:
        console.print(f"[red]错误: 文件未找到 — {e}[/]")
        logger.error("Excel 工具箱文件未找到: %s", e)
    except EOFError:
        return
    except Exception as e:
        console.print(f"[red]错误: Excel 操作失败 — {e}[/]")
        logger.exception("Excel 工具箱发生异常")


def handle_exit(db: DatabaseManager) -> None:
    """【菜单 0】退出系统"""
    if Confirm.ask("确定要退出 VSE TOOLBOX 吗？", default=True):
        console.print("[bold green]再见！VSE TOOLBOX 已安全退出。[/]")
        logger.info("用户正常退出系统")
        sys.exit(0)


# ── 菜单配置（须在所有 handle_* 之后定义） ────────────────────────
MENU_OPTIONS: dict[str, tuple[str, Callable[[DatabaseManager], None]]] = {
    "1": ("更新交付物状态", handle_update_deliverables),
    "2": ("生成周报 PPT", handle_generate_ppt),
    "3": ("扫描飞书待办", handle_scan_feishu),
    "4": ("内网数据抓取", handle_intranet_scrape),
    "5": ("查看项目概览", handle_project_overview),
    "6": ("Excel 工具箱 (P0)", handle_excel_toolbox),
    "0": ("退出系统", handle_exit),
}


def show_banner() -> None:
    """Render the CLI workbench banner."""
    banner = Text()
    banner.append("VSE TOOLBOX", style="vse.title")
    banner.append("  CLI Workbench", style="vse.subtitle")
    banner.append(f"\nData directory: {LOG_DIR}", style="vse.muted")
    console.print(Panel.fit(banner, border_style="vse.accent", box=box.ROUNDED))


def show_menu() -> None:
    """Render the main menu with stable option numbers."""
    rows = {
        "1": ("Deliverables", "Ready", "Update deliverable status"),
        "2": ("Weekly PPT", "Paused", "Deferred module"),
        "3": ("Feishu Assistant", "Paused", "Deferred module"),
        "4": ("Aras Cockpit", "Ready", "EWO, PAA and NCR queries"),
        "5": ("Overview", "Web", "Project dashboard summary"),
        "6": ("Excel Toolbox", "CLI", "Append, overlay and diff workbooks"),
        "0": ("Exit", "Ready", "Close VSE Toolbox"),
    }
    table = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="vse.muted")
    table.add_column("#", style="vse.accent", no_wrap=True)
    table.add_column("Module")
    table.add_column("Status", no_wrap=True)
    table.add_column("Description", style="vse.subtitle")
    for key, (label, _) in MENU_OPTIONS.items():
        module, status, description = rows.get(key, (label, "Ready", label))
        status_style = {
            "Ready": "vse.sage",
            "CLI": "vse.amber",
            "Web": "vse.plum",
            "Paused": "vse.muted",
        }.get(status, "vse.subtitle")
        table.add_row(key, module, f"[{status_style}]{status}[/]", description)
    console.print()
    console.print(table)
    console.print()


def main() -> None:
    """CLI 主循环入口"""
    logger.info("VSE TOOLBOX 启动")
    show_banner()

    db = DatabaseManager()
    db.init_database()
    console.print("[dim]数据库已就绪[/]")

    while True:
        try:
            show_menu()
            choice = Prompt.ask(
                "[bold]请输入选项编号[/]",
                choices=list(MENU_OPTIONS.keys()),
                default="0",
            )
            label, handler = MENU_OPTIONS[choice]
            handler(db)

        except KeyboardInterrupt:
            console.print("\n\n[bold green]收到中断信号，安全退出。[/]")
            logger.info("用户通过 Ctrl+C 中断退出")
            sys.exit(0)
        except EOFError:
            console.print("\n[bold green]输入流结束，安全退出。[/]")
            logger.info("EOF 输入流结束")
            sys.exit(0)
        except Exception as e:
            console.print(f"[red]未预期的错误: {e}[/]")
            logger.exception("主循环中发生未预期异常")


if __name__ == "__main__":
    main()

