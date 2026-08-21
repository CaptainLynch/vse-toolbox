# -*- coding: utf-8 -*-
"""
tests/test_tdc_probe_standalone.py — TDC 数模同步契约探测独立入口与流程测试。

验证清单：
1. tdc_probe_main 独立性：不导入 main 模块。
2. tdc_probe_cli 边界：不导入 core.db_manager。
3. tdc_probe_cli 边界：不导入 core.diagnostics。
4. tdc_probe_cli 边界：不导入 core.config。
5. 根路径解析：使用 _resolve_executable_root() 而非 app_root()，不直接依赖 core.runtime_paths。
6. 爬虫隔离：crawler_factory 接收显式 safe output_dir。
7. 报告路径解析：_resolve_report_dir 返回预期子路径。
8. 离线自检无网络：run_self_test 不发起网络连接且返回 0。
9. 离线自检无持久文件：self-test 结束后临时目录下无残留 .json/.md 文件。
10. 离线自检 COM 清理：pythoncom.CoUninitialize 正确调用。
11. CLI 参数校验：不支持 --username/--password 参数，支持 --self-test 与空参数。
12. 认证方式边界：tdc_probe_cli 不提供 Header/Cookie 交互函数。
13. 用户取消退出码：Confirm.ask 为 False 时 main([]) 返回 0。
14. 认证失败退出码：TDCAuthError 时 main([]) 返回 1。
15. 中断退出码：KeyboardInterrupt 时 main([]) 返回 130。
16. 生产注册表安全性：create_production_registry 保持为空。
"""

from __future__ import annotations

import ast
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

import tdc_probe_cli
import tdc_probe_main
from services.tdc_auth import TDCAuthError, TDCLoginResult
from services.tdc_crawler import TDCDataModelFilters, TDCPagedResult


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
        record_granularity="workflow",
    )


def _sample_rows() -> list[dict[str, Any]]:
    """构造用于契约探测的 fake 数据样本。"""
    return [
        {
            "formId": "FORM-101",
            "incident": "INC-101",
            "documentNo": "DOC-101",
            "approvalStatus": "已通过",
            "currentNode": "节点A",
            "requestDate": "2026-08-10",
            "applicant": "测试员A",
            "projectModel": "M01",
            "partNumber": "P101",
            "modelNumber": "MOD-101",
        },
        {
            "formId": "FORM-102",
            "incident": "INC-102",
            "documentNo": "DOC-102",
            "approvalStatus": "审批中",
            "currentNode": "节点B",
            "requestDate": "2026-08-11",
            "applicant": "测试员B",
            "projectModel": "M01",
            "partNumber": "P102",
            "modelNumber": "MOD-102",
        },
    ]


class FakeTDCPasswordAuthClient:
    """用于独立测试的 fake 账号密码认证客户端。"""

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
        return TDCLoginResult(session="fake-standalone-session", auth_mode="password")


class FakeTDCCrawlerClient:
    """用于独立测试的 fake TDC 爬虫客户端。"""

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
def _reset_standalone_fake_clients() -> None:
    """每个测试前后重置 fake client 的调用记录与状态。"""
    FakeTDCPasswordAuthClient.instances = []
    FakeTDCPasswordAuthClient.fail_with = None
    FakeTDCCrawlerClient.instances = []
    FakeTDCCrawlerClient.fail_with = None
    FakeTDCCrawlerClient.custom_rows = None


@pytest.fixture()
def standalone_console(monkeypatch: pytest.MonkeyPatch) -> Console:
    """提供支持输出捕获的 rich Console。"""
    console = Console(record=True, width=160)
    monkeypatch.setattr(tdc_probe_cli, "console", console)
    return console


# ── 1. tdc_probe_main 独立性 ────────────────────────────────────


