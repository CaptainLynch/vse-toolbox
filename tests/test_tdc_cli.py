from __future__ import annotations

from pathlib import Path

import pytest
from rich.console import Console

import main
from core.diagnostics import DiagnosticOptions, MarkdownDiagnosticReport
from services.tdc_auth import TDCAuthError, TDCLoginResult
from services.tdc_crawler import (
    DATA_MODEL_LIST_PATH,
    TDCCrawlerError,
    TDCDataModelFilters,
    TDCExportResult,
    TDCHttpDiagnosticEvent,
    TDCPagedResult,
    TDCSORFilters,
)


class FakeReport:
    instances: list["FakeReport"] = []

    def __init__(self, **kwargs):  # type: ignore[no-untyped-def]
        self.kwargs = kwargs
        self.events = []
        self.exceptions = []
        self.__class__.instances.append(self)

    def record_http_event(self, event):  # type: ignore[no-untyped-def]
        self.events.append(event)

    def record_exception(self, exc):  # type: ignore[no-untyped-def]
        self.exceptions.append(exc)

    def save(self, status):  # type: ignore[no-untyped-def]
        self.status = status
        return None


class FakeTDCClient:
    calls: list[dict[str, object]] = []
    fail: Exception | None = None
    emit_debug = False

    def __init__(self, base_url, session=None, headers=None, timeout=30.0, diagnostic_hook=None):  # type: ignore[no-untyped-def]
        self.diagnostic_hook = diagnostic_hook
        self.__class__.calls.append(
            {
                "method": "init",
                "base_url": base_url,
                "session": session,
                "headers": headers or {},
                "timeout": timeout,
            }
        )

    def _before(self, method: str, **kwargs):  # type: ignore[no-untyped-def]
        if self.fail:
            raise self.fail
        self.__class__.calls.append({"method": method, **kwargs})
        if self.emit_debug and self.diagnostic_hook:
            self.diagnostic_hook(
                TDCHttpDiagnosticEvent(
                    timestamp="2026-07-19T10:11:12.123",
                    stage="response",
                    request_id="abc12345",
                    page_type="data_model",
                    method="GET",
                    origin="https://tdc.example",
                    path=DATA_MODEL_LIST_PATH,
                    query={"current": "1", "applicant": "[redacted]", "token": "fictional-token"},
                    page=1,
                    page_size=25,
                    timeout=30,
                    status_code=200,
                    elapsed_ms=18.5,
                    content_type="application/json",
                    content_length=128,
                    json_fields=("code", "data", "msg"),
                    record_count=1,
                    total=1,
                    pages=1,
                    request_headers={
                        "Accept": "application/json",
                        "Cookie": "sid=fictional-cookie",
                        "Authorization": "Bearer fictional-token",
                        "X-Unsafe": "must-not-render",
                    },
                    response_headers={"Content-Type": "application/json", "Set-Cookie": "sid=fictional-set-cookie"},
                )
            )

    @staticmethod
    def _page(report_type: str) -> TDCPagedResult:
        return TDCPagedResult(
            report_type=report_type,
            rows=[{"incident": "WF-1", "processNo": "SOR-WF-1", "title": "Fictional report"}],
            page=1,
            page_size=25,
            total=1,
            pages=1,
            fetched_pages=1,
            unique_count=1,
            duplicate_count=0,
            stop_reason="single_page",
            record_granularity="part_detail",
        )

    def query_data_model_page(self, filters, **kwargs):  # type: ignore[no-untyped-def]
        self._before("data_model_page", filters=filters, **kwargs)
        return self._page("data_model")

    def crawl_data_model_all(self, filters, **kwargs):  # type: ignore[no-untyped-def]
        self._before("data_model_all", filters=filters, **kwargs)
        return self._page("data_model")

    def export_data_model(self, filters, file_name=None):  # type: ignore[no-untyped-def]
        self._before("data_model_export", filters=filters, file_name=file_name)
        return TDCExportResult(
            report_type="data_model",
            file_name=file_name or "data-model.xlsx",
            path=Path("C:/fictional/data-model.xlsx"),
            byte_count=12,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            signature_valid=True,
            elapsed_ms=3.5,
            record_granularity="part_detail",
        )

    def query_sor_page(self, filters, **kwargs):  # type: ignore[no-untyped-def]
        self._before("sor_page", filters=filters, **kwargs)
        return self._page("sor")

    def crawl_sor_all(self, filters, **kwargs):  # type: ignore[no-untyped-def]
        self._before("sor_all", filters=filters, **kwargs)
        return self._page("sor")

    def export_sor(self, filters, file_name=None):  # type: ignore[no-untyped-def]
        self._before("sor_export", filters=filters, file_name=file_name)
        return TDCExportResult(
            report_type="sor",
            file_name=file_name or "sor-details.xlsx",
            path=Path("C:/fictional/sor-details.xlsx"),
            byte_count=20,
            content_type="application/octet-stream",
            signature_valid=True,
            elapsed_ms=4.0,
            record_granularity="part_detail",
        )


