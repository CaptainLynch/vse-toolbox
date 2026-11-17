# -*- coding: utf-8 -*-
"""Excel 本机运行环境检测测试。

验证契约 docs/refactor-v2/CONTRACTS.md C10 与 W12-01 规格：
1. 注册表与进程枚举全 mock，绝不触碰真实 Windows 注册表和系统进程；
2. 覆盖已装（注册表/默认路径探测成功）；
3. 覆盖未装（无注册表且无默认路径）；
4. 覆盖激活状态在无法可靠确认时，绝不伪报通过，严格返回 {'state': 'need_check', 'text': '需要检查'}；
5. 覆盖残留进程检测：严格区分本工具所有的残留进程与用户自行打开的 Excel 进程，用户自开的 Excel 绝不纳入；
6. 字段白名单与脱敏验证；
7. 用户可见文案通俗中文，无违禁内部术语。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import services.excel_env_check as env_module
from services.excel_env_check import (
    check_excel_activation,
    check_excel_environment,
    detect_excel_installation,
    find_residual_excel_processes,
)

FORBIDDEN_TERMS = ["JSON", "Base URL", "Worker", "快照", "取证", "代码路径", "文件路径"]


def _assert_no_internal_terms(obj: Any) -> None:
    """递归断言字典/列表/字符串中不包含违禁内部术语。"""
    if isinstance(obj, str):
        for term in FORBIDDEN_TERMS:
            assert term not in obj, f"用户可见文案中出现了违禁术语: {term}"
    elif isinstance(obj, dict):
        for k, v in obj.items():
            _assert_no_internal_terms(v)
    elif isinstance(obj, list):
        for item in obj:
            _assert_no_internal_terms(item)


# ── 1. 已安装检测（注册表与路径）─────────────────────────────────


def test_excel_installed_via_registry() -> None:
    """通过注册表成功探测到 Excel 安装路径与版本。"""
    fake_exe = r"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE"

    def mock_registry() -> tuple[str | None, str | None]:
        return fake_exe, "16.0"

    installed, path, version = detect_excel_installation(
        registry_prober=mock_registry,
        path_prober=lambda: None,
    )
    assert installed is True
    assert path == fake_exe
    assert version == "16.0"


def test_excel_installed_via_fallback_path() -> None:
    """注册表缺失时，通过常见路径成功探测到安装位置。"""
    fake_exe = r"C:\Program Files (x86)\Microsoft Office\Office15\EXCEL.EXE"

    def mock_registry() -> tuple[str | None, str | None]:
        return None, None

    def mock_path() -> str | None:
        return fake_exe

    installed, path, version = detect_excel_installation(
        registry_prober=mock_registry,
        path_prober=mock_path,
    )
    assert installed is True
    assert path == fake_exe
    assert version == "15.0"


# ── 2. 未安装检测 ─────────────────────────────────────────────────


def test_excel_not_installed() -> None:
    """注册表与默认路径均未检测到，返回未安装状态。"""

    def mock_registry() -> tuple[str | None, str | None]:
        return None, None

    def mock_path() -> str | None:
        return None

    res = check_excel_environment(
        registry_prober=mock_registry,
        path_prober=mock_path,
        process_lister=lambda: [],
    )

    assert res["installed"] is False
    assert res["install_state"] == "not_installed"
    assert res["excel_path"] is None
    assert res["version"] is None
    # 未安装时激活状态必然落入 need_check
    assert res["activation"]["state"] == "need_check"
    assert res["activation"]["text"] == "需要检查"
    _assert_no_internal_terms(res)


# ── 3. 激活状态「需要检查」与不可靠判定 ───────────────────────────


def test_activation_unreliable_or_unknown_returns_need_check() -> None:
    """验收标准：激活状态在无法确认时返回「需要检查」，不得返回通过。"""
    # 模拟 1：探测器抛出异常
    def prober_raise(**kwargs: Any) -> Any:
        raise RuntimeError("Probe execution timed out")

    act1 = check_excel_activation(excel_path="fake", activation_prober=prober_raise)
    assert act1["state"] == "need_check"
    assert act1["text"] == "需要检查"
    assert act1["state"] != "activated"

    # 模拟 2：探测器返回不确定结果字典
    def prober_ambiguous(**kwargs: Any) -> Any:
        return {"state": "need_check", "detail": "许可证状态未在明确列表中"}

    act2 = check_excel_activation(excel_path="fake", activation_prober=prober_ambiguous)
    assert act2["state"] == "need_check"
    assert act2["text"] == "需要检查"
    assert act2["state"] != "activated"

    # 模拟 3：探测器返回 None
    def prober_none(**kwargs: Any) -> Any:
        return None

    act3 = check_excel_activation(excel_path="fake", activation_prober=prober_none)
    assert act3["state"] == "need_check"
    assert act3["text"] == "需要检查"
    assert act3["state"] != "activated"

    _assert_no_internal_terms(act1)
    _assert_no_internal_terms(act2)
    _assert_no_internal_terms(act3)


def test_activation_reliably_confirmed_states() -> None:
    """当探测器能够明确确认授权时，返回相应确定的状态。"""
    # 明确已授权
    act_ok = check_excel_activation(
        excel_path="fake",
        activation_prober=lambda **kw: {"state": "activated", "text": "已激活"},
    )
    assert act_ok["state"] == "activated"
    assert act_ok["text"] == "已激活"

    # 明确未授权
    act_unlic = check_excel_activation(
        excel_path="fake",
        activation_prober=lambda **kw: {"state": "unlicensed", "text": "未激活"},
    )
    assert act_unlic["state"] == "unlicensed"
    assert act_unlic["text"] == "未激活"


# ── 4. 残留进程检测（区分本工具与用户自开）─────────────────────────


def test_residual_processes_excludes_user_excel_and_includes_own() -> None:
    """验收标准：残留进程检测不得包含用户自开的 Excel（mock 覆盖这一区分）。"""
    app_exe = r"E:\project\vse-toolbox\vse-toolbox.exe"

    mock_processes = [
        # 1. 用户自行打开的 Excel 进程（普通编辑表格），绝不包含本工具路径
        {
            "pid": 1001,
            "name": "EXCEL.EXE",
            "command_line": r'"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE" "C:\Users\User\Documents\my_report.xlsx"',
        },
        # 2. 用户无参数单开的 Excel 进程
        {
            "pid": 1002,
            "name": "excel.exe",
            "command_line": r'"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE"',
        },
        # 3. 属于本工具调起的残留 Excel 进程（命令行包含本工具 exe 路径）
        {
            "pid": 2001,
            "name": "EXCEL.EXE",
            "command_line": r'"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE" /automation "E:\project\vse-toolbox\vse-toolbox.exe"',
        },
        # 4. 属于本工具调起的另一残留 Excel 进程（斜杠风格不同）
        {
            "pid": 2002,
            "name": "excel.exe",
            "command_line": r'"C:/Office/EXCEL.EXE" -r "E:/project/vse-toolbox/vse-toolbox.exe"',
        },
        # 5. 其他非 Excel 进程
        {
            "pid": 3001,
            "name": "chrome.exe",
            "command_line": r'"C:\Program Files\Chrome\chrome.exe" "E:\project\vse-toolbox\vse-toolbox.exe"',
        },
    ]

    residuals = find_residual_excel_processes(
        app_exe=app_exe,
        process_lister=lambda: mock_processes,
    )

    residual_pids = [p["pid"] for p in residuals]

    # 必须匹配到属于本工具的进程 2001 和 2002
    assert 2001 in residual_pids
    assert 2002 in residual_pids
    assert len(residuals) == 2

    # 核心约束：绝不把用户自开的 Excel 算进去！
    assert 1001 not in residual_pids
    assert 1002 not in residual_pids
    assert 3001 not in residual_pids

    _assert_no_internal_terms(residuals)


# ── 5. 全流程 check_excel_environment 与字段白名单 ───────────────


def test_check_excel_environment_full_contract_and_whitelist() -> None:
    """检验完整输出字典严格遵循字段白名单，并且所有字段均安全脱敏。"""
    app_exe = r"C:\Toolbox\vse-toolbox.exe"
    excel_exe = r"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE"

    mock_procs = [
        {
            "pid": 9999,
            "name": "EXCEL.EXE",
            "command_line": f'"{excel_exe}" /caller "{app_exe}"',
        }
    ]

    res = check_excel_environment(
        app_exe=app_exe,
        registry_prober=lambda: (excel_exe, "16.0"),
        path_prober=lambda: None,
        activation_prober=lambda **kw: {"state": "need_check", "text": "需要检查"},
        process_lister=lambda: mock_procs,
    )

    # 1. 字段白名单严格比对
    expected_keys = {
        "installed",
        "install_state",
        "excel_path",
        "version",
        "activation",
        "residual_processes",
        "residual_count",
    }
    assert set(res.keys()) == expected_keys

    assert res["installed"] is True
    assert res["install_state"] == "installed"
    assert res["excel_path"] == excel_exe
    assert res["version"] == "16.0"
    assert res["activation"]["state"] == "need_check"
    assert res["activation"]["text"] == "需要检查"
    assert res["residual_count"] == 1
    assert res["residual_processes"][0]["pid"] == 9999

    # 2. 违禁内部术语检查
    _assert_no_internal_terms(res)
