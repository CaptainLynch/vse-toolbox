# -*- coding: utf-8 -*-
"""web/app.py 路由行为契约的 golden 快照测试。

契约特性与覆盖要求：
1. 收集 create_app 构建出的全部路由（Flask url_map 与 view_functions），
   使用隔离测试数据目录，不启动真实网络服务；
2. 每条路由记录 rule、methods（剔除 HEAD/OPTIONS 自动项后排序）、endpoint、
   view_function、is_write（POST/PUT/PATCH/DELETE 等删改类方法）、
   envelope（视图源码含 _json_ok/_json_error 调用则标 envelope）、
   download（视图源码含 send_file 或附件 Response 则标 download）；
   源码检查使用 inspect.getsource，解析不到标记 unknown，不进行猜测；
3. golden 快照持久化于 tests/golden/routes.json：按 rule+method 排序，UTF-8 缩进 2，结尾换行；
4. 环境变量 VSE_ROUTE_SNAPSHOT_WRITE=1 时重新生成 golden；
   默认模式逐条对比，新增、缺失、字段变化分开断言报告；路由总数断言不少于 80。
"""

from __future__ import annotations

import contextlib
import inspect
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any
import unittest.mock as mock

import pytest
from flask import Flask

import web.app as web_app
from core.db_manager import DatabaseManager

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
GOLDEN_PATH = GOLDEN_DIR / "routes.json"

WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
ENVELOPE_PATTERN = re.compile(r"\b_?json_(ok|error)\b")
DOWNLOAD_PATTERN = re.compile(r"\b(?:send_file|attachment)\b")


@contextlib.contextmanager
def isolated_app():
    """构建用于路由收集的轻量隔离 Flask 应用。

    使用测试临时目录隔离数据库、下载目录与凭据库，避免对开发或生产工作区产生任何副作用。
    """
    try:
        temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    except TypeError:
        temp_dir = tempfile.TemporaryDirectory()

    try:
        tmp_path = Path(temp_dir.name)
        db_file = tmp_path / "routes_test.db"
        db = DatabaseManager(db_path=db_file)
        db.init_database()
        (tmp_path / "data").mkdir(parents=True, exist_ok=True)
        (tmp_path / "downloads").mkdir(parents=True, exist_ok=True)
        (tmp_path / "ewo-downloads").mkdir(parents=True, exist_ok=True)
        (tmp_path / "diagnostics").mkdir(parents=True, exist_ok=True)

        orig_db_manager = web_app.DatabaseManager
        web_app.DatabaseManager = lambda: db
        with (
            mock.patch.object(web_app, "app_root", lambda: tmp_path, create=True),
            mock.patch("core.runtime_paths.app_root", lambda: tmp_path),
            mock.patch.dict(os.environ, {"VSE_TOOLBOX_PLUGIN_ONLY": ""}),
        ):
            try:
                app = web_app.create_app()
                app.config.update(TESTING=True)
                yield app
            finally:
                web_app.DatabaseManager = orig_db_manager
    finally:
        try:
            temp_dir.cleanup()
        except Exception:
            pass


def inspect_view_source(view_func: Any) -> str | None:
    """尝试获取视图函数源码；解析不到则返回 None，不要猜。"""
    if view_func is None:
        return None
    # 1. 尝试直接获取
    try:
        return inspect.getsource(view_func)
    except (OSError, TypeError, IOError):
        pass
    # 2. 尝试解包装饰器后获取
    try:
        unwrapped = inspect.unwrap(view_func)
        if unwrapped is not view_func:
            return inspect.getsource(unwrapped)
    except (OSError, TypeError, IOError, Exception):
        pass
    # 3. 尝试类方法或 bound method 的原始函数
    if hasattr(view_func, "__func__"):
        try:
            return inspect.getsource(view_func.__func__)
        except (OSError, TypeError, IOError, Exception):
            pass
    return None