def test_tdc_probe_main_does_not_import_main() -> None:
    """1. import tdc_probe_main 正常运行且不导入 main 模块。"""
    res = subprocess.run(
        [sys.executable, "-c", "import tdc_probe_main, sys; assert 'main' not in sys.modules"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"tdc_probe_main imported main: {res.stderr}"

    # 静态 AST 检查
    source = Path(tdc_probe_main.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "main"
        elif isinstance(node, ast.ImportFrom):
            assert node.module != "main"


# ── 2-5. tdc_probe_cli 模块依赖边界 ─────────────────────────────


def test_tdc_probe_cli_does_not_load_db_manager() -> None:
    """2. tdc_probe_cli 源码不直接导入 core.db_manager 且不暴露 DatabaseManager。"""
    assert not hasattr(tdc_probe_cli, "DatabaseManager")

    source = Path(tdc_probe_cli.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "db_manager" not in alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                assert "db_manager" not in node.module


def test_tdc_probe_cli_does_not_load_diagnostics() -> None:
    """3. 导入 tdc_probe_cli 后不加载 core.diagnostics。"""
    res = subprocess.run(
        [
            sys.executable,
            "-c",
            "import tdc_probe_cli, sys; assert 'core.diagnostics' not in sys.modules",
        ],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"tdc_probe_cli loaded core.diagnostics: {res.stderr}"

    source = Path(tdc_probe_cli.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "diagnostics" not in alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                assert "diagnostics" not in node.module


def test_tdc_probe_cli_does_not_load_config() -> None:
    """4. 导入 tdc_probe_cli 后不加载 core.config。"""
    res = subprocess.run(
        [
            sys.executable,
            "-c",
            "import tdc_probe_cli, sys; assert 'core.config' not in sys.modules",
        ],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"tdc_probe_cli loaded core.config: {res.stderr}"

    source = Path(tdc_probe_cli.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "config" not in alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                assert "config" not in node.module


def test_no_app_root_call() -> None:
    """5. tdc_probe_cli 使用 _resolve_executable_root() 而非 app_root()，不直接导入 core.runtime_paths。"""
    assert hasattr(tdc_probe_cli, "_resolve_executable_root")
    assert not hasattr(tdc_probe_cli, "app_root")

    source = Path(tdc_probe_cli.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "runtime_paths" not in alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                assert "runtime_paths" not in node.module
    called_funcs = [
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    assert "app_root" not in called_funcs


# ── 6. 爬虫构造接收显式 output_dir ──────────────────────────────


def test_crawler_gets_explicit_output_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """6. run_probe 执行时向 crawler_factory 显式传递 output_dir 参数。"""
    crawler_init_kwargs: list[dict[str, Any]] = []

    def mock_crawler_factory(*args: Any, **kwargs: Any) -> FakeTDCCrawlerClient:
        crawler_init_kwargs.append(kwargs)
        return FakeTDCCrawlerClient(*args, **kwargs)

    monkeypatch.setattr(tdc_probe_cli.Confirm, "ask", lambda prompt, **kw: "继续" in prompt)
    monkeypatch.setattr(
        tdc_probe_cli,
        "_ask_tdc_data_model_filters",
        lambda: TDCDataModelFilters(serial_number="TEST-001"),
    )
    monkeypatch.setattr(tdc_probe_cli, "_ask_positive_int", lambda prompt, default: default)
    monkeypatch.setattr(
        tdc_probe_cli,
        "_ask_tdc_password_connection",
        lambda: ("https://tdc.fake.test", "probe_user", "probe_pass"),
    )
    monkeypatch.setattr(
        tdc_probe_cli,
        "save_report",
        lambda res, dir_path: (dir_path / "probe.json", dir_path / "probe.md"),
    )

    custom_report_dir = tmp_path / "probe_output"
    exit_code = tdc_probe_cli.run_probe(
        report_dir=custom_report_dir,
        auth_factory=lambda *a, **kw: FakeTDCPasswordAuthClient(*a, **kw),
        crawler_factory=mock_crawler_factory,
    )
    assert exit_code == 0
    assert len(crawler_init_kwargs) == 1
    assert "output_dir" in crawler_init_kwargs[0]
    expected_output_dir = custom_report_dir / "_crawler_output"
    assert crawler_init_kwargs[0]["output_dir"] == expected_output_dir


# ── 7. 报告路径解析 ──────────────────────────────────────────────


def test_report_path_relative_to_exe_dir() -> None:
    """7. _resolve_report_dir(Path('/tmp/fake_exe')) 返回预期路径。"""
    fake_exe = Path("/tmp/fake_exe")
    expected = fake_exe / ".runtime" / "tdc_contract_probe"
    assert tdc_probe_cli._resolve_report_dir(fake_exe) == expected


# ── 8. 离线自检无网络调用 ────────────────────────────────────────


def test_self_test_no_network(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """8. run_self_test(test_dir=tmp_path) 离线运行，不发起任何网络连接，返回 0。"""
    def forbid_connect(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("Network socket connect is forbidden during self-test")

    monkeypatch.setattr(socket.socket, "connect", forbid_connect)
    for mod in tdc_probe_cli._FORBIDDEN_MODULES:
        monkeypatch.delitem(sys.modules, mod, raising=False)

    exit_code = tdc_probe_cli.run_self_test(test_dir=tmp_path)
    assert exit_code == 0


# ── 9. 离线自检无持久文件残留 ────────────────────────────────────


def test_self_test_no_persistent_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """9. run_self_test 结束后 tmp_path 中无 .json / .md 文件残留，写探测文件已被删除。"""
    for mod in tdc_probe_cli._FORBIDDEN_MODULES:
        monkeypatch.delitem(sys.modules, mod, raising=False)

    exit_code = tdc_probe_cli.run_self_test(test_dir=tmp_path)
    assert exit_code == 0

    json_files = list(tmp_path.glob("*.json"))
    md_files = list(tmp_path.glob("*.md"))
    assert json_files == []
    assert md_files == []
    assert not (tmp_path / ".selftest_write_probe").exists()


# ── 10. 离线自检 COM 清理 ────────────────────────────────────────


def test_self_test_com_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """10. self-test 执行后 pythoncom.CoUninitialize 正确调用以释放 COM 资源。"""
    pytest.importorskip("win32com")
    import pythoncom

    uninit_calls: list[bool] = []
    orig_uninit = pythoncom.CoUninitialize

    def mock_uninit() -> None:
        uninit_calls.append(True)
        orig_uninit()

    monkeypatch.setattr(pythoncom, "CoUninitialize", mock_uninit)
    for mod in tdc_probe_cli._FORBIDDEN_MODULES:
        monkeypatch.delitem(sys.modules, mod, raising=False)

    exit_code = tdc_probe_cli.run_self_test(test_dir=tmp_path)
    assert exit_code == 0
    assert len(uninit_calls) >= 1


# ── 11. CLI 参数解析 ────────────────────────────────────────────


def test_cli_no_username_password_args() -> None:
    """11. parse_probe_args 拒绝 --username/--password，支持 --self-test 与空参数。"""
    with pytest.raises(SystemExit) as exc_info1:
        tdc_probe_cli.parse_probe_args(["--username", "test_user"])
    assert exc_info1.value.code == 2

    with pytest.raises(SystemExit) as exc_info2:
        tdc_probe_cli.parse_probe_args(["--password", "test_pass"])
    assert exc_info2.value.code == 2

    args_self_test = tdc_probe_cli.parse_probe_args(["--self-test"])
    assert args_self_test.self_test is True

    args_empty = tdc_probe_cli.parse_probe_args([])
    assert args_empty.self_test is False


# ── 12. 禁用 Header/Cookie ──────────────────────────────────────


def test_header_cookie_unreachable() -> None:
    """12. tdc_probe_cli 模块不提供 _ask_tdc_login_mode 或 _ask_tdc_connection。"""
    assert not hasattr(tdc_probe_cli, "_ask_tdc_login_mode")
    assert not hasattr(tdc_probe_cli, "_ask_tdc_connection")


# ── 13. 用户取消返回 0 ──────────────────────────────────────────


def test_cancel_returns_zero(
    monkeypatch: pytest.MonkeyPatch,
    standalone_console: Console,
) -> None:
    """13. 用户取消探测时 tdc_probe_main.main([]) 返回 0。"""
    monkeypatch.setattr(tdc_probe_cli.Confirm, "ask", lambda *args, **kwargs: False)
    monkeypatch.setattr(tdc_probe_cli, "TDCPasswordAuthClient", FakeTDCPasswordAuthClient)
    monkeypatch.setattr(tdc_probe_cli, "TDCCrawlerClient", FakeTDCCrawlerClient)

    ret = tdc_probe_main.main([])
    assert ret == 0
    assert len(FakeTDCPasswordAuthClient.instances) == 0


# ── 14. 认证失败返回 1 ──────────────────────────────────────────


def test_failure_returns_one(
    monkeypatch: pytest.MonkeyPatch,
    standalone_console: Console,
) -> None:
    """14. 认证失败时 tdc_probe_main.main([]) 返回 1。"""
    FakeTDCPasswordAuthClient.fail_with = TDCAuthError("Probe auth invalid")

    monkeypatch.setattr(
        tdc_probe_cli.Confirm,
        "ask",
        lambda prompt, **kw: "继续" in prompt and "第二次" not in prompt and "分类" not in prompt,
    )
    monkeypatch.setattr(
        tdc_probe_cli,
        "_ask_tdc_data_model_filters",
        lambda: TDCDataModelFilters(serial_number="TEST-FAIL"),
    )
    monkeypatch.setattr(tdc_probe_cli, "_ask_positive_int", lambda prompt, default: default)
    monkeypatch.setattr(
        tdc_probe_cli,
        "_ask_tdc_password_connection",
        lambda: ("https://tdc.fake.test", "user", "pass"),
    )
    monkeypatch.setattr(tdc_probe_cli, "TDCPasswordAuthClient", FakeTDCPasswordAuthClient)
    monkeypatch.setattr(tdc_probe_cli, "TDCCrawlerClient", FakeTDCCrawlerClient)

    ret = tdc_probe_main.main([])
    assert ret == 1


# ── 15. 捕获中断返回 130 ────────────────────────────────────────


def test_keyboard_interrupt_returns_130(
    monkeypatch: pytest.MonkeyPatch,
    standalone_console: Console,
) -> None:
    """15. 流程中抛出 KeyboardInterrupt 时 tdc_probe_main.main([]) 返回 130。"""
    def mock_run_probe(*args: Any, **kwargs: Any) -> int:
        raise KeyboardInterrupt()

    monkeypatch.setattr(tdc_probe_main, "run_probe", mock_run_probe)

    ret = tdc_probe_main.main([])
    assert ret == 130


# ── 16. 生产 ConnectorRegistry 为空 ──────────────────────────────


def test_production_registry_still_empty() -> None:
    """16. 生产 ConnectorRegistry 保持为空，不注册未受控连接器。"""
    from services.project_status_sync_runner import create_production_registry

    reg = create_production_registry()
    assert reg.registered_types == ()
