# -*- coding: utf-8 -*-
"""
tests/test_tdc_probe_packaging.py — TDC 数模同步契约探测 PyInstaller 打包规格静态测试。

验证清单：
1. spec 文件存在：VSE-TDC-Probe.spec 位于项目根目录。
2. 打包入口正确：entry 为 tdc_probe_main.py。
3. 明确排除非必需/禁止模块：excludes 包含 main, core.db_manager, flask, sqlite3, xlwings, selenium, services.project_status_*, web 等。
4. 控制台应用模式：console=True 且不包含 console=False。
5. 禁用 UPX 压缩：upx=False（避免部分杀毒软件误报）。
6. 无数据文件打包：datas=[]（不打包 web 模板、DB、HAR 或凭据文件）。
"""

from __future__ import annotations

from pathlib import Path


def _get_spec_path() -> Path:
    """获取项目根目录下的 VSE-TDC-Probe.spec 文件路径。"""
    repo_root = Path(__file__).resolve().parent.parent
    return repo_root / "VSE-TDC-Probe.spec"


def _read_spec_content() -> str:
    """读取 VSE-TDC-Probe.spec 的文本内容。"""
    spec_path = _get_spec_path()
    assert spec_path.exists(), f"Spec file not found at {spec_path}"
    return spec_path.read_text(encoding="utf-8")


def test_spec_file_exists() -> None:
    """1. VSE-TDC-Probe.spec 文件存在。"""
    spec_path = _get_spec_path()
    assert spec_path.exists()
    assert spec_path.is_file()


def test_spec_entry_is_tdc_probe_main() -> None:
    """2. 打包规格的入口文件为 tdc_probe_main.py。"""
    content = _read_spec_content()
    assert "tdc_probe_main.py" in content


def test_spec_excludes_forbidden_modules() -> None:
    """3. 打包规格明确排除了禁止模块与重型依赖。"""
    content = _read_spec_content()
    required_excludes = [
        "main",
        "core.db_manager",
        "flask",
        "sqlite3",
        "xlwings",
        "selenium",
        "services.project_status_updates",
        "services.project_status_sync_runner",
        "web",
    ]
    for mod in required_excludes:
        assert f'"{mod}"' in content or f"'{mod}'" in content, (
            f"Expected excluded module {mod!r} in VSE-TDC-Probe.spec"
        )


def test_spec_onefile_console() -> None:
    """4. 打包规格配置为 console=True 且不包含 console=False。"""
    content = _read_spec_content()
    assert "console=True" in content
    assert "console=False" not in content


def test_spec_no_upx() -> None:
    """5. 打包规格禁用 UPX 压缩 (upx=False)。"""
    content = _read_spec_content()
    assert "upx=False" in content


def test_spec_no_data_files() -> None:
    """6. 打包规格 datas 为空列表 (datas=[])，不打包任何数据或模板文件。"""
    content = _read_spec_content()
    assert "datas=[]" in content