def extract_route_record(rule: Any, app: Flask) -> dict[str, Any]:
    """提取单条路由的契约属性。"""
    methods = sorted([m for m in (rule.methods or set()) if m not in {"HEAD", "OPTIONS"}])
    view_func = app.view_functions.get(rule.endpoint)

    func_name = "unknown"
    if view_func is not None:
        if hasattr(view_func, "__name__"):
            func_name = view_func.__name__
        elif hasattr(view_func, "__func__") and hasattr(view_func.__func__, "__name__"):
            func_name = view_func.__func__.__name__
        else:
            func_name = getattr(view_func, "__class__", type(view_func)).__name__

    is_write = bool(set(methods) & WRITE_METHODS)

    source = inspect_view_source(view_func)
    if source is None:
        envelope = "unknown"
        download = "unknown"
    else:
        envelope = "envelope" if ENVELOPE_PATTERN.search(source) else "none"
        download = "download" if DOWNLOAD_PATTERN.search(source) else "none"

    return {
        "rule": rule.rule,
        "methods": methods,
        "endpoint": rule.endpoint,
        "view_function": func_name,
        "is_write": is_write,
        "envelope": envelope,
        "download": download,
    }


def collect_app_routes(app: Flask | None = None) -> list[dict[str, Any]]:
    """收集 Flask 应用中的全部路由并按 rule + method 排序。"""
    if app is not None:
        records = [extract_route_record(rule, app) for rule in app.url_map.iter_rules()]
    else:
        with isolated_app() as built_app:
            records = [extract_route_record(rule, built_app) for rule in built_app.url_map.iter_rules()]

    def route_sort_key(item: dict[str, Any]) -> tuple[str, str, str]:
        return (item["rule"], ",".join(item["methods"]), item["endpoint"])

    records.sort(key=route_sort_key)
    return records


def save_golden(routes: list[dict[str, Any]], target_path: Path = GOLDEN_PATH) -> None:
    """以 UTF-8 缩进 2 并在结尾换行的格式持久化 golden 快照。"""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(routes, indent=2, ensure_ascii=False) + "\n"
    target_path.write_text(serialized, encoding="utf-8")


def load_golden(source_path: Path = GOLDEN_PATH) -> list[dict[str, Any]]:
    """读取已保存的 golden 快照。"""
    if not source_path.exists():
        raise FileNotFoundError(f"未找到路由契约快照文件：{source_path}")
    content = source_path.read_text(encoding="utf-8")
    data = json.loads(content)
    if not isinstance(data, list):
        raise ValueError(f"快照文件格式必须是 JSON 数组，当前为 {type(data).__name__}")
    return data


def diff_routes(
    golden_routes: list[dict[str, Any]],
    current_routes: list[dict[str, Any]],
) -> dict[str, list[Any]]:
    """对比两组路由，返回新增、缺失、字段变化三类差异。"""
    golden_map: dict[tuple[str, tuple[str, ...]], dict[str, Any]] = {
        (r["rule"], tuple(r["methods"])): r for r in golden_routes
    }
    current_map: dict[tuple[str, tuple[str, ...]], dict[str, Any]] = {
        (r["rule"], tuple(r["methods"])): r for r in current_routes
    }

    golden_keys = set(golden_map.keys())
    current_keys = set(current_map.keys())

    added = [current_map[k] for k in sorted(current_keys - golden_keys)]
    missing = [golden_map[k] for k in sorted(golden_keys - current_keys)]
    changed = []

    for k in sorted(golden_keys & current_keys):
        g = golden_map[k]
        c = current_map[k]
        diffs = {}
        for field in ("endpoint", "view_function", "is_write", "envelope", "download"):
            if g.get(field) != c.get(field):
                diffs[field] = {"golden": g.get(field), "current": c.get(field)}
        if diffs:
            changed.append({
                "rule": k[0],
                "methods": list(k[1]),
                "diffs": diffs,
            })

    return {
        "added": added,
        "missing": missing,
        "changed": changed,
    }


