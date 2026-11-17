# -*- coding: utf-8 -*-
"""Excel 路径安全校验单元测试。

验证契约 docs/refactor-v2/CONTRACTS.md C10 Excel 部分：
1. 目录穿越（.. 段）拒绝，至少 2 例；
2. UNC 路径（\\\\ 开头）拒绝，至少 2 例；
3. ADS 备用数据流（含冒号的流名）拒绝，至少 2 例；
4. 符号链接/junction/重解析点越界与白名单根内路径替换拒绝，至少 2 例；
5. 正常安全路径通过，至少 2 例；
6. 多白名单根检验 validate_excel_paths 测试；
7. 全部使用合成数据（tmp_path），不触碰真实系统白名单；
8. 错误提示信息面向用户通俗中文，无违禁内部术语。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from services.excel_path_safety import (
    ExcelPathSafetyError,
    validate_excel_path,
    validate_excel_paths,
)

FORBIDDEN_TERMS = ["JSON", "Base URL", "Worker", "快照", "取证", "代码路径", "文件路径"]


def _assert_no_internal_terms(msg: str) -> None:
    """断言面向用户的提示文案中绝不包含内部违禁术语。"""
    for term in FORBIDDEN_TERMS:
        assert term not in msg, f"用户可见文案中出现了违禁术语: {term}"


# ── 1. 目录穿越（.. 段）拒绝 ───────────────────────────────────────


def test_directory_traversal_simple_parent_rejected(tmp_path: Path) -> None:
    """用例 1.1：直接跨级向上一层目录（../outside.xlsx）。"""
    root = tmp_path / "sandbox_root"
    root.mkdir()

    with pytest.raises(ExcelPathSafetyError) as exc_info:
        validate_excel_path(root, "../outside.xlsx")

    msg = str(exc_info.value)
    assert "上级目录" in msg or "穿越" in msg or ".." in msg
    _assert_no_internal_terms(msg)


def test_directory_traversal_nested_parent_rejected(tmp_path: Path) -> None:
    """用例 1.2：在子目录中通过连续 .. 穿越出安全目录（sub/../../escape.xlsx）。"""
    root = tmp_path / "sandbox_root"
    root.mkdir()

    with pytest.raises(ExcelPathSafetyError) as exc_info:
        validate_excel_path(root, "sub/../../escape.xlsx")

    msg = str(exc_info.value)
    assert "上级目录" in msg or "穿越" in msg or ".." in msg
    _assert_no_internal_terms(msg)


def test_directory_traversal_backslash_rejected(tmp_path: Path) -> None:
    """用例 1.3：Windows 风格反斜杠穿越（sub\\..\\outside.xlsx）。"""
    root = tmp_path / "sandbox_root"
    root.mkdir()

    with pytest.raises(ExcelPathSafetyError) as exc_info:
        validate_excel_path(root, r"sub\..\outside.xlsx")

    msg = str(exc_info.value)
    assert "上级目录" in msg or "穿越" in msg or ".." in msg
    _assert_no_internal_terms(msg)


# ── 2. UNC 网络共享路径拒绝 ─────────────────────────────────────────


def test_unc_path_standard_double_backslash_rejected(tmp_path: Path) -> None:
    """用例 2.1：标准 Windows UNC 共享路径（\\\\server\\share\\data.xlsx）。"""
    root = tmp_path / "sandbox_root"
    root.mkdir()

    with pytest.raises(ExcelPathSafetyError) as exc_info:
        validate_excel_path(root, r"\\192.168.1.100\share\data.xlsx")

    msg = str(exc_info.value)
    assert "网络共享" in msg or "UNC" in msg
    _assert_no_internal_terms(msg)


def test_unc_path_forward_slash_rejected(tmp_path: Path) -> None:
    """用例 2.2：正斜杠 UNC 变体（//nas/storage/data.xlsx）。"""
    root = tmp_path / "sandbox_root"
    root.mkdir()

    with pytest.raises(ExcelPathSafetyError) as exc_info:
        validate_excel_path(root, "//nas/storage/data.xlsx")

    msg = str(exc_info.value)
    assert "网络共享" in msg or "UNC" in msg
    _assert_no_internal_terms(msg)


