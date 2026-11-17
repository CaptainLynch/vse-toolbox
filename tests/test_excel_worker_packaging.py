# -*- coding: utf-8 -*-
"""Static packaging specification tests for Excel Worker and WebUI."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _read_spec(filename: str) -> str:
    spec_path = _repo_root() / filename
    assert spec_path.exists(), f"Spec file not found: {spec_path}"
    assert spec_path.is_file(), f"Spec path is not a file: {spec_path}"
    return spec_path.read_text(encoding="utf-8")


def _get_analysis_excludes(content: str) -> list[str]:
    tree = ast.parse(content)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Analysis":
            for kw in node.keywords:
                if kw.arg == "excludes" and isinstance(kw.value, ast.List):
                    return [elt.value for elt in kw.value.elts if isinstance(elt, ast.Constant)]
    return []


def _get_hiddenimports_literals(content: str) -> list[str]:
    tree = ast.parse(content)
    literals: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            target_names = [t.id for t in targets if isinstance(t, ast.Name)]
            if "hiddenimports" in target_names:
                val = node.value
                if isinstance(val, ast.List):
                    for elt in val.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            literals.append(elt.value)
                elif isinstance(val, ast.Call):
                    for arg in val.args:
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            literals.append(arg.value)
    return literals


def test_spec_files_exist() -> None:
    root = _repo_root()
    webui_spec = root / "VSE-WebUI.spec"
    assert webui_spec.is_file(), "VSE-WebUI.spec must exist"
    # VSE-ExcelWorker.spec 保留在仓库供开发机单独构建 Worker；它已不在发布链路
    # （单 exe 部署，2026-10-09 顾问复核方案 A），因此不再强制其存在。


def test_webui_spec_collects_excel_com_for_single_exe() -> None:
    """单 exe 部署：宿主同时承担 Excel Worker，必须收进 xlwings 与 win32com。"""
    content = _read_spec("VSE-WebUI.spec")
    assert "webui.py" in content
    assert "name='VSE-WebUI'" in content or 'name="VSE-WebUI"' in content

    assert "collect_submodules('win32com')" in content or 'collect_submodules("win32com")' in content
    assert "collect_submodules('xlwings')" in content or 'collect_submodules("xlwings")' in content

    hidden_imports = _get_hiddenimports_literals(content)
    for item in ("pythoncom", "pywintypes", "win32com.client", "excel_worker_cli"):
        assert item in hidden_imports, (
            f"VSE-WebUI.spec must include {item} in hiddenimports, found: {hidden_imports!r}"
        )

    # xlwings 不能再被排除，否则 collect_submodules 的收集会被 excludes 覆盖。
    excludes = _get_analysis_excludes(content)
    assert "xlwings" not in excludes, (
        f"VSE-WebUI.spec must not exclude 'xlwings' in single-exe mode, found: {excludes!r}"
    )
    # CLI-only 集成仍应排除（它们不在 Worker 导入闭包内）。
    for mod in ("selenium", "services.office_toolbox", "services.feishu_imap"):
        assert mod in excludes, f"VSE-WebUI.spec should still exclude {mod!r}"


def test_worker_spec_stays_a_subset_of_host_spec() -> None:
    """防漂移：保留的 Worker spec 的 COM 依赖不得超出宿主已收集的范围。

    两个 spec 曾各自维护依赖清单；单 exe 后宿主是唯一发布产物，Worker spec 若
    需要额外依赖，说明合包漏收了模块——此断言把漂移变成红灯。
    """
    root = _repo_root()
    worker_spec = root / "VSE-ExcelWorker.spec"
    if not worker_spec.is_file():
        pytest.skip("VSE-ExcelWorker.spec removed (single-exe only)")

    host_hidden = set(_get_hiddenimports_literals(_read_spec("VSE-WebUI.spec")))
    worker_hidden = set(_get_hiddenimports_literals(_read_spec("VSE-ExcelWorker.spec")))
    # rich 是 Worker spec 的历史残留（worker 导入闭包内无 rich 导入）。
    worker_hidden -= {"rich"}
    missing = sorted(item for item in worker_hidden if item not in host_hidden)
    assert not missing, f"VSE-WebUI.spec 缺少 Worker 依赖: {missing!r}"


def test_build_script_does_not_build_a_sibling_worker() -> None:
    """单 exe：构建脚本只建宿主，并断言产物目录不存在 VSE-ExcelWorker.exe。"""
    script = (_repo_root() / "tools" / "build_excel_bundle.ps1").read_text(encoding="utf-8")
    assert "VSE-ExcelWorker.spec" not in script
    assert "VSE-ExcelWorker.exe" in script  # 仍要显式断言其不存在
    assert "must not exist in the single-executable bundle" in script


def test_excel_worker_spec_includes_excel_com() -> None:
    content = _read_spec("VSE-ExcelWorker.spec")
    assert "tools\\\\excel_worker_cli.py" in content or "tools/excel_worker_cli.py" in content
    assert "name='VSE-ExcelWorker'" in content or 'name="VSE-ExcelWorker"' in content
    assert "console=True" in content
    assert "console=False" not in content
    assert "datas=[]" in content

    # Worker must include COM and xlwings dependencies
    hidden_imports = _get_hiddenimports_literals(content)
    required_hidden = ["pythoncom", "pywintypes", "win32com", "xlwings"]
    for item in required_hidden:
        assert item in hidden_imports, (
            f"VSE-ExcelWorker.spec must include {item} in hiddenimports, found: {hidden_imports!r}"
        )

    # Worker spec should exclude heavy web/UI modules
    excludes = _get_analysis_excludes(content)
    worker_excludes = ["flask", "selenium", "web"]
    for mod in worker_excludes:
        assert mod in excludes, (
            f"VSE-ExcelWorker.spec should exclude {mod!r}, found: {excludes!r}"
        )
