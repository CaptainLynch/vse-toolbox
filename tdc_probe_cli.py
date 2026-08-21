# -*- coding: utf-8 -*-
"""
tdc_probe_cli.py — TDC 数模同步契约探测共享交互流程。

被 main.py（菜单 7 > 5 和 tdc-contract-probe 子命令）和
tdc_probe_main.py（专用 EXE 入口）共同复用。

依赖边界：
- 不 import main、core.db_manager、core.config、core.diagnostics、core.runtime_paths
- 不 import services.project_status_*、web.app、xlwings、selenium、flask
- 只依赖：services.tdc_contract_probe、services.tdc_auth、services.tdc_crawler、
  core.redaction、Rich 必要组件、Python 标准库
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.prompt import Prompt, Confirm
from rich import box

from core.redaction import redact_sensitive_text
from services.tdc_auth import TDCAuthError, TDCPasswordAuthClient
from services.tdc_crawler import (
    DEFAULT_TDC_BASE_URL,
    TDCCrawlerClient,
    TDCCrawlerError,
    TDCDataModelFilters,
    TDCPagedResult,
)
from services.tdc_contract_probe import (
    REPORT_DIR_NAME,
    TDCContractProbeOptions,
    build_report,
    get_filter_field_labels,
    profile_rows,
    save_report,
    validate_categorical_fields,
    validate_filters_non_empty,
    validate_options,
)

console = Console()

#: 禁止模块列表 — self-test 检查这些模块未被导入。
_FORBIDDEN_MODULES: tuple[str, ...] = (
    "main",
    "core.db_manager",
    "core.config",
    "core.diagnostics",
    "flask",
    "xlwings",
    "selenium",
    "services.project_status_updates",
    "services.project_status_sync_runner",
)

_IDENTIFIER_FIELDS: tuple[str, ...] = ("incident", "documentNo", "formId")
_IDENTIFIER_DISPLAY_LIMIT = 256


def _blank_to_none(value: str) -> str | None:
    value = value.strip()
    return value or None


def _ask_positive_int(label: str, default: int) -> int:
    raw = Prompt.ask(label, default=str(default))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        console.print(f"[yellow]{label} invalid, using {default}[/]")
        return default
    if value <= 0:
        console.print(f"[yellow]{label} must be positive, using {default}[/]")
        return default
    return value


def _safe_error_message(exc: Exception) -> str:
    return redact_sensitive_text(exc)


def _identifier_display_value(value: object) -> str:
    """Prepare an identifier for the local terminal without Rich markup."""
    if value is None:
        return "-"
    normalized = " ".join(str(value).split())
    if not normalized:
        return "-"
    return normalized[:_IDENTIFIER_DISPLAY_LIMIT]


def _render_candidate_identifiers(rows: Sequence[Mapping[str, Any]]) -> Table:
    """Render local-only workflow identifiers; they are never written to reports."""
    table = Table(
        title="候选流程编号（仅本地终端显示，不写入探测报告）",
        box=box.SIMPLE_HEAVY,
    )
    table.add_column("#", justify="right", style="#88a6a4")
    table.add_column("incident")
    table.add_column("documentNo")
    table.add_column("formId")
    for index, row in enumerate(rows, start=1):
        table.add_row(
            str(index),
            *(Text(_identifier_display_value(row.get(field))) for field in _IDENTIFIER_FIELDS),
        )
    return table


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


def _ask_tdc_password_connection() -> tuple[str, str, str]:
    base_url = Prompt.ask("TDC base_url", default=DEFAULT_TDC_BASE_URL).strip()
    username = Prompt.ask("TDC 用户名", default="").strip()
    password = Prompt.ask("TDC 密码", password=True)
    return base_url, username, password


def _resolve_executable_root() -> Path:
    """
    计算可执行文件根目录。

    PyInstaller frozen：sys.executable 所在目录。
    源码运行：__file__ 所在目录。
    不调用 app_root()。
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _resolve_report_dir(root: Path | None = None) -> Path:
    """报告目录固定为 <root>/.runtime/tdc_contract_probe/。"""
    base = root or _resolve_executable_root()
    return base / ".runtime" / REPORT_DIR_NAME