def test_unc_path_mixed_slash_rejected(tmp_path: Path) -> None:
    """用例 2.3：混合斜杠 UNC 变体（\\/host/share/data.xlsx）。"""
    root = tmp_path / "sandbox_root"
    root.mkdir()

    with pytest.raises(ExcelPathSafetyError) as exc_info:
        validate_excel_path(root, r"\/host/share/data.xlsx")

    msg = str(exc_info.value)
    assert "网络共享" in msg or "UNC" in msg
    _assert_no_internal_terms(msg)


# ── 3. NTFS ADS 备用数据流拒绝 ─────────────────────────────────────


def test_ads_stream_simple_colon_rejected(tmp_path: Path) -> None:
    """用例 3.1：相对文件名携带 ADS 流名称（data.xlsx:hidden_stream）。"""
    root = tmp_path / "sandbox_root"
    root.mkdir()

    with pytest.raises(ExcelPathSafetyError) as exc_info:
        validate_excel_path(root, "data.xlsx:hidden_stream")

    msg = str(exc_info.value)
    assert "附加数据流" in msg or "ADS" in msg
    _assert_no_internal_terms(msg)


def test_ads_stream_with_data_descriptor_rejected(tmp_path: Path) -> None:
    """用例 3.2：带 $DATA 描述符的 ADS 路径（sub/book.xlsx:stream:$DATA）。"""
    root = tmp_path / "sandbox_root"
    root.mkdir()

    with pytest.raises(ExcelPathSafetyError) as exc_info:
        validate_excel_path(root, "sub/book.xlsx:stream:$DATA")

    msg = str(exc_info.value)
    assert "附加数据流" in msg or "ADS" in msg
    _assert_no_internal_terms(msg)


def test_ads_stream_on_drive_path_rejected(tmp_path: Path) -> None:
    """用例 3.3：带盘符路径中的附加流（C:\\safe\\file.xlsx:evil）。"""
    root = tmp_path / "sandbox_root"
    root.mkdir()

    with pytest.raises(ExcelPathSafetyError) as exc_info:
        validate_excel_path(root, r"C:\safe\file.xlsx:evil")

    msg = str(exc_info.value)
    assert "附加数据流" in msg or "ADS" in msg
    _assert_no_internal_terms(msg)


# ── 4. 越界与白名单根内路径替换拒绝 ────────────────────────────────


def test_out_of_bounds_absolute_path_outside_root(tmp_path: Path) -> None:
    """用例 4.1：绝对路径直接指向完全在根之外的目录。"""
    root = tmp_path / "allowed_root"
    root.mkdir()
    outside_dir = tmp_path / "forbidden_root"
    outside_dir.mkdir()
    outside_file = outside_dir / "secret.xlsx"

    with pytest.raises(ExcelPathSafetyError) as exc_info:
        validate_excel_path(root, str(outside_file))

    msg = str(exc_info.value)
    assert "超出" in msg or "范围" in msg
    _assert_no_internal_terms(msg)


def test_out_of_bounds_path_replacement_drive_root(tmp_path: Path) -> None:
    """用例 4.2：通过前置斜杠触发盘符根替换（/forbidden/file.xlsx）。"""
    root = tmp_path / "allowed_root"
    root.mkdir()

    with pytest.raises(ExcelPathSafetyError) as exc_info:
        validate_excel_path(root, "/forbidden_global/file.xlsx")

    msg = str(exc_info.value)
    assert "超出" in msg or "范围" in msg
    _assert_no_internal_terms(msg)


def test_out_of_bounds_symlink_or_junction_escaping_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """用例 4.3：白名单根内部的符号链接/重解析点指向了外部目录，解析后越界。"""
    root = tmp_path / "allowed_root"
    root.mkdir()
    outside_dir = tmp_path / "secret_zone"
    outside_dir.mkdir()
    (outside_dir / "target.xlsx").write_bytes(b"payload")

    # 优先尝试创建真实符号链接
    link_created = False
    link_dir = root / "symlink_out"
    try:
        link_dir.symlink_to(outside_dir, target_is_directory=True)
        link_created = True
    except OSError:
        pass

    if link_created:
        with pytest.raises(ExcelPathSafetyError) as exc_info:
            validate_excel_path(root, "symlink_out/target.xlsx")
        msg = str(exc_info.value)
        assert "超出" in msg or "范围" in msg
        _assert_no_internal_terms(msg)
    else:
        # 当 Windows 本机无创建符号链接权限时，对 resolve 行为进行模拟
        orig_resolve = Path.resolve

        def fake_resolve(self: Path, strict: bool = False) -> Path:
            resolved = orig_resolve(self, strict=strict)
            if "symlink_out" in resolved.parts:
                return outside_dir / "target.xlsx"
            return resolved

        monkeypatch.setattr(Path, "resolve", fake_resolve)
        with pytest.raises(ExcelPathSafetyError) as exc_info:
            validate_excel_path(root, "symlink_out/target.xlsx")
        msg = str(exc_info.value)
        assert "超出" in msg or "范围" in msg
        _assert_no_internal_terms(msg)


