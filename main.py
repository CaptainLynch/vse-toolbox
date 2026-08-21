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

import argparse
import logging
import re
import sys
from pathlib import Path
from typing import Callable, Sequence
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
from core.archive_store import ArchiveStore
from services.excel_toolbox import ExcelToolbox
from services.feishu_imap import FeishuImapParser
from services.office_toolbox import OfficeToolbox
from services.aras_crawler import (
    ArasCrawlerClient,
    ArasCrawlerError,
    DEFAULT_BROWSER_USER_AGENT,
    DEFAULT_PAA_SELECT_FIELDS,
    EWOReportFilters,
    NCRApprovalFilters,
    PAAReportFilters,
)
from services.aras_auth import ArasAuthError, ArasECMAuthClient
from services.aras_department_mapping import (
    NCR_SECTION_CODES,
    normalize_departments,
    resolve_ncr_section_codes,
)
from services.aras_export import export_ewo_report_csv, export_report_csv
from services.tdc_crawler import (
    AFACE_CONTRACT_BLOCKER,
    DATA_MODEL_PAGE_PATH,
    DEFAULT_TDC_BASE_URL,
    SOR_PAGE_PATH,
    TDCAFaceFilters,
    TDCCrawlerClient,
    TDCCrawlerError,
    TDCDataModelFilters,
    TDCHttpDiagnosticEvent,
    TDCSORFilters,
    combine_diagnostic_hooks,
)
from services.tdc_auth import TDCAuthError, TDCPasswordAuthClient
from services.project_status_updates import ProjectStatusUpdateService
from services.project_status_sync_runner import (
    BindingRunResult,
    EXIT_ATTENTION,
    EXIT_FAILED,
    EXIT_INTERRUPTED,
    EXIT_OK,
    ProjectStatusSyncRunner,
    RunOnceResult,
    create_production_registry,
)
from services.tdc_contract_probe import (
    REPORT_DIR_NAME,
    TDCContractProbeOptions,
    build_report,
    get_filter_field_labels,
    save_report,
    validate_categorical_fields,
    validate_filters_non_empty,
    validate_options,
)
import tdc_probe_cli as _probe_cli

PROJECT_ROOT = app_root()

# ── 日志配置 ────────────────────────────────────────────────────
LOG_DIR = PROJECT_ROOT / "data"
LOG_DIR.mkdir(parents=True, exist_ok=True)

try:
    logging.basicConfig(
        filename=str(LOG_DIR / "vse_toolbox.log"),
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        encoding="utf-8",
    )
except OSError:
    # A stale or policy-protected log file must not prevent the CLI or tests from starting.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
logger = logging.getLogger("vse_toolbox")

DEFAULT_ARAS_BASE_URL = "http://ecm.sgmw.com.cn/innovatorserver"

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
    cookie_parts: list[str] = []
    for line in lines:
        if line.lower().startswith("cookie:"):
            line = line.split(":", 1)[1].strip()
        elif re.match(r"^[A-Za-z0-9_-]+\s*:", line):
            continue
        if line:
            cookie_parts.append(line.strip(" ;"))
    return "; ".join(part for part in cookie_parts if part) or raw.strip()


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
    """Ask for extra headers, visibly showing the safe plaintext defaults.

    Enter accepts the defaults; pasted headers replace them. Only non-secret
    browser/SOAP headers appear in the defaults (never Cookie/Authorization/
    token/password).
    """
    console.print(
        "Extra headers（可粘贴多行，空行结束；直接回车使用下列安全默认 headers）:"
    )
    for line in default_headers.split(", "):
        if line:
            console.print(f"  [dim]{line}[/]")
    lines: list[str] = []
    while True:
        line = console.input("Header> " if not lines else "      > ")
        if line == "":
            break
        lines.append(line)
    return "\n".join(lines) if lines else default_headers