def run_probe(
    debug_enabled: bool = False,
    report_dir: Path | None = None,
    auth_factory: Callable[..., TDCPasswordAuthClient] | None = None,
    crawler_factory: Callable[..., TDCCrawlerClient] | None = None,
    diagnostic_hook: Callable[[Any], None] | None = None,
) -> int:
    """
    执行 TDC 数模同步契约探测（只读）。

    不构造 DatabaseManager，不初始化数据库，不写 project-status 表。
    报告只写 report_dir（默认 <exe_root>/.runtime/tdc_contract_probe/）。

    Args:
        debug_enabled: 是否开启调试（专用 EXE 不支持，main.py 可传入）。
        report_dir: 报告保存目录。None 时使用 _resolve_report_dir()。
        auth_factory: 可选的 TDCPasswordAuthClient 工厂（测试注入）。
        crawler_factory: 可选的 TDCCrawlerClient 工厂（测试注入）。
        diagnostic_hook: 可选的诊断回调（main.py 的 debug 模式传入）。

    Returns:
        0=成功/取消，1=失败，KeyboardInterrupt 上抛由调用方处理。
    """
    probe_dir = report_dir or _resolve_report_dir()

    console.print(
        Panel(
            "[yellow]数模同步契约探测（只读）\n\n"
            "本操作只读取 TDC 数模报表样本，用于收集字段统计、candidate key 证据和稳定性验证。\n"
            "不会更新项目状态、不会启用自动同步、不会获取租约或创建同步运行。\n"
            "只允许账号密码登录，不支持 Header/Cookie 备用认证。\n"
            "探测结果经脱敏后保存到报告目录。[/]",
            border_style="#88a6a4",
            box=box.ROUNDED,
        )
    )

    if not Confirm.ask("继续探测？", default=False):
        console.print("[dim]已取消探测，未登录、未查询、未写报告。[/]")
        return 0

    # 1. 收集过滤条件。
    filters = _ask_tdc_data_model_filters()
    try:
        validate_filters_non_empty(filters)
    except ValueError as exc:
        console.print(f"[red]{_safe_error_message(exc)}[/]")
        return 0

    filter_labels = get_filter_field_labels(filters)

    # 2. 收集 page/record 上限。
    page_size = _ask_positive_int("Page size (max 100)", 50)
    max_pages = _ask_positive_int("Max pages (max 5)", 2)
    max_records = _ask_positive_int("Max records (max 500)", 200)

    # 3. 询问是否执行第二次稳定性读取。
    stability_check = Confirm.ask(
        "执行第二次相同查询以验证稳定性？（会增加一次查询）", default=False
    )

    # 4. 构建选项并校验。
    try:
        options = TDCContractProbeOptions(
            page_size=page_size,
            max_pages=max_pages,
            max_records=max_records,
            stability_check=stability_check,
        )
        validate_options(options)
    except ValueError as exc:
        console.print(f"[red]{_safe_error_message(exc)}[/]")
        return 0

    # 5. 隐藏密码登录。
    base_url, username, password = _ask_tdc_password_connection()

    # 安全 output_dir：避免 TDCCrawlerClient 默认调用 app_root()/data/tdc。
    # The probe never exports files, so this directory is only supplied to
    # prevent TDCCrawlerClient from falling back to app_root()/data/tdc.
    # Do not create it: a successful probe should leave only its reports.
    safe_output_dir = probe_dir / "_crawler_output"

    try:
        console.print("[dim]正在通过企业账号中心登录 TDC...[/]")
        auth_factory_fn = auth_factory or TDCPasswordAuthClient
        auth_client = auth_factory_fn(base_url, timeout=30.0, diagnostic_hook=diagnostic_hook)
        try:
            login_result = auth_client.login(username, password)
        finally:
            password = ""
            username = ""
        session = login_result.session
        console.print("[dim]TDC 登录成功，开始只读探测...[/]")

        crawler_factory_fn = crawler_factory or TDCCrawlerClient
        client = crawler_factory_fn(
            base_url,
            session=session,
            timeout=30.0,
            diagnostic_hook=diagnostic_hook,
            output_dir=safe_output_dir,
        )

        # 6. 获取有限样本。
        result = client.crawl_data_model_all(
            filters,
            page_size=options.page_size,
            max_pages=options.max_pages,
            max_records=options.max_records,
        )
        rows = list(result.rows)
        paged_meta = {
            "fetched_pages": result.fetched_pages,
            "truncated": result.stop_reason not in ("empty_page", "reported_pages", "short_page"),
            "stop_reason": result.stop_reason,
        }

        # 7. Display workflow identifiers locally so the operator can find the
        # intended process.  They deliberately do not enter the saved report.
        console.print(_render_candidate_identifiers(rows))

        # 8. Display field statistics without raw values.
        profiles, _, _ = profile_rows(rows)
        table = Table(title="字段统计（只读，不含原始值）", box=box.SIMPLE_HEAVY)
        table.add_column("Field", style="#88a6a4")
        table.add_column("Present", justify="right")
        table.add_column("NonEmpty", justify="right")
        table.add_column("Distinct", justify="right")
        table.add_column("Duplicate", justify="right")
        table.add_column("Types")
        for fp in sorted(profiles.values(), key=lambda p: p.field_name):
            table.add_row(
                fp.field_name,
                str(fp.present_count),
                str(fp.non_empty_count),
                str(fp.distinct_count),
                str(fp.duplicate_count),
                ", ".join(fp.observed_types),
            )
        console.print(table)

        if not rows:
            console.print("[yellow]查询返回零条记录，无法生成有效证据。[/]")
            session = None
            return 0

        # 9. Let the user select a small set of categorical field values.
        available_fields = sorted(profiles.keys())
        categorical_fields: tuple[str, ...] = ()
        if Confirm.ask("是否查看少量分类字段的 distinct 值？（需从实际存在字段中选择）", default=False):
            console.print(f"[dim]可选择的字段: {', '.join(available_fields)}[/]")
            raw_selection = Prompt.ask(
                "输入字段名（逗号分隔，最多 5 个，留空跳过）",
                default="",
            )
            requested = [s.strip() for s in raw_selection.split(",") if s.strip()]
            if requested:
                try:
                    categorical_fields = validate_categorical_fields(
                        requested, available_fields
                    )
                except ValueError as exc:
                    console.print(f"[red]{_safe_error_message(exc)}[/]")
                    categorical_fields = ()

        options = TDCContractProbeOptions(
            page_size=options.page_size,
            max_pages=options.max_pages,
            max_records=options.max_records,
            stability_check=stability_check,
            categorical_fields=categorical_fields,
        )

        # 10. Stability second read.
        stability_rows = None
        stability_truncated = False
        if stability_check:
            console.print("[dim]执行第二次读取以验证稳定性...[/]")
            result2 = client.crawl_data_model_all(
                filters,
                page_size=options.page_size,
                max_pages=options.max_pages,
                max_records=options.max_records,
            )
            stability_rows = list(result2.rows)
            stability_truncated = result2.stop_reason not in ("empty_page", "reported_pages", "short_page")

        # 11. Generate the final redacted report.
        probe_result = build_report(
            rows,
            options,
            filter_fields_used=filter_labels,
            paged_result_meta=paged_meta,
            stability_rows=stability_rows,
            stability_truncated=stability_truncated,
        )

        # 12. Save the report.
        saved = save_report(probe_result, probe_dir)
        probe_save_failed = False
        if saved is None:
            probe_save_failed = True
            reason = getattr(save_report, "safety_reason", None)
            console.print(
                f"[red]报告安全检查失败，已拒绝保存。原因: {reason or '未知敏感内容'}[/]"
            )
        else:
            json_path, md_path = saved
            console.print(f"[dim]探测报告已保存:[/]")
            console.print(f"  JSON: {json_path}")
            console.print(f"  MD:   {md_path}")

        # 13. Clear references.
        rows = []
        stability_rows = []
        session = None
        client = None

        return 1 if probe_save_failed else 0

    except (TDCAuthError, TDCCrawlerError) as exc:
        console.print(Panel(Text(_safe_error_message(exc)), title=type(exc).__name__, border_style="#c19191"))
        return 1
    except Exception as exc:
        console.print(Panel(Text(_safe_error_message(exc)), title=type(exc).__name__, border_style="#c19191"))
        return 1
    finally:
        password = ""
        username = ""
        session = None