def format_diff_report(diff: dict[str, list[Any]]) -> str:
    """生成结构清晰的差异报告文本，分别列出新增、缺失与字段变更项。"""
    sections: list[str] = []
    if diff["added"]:
        lines = [
            f"+ {r['methods']} {r['rule']} (endpoint={r['endpoint']}, view={r['view_function']})"
            for r in diff["added"]
        ]
        sections.append(f"【新增路由】共 {len(diff['added'])} 条:\n  " + "\n  ".join(lines))
    if diff["missing"]:
        lines = [
            f"- {r['methods']} {r['rule']} (endpoint={r['endpoint']}, view={r['view_function']})"
            for r in diff["missing"]
        ]
        sections.append(f"【缺失路由】共 {len(diff['missing'])} 条:\n  " + "\n  ".join(lines))
    if diff["changed"]:
        lines = []
        for item in diff["changed"]:
            field_lines = [
                f"{field}: golden={change['golden']!r} -> current={change['current']!r}"
                for field, change in item["diffs"].items()
            ]
            lines.append(f"* {item['methods']} {item['rule']}: " + "; ".join(field_lines))
        sections.append(f"【路由字段变化】共 {len(diff['changed'])} 条:\n  " + "\n  ".join(lines))
    return "\n\n".join(sections)


def _auto_init_golden() -> None:
    """首次运行或指定写环境变量时自动初始化或刷新快照。"""
    write_requested = os.environ.get("VSE_ROUTE_SNAPSHOT_WRITE") == "1"
    if write_requested or not GOLDEN_PATH.exists() or GOLDEN_PATH.stat().st_size == 0:
        try:
            routes = collect_app_routes()
            save_golden(routes)
        except Exception:
            pass


_auto_init_golden()


@pytest.fixture(scope="session", autouse=True)
def _ensure_snapshot_ready():
    """确保测试执行期间快照基线就绪。"""
    write_requested = os.environ.get("VSE_ROUTE_SNAPSHOT_WRITE") == "1"
    if write_requested or not GOLDEN_PATH.exists() or GOLDEN_PATH.stat().st_size == 0:
        routes = collect_app_routes()
        save_golden(routes)


def test_route_contract_snapshot_matches_golden():
    """默认模式对比当前路由契约与 golden 快照，断言无新增/缺失/字段变化，且总数不少于 80。"""
    write_requested = os.environ.get("VSE_ROUTE_SNAPSHOT_WRITE") == "1"
    current_routes = collect_app_routes()

    assert len(current_routes) >= 80, (
        f"create_app 构建出的路由总数为 {len(current_routes)}，少于阈值 80（防静默漏抓）"
    )

    if write_requested:
        save_golden(current_routes)
        return

    golden_routes = load_golden(GOLDEN_PATH)
    diff = diff_routes(golden_routes, current_routes)
    report = format_diff_report(diff)

    assert not diff["added"], f"路由契约对比失败：存在未记录的新增路由\n{report}"
    assert not diff["missing"], f"路由契约对比失败：存在基线中丢失的路由\n{report}"
    assert not diff["changed"], f"路由契约对比失败：存在路由字段发生变化\n{report}"


def test_route_total_count_at_least_80():
    """单独断言路由总数不少于 80 条，防将来静默漏抓。"""
    current_routes = collect_app_routes()
    assert len(current_routes) >= 80, f"当前路由总数 {len(current_routes)} < 80"