def _ask_tdc_extra_headers(default_headers: str) -> str:
    console.print(
        "Extra headers（可粘贴浏览器中对应 TDC 页面请求头；"
        "可粘贴多行，空行结束；直接回车使用安全默认 headers）:"
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


def _reject_aras_secret_headers(headers: dict[str, str]) -> None:
    """Fail fast when Aras extra headers carry Cookie/Authorization.

    The Aras CLI authenticates with ECM username/password only; pasted
    Cookie/Authorization values are rejected with a credential-free message
    instead of being silently ignored or used as a fallback.
    """
    for name in ("Cookie", "Authorization"):
        if _has_header(headers, name):
            raise ValueError(
                f"Extra headers must not contain {name}: Aras 登录仅支持 ECM 用户名/密码，"
                "请勿在 Extra headers 粘贴 Cookie/Authorization"
            )


def _default_aras_headers_text(base_url: str) -> str:
    """Safe plaintext default extra headers for the Aras CLI flow.

    Only non-secret browser/SOAP headers are included: Accept, Accept-Language,
    Content-Type, Origin, Referer, TIMEZONE_NAME, User-Agent.
    """
    parsed = urlsplit(base_url.rstrip("/") + "/")
    origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else base_url.rstrip("/")
    headers = {
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Content-Type": "text/xml; charset=UTF-8",
        "Origin": origin,
        "Referer": urljoin(origin + "/", "innovatorserver/Client/default.aspx"),
        "TIMEZONE_NAME": "China Standard Time",
        "User-Agent": DEFAULT_BROWSER_USER_AGENT,
    }
    return ", ".join(f"{key}: {value}" for key, value in headers.items())


def _default_tdc_headers_text(base_url: str, page_path: str) -> str:
    parsed = urlsplit(base_url.rstrip("/") + "/")
    origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else base_url.rstrip("/")
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "User-Agent": DEFAULT_BROWSER_USER_AGENT,
        "Referer": urljoin(origin + "/", page_path.lstrip("/")),
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


def _ask_aras_connection() -> tuple[str, dict[str, str], tuple[str, str] | None]:
    """Ask for the Aras connection: base_url, extra headers, ECM username/password.

    The base_url prompt displays the plaintext default
    ``http://ecm.sgmw.com.cn/innovatorserver`` and the extra headers prompt
    visibly shows the safe defaults (Enter accepts them). Cookie and
    Authorization in extra headers are rejected fail-fast with a
    credential-free message. Authentication is username + hidden password only;
    both are required after a nonblank base_url, with no Cookie prompt and no
    silent Cookie fallback.
    """
    base_url = Prompt.ask("Aras base_url", default=DEFAULT_ARAS_BASE_URL).strip()
    if not base_url:
        return "", {}, None
    default_headers = _default_aras_headers_text(base_url)
    raw_headers = _ask_extra_headers(default_headers)
    headers = _parse_header_lines(raw_headers)
    _reject_aras_secret_headers(headers)
    username = Prompt.ask("ECM 用户名", default="").strip()
    if not username:
        raise ValueError("ECM 用户名不能为空：Aras 登录仅支持 ECM 用户名/密码，拒绝无凭据访问")
    password = Prompt.ask("ECM 密码", password=True)
    if not password:
        raise ValueError("ECM 密码不能为空：Aras 登录仅支持 ECM 用户名/密码，拒绝无凭据访问")
    credentials = (username, password)
    if urlsplit(base_url).scheme.lower() == "http":
        console.print(
            "[vse.amber]警告：当前 Aras 地址使用 HTTP。账号密码仅发送到 HTTPS 企业账号中心"
            "（account.sgmw.com.cn），不会发送到此 HTTP 地址；登录后的 Bearer/SOAP 数据请求将走明文 HTTP。[/]"
        )
    console.print(
        "[vse.amber]认证说明：Aras 将通过企业账号中心（ECM 账号密码）登录，"
        "登录成功后才会调用 SOAP ValidateUser 校验会话；"
        "不会使用 Cookie 登录，也不会在失败时回退到 Cookie。[/]"
    )
    return base_url, headers, credentials


def _ask_tdc_connection(page_path: str) -> tuple[str, dict[str, str]]:
    base_url = Prompt.ask("TDC base_url", default=DEFAULT_TDC_BASE_URL).strip()
    raw_headers = _ask_tdc_extra_headers(_default_tdc_headers_text(base_url, page_path))
    headers = _parse_header_lines(raw_headers)
    cookie = _ask_cookie_header()
    if cookie:
        if _contains_control_char(cookie):
            console.print("[vse.amber]Cookie header contains control characters and was ignored.[/]")
        else:
            headers["Cookie"] = cookie
    return base_url, headers


def _ask_tdc_login_mode() -> str:
    table = Table(box=box.SIMPLE_HEAVY, show_header=False)
    table.add_column("Key", style="#88a6a4", no_wrap=True)
    table.add_column("Login")
    table.add_row("1", "账号密码登录（主要）")
    table.add_row("2", "浏览器 Header/Cookie（备用）")
    table.add_row("0", "返回 TDC 菜单")
    console.print(table)
    return Prompt.ask("选择登录方式", choices=["0", "1", "2"], default="1")


def _ask_tdc_password_connection() -> tuple[str, str, str]:
    base_url = Prompt.ask("TDC base_url", default=DEFAULT_TDC_BASE_URL).strip()
    username = Prompt.ask("TDC 用户名", default="").strip()
    password = Prompt.ask("TDC 密码", password=True)
    return base_url, username, password


def _ask_aras_diagnostic_options() -> DiagnosticOptions:
    enabled = Confirm.ask("生成 Aras 调试诊断 MD 报告？", default=False)
    if not enabled:
        return DiagnosticOptions()
    unsafe_raw = Confirm.ask("报告中包含原始 Cookie/token/Authorization？仅排障使用", default=False)
    return DiagnosticOptions(enabled=True, unsafe_raw=unsafe_raw)


#: Fixed page size for full export crawls (EWO/PAA) — not derived from max_records.
_FULL_EXPORT_PAGE_SIZE = 2000


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
    department = _ask_department_filter("业务部门（多个用逗号分隔，可空）")
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
        department=department,
    )
    return (
        filters,
        _ask_positive_int("Page", 1),
        _ask_positive_int("Page size", 50),
        _ask_positive_int("Max records", 2000),
        _ask_positive_int("Max pages", 1000),
    )


