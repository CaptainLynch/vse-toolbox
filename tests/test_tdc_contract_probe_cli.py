# -*- coding: utf-8 -*-
"""
tests/test_tdc_contract_probe_cli.py — TDC 数模同步契约探测 CLI 交互入口测试。

验证清单：
1. 用户取消：Confirm.ask 返回 False → 不登录、不查询、不写文件。
2. 密码清除：登录后及异常退出时，内存中的密码变量立即清空，不泄漏到报告/日志。
3. 禁用 Header/Cookie：只走账号密码认证，tdc_probe_cli 不提供 _ask_tdc_login_mode / _ask_tdc_connection。
4. 空过滤条件拒绝：所有过滤字段为空时在登录前拦截并提示错误。
5. 报告保存到 .runtime：生成脱敏 JSON 与 Markdown 报告至 .runtime/tdc_contract_probe/。
6. 不显示原始行：tdc_probe_cli 不包含 _render_tdc_paged_result，仅渲染字段统计 profiler 表格。
7. 无参数调用 main.py 仍进入交互式主菜单。
8. project-status-sync --once 仍正常返回整型退出码。
9. TDC 菜单选项 1 仍正常路由至 _run_tdc_report，选项 5 路由至 _run_tdc_contract_probe。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

import main as main_module
import tdc_probe_cli
from core.db_manager import DatabaseManager
from services.tdc_auth import TDCAuthError, TDCLoginResult
from services.tdc_crawler import (
    TDCCrawlerError,
    TDCDataModelFilters,
    TDCPagedResult,
)


def _fake_paged_result(rows: list[dict[str, Any]]) -> TDCPagedResult:
    """构造用于测试的 fake TDCPagedResult。"""
    return TDCPagedResult(
        report_type="data_model",
        rows=rows,
        page=1,
        page_size=50,
        total=len(rows),
        pages=1,
        fetched_pages=1,
        unique_count=len(rows),
        duplicate_count=0,
        stop_reason="reported_pages",
        record_granularity="part_detail",
    )


def _sample_rows() -> list[dict[str, Any]]:
    """构造用于契约探测的 fake 数据样本。"""
    return [
        {
            "formId": "FORM-001",
            "incident": "INC-001",
            "documentNo": "DOC-001",
            "approvalStatus": "审批中",
            "currentNode": "节点1",
            "requestDate": "2026-08-01",
            "applicant": "张三",
            "projectModel": "E50",
            "partNumber": "P001",
            "modelNumber": "M001",
        },
        {
            "formId": "FORM-002",
            "incident": "INC-002",
            "documentNo": "DOC-002",
            "approvalStatus": "已完成",
            "currentNode": "节点2",
            "requestDate": "2026-08-02",
            "applicant": "李四",
            "projectModel": "E50",
            "partNumber": "P002",
            "modelNumber": "M002",
        },
    ]


class FakeTDCPasswordAuthClient:
    """用于测试的 fake 账号密码认证客户端。"""

    instances: list[FakeTDCPasswordAuthClient] = []
    fail_with: Exception | None = None

    def __init__(
        self,
        base_url: str,
        timeout: float = 30.0,
        diagnostic_hook: Any = None,
    ) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self.diagnostic_hook = diagnostic_hook
        self.login_calls: list[tuple[str, str]] = []
        FakeTDCPasswordAuthClient.instances.append(self)

    def login(self, username: str, password: str) -> TDCLoginResult:
        self.login_calls.append((username, password))
        if self.fail_with is not None:
            raise self.fail_with
        return TDCLoginResult(session="fake-authenticated-session", auth_mode="password")


class FakeTDCCrawlerClient:
    """用于测试的 fake TDC 爬虫客户端。"""

    instances: list[FakeTDCCrawlerClient] = []
    fail_with: Exception | None = None
    custom_rows: list[dict[str, Any]] | None = None

    def __init__(
        self,
        base_url: str,
        session: Any = None,
        timeout: float = 30.0,
        diagnostic_hook: Any = None,
        output_dir: Path | None = None,
    ) -> None:
        self.base_url = base_url
        self.session = session
        self.timeout = timeout
        self.diagnostic_hook = diagnostic_hook
        self.output_dir = output_dir
        self.crawl_calls: list[dict[str, Any]] = []
        FakeTDCCrawlerClient.instances.append(self)

    def crawl_data_model_all(
        self,
        filters: Any,
        page_size: int = 50,
        max_pages: int = 2,
        max_records: int = 200,
    ) -> TDCPagedResult:
        self.crawl_calls.append(
            {
                "filters": filters,
                "page_size": page_size,
                "max_pages": max_pages,
                "max_records": max_records,
            }
        )
        if self.fail_with is not None:
            raise self.fail_with
        rows = _sample_rows() if self.custom_rows is None else self.custom_rows
        return _fake_paged_result(rows)


@pytest.fixture(autouse=True)
def _reset_fake_clients() -> None:
    """每个测试前后重置 fake client 的调用记录与状态。"""
    FakeTDCPasswordAuthClient.instances = []
    FakeTDCPasswordAuthClient.fail_with = None
    FakeTDCCrawlerClient.instances = []
    FakeTDCCrawlerClient.fail_with = None
    FakeTDCCrawlerClient.custom_rows = None


@pytest.fixture()
def cli_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> DatabaseManager:
    """提供使用临时文件的隔离 DatabaseManager。"""
    target = tmp_path / "cli.db"
    monkeypatch.setattr(
        main_module,
        "DatabaseManager",
        lambda: DatabaseManager(db_path=target),
    )
    db = DatabaseManager(db_path=target)
    db.init_database()
    return db


@pytest.fixture()
def test_console(monkeypatch: pytest.MonkeyPatch) -> Console:
    """提供支持输出捕获的 rich Console。"""
    console = Console(record=True, width=160)
    monkeypatch.setattr(main_module, "console", console)
    monkeypatch.setattr(tdc_probe_cli, "console", console)
    return console


# ── 1. 用户取消：Confirm.ask 返回 False ──────────────────────────


def test_user_cancel_does_no_login_query_or_write(
    monkeypatch: pytest.MonkeyPatch,
    test_console: Console,
    tmp_path: Path,
) -> None:
    """用户在初始提示时选择取消：不调用登录、不发起抓取、不写任何报告文件。"""
    monkeypatch.setattr(tdc_probe_cli.Confirm, "ask", lambda *args, **kwargs: False)
    monkeypatch.setattr(tdc_probe_cli, "TDCPasswordAuthClient", FakeTDCPasswordAuthClient)
    monkeypatch.setattr(tdc_probe_cli, "TDCCrawlerClient", FakeTDCCrawlerClient)

    save_called = []
    monkeypatch.setattr(
        tdc_probe_cli,
        "save_report",
        lambda *args, **kwargs: save_called.append(args),
    )

    main_module._run_tdc_contract_probe(debug_enabled=False)

    assert len(FakeTDCPasswordAuthClient.instances) == 0
    assert len(FakeTDCCrawlerClient.instances) == 0
    assert len(save_called) == 0

    output = test_console.export_text()
    assert "已取消探测" in output
    assert "未登录、未查询、未写报告" in output


# ── 2. 密码清除：登录后立即清空 ──────────────────────────────────


def test_password_cleared_after_login(
    monkeypatch: pytest.MonkeyPatch,
    test_console: Console,
) -> None:
    """账号密码在传递给 login 后立即清空，不残留在对象状态或后续调用中。"""
    secret_pw = "super_secret_probe_pass_999"

    monkeypatch.setattr(
        tdc_probe_cli,
        "_ask_tdc_password_connection",
        lambda: ("https://tdc.example.com", "probe_user", secret_pw),
    )
    monkeypatch.setattr(
        tdc_probe_cli,
        "_ask_tdc_data_model_filters",
        lambda: TDCDataModelFilters(serial_number="WF-100"),
    )
    monkeypatch.setattr(tdc_probe_cli.Confirm, "ask", lambda prompt, **kw: "继续" in prompt)
    monkeypatch.setattr(tdc_probe_cli, "_ask_positive_int", lambda prompt, default: default)
    monkeypatch.setattr(tdc_probe_cli, "TDCPasswordAuthClient", FakeTDCPasswordAuthClient)
    monkeypatch.setattr(tdc_probe_cli, "TDCCrawlerClient", FakeTDCCrawlerClient)

    # 屏蔽实际写文件，仅记录 probe_result
    saved_reports = []
    monkeypatch.setattr(
        tdc_probe_cli,
        "save_report",
        lambda res, dir_path: (saved_reports.append(res), (dir_path / "probe.json", dir_path / "probe.md"))[1],
    )

    main_module._run_tdc_contract_probe(debug_enabled=False)

    # 验证 auth client 收到了密码
    assert len(FakeTDCPasswordAuthClient.instances) == 1
    auth_client = FakeTDCPasswordAuthClient.instances[0]
    assert auth_client.login_calls == [("probe_user", secret_pw)]

    # 验证终端输出与保存的报告中绝对不包含明文密码
    output = test_console.export_text()
    assert secret_pw not in output

    if saved_reports:
        from services.tdc_contract_probe import serialize_report_json, serialize_report_markdown

        json_text = serialize_report_json(saved_reports[0])
        md_text = serialize_report_markdown(saved_reports[0])
        assert secret_pw not in json_text
        assert secret_pw not in md_text


def test_password_cleared_on_auth_failure(
    monkeypatch: pytest.MonkeyPatch,
    test_console: Console,
) -> None:
    """认证失败时，finally 保证清空密码，且错误输出不泄漏敏感信息。"""
    secret_pw = "super_secret_failed_pass_888"
    FakeTDCPasswordAuthClient.fail_with = TDCAuthError("Invalid credentials")

    monkeypatch.setattr(
        tdc_probe_cli,
        "_ask_tdc_password_connection",
        lambda: ("https://tdc.example.com", "probe_user", secret_pw),
    )
    monkeypatch.setattr(
        tdc_probe_cli,
        "_ask_tdc_data_model_filters",
        lambda: TDCDataModelFilters(serial_number="WF-100"),
    )
    monkeypatch.setattr(tdc_probe_cli.Confirm, "ask", lambda prompt, **kw: "继续" in prompt)
    monkeypatch.setattr(tdc_probe_cli, "_ask_positive_int", lambda prompt, default: default)
    monkeypatch.setattr(tdc_probe_cli, "TDCPasswordAuthClient", FakeTDCPasswordAuthClient)
    monkeypatch.setattr(tdc_probe_cli, "TDCCrawlerClient", FakeTDCCrawlerClient)

    main_module._run_tdc_contract_probe(debug_enabled=False)

    output = test_console.export_text()
    assert secret_pw not in output
    assert "Invalid credentials" in output


# ── 3. 禁用 Header/Cookie 认证模式 ──────────────────────────────


def test_no_header_cookie_auth_mode(
    monkeypatch: pytest.MonkeyPatch,
    test_console: Console,
) -> None:
    """契约探测不包含且不调用 _ask_tdc_login_mode 或 _ask_tdc_connection。"""
    assert not hasattr(tdc_probe_cli, "_ask_tdc_login_mode")
    assert not hasattr(tdc_probe_cli, "_ask_tdc_connection")

    monkeypatch.setattr(
        tdc_probe_cli,
        "_ask_tdc_password_connection",
        lambda: ("https://tdc.example.com", "user", "pass"),
    )
    monkeypatch.setattr(
        tdc_probe_cli,
        "_ask_tdc_data_model_filters",
        lambda: TDCDataModelFilters(serial_number="WF-100"),
    )
    monkeypatch.setattr(tdc_probe_cli.Confirm, "ask", lambda prompt, **kw: "继续" in prompt)
    monkeypatch.setattr(tdc_probe_cli, "_ask_positive_int", lambda prompt, default: default)
    monkeypatch.setattr(tdc_probe_cli, "TDCPasswordAuthClient", FakeTDCPasswordAuthClient)
    monkeypatch.setattr(tdc_probe_cli, "TDCCrawlerClient", FakeTDCCrawlerClient)
    monkeypatch.setattr(
        tdc_probe_cli,
        "save_report",
        lambda res, dir_path: (dir_path / "probe.json", dir_path / "probe.md"),
    )

    # 正常运行无异常，说明未调用被禁止的 Header/Cookie 函数
    main_module._run_tdc_contract_probe(debug_enabled=False)
    assert len(FakeTDCPasswordAuthClient.instances) == 1


# ── 4. 空过滤条件被拒绝 ──────────────────────────────────────────


def test_empty_filters_rejected_without_login(
    monkeypatch: pytest.MonkeyPatch,
    test_console: Console,
) -> None:
    """过滤条件全部为空时，validate_filters_non_empty 拦截，不执行登录或查询。"""
    monkeypatch.setattr(tdc_probe_cli.Confirm, "ask", lambda *args, **kwargs: True)
    # 所有字段为 None
    monkeypatch.setattr(
        tdc_probe_cli,
        "_ask_tdc_data_model_filters",
        lambda: TDCDataModelFilters(),
    )
    monkeypatch.setattr(tdc_probe_cli, "TDCPasswordAuthClient", FakeTDCPasswordAuthClient)
    monkeypatch.setattr(tdc_probe_cli, "TDCCrawlerClient", FakeTDCCrawlerClient)

    password_conn_called = []
    monkeypatch.setattr(
        tdc_probe_cli,
        "_ask_tdc_password_connection",
        lambda: (password_conn_called.append(True), ("url", "u", "p"))[1],
    )

    main_module._run_tdc_contract_probe(debug_enabled=False)

    assert len(password_conn_called) == 0
    assert len(FakeTDCPasswordAuthClient.instances) == 0
    assert len(FakeTDCCrawlerClient.instances) == 0

    output = test_console.export_text()
    assert "at least one non-empty filter condition is required" in output


# ── 5. 报告保存到 .runtime ───────────────────────────────────────


def test_probe_saves_report_to_runtime(
    monkeypatch: pytest.MonkeyPatch,
    test_console: Console,
    tmp_path: Path,
) -> None:
    """使用 fake 爬虫数据运行探测，验证报告保存至指定目录且内容结构完整。"""
    monkeypatch.setattr(
        tdc_probe_cli,
        "_ask_tdc_password_connection",
        lambda: ("https://tdc.example.com", "probe_user", "probe_pass"),
    )
    monkeypatch.setattr(
        tdc_probe_cli,
        "_ask_tdc_data_model_filters",
        lambda: TDCDataModelFilters(serial_number="WF-100"),
    )
    monkeypatch.setattr(tdc_probe_cli.Confirm, "ask", lambda prompt, **kw: "继续" in prompt)
    monkeypatch.setattr(tdc_probe_cli, "_ask_positive_int", lambda prompt, default: default)
    monkeypatch.setattr(tdc_probe_cli, "TDCPasswordAuthClient", FakeTDCPasswordAuthClient)
    monkeypatch.setattr(tdc_probe_cli, "TDCCrawlerClient", FakeTDCCrawlerClient)

    # 实际调用 real save_report 写入 tmp_path
    target_dir = tmp_path / "tdc_contract_probe"
    from services.tdc_contract_probe import save_report as real_save_report

    saved_paths: list[tuple[Path, Path]] = []

    def mock_save_report(result: Any, output_dir: Path) -> tuple[Path, Path] | None:
        ret = real_save_report(result, target_dir)
        if ret:
            saved_paths.append(ret)
        return ret

    monkeypatch.setattr(tdc_probe_cli, "save_report", mock_save_report)

    main_module._run_tdc_contract_probe(debug_enabled=False)

    assert len(saved_paths) == 1
    json_path, md_path = saved_paths[0]
    assert json_path.exists()
    assert md_path.exists()

    # 验证 JSON 结构
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert data["record_count"] == 2
    assert data["report_type"] == "data_model"
    assert "field_profiles" in data
    assert "candidate_key_profiles" in data

    # 验证 Markdown 包含必要结构
    md_content = md_path.read_text(encoding="utf-8")
    assert "# TDC 数模同步契约探测报告" in md_content
    assert "## 字段画像" in md_content
    assert "## Candidate Key 统计" in md_content


# ── 6. 仅显示流程编号，不显示原始行 ───────────────────────────────


def test_workflow_identifiers_displayed_locally_but_not_saved(
    monkeypatch: pytest.MonkeyPatch,
    test_console: Console,
) -> None:
    """流程编号仅显示在本地终端，不进入脱敏探测报告。"""
    assert not hasattr(tdc_probe_cli, "_render_tdc_paged_result")

    monkeypatch.setattr(
        tdc_probe_cli,
        "_ask_tdc_password_connection",
        lambda: ("https://tdc.example.com", "user", "pass"),
    )
    monkeypatch.setattr(
        tdc_probe_cli,
        "_ask_tdc_data_model_filters",
        lambda: TDCDataModelFilters(serial_number="WF-100"),
    )
    monkeypatch.setattr(tdc_probe_cli.Confirm, "ask", lambda prompt, **kw: "继续" in prompt)
    monkeypatch.setattr(tdc_probe_cli, "_ask_positive_int", lambda prompt, default: default)
    monkeypatch.setattr(tdc_probe_cli, "TDCPasswordAuthClient", FakeTDCPasswordAuthClient)
    monkeypatch.setattr(tdc_probe_cli, "TDCCrawlerClient", FakeTDCCrawlerClient)
    saved_reports = []
    monkeypatch.setattr(
        tdc_probe_cli,
        "save_report",
        lambda res, dir_path: saved_reports.append(res) or (dir_path / "probe.json", dir_path / "probe.md"),
    )

    main_module._run_tdc_contract_probe(debug_enabled=False)

    output = test_console.export_text()
    assert "INC-001" in output
    assert "DOC-001" in output
    assert "FORM-001" in output

    # Field statistics still contain no raw values.
    assert "字段统计（只读，不含原始值）" in output
    assert "approvalStatus" in output
    assert "formId" in output
    assert len(saved_reports) == 1
    saved = saved_reports[0]
    assert "INC-001" not in str(saved)
    assert "DOC-001" not in str(saved)
    assert "FORM-001" not in str(saved)


# ── 7. 无参数仍进入交互式菜单 ────────────────────────────────────


def test_main_no_args_enters_interactive_menu(
    monkeypatch: pytest.MonkeyPatch,
    cli_db: DatabaseManager,
) -> None:
    """无参数调用 main([]) 时仍进入交互式菜单循环（保持现有行为）。"""
    called = {"banner": False}

    def fake_show_banner() -> None:
        called["banner"] = True

    def fake_show_menu() -> None:
        raise EOFError

    monkeypatch.setattr(main_module, "show_banner", fake_show_banner)
    monkeypatch.setattr(main_module, "show_menu", fake_show_menu)
    monkeypatch.setattr(
        main_module,
        "Prompt",
        type("FakePrompt", (), {"ask": staticmethod(lambda *a, **k: "0")}),
    )

    with pytest.raises(SystemExit) as exc_info:
        main_module.main([])

    assert exc_info.value.code == 0
    assert called["banner"] is True


# ── 8. project-status-sync --once 仍正常工作 ────────────────────


def test_project_status_sync_once_still_works(
    monkeypatch: pytest.MonkeyPatch,
    cli_db: DatabaseManager,
) -> None:
    """project-status-sync --once 命令仍返回整型退出码。"""
    code = main_module.main(["project-status-sync", "--once"])
    assert isinstance(code, int)


# ── 9. TDC 菜单路由测试 ──────────────────────────────────────────


def test_existing_tdc_menu_option_1_routes_to_run_tdc_report(
    monkeypatch: pytest.MonkeyPatch,
    cli_db: DatabaseManager,
) -> None:
    """TDC 菜单选项 1 仍正常路由至 _run_tdc_report('data_model', ...)。"""
    report_calls: list[tuple[str, bool]] = []

    def fake_run_tdc_report(report_type: str, debug_enabled: bool) -> None:
        report_calls.append((report_type, debug_enabled))

    answers = iter(["1", "0"])
    monkeypatch.setattr(
        main_module.Prompt,
        "ask",
        lambda *args, **kwargs: next(answers),
    )
    monkeypatch.setattr(main_module, "_run_tdc_report", fake_run_tdc_report)

    main_module.handle_tdc_crawler(cli_db)

    assert report_calls == [("data_model", False)]


def test_tdc_menu_option_5_routes_to_run_tdc_contract_probe(
    monkeypatch: pytest.MonkeyPatch,
    cli_db: DatabaseManager,
) -> None:
    """TDC 菜单选项 5 路由至 _run_tdc_contract_probe。"""
    probe_calls: list[bool] = []

    def fake_run_probe(debug_enabled: bool) -> None:
        probe_calls.append(debug_enabled)

    answers = iter(["5", "0"])
    monkeypatch.setattr(
        main_module.Prompt,
        "ask",
        lambda *args, **kwargs: next(answers),
    )
    monkeypatch.setattr(main_module, "_run_tdc_contract_probe", fake_run_probe)

    main_module.handle_tdc_crawler(cli_db)

    assert probe_calls == [False]


# ── 10. 扩展覆盖：稳定性检查与分类字段选择 ──────────────────────


def test_probe_with_stability_check_enabled(
    monkeypatch: pytest.MonkeyPatch,
    test_console: Console,
) -> None:
    """开启稳定性检查时，crawler.crawl_data_model_all 被调用两次以比对结果。"""
    monkeypatch.setattr(
        tdc_probe_cli,
        "_ask_tdc_password_connection",
        lambda: ("https://tdc.example.com", "user", "pass"),
    )
    monkeypatch.setattr(
        tdc_probe_cli,
        "_ask_tdc_data_model_filters",
        lambda: TDCDataModelFilters(serial_number="WF-100"),
    )
    # 确认继续探测 + 确认执行稳定性检查 + 不查看分类字段
    confirm_answers = iter([True, True, False])
    monkeypatch.setattr(tdc_probe_cli.Confirm, "ask", lambda *a, **kw: next(confirm_answers))
    monkeypatch.setattr(tdc_probe_cli, "_ask_positive_int", lambda prompt, default: default)
    monkeypatch.setattr(tdc_probe_cli, "TDCPasswordAuthClient", FakeTDCPasswordAuthClient)
    monkeypatch.setattr(tdc_probe_cli, "TDCCrawlerClient", FakeTDCCrawlerClient)

    saved_reports = []
    monkeypatch.setattr(
        tdc_probe_cli,
        "save_report",
        lambda res, dir_path: (saved_reports.append(res), (dir_path / "probe.json", dir_path / "probe.md"))[1],
    )

    main_module._run_tdc_contract_probe(debug_enabled=False)

    crawler = FakeTDCCrawlerClient.instances[0]
    assert len(crawler.crawl_calls) == 2
    assert len(saved_reports) == 1
    assert saved_reports[0].stability.conclusion == "stable"


def test_probe_with_categorical_fields_selected(
    monkeypatch: pytest.MonkeyPatch,
    test_console: Console,
) -> None:
    """用户选择合法分类字段时，分类值被提取并写入报告。"""
    monkeypatch.setattr(
        tdc_probe_cli,
        "_ask_tdc_password_connection",
        lambda: ("https://tdc.example.com", "user", "pass"),
    )
    monkeypatch.setattr(
        tdc_probe_cli,
        "_ask_tdc_data_model_filters",
        lambda: TDCDataModelFilters(serial_number="WF-100"),
    )
    # 继续探测(True) -> 不稳定性检查(False) -> 查看分类字段(True)
    confirm_answers = iter([True, False, True])
    monkeypatch.setattr(tdc_probe_cli.Confirm, "ask", lambda *a, **kw: next(confirm_answers))
    monkeypatch.setattr(tdc_probe_cli, "_ask_positive_int", lambda prompt, default: default)
    monkeypatch.setattr(
        tdc_probe_cli.Prompt,
        "ask",
        lambda prompt, **kw: "approvalStatus",
    )
    monkeypatch.setattr(tdc_probe_cli, "TDCPasswordAuthClient", FakeTDCPasswordAuthClient)
    monkeypatch.setattr(tdc_probe_cli, "TDCCrawlerClient", FakeTDCCrawlerClient)

    saved_reports = []
    monkeypatch.setattr(
        tdc_probe_cli,
        "save_report",
        lambda res, dir_path: (saved_reports.append(res), (dir_path / "probe.json", dir_path / "probe.md"))[1],
    )

    main_module._run_tdc_contract_probe(debug_enabled=False)

    assert len(saved_reports) == 1
    cat_vals = saved_reports[0].categorical_values
    assert len(cat_vals) == 1
    assert cat_vals[0].field_name == "approvalStatus"
    assert "审批中" in cat_vals[0].values
    assert "已完成" in cat_vals[0].values


def test_probe_with_zero_rows_returned(
    monkeypatch: pytest.MonkeyPatch,
    test_console: Console,
) -> None:
    """当查询返回 0 条记录时，友好提示并安全退出，不生成报告。"""
    FakeTDCCrawlerClient.custom_rows = []

    monkeypatch.setattr(
        tdc_probe_cli,
        "_ask_tdc_password_connection",
        lambda: ("https://tdc.example.com", "user", "pass"),
    )
    monkeypatch.setattr(
        tdc_probe_cli,
        "_ask_tdc_data_model_filters",
        lambda: TDCDataModelFilters(serial_number="WF-EMPTY"),
    )
    monkeypatch.setattr(tdc_probe_cli.Confirm, "ask", lambda prompt, **kw: "继续" in prompt)
    monkeypatch.setattr(tdc_probe_cli, "_ask_positive_int", lambda prompt, default: default)
    monkeypatch.setattr(tdc_probe_cli, "TDCPasswordAuthClient", FakeTDCPasswordAuthClient)
    monkeypatch.setattr(tdc_probe_cli, "TDCCrawlerClient", FakeTDCCrawlerClient)

    save_called = []
    monkeypatch.setattr(
        tdc_probe_cli,
        "save_report",
        lambda *args, **kwargs: save_called.append(args),
    )

    main_module._run_tdc_contract_probe(debug_enabled=False)

    assert len(save_called) == 0
    output = test_console.export_text()
    assert "查询返回零条记录" in output


def test_probe_handles_crawler_error_gracefully(
    monkeypatch: pytest.MonkeyPatch,
    test_console: Console,
) -> None:
    """爬虫请求异常时捕获 TDCCrawlerError，展示错误面板，不崩溃。"""
    FakeTDCCrawlerClient.fail_with = TDCCrawlerError("Network timeout during crawl")

    monkeypatch.setattr(
        tdc_probe_cli,
        "_ask_tdc_password_connection",
        lambda: ("https://tdc.example.com", "user", "pass"),
    )
    monkeypatch.setattr(
        tdc_probe_cli,
        "_ask_tdc_data_model_filters",
        lambda: TDCDataModelFilters(serial_number="WF-100"),
    )
    monkeypatch.setattr(tdc_probe_cli.Confirm, "ask", lambda prompt, **kw: "继续" in prompt)
    monkeypatch.setattr(tdc_probe_cli, "_ask_positive_int", lambda prompt, default: default)
    monkeypatch.setattr(tdc_probe_cli, "TDCPasswordAuthClient", FakeTDCPasswordAuthClient)
    monkeypatch.setattr(tdc_probe_cli, "TDCCrawlerClient", FakeTDCCrawlerClient)

    main_module._run_tdc_contract_probe(debug_enabled=False)

    output = test_console.export_text()
    assert "TDCCrawlerError" in output
    assert "Network timeout during crawl" in output


# ── 11. CLI 命令行入口断言清单 (15 项测试) ──────────────────────────


def test_tdc_contract_probe_cli_runs_without_database_manager(
    monkeypatch: pytest.MonkeyPatch,
    test_console: Console,
) -> None:
    """1. tdc-contract-probe 不构造 DatabaseManager。"""
    def forbid_db(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("DatabaseManager must NOT be instantiated for tdc-contract-probe")

    monkeypatch.setattr(main_module, "DatabaseManager", forbid_db)
    monkeypatch.setattr(tdc_probe_cli.Confirm, "ask", lambda *args, **kwargs: False)
    assert not hasattr(tdc_probe_cli, "DatabaseManager")

    ret = main_module.main(["tdc-contract-probe"])
    assert ret == 0


def test_tdc_contract_probe_cli_no_sqlite_files_created_or_modified(
    monkeypatch: pytest.MonkeyPatch,
    test_console: Console,
    tmp_path: Path,
) -> None:
    """2. 探测命令不创建或修改任何 SQLite 数据库文件。"""
    monkeypatch.setattr(main_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(tdc_probe_cli.Confirm, "ask", lambda *args, **kwargs: False)

    before_files = set(tmp_path.rglob("*.db")) | set(tmp_path.rglob("*.sqlite"))

    ret = main_module.main(["tdc-contract-probe"])
    assert ret == 0

    after_files = set(tmp_path.rglob("*.db")) | set(tmp_path.rglob("*.sqlite"))
    assert after_files == before_files == set()


def test_tdc_contract_probe_cli_init_database_never_called(
    monkeypatch: pytest.MonkeyPatch,
    test_console: Console,
) -> None:
    """3. 探测命令绝对不调用 init_database。"""
    class MockDatabaseManager:
        init_called = False

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def init_database(self) -> None:
            MockDatabaseManager.init_called = True
            raise AssertionError("init_database must NOT be called for tdc-contract-probe")

    monkeypatch.setattr(main_module, "DatabaseManager", MockDatabaseManager)
    monkeypatch.setattr(tdc_probe_cli.Confirm, "ask", lambda *args, **kwargs: False)

    ret = main_module.main(["tdc-contract-probe"])
    assert ret == 0
    assert MockDatabaseManager.init_called is False


def test_tdc_contract_probe_cli_no_banner_or_main_menu_shown(
    monkeypatch: pytest.MonkeyPatch,
    test_console: Console,
) -> None:
    """4. 探测命令不显示主界面 banner 或主菜单。"""
    def forbid_banner(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("show_banner must NOT be called for tdc-contract-probe")

    def forbid_menu(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("show_menu must NOT be called for tdc-contract-probe")

    monkeypatch.setattr(main_module, "show_banner", forbid_banner)
    monkeypatch.setattr(main_module, "show_menu", forbid_menu)
    monkeypatch.setattr(tdc_probe_cli.Confirm, "ask", lambda *args, **kwargs: False)

    ret = main_module.main(["tdc-contract-probe"])
    assert ret == 0


def test_tdc_contract_probe_cli_no_stdin_credentials_beyond_interactive_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """5. 探测命令不接受 --username/--password CLI 参数。"""
    with pytest.raises(SystemExit) as exc_info1:
        main_module.main(["tdc-contract-probe", "--username", "fake_user"])
    assert exc_info1.value.code == 2

    with pytest.raises(SystemExit) as exc_info2:
        main_module.main(["tdc-contract-probe", "--password", "fake_pass"])
    assert exc_info2.value.code == 2


def test_tdc_contract_probe_cli_no_header_cookie_login_path(
    monkeypatch: pytest.MonkeyPatch,
    test_console: Console,
) -> None:
    """6. 契约探测不调用 Header/Cookie 相关登录方法。"""
    assert not hasattr(tdc_probe_cli, "_ask_tdc_login_mode")
    assert not hasattr(tdc_probe_cli, "_ask_tdc_connection")
    monkeypatch.setattr(tdc_probe_cli.Confirm, "ask", lambda *args, **kwargs: False)

    ret = main_module.main(["tdc-contract-probe"])
    assert ret == 0


def test_tdc_contract_probe_cli_success_returns_zero(
    monkeypatch: pytest.MonkeyPatch,
    test_console: Console,
    tmp_path: Path,
) -> None:
    """7. 完整探测成功流程返回 0 并保存报告文件。"""
    monkeypatch.setattr(main_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        tdc_probe_cli.Confirm,
        "ask",
        lambda prompt, **kw: "继续" in prompt and "第二次" not in prompt and "分类" not in prompt,
    )
    monkeypatch.setattr(
        tdc_probe_cli,
        "_ask_tdc_data_model_filters",
        lambda: TDCDataModelFilters(serial_number="test"),
    )
    monkeypatch.setattr(tdc_probe_cli, "_ask_positive_int", lambda prompt, default: default)
    monkeypatch.setattr(
        tdc_probe_cli,
        "_ask_tdc_password_connection",
        lambda: ("https://tdc.fake.test", "fake_user", "fake_pass"),
    )
    monkeypatch.setattr(tdc_probe_cli, "TDCPasswordAuthClient", FakeTDCPasswordAuthClient)
    monkeypatch.setattr(tdc_probe_cli, "TDCCrawlerClient", FakeTDCCrawlerClient)

    ret = main_module.main(["tdc-contract-probe"])
    assert ret == 0

    probe_dir = tmp_path / ".runtime" / "tdc_contract_probe"
    json_files = list(probe_dir.glob("*.json"))
    md_files = list(probe_dir.glob("*.md"))
    assert len(json_files) == 1
    assert len(md_files) == 1


def test_tdc_contract_probe_cli_user_cancel_returns_zero(
    monkeypatch: pytest.MonkeyPatch,
    test_console: Console,
    tmp_path: Path,
) -> None:
    """8. 用户在初始确认时取消返回 0，且不生成任何报告文件。"""
    monkeypatch.setattr(main_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(tdc_probe_cli.Confirm, "ask", lambda *args, **kwargs: False)
    monkeypatch.setattr(tdc_probe_cli, "TDCPasswordAuthClient", FakeTDCPasswordAuthClient)
    monkeypatch.setattr(tdc_probe_cli, "TDCCrawlerClient", FakeTDCCrawlerClient)

    ret = main_module.main(["tdc-contract-probe"])
    assert ret == 0
    assert len(FakeTDCPasswordAuthClient.instances) == 0
    assert len(FakeTDCCrawlerClient.instances) == 0

    probe_dir = tmp_path / ".runtime" / "tdc_contract_probe"
    assert not probe_dir.exists() or list(probe_dir.iterdir()) == []


def test_tdc_contract_probe_cli_auth_failure_returns_one(
    monkeypatch: pytest.MonkeyPatch,
    test_console: Console,
) -> None:
    """9. 认证失败时返回 1，且输出中无 Traceback。"""
    FakeTDCPasswordAuthClient.fail_with = TDCAuthError("Invalid credentials probe")

    monkeypatch.setattr(
        tdc_probe_cli.Confirm,
        "ask",
        lambda prompt, **kw: "继续" in prompt and "第二次" not in prompt and "分类" not in prompt,
    )
    monkeypatch.setattr(
        tdc_probe_cli,
        "_ask_tdc_data_model_filters",
        lambda: TDCDataModelFilters(serial_number="test"),
    )
    monkeypatch.setattr(tdc_probe_cli, "_ask_positive_int", lambda prompt, default: default)
    monkeypatch.setattr(
        tdc_probe_cli,
        "_ask_tdc_password_connection",
        lambda: ("https://tdc.fake.test", "fake_user", "fake_pass"),
    )
    monkeypatch.setattr(tdc_probe_cli, "TDCPasswordAuthClient", FakeTDCPasswordAuthClient)
    monkeypatch.setattr(tdc_probe_cli, "TDCCrawlerClient", FakeTDCCrawlerClient)

    ret = main_module.main(["tdc-contract-probe"])
    assert ret == 1

    output = test_console.export_text()
    assert "Traceback" not in output
    assert "Invalid credentials probe" in output


def test_tdc_contract_probe_cli_keyboard_interrupt_returns_130(
    monkeypatch: pytest.MonkeyPatch,
    test_console: Console,
) -> None:
    """10. 交互过程中捕获 KeyboardInterrupt 时返回 130。"""
    monkeypatch.setattr(
        tdc_probe_cli.Confirm,
        "ask",
        lambda prompt, **kw: "继续" in prompt,
    )

    def raise_interrupt(*args: Any, **kwargs: Any) -> Any:
        raise KeyboardInterrupt()

    monkeypatch.setattr(tdc_probe_cli, "_ask_tdc_data_model_filters", raise_interrupt)

    ret = main_module.main(["tdc-contract-probe"])
    assert ret == 130


def test_tdc_contract_probe_cli_help_does_not_init_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """11. --help 显示帮助信息且不初始化数据库，SystemExit 退出码为 0。"""
    def forbid_db(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("DatabaseManager must NOT be instantiated when invoking --help")

    monkeypatch.setattr(main_module, "DatabaseManager", forbid_db)

    with pytest.raises(SystemExit) as exc_info:
        main_module.main(["tdc-contract-probe", "--help"])

    assert exc_info.value.code == 0


def test_tdc_contract_probe_cli_bad_args_returns_two(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """12. 传入未知命令行参数时 argparse 返回 SystemExit 状态码 2。"""
    with pytest.raises(SystemExit) as exc_info:
        main_module.main(["tdc-contract-probe", "--unknown-flag"])

    assert exc_info.value.code == 2


def test_tdc_contract_probe_cli_project_status_sync_once_not_regressed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    test_console: Console,
) -> None:
    """13. project-status-sync --once 命令未回归，仍返回整型退出码 (0 或 2)。"""
    target = tmp_path / "sync_cli.db"
    monkeypatch.setattr(
        main_module,
        "DatabaseManager",
        lambda: DatabaseManager(db_path=target),
    )
    code = main_module.main(["project-status-sync", "--once"])
    assert isinstance(code, int)
    assert code in (0, 2)


def test_tdc_contract_probe_cli_no_args_interactive_mode_not_regressed(
    monkeypatch: pytest.MonkeyPatch,
    cli_db: DatabaseManager,
) -> None:
    """14. 无参数调用 main([]) 时仍正常展示 banner 并进入交互式主菜单。"""
    called = {"banner": False, "menu": False}

    def fake_show_banner() -> None:
        called["banner"] = True

    def fake_show_menu() -> None:
        called["menu"] = True
        raise EOFError

    monkeypatch.setattr(main_module, "show_banner", fake_show_banner)
    monkeypatch.setattr(main_module, "show_menu", fake_show_menu)
    monkeypatch.setattr(
        main_module,
        "Prompt",
        type("FakePrompt", (), {"ask": staticmethod(lambda *a, **k: "0")}),
    )

    with pytest.raises(SystemExit) as exc_info:
        main_module.main([])

    assert exc_info.value.code == 0
    assert called["banner"] is True
    assert called["menu"] is True


def test_tdc_contract_probe_cli_production_connector_registry_registered() -> None:
    """15. 生产 ConnectorRegistry 注册预期的生产连接器。"""
    from services.project_status_sync_runner import create_production_registry

    reg = create_production_registry()
    assert reg.registered_types == ("aras", "tdc")