def run_self_test(test_dir: Path | None = None) -> int:
    """
    离线 self-test：不访问 TDC、DNS 或其他网络。

    Returns:
        0=全部通过，1=至少一项失败。
    """
    checks: list[tuple[str, bool, str]] = []

    # 1. 核心模块可导入。
    try:
        import services.tdc_contract_probe  # noqa: F401
        checks.append(("core module import", True, ""))
    except Exception as exc:
        checks.append(("core module import", False, _safe_error_message(exc)))

    # 2. Rich 控制台可用。
    try:
        from rich.console import Console as _C
        _C()
        checks.append(("rich console", True, ""))
    except Exception as exc:
        checks.append(("rich console", False, _safe_error_message(exc)))

    # 3. pythoncom / pywintypes / win32com.client 可导入。
    try:
        import pythoncom  # noqa: F401
        import pywintypes  # noqa: F401
        import win32com.client  # noqa: F401
        checks.append(("win32com imports", True, ""))
    except Exception as exc:
        checks.append(("win32com imports", False, _safe_error_message(exc)))

    # 4. 创建 WinHttp COM 对象。
    com_initialized = False
    try:
        import pythoncom
        pythoncom.CoInitialize()
        com_initialized = True
        obj = win32com.client.Dispatch("WinHttp.WinHttpRequest.5.1")
        del obj
        checks.append(("WinHttp COM object", True, ""))
    except Exception as exc:
        checks.append(("WinHttp COM object", False, _safe_error_message(exc)))
    finally:
        if com_initialized:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass

    # 5. profiler 能用虚构记录在内存生成报告。
    try:
        from services.tdc_contract_probe import (
            TDCContractProbeOptions,
            build_report,
            serialize_report_json,
            serialize_report_markdown,
            check_report_safety,
        )
        fake_rows = [
            {"formId": "TEST-001", "incident": "TEST-WF-001", "approvalStatus": "测试状态A"},
            {"formId": "TEST-002", "incident": "TEST-WF-002", "approvalStatus": "测试状态B"},
        ]
        opts = TDCContractProbeOptions(
            categorical_fields=("approvalStatus",),
        )
        result = build_report(fake_rows, opts, filter_fields_used=("incident",))
        json_text = serialize_report_json(result)
        md_text = serialize_report_markdown(result)
        safe_j, _ = check_report_safety(json_text)
        safe_m, _ = check_report_safety(md_text)
        if safe_j and safe_m:
            checks.append(("profiler report generation", True, ""))
        else:
            checks.append(("profiler report generation", False, "safety check failed"))
    except Exception as exc:
        checks.append(("profiler report generation", False, _safe_error_message(exc)))

    # 6. executable root 可解析。
    try:
        root = _resolve_executable_root()
        if root.exists() and root.is_dir():
            checks.append(("executable root resolution", True, ""))
        else:
            checks.append(("executable root resolution", False, "path not accessible"))
    except Exception as exc:
        checks.append(("executable root resolution", False, _safe_error_message(exc)))

    # 7. Check that the executable directory is writable without leaving a
    # report directory or other persistent files behind.
    write_parent = test_dir or _resolve_executable_root()
    try:
        with tempfile.TemporaryDirectory(prefix=".tdc_probe_selftest_", dir=write_parent) as temp_dir:
            probe_file = Path(temp_dir) / ".selftest_write_probe"
            probe_file.write_text("ok", encoding="utf-8")
            probe_file.unlink(missing_ok=True)
        checks.append(("write permission", True, ""))
    except Exception as exc:
        checks.append(("write permission", False, _safe_error_message(exc)))

    # 8. 禁止模块未被导入。
    forbidden_found: list[str] = []
    for mod_name in _FORBIDDEN_MODULES:
        if mod_name in sys.modules:
            forbidden_found.append(mod_name)
    if forbidden_found:
        checks.append((
            "forbidden modules not loaded",
            False,
            f"unexpected modules loaded: {', '.join(forbidden_found)}",
        ))
    else:
        checks.append(("forbidden modules not loaded", True, ""))

    # 输出结果。
    all_pass = True
    for name, ok, detail in checks:
        status = "[green]PASS[/]" if ok else "[red]FAIL[/]"
        console.print(f"  {status} {name}")
        if not ok:
            all_pass = False

    if all_pass:
        console.print("[green]self-test: all checks passed[/]")
        return 0
    else:
        console.print("[red]self-test: one or more checks failed[/]")
        return 1


def parse_probe_args(argv: Sequence[str]) -> argparse.Namespace:
    """解析 tdc-contract-probe 子命令参数。"""
    parser = argparse.ArgumentParser(
        prog="VSE-TDC-Contract-Probe",
        description="TDC 数模同步契约只读探测（不接触数据库，不启用自动同步）。",
        add_help=True,
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        default=False,
        help="离线自检：检查模块导入、COM、profiler 和写权限，不访问网络。",
    )
    return parser.parse_args(argv)