def _ask_department_filter(label: str) -> str | None:
    """Ask a business department and normalize it fail-closed to system departments.

    Unknown names raise ValueError, which the Aras menu surfaces as a safe error
    and returns to the menu; blank input means no department filter.
    """
    raw = _blank_to_none(Prompt.ask(label, default=""))
    if not raw:
        return None
    names = [part.strip() for part in raw.split(",") if part.strip()]
    if not names:
        return None
    return ",".join(dict.fromkeys(normalize_departments(names)))


def _ask_ncr_filters() -> NCRApprovalFilters:
    projects = [
        item.strip()
        for item in Prompt.ask("项目名称（多个用逗号分隔）", default="").split(",")
        if item.strip()
    ]
    raw_department = _blank_to_none(
        Prompt.ask("业务部门（多个用逗号分隔，可空；映射为科室代码）", default="")
    )
    section_codes: tuple[str, ...] = ()
    if raw_department:
        names = [part.strip() for part in raw_department.split(",") if part.strip()]
        section_codes = resolve_ncr_section_codes(names)
    section_codes_hint = "，".join(NCR_SECTION_CODES)
    return NCRApprovalFilters(
        buy_start=_blank_to_none(Prompt.ask("采购开始日期", default="")),
        buy_end=_blank_to_none(Prompt.ask("采购结束日期", default="")),
        pe_start=_blank_to_none(Prompt.ask("PE 开始日期", default="")),
        pe_end=_blank_to_none(Prompt.ask("PE 结束日期", default="")),
        ncr_no=_blank_to_none(Prompt.ask("NCR 编号", default="")),
        project_names=tuple(projects),
        section_code=_blank_to_none(Prompt.ask(f"科室代码（高级，可空；例如 {section_codes_hint}）", default="")),
        section_codes=section_codes,
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
    "applicanttel",
    "phone",
    "telephone",
    "mobile",
}