class FakeTDCAuthClient:
    calls: list[dict[str, object]] = []
    session = object()
    fail: Exception | None = None

    def __init__(self, base_url, timeout=30.0, diagnostic_hook=None):  # type: ignore[no-untyped-def]
        self.__class__.calls.append(
            {
                "method": "init",
                "base_url": base_url,
                "timeout": timeout,
                "diagnostic_hook": diagnostic_hook,
            }
        )

    def login(self, username, password):  # type: ignore[no-untyped-def]
        self.__class__.calls.append({"method": "login", "username": username, "password": password})
        if self.fail:
            raise self.fail
        return TDCLoginResult(session=self.session, token_expires_in=600)


@pytest.fixture()
def cli(monkeypatch):  # type: ignore[no-untyped-def]
    FakeTDCClient.calls = []
    FakeTDCClient.fail = None
    FakeTDCClient.emit_debug = False
    FakeTDCAuthClient.calls = []
    FakeTDCAuthClient.fail = None
    FakeReport.instances = []
    console = Console(record=True, width=160)
    monkeypatch.setattr(main, "console", console)
    monkeypatch.setattr(main, "TDCCrawlerClient", FakeTDCClient)
    monkeypatch.setattr(main, "TDCPasswordAuthClient", FakeTDCAuthClient)
    monkeypatch.setattr(main, "MarkdownDiagnosticReport", FakeReport)
    monkeypatch.setattr(main, "_ask_tdc_connection", lambda page_path: ("https://tdc.example", {}))
    monkeypatch.setattr(main, "_ask_tdc_login_mode", lambda: "2")
    monkeypatch.setattr(main, "_ask_positive_int", lambda label, default: 1 if label == "Page" else 25)
    return console


