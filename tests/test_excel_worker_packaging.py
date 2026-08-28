# -*- coding: utf-8 -*-
"""Static packaging specification tests for Excel Worker and WebUI."""

from __future__ import annotations

import ast
from pathlib import Path


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
    worker_spec = root / "VSE-ExcelWorker.spec"
    assert webui_spec.is_file(), "VSE-WebUI.spec must exist"
    assert worker_spec.is_file(), "VSE-ExcelWorker.spec must exist"


def test_webui_spec_excludes_excel_com() -> None:
    content = _read_spec("VSE-WebUI.spec")
    assert "web\\\\app.py" in content or "web/app.py" in content
    assert "name='VSE-WebUI'" in content or 'name="VSE-WebUI"' in content

    # Flask WebUI must not collect win32com or xlwings submodules
    assert "collect_submodules('win32com')" not in content
    assert 'collect_submodules("win32com")' not in content
    assert "collect_submodules('xlwings')" not in content
    assert 'collect_submodules("xlwings")' not in content

    # Hiddenimports must not pull in Excel automation (xlwings). WinHTTP COM
    # modules (pythoncom/pywintypes/win32com.client) ARE allowed and required,
    # because services/windows_http.py drives WinHttp.WinHttpRequest.5.1 via COM.
    hidden_imports = _get_hiddenimports_literals(content)
    forbidden_com = {
        "xlwings",
    }
    for item in hidden_imports:
        assert item not in forbidden_com, (
            f"VSE-WebUI.spec must not include {item} in hiddenimports"
        )

    # xlwings (Excel automation) must stay excluded; WinHTTP COM modules are
    # intentionally no longer excluded so the WebUI auth stack can dispatch
    # WinHttp.WinHttpRequest.5.1.
    excludes = _get_analysis_excludes(content)
    required_excludes = ["xlwings"]
    for mod in required_excludes:
        assert mod in excludes, (
            f"VSE-WebUI.spec must exclude {mod!r}, found: {excludes!r}"
        )


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
