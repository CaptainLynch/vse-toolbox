# -*- coding: utf-8 -*-
"""Static regression tests for VSE-WebUI WinHTTP COM packaging."""

from __future__ import annotations

import ast
from pathlib import Path


def _spec_path() -> Path:
    return Path(__file__).resolve().parents[1] / "VSE-WebUI.spec"


def _parse_spec() -> ast.Module:
    path = _spec_path()
    assert path.is_file(), f"Spec file not found: {path}"
    return ast.parse(path.read_text(encoding="utf-8"), filename=path.name)


def _string_list(node: ast.AST) -> list[str]:
    if not isinstance(node, ast.List):
        return []
    return [
        item.value
        for item in node.elts
        if isinstance(item, ast.Constant) and isinstance(item.value, str)
    ]


def _hiddenimports(tree: ast.Module) -> list[str]:
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == "hiddenimports" for target in node.targets):
                imports.extend(_string_list(node.value))
        elif isinstance(node, ast.AugAssign):
            if isinstance(node.target, ast.Name) and node.target.id == "hiddenimports":
                imports.extend(_string_list(node.value))
    return imports


def _analysis_excludes(tree: ast.Module) -> list[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Analysis":
            for keyword in node.keywords:
                if keyword.arg == "excludes":
                    return _string_list(keyword.value)
    return []


def _collected_submodules(tree: ast.Module) -> list[str]:
    collected: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "collect_submodules":
            continue
        if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            collected.append(node.args[0].value)
    return collected


def _analysis_datas(tree: ast.Module) -> list[tuple[str, str]]:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != "Analysis":
            continue
        for keyword in node.keywords:
            if keyword.arg != "datas" or not isinstance(keyword.value, ast.List):
                continue
            result: list[tuple[str, str]] = []
            for item in keyword.value.elts:
                if not isinstance(item, ast.Tuple) or len(item.elts) != 2:
                    continue
                if all(isinstance(value, ast.Constant) and isinstance(value.value, str) for value in item.elts):
                    result.append((item.elts[0].value, item.elts[1].value))
            return result
    return []


def test_spec_hiddenimports_include_required_winhttp_modules() -> None:
    explicit_imports = _hiddenimports(_parse_spec())
    required = {
        "pythoncom",
        "pywintypes",
        "win32crypt",
        "win32timezone",
        "win32com.client",
        "win32com.client.gencache",
    }
    assert required <= set(explicit_imports)
    assert {"tkinter", "tkinter.filedialog"} <= set(explicit_imports)


def test_spec_excludes_xlwings_and_preserves_pywin32() -> None:
    excludes = set(_analysis_excludes(_parse_spec()))
    assert "xlwings" in excludes
    assert not {"pythoncom", "pywintypes", "win32com"} & excludes


def test_spec_does_not_collect_all_win32com_or_xlwings() -> None:
    collected = set(_collected_submodules(_parse_spec()))
    assert "win32com" not in collected
    assert "xlwings" not in collected


def test_spec_packages_report_contract_data() -> None:
    datas = set(_analysis_datas(_parse_spec()))
    assert ("core/report_headers.json", "core") in datas