def test_main_menu_has_stable_tdc_option_and_cli_row(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    assert main.MENU_OPTIONS["7"] == ("TDC 报表爬虫", main.handle_tdc_crawler)
    assert main.DEFERRED == {"2", "3"}
    console = Console(record=True, width=160)
    monkeypatch.setattr(main, "console", console)

    main.show_menu()

    rendered = console.export_text()
    assert "TDC Reports" in rendered
    assert "CLI" in rendered
    assert "三个 TDC 报表的查询与导出" in rendered
    assert "Aras Cockpit" in rendered


def test_tdc_submenu_lists_three_pages_and_return(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    answers = iter(["0"])
    monkeypatch.setattr(main.Prompt, "ask", lambda *args, **kwargs: next(answers))
    console = Console(record=True, width=160)
    monkeypatch.setattr(main, "console", console)

    main.handle_tdc_crawler(None)  # type: ignore[arg-type]

    rendered = console.export_text()
    assert "数模设计审核流程报表" in rendered
    assert "SOR 流程报表" in rendered
    assert "造型 A 面冻结发布单" in rendered
    assert "调试与诊断设置" in rendered
    assert "返回主菜单" in rendered


def test_a_face_page_shows_precise_har_blocker_without_client(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    answers = iter(["3", "0"])
    monkeypatch.setattr(main.Prompt, "ask", lambda *args, **kwargs: next(answers))
    console = Console(record=True, width=160)
    monkeypatch.setattr(main, "console", console)

    main.handle_tdc_crawler(None)  # type: ignore[arg-type]

    rendered = console.export_text()
    assert "待 HAR 验证" in rendered
    assert "/tpc/dataAdmin/intelligent/ots2/index" in rendered


def test_debug_toggle_is_session_local_and_never_prompts_for_unsafe_raw(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    answers = iter(["4", "0"])
    confirms = []
    monkeypatch.setattr(main.Prompt, "ask", lambda *args, **kwargs: next(answers))
    monkeypatch.setattr(
        main.Confirm,
        "ask",
        lambda prompt, **kwargs: confirms.append(prompt) or True,
    )
    console = Console(record=True, width=160)
    monkeypatch.setattr(main, "console", console)

    main.handle_tdc_crawler(None)  # type: ignore[arg-type]

    rendered = console.export_text()
    assert "当前：开启" in rendered
    assert "TDC Debug 已开启" in rendered
    assert len(confirms) == 1
    assert "unsafe_raw" not in confirms[0]


def test_data_model_page_normal_mode_calls_service_without_http_noise(cli, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    filters = TDCDataModelFilters(serial_number="WF-1")
    monkeypatch.setattr(main, "_tdc_action_menu", lambda: "1")
    monkeypatch.setattr(main, "_ask_tdc_data_model_filters", lambda: filters)

    main._run_tdc_report("data_model", False)

    call = next(item for item in FakeTDCClient.calls if item["method"] == "data_model_page")
    assert call["filters"] == filters
    assert call["page"] == 1
    assert call["page_size"] == 25
    rendered = cli.export_text()
    assert "开始: 数模设计审核流程报表" in rendered
    assert "数模设计审核流程报表（流程粒度）" in rendered
    assert "TDC Debug" not in rendered


def test_password_login_is_primary_and_authenticated_session_is_injected(cli, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(main, "_tdc_action_menu", lambda: "1")
    monkeypatch.setattr(main, "_ask_tdc_data_model_filters", lambda: TDCDataModelFilters())
    monkeypatch.setattr(main, "_ask_tdc_login_mode", lambda: "1")
    monkeypatch.setattr(
        main,
        "_ask_tdc_password_connection",
        lambda: ("https://tdc.example", "fictional-user", "fictional-password-secret"),
    )

    main._run_tdc_report("data_model", False)

    auth_call = next(item for item in FakeTDCAuthClient.calls if item["method"] == "login")
    assert auth_call["username"] == "fictional-user"
    assert auth_call["password"] == "fictional-password-secret"
    init_call = next(item for item in FakeTDCClient.calls if item["method"] == "init")
    assert init_call["session"] is FakeTDCAuthClient.session
    assert init_call["headers"] == {}
    rendered = cli.export_text()
    assert "正在通过企业账号中心登录 TDC" in rendered
    assert "TDC 账号密码登录成功" in rendered
    assert "fictional-user" not in rendered
    assert "fictional-password-secret" not in rendered
    report_inputs = FakeReport.instances[-1].kwargs["inputs"]
    assert report_inputs["auth_mode"] == "password"
    assert "username" not in report_inputs
    assert "password" not in report_inputs


def test_password_prompt_is_hidden_and_login_mode_defaults_to_primary(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    prompts = []
    answers = iter(["https://tdc.example", "fictional-user", "fictional-password"])

    def fake_ask(prompt, **kwargs):  # type: ignore[no-untyped-def]
        prompts.append((prompt, kwargs))
        return next(answers)

    monkeypatch.setattr(main.Prompt, "ask", fake_ask)
    assert main._ask_tdc_password_connection() == (
        "https://tdc.example",
        "fictional-user",
        "fictional-password",
    )
    assert prompts[-1][0] == "TDC 密码"
    assert prompts[-1][1]["password"] is True

    captured = {}

    def login_mode_ask(prompt, **kwargs):  # type: ignore[no-untyped-def]
        captured.update({"prompt": prompt, **kwargs})
        return kwargs["default"]

    monkeypatch.setattr(main.Prompt, "ask", login_mode_ask)
    assert main._ask_tdc_login_mode() == "1"
    assert captured["default"] == "1"
    assert captured["choices"] == ["0", "1", "2"]


def test_header_cookie_fallback_remains_available(cli, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(main, "_tdc_action_menu", lambda: "1")
    monkeypatch.setattr(main, "_ask_tdc_data_model_filters", lambda: TDCDataModelFilters())
    monkeypatch.setattr(main, "_ask_tdc_login_mode", lambda: "2")
    monkeypatch.setattr(
        main,
        "_ask_tdc_connection",
        lambda page_path: ("https://tdc.example", {"Cookie": "sid=fictional-cookie"}),
    )

    main._run_tdc_report("data_model", False)

    assert FakeTDCAuthClient.calls == []
    init_call = next(item for item in FakeTDCClient.calls if item["method"] == "init")
    assert init_call["session"] is None
    assert init_call["headers"] == {"Cookie": "sid=fictional-cookie"}
    rendered = cli.export_text()
    assert "使用浏览器 Header/Cookie 备用登录方式" in rendered
    assert "fictional-cookie" not in rendered


def test_password_login_error_is_redacted_and_reported(cli, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    FakeTDCAuthClient.fail = TDCAuthError(
        "password=fictional-password-secret token=fictional-token-secret",
        stage="auth-credentials",
    )
    monkeypatch.setattr(main, "_tdc_action_menu", lambda: "1")
    monkeypatch.setattr(main, "_ask_tdc_data_model_filters", lambda: TDCDataModelFilters())
    monkeypatch.setattr(main, "_ask_tdc_login_mode", lambda: "1")
    monkeypatch.setattr(
        main,
        "_ask_tdc_password_connection",
        lambda: ("https://tdc.example", "fictional-user", "fictional-password-secret"),
    )

    main._run_tdc_report("data_model", True)

    rendered = cli.export_text()
    assert "TDCAuthError" in rendered
    assert "fictional-user" not in rendered
    assert "fictional-password-secret" not in rendered
    assert "fictional-token-secret" not in rendered
    assert "[redacted]" in rendered
    assert FakeReport.instances[-1].exceptions


def test_sor_export_summary_distinguishes_part_detail_granularity(cli, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    filters = TDCSORFilters(sor_number="SOR-1")
    monkeypatch.setattr(main, "_tdc_action_menu", lambda: "3")
    monkeypatch.setattr(main, "_ask_tdc_sor_filters", lambda: filters)
    monkeypatch.setattr(main.Prompt, "ask", lambda *args, **kwargs: "safe-export.xlsx")

    main._run_tdc_report("sor", False)

    call = next(item for item in FakeTDCClient.calls if item["method"] == "sor_export")
    assert call["filters"] == filters
    rendered = cli.export_text()
    assert "SOR 官方导出（零件明细粒度）" in rendered
    assert "零件明细" in rendered


def test_detailed_mode_combines_console_and_markdown_hooks_without_secrets(cli, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    FakeTDCClient.emit_debug = True
    monkeypatch.setattr(main, "_tdc_action_menu", lambda: "1")
    monkeypatch.setattr(main, "_ask_tdc_data_model_filters", lambda: TDCDataModelFilters())

    main._run_tdc_report("data_model", True)

    rendered = cli.export_text()
    assert "TDC Debug [abc12345]" in rendered
    assert "request_id" in rendered
    assert "application/json" in rendered
    assert "fictional-cookie" not in rendered
    assert "fictional-set-cookie" not in rendered
    assert "fictional-token" not in rendered
    assert "must-not-render" not in rendered
    assert "[redacted]" in rendered
    report = FakeReport.instances[-1]
    assert report.events
    assert report.kwargs["report_title"] == "TDC CLI Diagnostic Report"
    assert report.kwargs["file_name_prefix"] == "tdc_cli_debug"
    assert report.kwargs["allow_unsafe_raw"] is False
    assert report.kwargs["options"].unsafe_raw is False


def test_cli_error_is_redacted_in_normal_and_detailed_modes(cli, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    FakeTDCClient.fail = TDCCrawlerError(
        "failed Cookie: sid=fictional-cookie Authorization: Bearer fictional-token token=fictional-query-token"
    )
    monkeypatch.setattr(main, "_tdc_action_menu", lambda: "1")
    monkeypatch.setattr(main, "_ask_tdc_data_model_filters", lambda: TDCDataModelFilters())

    main._run_tdc_report("data_model", True)

    rendered = cli.export_text()
    assert "TDCCrawlerError" in rendered
    assert "fictional-cookie" not in rendered
    assert "fictional-token" not in rendered
    assert "fictional-query-token" not in rendered
    assert "[redacted]" in rendered
    assert FakeReport.instances[-1].exceptions


def test_tdc_diagnostic_filename_request_id_pagination_and_aras_compatibility(tmp_path: Path) -> None:
    tdc = MarkdownDiagnosticReport(
        options=DiagnosticOptions(enabled=True),
        base_url="https://tdc.example",
        mode="sor:all",
        output_dir=tmp_path,
        report_title="TDC CLI Diagnostic Report",
        file_name_prefix="tdc_cli_debug",
        allow_unsafe_raw=False,
    )
    tdc.record_http_event(
        TDCHttpDiagnosticEvent(
            timestamp="2026-07-19T10:11:12.123",
            stage="pagination",
            request_id="req12345",
            page_type="sor",
            page=2,
            page_size=50,
            accumulated_count=100,
            unique_count=98,
            duplicate_count=2,
            current_page=2,
            estimated_pages=9,
            stop_reason="continue",
        )
    )
    tdc_path = tdc.save("success")
    assert tdc_path is not None
    assert tdc_path.name.startswith("tdc_cli_debug_")
    text = tdc_path.read_text(encoding="utf-8")
    assert text.startswith("# TDC CLI Diagnostic Report")
    assert "req12345" in text
    assert "Accumulated Count: `100`" in text
    assert "Duplicate Count: `2`" in text
    assert "Stop Reason: `continue`" in text

    aras = MarkdownDiagnosticReport(
        options=DiagnosticOptions(enabled=True),
        base_url="https://aras.example",
        mode="1",
        output_dir=tmp_path,
    )
    aras_path = aras.save("success")
    assert aras_path is not None
    assert aras_path.name.startswith("aras_cli_debug_")
    assert aras_path.read_text(encoding="utf-8").startswith("# Aras CLI Diagnostic Report")


def test_tdc_diagnostics_reject_unsafe_raw(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not allowed"):
        MarkdownDiagnosticReport(
            options=DiagnosticOptions(enabled=True, unsafe_raw=True),
            base_url="https://tdc.example",
            mode="sor",
            output_dir=tmp_path,
            report_title="TDC CLI Diagnostic Report",
            file_name_prefix="tdc_cli_debug",
            allow_unsafe_raw=False,
        )