def test_out_of_bounds_prefix_collision_rejected(tmp_path: Path) -> None:
    """用例 4.4：目录名同名前缀攻击（如 root 为 allowed，目标在 allowed_evil 中）。"""
    base = tmp_path / "sandbox"
    base.mkdir()
    allowed_root = base / "allowed"
    allowed_root.mkdir()
    evil_root = base / "allowed_evil"
    evil_root.mkdir()
    target_file = evil_root / "test.xlsx"

    with pytest.raises(ExcelPathSafetyError) as exc_info:
        validate_excel_path(allowed_root, str(target_file))

    msg = str(exc_info.value)
    assert "超出" in msg or "范围" in msg
    _assert_no_internal_terms(msg)


# ── 5. 正常安全路径通过 ─────────────────────────────────────────────


def test_normal_path_simple_relative(tmp_path: Path) -> None:
    """用例 5.1：白名单根目录下的简单相对路径。"""
    root = tmp_path / "sandbox_root"
    root.mkdir()

    resolved = validate_excel_path(root, "report.xlsx")
    expected = (root / "report.xlsx").resolve()
    assert resolved == expected


def test_normal_path_nested_relative(tmp_path: Path) -> None:
    """用例 5.2：白名单根目录下的嵌套子目录相对路径。"""
    root = tmp_path / "sandbox_root"
    root.mkdir()
    sub_dir = root / "data" / "2026"
    sub_dir.mkdir(parents=True)

    resolved = validate_excel_path(root, "data/2026/quarterly.xlsx")
    expected = (sub_dir / "quarterly.xlsx").resolve()
    assert resolved == expected


def test_normal_path_absolute_within_root(tmp_path: Path) -> None:
    """用例 5.3：用户提供合法的绝对路径且该路径完全落在白名单根内部。"""
    root = tmp_path / "sandbox_root"
    root.mkdir()
    target = root / "valid.xlsx"
    target.write_bytes(b"dummy")

    resolved = validate_excel_path(root, str(target))
    assert resolved == target.resolve()


# ── 6. 多白名单根检验 validate_excel_paths ─────────────────────────


def test_multiple_roots_validation_success_and_fail(tmp_path: Path) -> None:
    """多白名单根选择：匹配 root1、匹配 root2，以及不在任何白名单根内。"""
    root1 = tmp_path / "root1"
    root1.mkdir()
    root2 = tmp_path / "root2"
    root2.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    # 1. 位于 root1 的绝对路径
    path1 = root1 / "file1.xlsx"
    assert validate_excel_paths([root1, root2], str(path1)) == path1.resolve()

    # 2. 位于 root2 的绝对路径
    path2 = root2 / "file2.xlsx"
    assert validate_excel_paths([root1, root2], str(path2)) == path2.resolve()

    # 3. 根外绝对路径拒绝
    path_out = outside / "secret.xlsx"
    with pytest.raises(ExcelPathSafetyError) as exc_info:
        validate_excel_paths([root1, root2], str(path_out))
    assert "不在任何允许的安全目录范围" in str(exc_info.value)
    _assert_no_internal_terms(str(exc_info.value))

    # 4. 相对路径且已存在于 root2
    existing_in_2 = root2 / "target.xlsx"
    existing_in_2.write_bytes(b"data")
    assert validate_excel_paths([root1, root2], "target.xlsx") == existing_in_2.resolve()

    # 5. 空白名单根抛错
    with pytest.raises(ExcelPathSafetyError):
        validate_excel_paths([], "file.xlsx")


def test_empty_and_null_byte_inputs_rejected(tmp_path: Path) -> None:
    """空路径与含空字符的非法输入拒绝。"""
    root = tmp_path / "sandbox"
    root.mkdir()

    with pytest.raises(ExcelPathSafetyError):
        validate_excel_path(root, "")

    with pytest.raises(ExcelPathSafetyError):
        validate_excel_path(root, "   ")

    with pytest.raises(ExcelPathSafetyError):
        validate_excel_path(root, "file\x00.xlsx")