_EWO_COLUMNS = [
    "_no",
    "eplmwriteneplcode",
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


_TDC_DATA_MODEL_COLUMNS = [
    "incident",
    "applicant",
    "superDepartment",
    "department",
    "requestDate",
    "projectModel",
    "partNumber",
    "modelNumber",
]

_TDC_SOR_COLUMNS = [
    "processNo",
    "bizName",
    "carTypeProject",
    "startUser",
    "title",
    "deptName",
    "sectionName",
    "startTime",
    "sorPartNo",
    "sorNo",
    "processInstanceStatus",
]


def _ask_tdc_data_model_filters() -> TDCDataModelFilters:
    return TDCDataModelFilters(
        serial_number=_blank_to_none(Prompt.ask("流水单号", default="")),
        applicant=_blank_to_none(Prompt.ask("申请人", default="")),
        department=_blank_to_none(Prompt.ask("部门", default="")),
        section=_blank_to_none(Prompt.ask("科室", default="")),
        application_start=_blank_to_none(Prompt.ask("申请开始日期 (YYYY-MM-DD)", default="")),
        application_end=_blank_to_none(Prompt.ask("申请结束日期 (YYYY-MM-DD)", default="")),
        project_model=_blank_to_none(Prompt.ask("项目/车型", default="")),
        part_number=_blank_to_none(Prompt.ask("零件号", default="")),
        model_number=_blank_to_none(Prompt.ask("数模号", default="")),
    )


def _ask_tdc_sor_filters() -> TDCSORFilters:
    return TDCSORFilters(
        serial_number=_blank_to_none(Prompt.ask("流水单号", default="")),
        process_type=_blank_to_none(Prompt.ask("流程类型", default="")),
        car_type_project=_blank_to_none(Prompt.ask("车型项目", default="")),
        applicant=_blank_to_none(Prompt.ask("申请人", default="")),
        title=_blank_to_none(Prompt.ask("标题", default="")),
        department=_blank_to_none(Prompt.ask("部门", default="")),
        section=_blank_to_none(Prompt.ask("科室", default="")),
        application_start=_blank_to_none(Prompt.ask("申请开始日期 (YYYY-MM-DD)", default="")),
        application_end=_blank_to_none(Prompt.ask("申请结束日期 (YYYY-MM-DD)", default="")),
        part_number=_blank_to_none(Prompt.ask("零件号", default="")),
        part_name=_blank_to_none(Prompt.ask("零件名称", default="")),
        version=_blank_to_none(Prompt.ask("版本号", default="")),
        sor_number=_blank_to_none(Prompt.ask("SOR 号", default="")),
        latest_completed_node=_blank_to_none(Prompt.ask("最新完成节点", default="")),
        approval_status=_blank_to_none(Prompt.ask("审批状态", default="")),
    )


def _render_tdc_paged_result(result) -> Table:
    if result.report_type == "sor":
        title = "SOR 流程查询（流程粒度）"
        preferred = _TDC_SOR_COLUMNS
    else:
        title = "数模设计审核流程报表（流程粒度）"
        preferred = _TDC_DATA_MODEL_COLUMNS
    table = Table(
        title=(
            f"{title} | page={result.page} rows={len(result.rows)} total={result.total or '-'} "
            f"pages={result.pages or '-'} unique={result.unique_count} duplicates={result.duplicate_count} "
            f"stop={result.stop_reason}"
        ),
        show_lines=True,
        box=box.SIMPLE_HEAVY,
    )
    keys = _select_display_columns(result.rows, preferred)
    for key in keys or ["message"]:
        table.add_column(key, overflow="fold")
    if result.rows:
        for row in result.rows:
            table.add_row(*(Text(safe_display_value(row.get(key))) for key in keys))
    else:
        table.add_row("No results")
    return table


def _render_tdc_export_result(result) -> Table:
    granularity = "零件明细" if result.record_granularity == "part_detail" else "流程"
    title = "SOR 官方导出（零件明细粒度）" if result.report_type == "sor" else "TDC 官方 XLSX 导出"
    table = Table(title=title, show_lines=True, box=box.SIMPLE_HEAVY)
    table.add_column("field", style="#88a6a4", no_wrap=True)
    table.add_column("value", overflow="fold")
    table.add_row("file_name", safe_display_value(result.file_name))
    table.add_row("absolute_path", safe_display_value(result.path))
    table.add_row("bytes", str(result.byte_count))
    table.add_row("validation", "Content-Type + XLSX PK: passed" if result.signature_valid else "failed")
    table.add_row("record_granularity", granularity)
    table.add_row("elapsed_ms", f"{result.elapsed_ms:.3f}")
    return table


_TDC_DEBUG_HEADER_ALLOWLIST = {
    "accept",
    "accept-language",
    "content-type",
    "origin",
    "referer",
    "user-agent",
}


def _format_tdc_debug_mapping(values, *, headers: bool = False) -> str:
    parts: list[str] = []
    for key, value in (values or {}).items():
        lowered = str(key).lower()
        if lowered in {"cookie", "authorization", "set-cookie"}:
            shown = "[redacted]"
        elif headers and lowered not in _TDC_DEBUG_HEADER_ALLOWLIST:
            continue
        else:
            shown = redact_sensitive_text(value, limit=240, collapse_newlines=True)
        parts.append(f"{key}={shown}")
    return ", ".join(parts) or "-"


def _tdc_console_debug_hook(event: TDCHttpDiagnosticEvent) -> None:
    table = Table(box=box.SIMPLE, show_header=False, pad_edge=False)
    table.add_column("field", style="#88a6a4", no_wrap=True)
    table.add_column("value", overflow="fold")

    def add(label: str, value) -> None:
        if value is not None and value != "" and value != ():
            table.add_row(label, Text(safe_display_value(redact_sensitive_text(value, limit=1000))))

    add("timestamp", event.timestamp)
    add("stage", event.stage)
    add("request_id", event.request_id)
    add("page_type", event.page_type)
    add("method", event.method)
    add("origin", event.origin)
    add("path", event.path)
    add("query", _format_tdc_debug_mapping(event.query))
    add("page / page_size", f"{event.page or '-'} / {event.page_size or '-'}")
    add("attempt / timeout", f"{event.attempt} / {event.timeout or '-'}")
    add("status / elapsed_ms", f"{event.status_code or '-'} / {event.elapsed_ms or '-'}")
    add("Content-Type", event.content_type)
    add("Content-Length", event.content_length)
    add("request headers", _format_tdc_debug_mapping(event.request_headers, headers=True))
    add("response headers", _format_tdc_debug_mapping(event.response_headers, headers=True))
    add("JSON fields", ", ".join(event.json_fields))
    add("records / total / pages", f"{event.record_count or 0} / {event.total or '-'} / {event.pages or '-'}")
    add(
        "pagination",
        (
            f"accumulated={event.accumulated_count or 0}, unique={event.unique_count or 0}, "
            f"duplicates={event.duplicate_count or 0}, current={event.current_page or '-'}, "
            f"estimated={event.estimated_pages or '-'}, stop={event.stop_reason or '-'}"
        ),
    )
    if event.file_name or event.saved_path:
        add(
            "export",
            (
                f"file={event.file_name or '-'}, path={event.saved_path or '-'}, bytes={event.bytes_written or 0}, "
                f"validation={event.validation or '-'}"
            ),
        )
    if event.exception_type or event.reason:
        add(
            "failure",
            (
                f"type={event.exception_type or '-'}, reason={event.reason or '-'}, status={event.status_code or '-'}, "
                f"completed_pages={event.completed_pages or 0}"
            ),
        )
    console.print(
        Panel(table, title=Text(f"TDC Debug [{event.request_id}]"), border_style="#c7ad7a", box=box.ROUNDED)
    )


def _tdc_action_menu() -> str:
    table = Table(box=box.SIMPLE_HEAVY, show_header=False)
    table.add_column("Key", style="#88a6a4", no_wrap=True)
    table.add_column("Action")
    table.add_row("1", "单页查询")
    table.add_row("2", "全量分页抓取")
    table.add_row("3", "官方 XLSX 导出")
    table.add_row("0", "返回 TDC 菜单")
    console.print(table)
    return Prompt.ask("选择操作", choices=["0", "1", "2", "3"], default="0")


def _run_tdc_report(report_type: str, debug_enabled: bool) -> None:
    page_path = DATA_MODEL_PAGE_PATH if report_type == "data_model" else SOR_PAGE_PATH
    action = _tdc_action_menu()
    if action == "0":
        return
    filters = _ask_tdc_data_model_filters() if report_type == "data_model" else _ask_tdc_sor_filters()
    login_choice = _ask_tdc_login_mode()
    if login_choice == "0":
        return
    auth_mode = "password" if login_choice == "1" else "headers"
    username = ""
    password = ""
    if auth_mode == "password":
        base_url, username, password = _ask_tdc_password_connection()
        headers: dict[str, str] = {}
    else:
        base_url, headers = _ask_tdc_connection(page_path)
    report = MarkdownDiagnosticReport(
        options=DiagnosticOptions(enabled=debug_enabled, unsafe_raw=False),
        base_url=base_url,
        mode=f"{report_type}:{action}",
        inputs={
            "report_type": report_type,
            "action": action,
            "auth_mode": auth_mode,
            "origin": urlsplit(base_url).netloc,
            "headers": headers,
        },
        report_title="TDC CLI Diagnostic Report",
        file_name_prefix="tdc_cli_debug",
        allow_unsafe_raw=False,
    )
    hook = combine_diagnostic_hooks(
        _tdc_console_debug_hook if debug_enabled else None,
        report.record_http_event if debug_enabled else None,
    )
    label = "数模设计审核流程报表" if report_type == "data_model" else "SOR 流程报表"
    try:
        session = None
        if auth_mode == "password":
            console.print("[vse.muted]正在通过企业账号中心登录 TDC...[/]")
            auth_client = TDCPasswordAuthClient(base_url, timeout=30.0, diagnostic_hook=hook)
            try:
                login_result = auth_client.login(username, password)
            finally:
                password = ""
            session = login_result.session
            console.print("[vse.muted]TDC 账号密码登录成功[/]")
        else:
            console.print("[vse.muted]使用浏览器 Header/Cookie 备用登录方式[/]")
        client = TDCCrawlerClient(
            base_url,
            session=session,
            headers=headers,
            timeout=30.0,
            diagnostic_hook=hook,
        )
        console.print(f"[vse.muted]开始: {label}[/]")
        if action == "1":
            page = _ask_positive_int("Page", 1)
            page_size = _ask_positive_int("Page size", 50)
            result = (
                client.query_data_model_page(filters, page=page, page_size=page_size)
                if report_type == "data_model"
                else client.query_sor_page(filters, page=page, page_size=page_size)
            )
            console.print(_render_tdc_paged_result(result))
        elif action == "2":
            page_size = _ask_positive_int("Page size", 50)
            max_pages = _ask_positive_int("Max pages", 100)
            max_records = _ask_positive_int("Max records", 10000)
            if not Confirm.ask("全量抓取可能耗时，继续？", default=False):
                console.print("[vse.muted]已取消全量抓取[/]")
                return
            result = (
                client.crawl_data_model_all(
                    filters, page_size=page_size, max_pages=max_pages, max_records=max_records
                )
                if report_type == "data_model"
                else client.crawl_sor_all(filters, page_size=page_size, max_pages=max_pages, max_records=max_records)
            )
            console.print(_render_tdc_paged_result(result))
        else:
            file_name = _blank_to_none(Prompt.ask("保存文件名（留空使用官方名称）", default=""))
            result = (
                client.export_data_model(filters, file_name=file_name)
                if report_type == "data_model"
                else client.export_sor(filters, file_name=file_name)
            )
            console.print(_render_tdc_export_result(result))
        if report_path := report.save("success"):
            console.print(f"[vse.muted]诊断报告已保存: {report_path}[/]")
        logger.info("TDC CLI operation finished: report_type=%s action=%s", report_type, action)
    except (TDCAuthError, TDCCrawlerError) as exc:
        console.print(Panel(Text(_safe_error_message(exc)), title=type(exc).__name__, border_style="#c19191"))
        report.record_exception(exc)
        if report_path := report.save("failed"):
            console.print(f"[vse.rose]诊断报告已保存: {report_path}[/]")
        logger.warning("TDC CLI operation failed: report_type=%s action=%s type=%s", report_type, action, type(exc).__name__)
    except Exception as exc:
        console.print(Panel(Text(_safe_error_message(exc)), title=type(exc).__name__, border_style="#c19191"))
        report.record_exception(exc)
        if report_path := report.save("failed"):
            console.print(f"[vse.rose]诊断报告已保存: {report_path}[/]")
        logger.warning("TDC CLI operation failed: report_type=%s action=%s type=%s", report_type, action, type(exc).__name__)


def _run_tdc_contract_probe(debug_enabled: bool) -> int:
    """
    数模同步契约探测（只读）。

    委托给 tdc_probe_cli.run_probe() 共享流程。
    main.py 在此基础上可选叠加 diagnostics（debug 模式）。
    不构造 DatabaseManager，不初始化数据库。
    """
    diagnostic_hook = None
    report: MarkdownDiagnosticReport | None = None

    if debug_enabled:
        report = MarkdownDiagnosticReport(
            options=DiagnosticOptions(enabled=True, unsafe_raw=False),
            base_url="",
            mode="data_model:probe",
            inputs={"report_type": "data_model", "action": "probe"},
            report_title="TDC Contract Probe Diagnostic",
            file_name_prefix="tdc_probe_debug",
            allow_unsafe_raw=False,
        )
        hook = combine_diagnostic_hooks(
            _tdc_console_debug_hook,
            report.record_http_event,
        )
        diagnostic_hook = hook

    try:
        exit_code = _probe_cli.run_probe(
            debug_enabled=debug_enabled,
            report_dir=PROJECT_ROOT / ".runtime" / REPORT_DIR_NAME,
            diagnostic_hook=diagnostic_hook,
        )
        if report is not None:
            report.save("success" if exit_code == 0 else "failed")
        return exit_code
    except Exception as exc:
        if report is not None:
            report.record_exception(exc)
            report.save("failed")
        console.print(Panel(Text(_safe_error_message(exc)), title=type(exc).__name__, border_style="#c19191"))
        return 1


def _profile_rows_for_display(rows):
    """复用 tdc_contract_probe 的 profile_rows 供 CLI 显示。"""
    from services.tdc_contract_probe import FieldProfile, profile_rows
    profiles, _, _ = profile_rows(rows)
    return list(profiles.values()), {}, {}


def handle_tdc_crawler(db: DatabaseManager) -> None:
    """Menu 7: TDC report queries and official exports."""
    del db
    debug_enabled = False
    while True:
        menu = Table(box=box.SIMPLE_HEAVY, show_header=False)
        menu.add_column("Key", style="#88a6a4", no_wrap=True)
        menu.add_column("Mode")
        menu.add_row("1", "数模设计审核流程报表")
        menu.add_row("2", "SOR 流程报表")
        menu.add_row("3", "造型 A 面冻结发布单")
        menu.add_row("4", f"调试与诊断设置（当前：{'开启' if debug_enabled else '关闭'}）")
        menu.add_row("5", "数模同步契约探测（只读）")
        menu.add_row("0", "返回主菜单")
        console.print(Panel(menu, title="TDC 报表爬虫", border_style="#88a6a4", box=box.ROUNDED))
        sub = Prompt.ask("选择 TDC 报表", choices=["0", "1", "2", "3", "4", "5"], default="0")
        if sub == "0":
            return
        if sub == "4":
            debug_enabled = Confirm.ask("开启 TDC 详细 Debug 与安全诊断报告？", default=debug_enabled)
            state = "开启" if debug_enabled else "关闭"
            console.print(f"[vse.muted]TDC Debug 已{state}；TDC 始终禁用 unsafe_raw。[/]")
            continue
        if sub == "3":
            # Keep the third page visible without inventing an HTTP contract from its output workbook.
            _ = TDCAFaceFilters()
            console.print(Panel(AFACE_CONTRACT_BLOCKER, title="造型 A 面冻结发布单", border_style="#c7ad7a"))
            continue
        if sub == "5":
            _run_tdc_contract_probe(debug_enabled)
            continue  # noqa: ignoring exit code in interactive mode
        _run_tdc_report("data_model" if sub == "1" else "sor", debug_enabled)


def handle_intranet_scrape(db: DatabaseManager) -> None:
    """Menu 4: Aras CLI adapter."""
    menu = Table(box=box.SIMPLE_HEAVY, show_header=False)
    menu.add_column("Key", style="#88a6a4", no_wrap=True)
    menu.add_column("Mode")
    menu.add_row("1", "EWO report query / CSV export")
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
        base_url, headers, credentials = _ask_aras_connection()
        if not base_url:
            console.print("[bold #c19191]base_url is required[/]")
            return
        if credentials is None:
            console.print("[bold #c19191]ECM 用户名和密码为必填，拒绝无凭据访问[/]")
            return
        _reject_aras_secret_headers(headers)
        parsed = urlsplit(base_url.rstrip("/") + "/")
        origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else base_url
        auth_mode = "password"
        report = MarkdownDiagnosticReport(
            options=diagnostic_options,
            base_url=base_url,
            mode=sub,
            inputs={
                "sub_menu": sub,
                "origin": origin,
                "headers": headers,
                "auth_mode": auth_mode,
                "timeout": 30.0,
            },
        )
        diagnostic_hook = report.record_http_event if diagnostic_options.enabled else None
        console.print("[vse.muted]正在通过企业账号中心登录 ECM...[/]")
        auth_client = ArasECMAuthClient(base_url, timeout=30.0, diagnostic_hook=diagnostic_hook)
        username, password = credentials
        try:
            login_result = auth_client.login(username, password)
        finally:
            password = ""
            credentials = None
        session = login_result.session
        console.print("[vse.muted]ECM 账号密码登录成功[/]")
        client = ArasCrawlerClient(
            base_url,
            session=session,
            headers=headers,
            timeout=30.0,
            diagnostic_hook=diagnostic_hook,
        )

        if sub == "1":
            filters, page, page_size, max_records = _ask_ewo_filters()
            console.print(
                f"[#747a83]mode=EWO origin={origin} page={page} page_size={page_size} max_records={max_records}[/]"
            )
            with console.status("Querying Aras", spinner="dots"):
                result = client.query_ewo_report(filters, page=page, page_size=page_size, max_records=max_records)
            console.print(_render_ewo_result(result))
            if result.rows and Confirm.ask(
                f"导出全部匹配 EWO（最多 {max_records} 条）为 Excel 兼容 CSV？",
                default=False,
            ):
                file_name = Prompt.ask("CSV file name", default="").strip() or None
                max_pages = max(1, (max_records + _FULL_EXPORT_PAGE_SIZE - 1) // _FULL_EXPORT_PAGE_SIZE)
                with console.status("Exporting EWO", spinner="dots"):
                    export_page = client.crawl_ewo_report_all(
                        filters,
                        page_size=_FULL_EXPORT_PAGE_SIZE,
                        max_pages=max_pages,
                        max_records=max_records,
                    )
                    export_result = export_ewo_report_csv(export_page, file_name=file_name)
                console.print(
                    f"[vse.sage]EWO CSV 已保存: {export_result.path} "
                    f"({export_result.row_count} rows)[/]"
                )
                if len(export_page.rows) >= max_records or (
                    export_page.page is not None and export_page.page >= max_pages
                ):
                    console.print("[vse.amber]提示：已达到最大页数/记录数上限，导出结果可能截断。[/]")
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
            file_name = getattr(result, "file_name", None)
            if file_name:
                destination = Prompt.ask("保存目录或完整路径", default="").strip() or str(Path.cwd())
                with console.status("Downloading NCR detail", spinner="dots"):
                    saved_path = client.download_ncr_detail_file(file_name, destination)
                console.print(f"[vse.sage]NCR 明细文件已保存: {saved_path}[/]")
            else:
                console.print("[#747a83]未生成可下载的明细文件（file_name 为空）。[/]")
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
            filters, _page, _page_size, max_records, max_pages = _ask_paa_filters()
            if not Confirm.ask("PAA full crawl may be slow. Continue?", default=False):
                console.print("[#747a83]PAA full crawl cancelled[/]")
                return
            console.print(
                f"[#747a83]mode=PAA all origin={origin} page_size={_FULL_EXPORT_PAGE_SIZE} "
                f"max_pages={max_pages} max_records={max_records}[/]"
            )
            with console.status("Querying Aras", spinner="dots"):
                result = client.crawl_paa_report_all(
                    filters,
                    page_size=_FULL_EXPORT_PAGE_SIZE,
                    max_pages=max_pages,
                    max_records=max_records,
                )
            console.print(_render_paa_result(result))
            if len(result.rows) >= max_records or (result.page is not None and result.page >= max_pages):
                console.print("[vse.amber]提示：已达到最大页数/记录数上限，结果可能截断。[/]")
            if result.rows and Confirm.ask("导出全部 PAA 结果为 Excel 兼容 CSV？", default=False):
                with console.status("Exporting PAA", spinner="dots"):
                    export_result = export_report_csv(
                        result.rows,
                        report_name="paa",
                        preferred_fields=DEFAULT_PAA_SELECT_FIELDS,
                    )
                console.print(
                    f"[vse.sage]PAA CSV 已保存: {export_result.path} "
                    f"({export_result.row_count} rows)[/]"
                )
            if report_path := report.save("success"):
                console.print(f"[#747a83]诊断报告已保存: {report_path}[/]")
        logger.info("Aras CLI query finished: type=%s", sub)
    except (ArasAuthError, ArasCrawlerError) as e:
        console.print(Panel(Text(_safe_error_message(e)), title=type(e).__name__, border_style="#c19191"))
        if report:
            report.record_exception(e)
            if report_path := report.save("failed"):
                console.print(f"[#c19191]诊断报告已保存: {report_path}[/]")
        logger.warning("Aras CLI query failed with %s", type(e).__name__)
    except Exception as e:
        console.print(Panel(Text(_safe_error_message(e)), title=type(e).__name__, border_style="#c19191"))
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
    "7": ("TDC 报表爬虫", handle_tdc_crawler),
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
        "7": ("TDC Reports", "CLI", "三个 TDC 报表的查询与导出"),
        "0": ("Exit", "Ready", "Close VSE Toolbox"),
    }
    table = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="#747a83")
    table.add_column("#", style="#88a6a4", no_wrap=True)
    table.add_column("Module")
    table.add_column("Status", no_wrap=True)
    table.add_column("Description", style="#a7a49a")
    for key, (label, _) in MENU_OPTIONS.items():
        module, status, description = rows.get(key, (label, "Ready", label))
        status_style = {
            "Ready": "#9caf88",
            "CLI": "#c7ad7a",
            "Web": "#a899b8",
            "Paused": "#747a83",
        }.get(status, "#a7a49a")
        table.add_row(key, module, f"[{status_style}]{status}[/]", description)
    console.print()
    console.print(table)
    console.print()