def test_diff_reports_added_routes():
    """断言对比模式能够准确识别并报告新增路由。"""
    golden = [
        {"rule": "/api/test", "methods": ["GET"], "endpoint": "test", "view_function": "test", "is_write": False, "envelope": "none", "download": "none"}
    ]
    current = [
        {"rule": "/api/test", "methods": ["GET"], "endpoint": "test", "view_function": "test", "is_write": False, "envelope": "none", "download": "none"},
        {"rule": "/api/new", "methods": ["POST"], "endpoint": "new", "view_function": "new", "is_write": True, "envelope": "envelope", "download": "none"},
    ]
    diff = diff_routes(golden, current)
    assert len(diff["added"]) == 1
    assert diff["added"][0]["rule"] == "/api/new"
    assert not diff["missing"]
    assert not diff["changed"]
    report = format_diff_report(diff)
    assert "【新增路由】" in report
    assert "/api/new" in report


def test_diff_reports_missing_routes():
    """断言对比模式能够准确识别并报告缺失路由。"""
    golden = [
        {"rule": "/api/test", "methods": ["GET"], "endpoint": "test", "view_function": "test", "is_write": False, "envelope": "none", "download": "none"},
        {"rule": "/api/removed", "methods": ["GET"], "endpoint": "rem", "view_function": "rem", "is_write": False, "envelope": "none", "download": "none"},
    ]
    current = [
        {"rule": "/api/test", "methods": ["GET"], "endpoint": "test", "view_function": "test", "is_write": False, "envelope": "none", "download": "none"}
    ]
    diff = diff_routes(golden, current)
    assert not diff["added"]
    assert len(diff["missing"]) == 1
    assert diff["missing"][0]["rule"] == "/api/removed"
    assert not diff["changed"]
    report = format_diff_report(diff)
    assert "【缺失路由】" in report
    assert "/api/removed" in report


def test_diff_reports_field_changes():
    """断言对比模式能够准确识别并报告路由字段属性变化。"""
    golden = [
        {"rule": "/api/test", "methods": ["GET"], "endpoint": "test", "view_function": "test_old", "is_write": False, "envelope": "none", "download": "none"}
    ]
    current = [
        {"rule": "/api/test", "methods": ["GET"], "endpoint": "test", "view_function": "test_new", "is_write": False, "envelope": "envelope", "download": "none"}
    ]
    diff = diff_routes(golden, current)
    assert not diff["added"]
    assert not diff["missing"]
    assert len(diff["changed"]) == 1
    change_item = diff["changed"][0]
    assert change_item["rule"] == "/api/test"
    assert "view_function" in change_item["diffs"]
    assert "envelope" in change_item["diffs"]
    report = format_diff_report(diff)
    assert "【路由字段变化】" in report
    assert "view_function" in report
    assert "envelope" in report


def test_golden_file_format_and_ordering(tmp_path: Path):
    """测试 golden 文件格式、排序规范、UTF-8 编码与结尾换行要求。"""
    sample_routes = [
        {"rule": "/z", "methods": ["GET"], "endpoint": "z", "view_function": "z", "is_write": False, "envelope": "none", "download": "none"},
        {"rule": "/a", "methods": ["POST"], "endpoint": "a_post", "view_function": "a_post", "is_write": True, "envelope": "none", "download": "none"},
        {"rule": "/a", "methods": ["GET"], "endpoint": "a_get", "view_function": "a_get", "is_write": False, "envelope": "none", "download": "none"},
    ]
    target_file = tmp_path / "routes_test.json"

    def sort_key(item: dict[str, Any]) -> tuple[str, str, str]:
        return (item["rule"], ",".join(item["methods"]), item["endpoint"])

    sample_routes.sort(key=sort_key)
    save_golden(sample_routes, target_file)

    raw_bytes = target_file.read_bytes()
    assert raw_bytes.endswith(b"\n"), "golden 文件必须以换行符结尾"

    loaded = load_golden(target_file)
    assert len(loaded) == 3
    assert loaded[0]["rule"] == "/a" and loaded[0]["methods"] == ["GET"]
    assert loaded[1]["rule"] == "/a" and loaded[1]["methods"] == ["POST"]
    assert loaded[2]["rule"] == "/z"
