# -*- coding: utf-8 -*-
"""构建输出隔离：build_v2_test_install 的输出根可配置，旧包清理失败不静默。

覆盖：
    * 默认输出根仍是仓库内 ``dist/v2-test``（只断言解析结果，不写 dist）；
    * ``--out`` / ``VSE_TEST_INSTALL_ROOT`` 解析，参数优先；
    * 成功路径在临时输出根完成真实构建，并清掉上次留下的旧包；
    * unlink 抛 PermissionError / OSError（模拟 Windows access-denied）时保留旧包、
      打印路径与错误类型、非零退出，且不继续构建。

所有写操作只发生在 ``tmp_path``；测试信任链在临时输出根生成，不读既有 keys。
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("cryptography")

REPO = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO / "tools" / "build_v2_test_install.py"

SPEC = importlib.util.spec_from_file_location("build_v2_test_install_under_test", MODULE_PATH)
build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build)

from vse_boot.packages import load_trusted_keys, verify_app_package  # noqa: E402

DEFAULT_ROOT = REPO / "dist" / "v2-test"


def test_default_output_root_is_still_dist_v2_test(monkeypatch) -> None:
    """不传参数、不设环境变量时输出根保持 dist/v2-test（只解析，不落盘）。"""
    monkeypatch.delenv(build.OUT_ENV, raising=False)

    assert build.OUT == DEFAULT_ROOT
    assert build.resolve_out_root(None) == DEFAULT_ROOT
    assert build.resolve_out_root("") == DEFAULT_ROOT


def test_out_root_resolves_from_argument_and_env(tmp_path, monkeypatch) -> None:
    """--out 优先于环境变量；两者都指向临时目录。"""
    monkeypatch.delenv(build.OUT_ENV, raising=False)
    arg_root = tmp_path / "from-arg"
    env_root = tmp_path / "from-env"

    assert build.resolve_out_root(str(arg_root)) == arg_root

    monkeypatch.setenv(build.OUT_ENV, str(env_root))
    assert build.resolve_out_root(None) == env_root
    assert build.resolve_out_root(str(arg_root)) == arg_root


def test_success_path_cleans_stale_packages_in_temp_root(tmp_path, monkeypatch, capsys) -> None:
    """真实调用链在临时输出根构建，并删除上次留下的旧包。"""
    out_root = tmp_path / "out"
    install = out_root / "VSE-Toolbox"
    updates = out_root / "updates"
    install.mkdir(parents=True)
    updates.mkdir(parents=True)
    stale = [install / "vse-app-2.2.9.vsepkg", updates / "vse-app-2.3.10.vsepkg"]
    for path in stale:
        path.write_bytes(b"stale package from an earlier build")

    monkeypatch.setenv(build.OUT_ENV, str(out_root))
    code = build.main(["--skip-exe"])
    capsys.readouterr()

    assert code == 0
    for path in stale:
        assert not path.exists(), f"旧包未被清理：{path}"
    assert sorted(p.name for p in install.glob("*.vsepkg")) == ["vse-app-2.3.0.vsepkg"]
    assert sorted(p.name for p in updates.glob("*.vsepkg")) == [
        "vse-app-2.3.0.vsepkg",
        "vse-app-2.3.1.vsepkg",
        "vse-app-2.3.2.vsepkg",
    ]

    # 信任链在临时输出根生成，包由它签名并可通过同一份 trusted_keys.json 校验。
    keys_dir = out_root / "keys"
    assert (keys_dir / "TEST-ONLY-signing.pem").is_file()
    trusted = json.loads((keys_dir / "trusted_keys.json").read_text(encoding="utf-8"))
    assert [item["label"] for item in trusted["keys"]] == ["TEST ONLY"]
    verified = verify_app_package(
        (install / "vse-app-2.3.0.vsepkg").read_bytes(),
        load_trusted_keys([keys_dir / "trusted_keys.json"]),
    )
    assert verified.version == "2.3.0"

    assert (install / "portable.flag").is_file()
    assert (out_root / "测试步骤.txt").is_file()


@pytest.mark.parametrize(
    ("error_factory", "expected_type"),
    [
        (lambda path: PermissionError(13, "Access is denied", str(path)), "PermissionError"),
        (lambda path: OSError(5, "input/output error", str(path)), "OSError"),
    ],
    ids=["permission-denied", "generic-oserror"],
)
def test_unlink_failure_keeps_old_package_and_exits_nonzero(
    tmp_path, monkeypatch, capsys, error_factory, expected_type
) -> None:
    """unlink 失败（模拟 Windows WinError 5）时保留旧包、报错并非零退出。"""
    out_root = tmp_path / "out"
    updates = out_root / "updates"
    updates.mkdir(parents=True)
    stale = updates / "vse-app-2.3.10.vsepkg"
    stale.write_bytes(b"locked by another process")
    real_unlink = Path.unlink

    def deny_unlink(self, *args, **kwargs):
        if self == stale:
            raise error_factory(self)
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", deny_unlink)
    code = build.main(["--skip-exe", "--out", str(out_root)])
    captured = capsys.readouterr()
    message = captured.out + captured.err

    assert code != 0
    assert stale.exists(), "失败路径必须保留旧包"
    assert stale.read_bytes() == b"locked by another process"
    assert str(stale) in message
    assert expected_type in message
    assert "下一步" in message
    # 失败后不再继续构建：不生成新包，也不生成测试密钥。
    assert not (updates / "vse-app-2.3.1.vsepkg").exists()
    assert not (out_root / "keys").exists()


@pytest.mark.skipif(os.name != "nt", reason="WinError 5 只在 Windows 上可复现")
def test_real_winerror5_aborts_script_with_nonzero_process_exit(tmp_path) -> None:
    """真实 Windows 场景：旧包名被目录占用，unlink 抛 WinError 5，脚本进程非零退出。"""
    out_root = tmp_path / "out"
    updates = out_root / "updates"
    updates.mkdir(parents=True)
    stale = updates / "vse-app-2.3.10.vsepkg"
    stale.mkdir()  # Windows 上删除目录会抛 PermissionError [WinError 5]

    result = subprocess.run(
        [sys.executable, "-B", str(MODULE_PATH), "--skip-exe", "--out", str(out_root)],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=dict(os.environ, PYTHONIOENCODING="utf-8"),
    )

    assert result.returncode != 0
    assert stale.is_dir(), "失败路径必须保留旧包"
    message = result.stdout + result.stderr
    assert str(stale) in message
    assert "PermissionError" in message
    assert "下一步" in message
    assert not (updates / "vse-app-2.3.1.vsepkg").exists()