def _run_sync_once(
    db: DatabaseManager,
    deliverable_id: str | None,
    dry_run: bool,
) -> int:
    """非交互式 project-status-sync --once 执行路径。不显示 banner/菜单。"""
    service = ProjectStatusUpdateService(db)
    registry = create_production_registry()
    runner = ProjectStatusSyncRunner(db, service, registry)

    try:
        result = runner.run_once(
            deliverable_id=deliverable_id,
            dry_run=dry_run,
        )
    except KeyboardInterrupt:
        return EXIT_INTERRUPTED

    _print_sync_summary(result)
    return result.exit_code


def _print_sync_summary(result: RunOnceResult) -> None:
    """打印适合 Task Scheduler 日志的脱敏摘要。不输出敏感字段或 traceback。"""
    if result.dry_run:
        if not result.readiness:
            console.print("[dim]dry-run: 无符合条件的 enabled binding。[/]")
            return
        for item in result.readiness:
            if not item.binding_ready:
                status = "binding not ready"
            elif item.connector_available:
                status = "ready"
            else:
                status = "no connector"
            console.print(
                f"[dim]dry-run[/] binding {item.binding_id} "
                f"({item.deliverable_id}, {item.source_type}): {status}"
            )
        return

    if not result.results:
        console.print("[dim]无符合条件的 enabled binding，未执行同步。[/]")
        return

    for r in result.results:
        _print_binding_result(r)


def _print_binding_result(r: BindingRunResult) -> None:
    """打印单个 binding 的脱敏结果。"""
    parts = [
        f"binding {r.binding_id} ({r.deliverable_id}, {r.source_type})",
        f"outcome={r.outcome}",
    ]
    if r.final_state:
        parts.append(f"state={r.final_state}")
    if r.applied_fields:
        parts.append(f"applied={','.join(r.applied_fields)}")
    if r.error_type:
        parts.append(f"error_type={r.error_type}")
    if r.error_message:
        parts.append(f"message={r.error_message}")
    console.print("[dim]sync[/] " + " | ".join(parts))


def _parse_sync_args(argv: Sequence[str]) -> argparse.Namespace:
    """解析 project-status-sync 子命令参数。"""
    parser = argparse.ArgumentParser(
        prog="main.py project-status-sync",
        description="执行一次项目状态同步（适合 Windows Task Scheduler）。",
        add_help=True,
    )
    parser.add_argument(
        "--once",
        action="store_true",
        required=True,
        help="执行一次同步后退出（必选）。",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="只读就绪检查，不获取租约、不创建 run、不调用 connector。",
    )
    parser.add_argument(
        "--deliverable-id",
        type=str,
        default=None,
        help="只同步指定交付物的绑定。",
    )
    return parser.parse_args(argv)


_SYNC_SUBCOMMAND = "project-status-sync"
_ARCHIVE_CLEANUP_SUBCOMMAND = "project-status-archive-cleanup"
_PROBE_SUBCOMMAND = "tdc-contract-probe"


def _parse_archive_cleanup_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="main.py project-status-archive-cleanup",
        description="计划或显式执行受控交付物归档保留清理。",
    )
    parser.add_argument("--retention-days", type=int, default=90)
    parser.add_argument("--execute", action="store_true", default=False)
    return parser.parse_args(argv)


def _parse_probe_args(argv: Sequence[str]) -> argparse.Namespace:
    """解析 tdc-contract-probe 子命令参数。"""
    parser = argparse.ArgumentParser(
        prog="main.py tdc-contract-probe",
        description="TDC 数模同步契约只读探测（不接触数据库，不启用自动同步）。",
        add_help=True,
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="开启 TDC 诊断调试报告（仍禁用 unsafe_raw）。",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """
    CLI 主入口。

    - 无参数或非已知子命令前缀时进入现有交互式菜单。
    - project-status-sync --once 时进入非交互式单次同步。
    - tdc-contract-probe 时进入只读探测，不构造 DatabaseManager。
    """
    raw_argv = list(sys.argv[1:] if argv is None else argv)

    if raw_argv and raw_argv[0] == _ARCHIVE_CLEANUP_SUBCOMMAND:
        args = _parse_archive_cleanup_args(raw_argv[1:])
        try:
            archive = ArchiveStore()
            plan = archive.plan_retention(retention_days=args.retention_days)
            if not args.execute:
                console.print(
                    f"[dim]dry-run: {len(plan)} 个归档文件符合 {args.retention_days} 天保留清理条件；未删除。[/]"
                )
                return EXIT_OK
            removed = archive.execute_retention(plan)
            console.print(f"[dim]已删除 {len(removed)} 个受控归档文件。[/]")
            return EXIT_OK
        except (OSError, ValueError) as exc:
            console.print(
                f"[red]归档清理失败: {redact_sensitive_text(str(exc), limit=500)}[/]"
            )
            return EXIT_FAILED

    # tdc-contract-probe：在任何 DatabaseManager 构造之前拦截。
    # 该命令不接触数据库，不初始化 SQLite，不进入菜单。
    if raw_argv and raw_argv[0] == _PROBE_SUBCOMMAND:
        args = _parse_probe_args(raw_argv[1:])
        try:
            return _run_tdc_contract_probe(args.debug)
        except KeyboardInterrupt:
            return EXIT_INTERRUPTED
        except Exception as exc:
            console.print(
                f"[red]探测运行失败: {redact_sensitive_text(str(exc), limit=500)}[/]"
            )
            return EXIT_FAILED

    # 非交互式子命令检测。
    if raw_argv and raw_argv[0] == _SYNC_SUBCOMMAND:
        args = _parse_sync_args(raw_argv[1:])
        try:
            db = DatabaseManager()
            db.init_database()
            return _run_sync_once(
                db,
                deliverable_id=args.deliverable_id,
                dry_run=args.dry_run,
            )
        except KeyboardInterrupt:
            return EXIT_INTERRUPTED
        except Exception as exc:
            console.print(
                f"[red]同步运行失败: {redact_sensitive_text(str(exc), limit=500)}[/]"
            )
            return EXIT_FAILED

    # 交互式模式：保持现有行为不变。
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

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

